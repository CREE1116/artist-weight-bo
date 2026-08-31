from __future__ import annotations

from pathlib import Path

import torch

from . import store
from .gp_preference import GPPreferenceModel

torch.set_default_dtype(torch.float64)


class BOSession:
    """Preferential Bayesian optimization over a fixed artist-tag weight vector.

    Each round proposes a duel: an incumbent (posterior-mean best so far) vs a
    Thompson-sampled challenger. The user's A/B pick becomes one pairwise
    observation for the preference GP.
    """

    def __init__(self, tags: list[str], weight_bounds: tuple[float, float], work_dir: Path,
                 max_rounds: int = 25, pool_size: int = 300, seed: int = 0,
                 initial_weights: dict[str, float] | None = None):
        self.tags = tags
        self.dim = len(tags)
        self.lo, self.hi = weight_bounds
        self.max_rounds = max_rounds
        self.pool_size = pool_size
        self.work_dir = work_dir
        self.state_path = work_dir / "state.json"
        self.gp = GPPreferenceModel(self.dim)
        self.generator = torch.Generator().manual_seed(seed)

        # Where the very first duel's incumbent starts — user-provided weights
        # (e.g. from a pasted prompt) beat a blind uniform 1.0 for every tag.
        initial_weights = initial_weights or {}
        self.initial_point = [
            min(1.0, max(0.0, self._normalize(initial_weights.get(tag, 1.0)))) for tag in tags
        ]

        self.points: list[list[float]] = []  # normalized [0,1]^dim, index-addressed
        self.pairs: list[list[int]] = []  # [win_idx, lose_idx]
        self.round = 0
        self.history: list[dict] = []  # for display: {round, left, right, winner}
        self._best_cache: tuple[int, torch.Tensor] | None = None  # (len(pairs), x) at last compute

        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        data = store.load(self.state_path)
        if not data or data.get("tags") != self.tags:
            return
        self.points = data.get("points", [])
        self.pairs = data.get("pairs", [])
        self.round = data.get("round", 0)
        self.history = data.get("history", [])

    def _persist(self) -> None:
        store.save(self.state_path, {
            "tags": self.tags,
            "points": self.points,
            "pairs": self.pairs,
            "round": self.round,
            "history": self.history,
        })

    # -- weight space helpers --------------------------------------------
    def _normalize(self, weight: float) -> float:
        return (weight - self.lo) / (self.hi - self.lo)

    def _denormalize(self, x: float) -> float:
        return self.lo + x * (self.hi - self.lo)

    def to_weights(self, x_vector: torch.Tensor) -> dict[str, float]:
        return {tag: round(self._denormalize(float(v)), 2) for tag, v in zip(self.tags, x_vector)}

    def is_done(self) -> bool:
        return self.round >= self.max_rounds

    def reset(self) -> None:
        """Clear all duel history/observations, keep tags/config as-is."""
        self.points = []
        self.pairs = []
        self.round = 0
        self.history = []
        self._best_cache = None
        self._persist()

    # -- duel proposal -----------------------------------------------------
    def propose_duel(self) -> tuple[dict[str, float], dict[str, float], int, int]:
        if not self.pairs:
            neutral = torch.full((self.dim,), self._normalize(1.0)).clamp(0.0, 1.0)
            random_point = torch.rand(self.dim, generator=self.generator)
            left_x, right_x = neutral, random_point
        else:
            X = torch.tensor(self.points)
            self.gp.fit(X, [tuple(p) for p in self.pairs])

            pool = torch.rand(self.pool_size, self.dim, generator=self.generator)
            mean, var = self.gp.predict(pool)

            incumbent_idx = int(torch.argmax(mean))
            left_x = pool[incumbent_idx]

            samples = mean + torch.sqrt(var) * torch.randn(mean.shape, generator=self.generator)
            dist = torch.linalg.norm(pool - left_x, dim=1)
            samples = torch.where(dist > 0.05, samples, torch.full_like(samples, -1e9))
            challenger_idx = int(torch.argmax(samples))
            right_x = pool[challenger_idx]

        left_idx = len(self.points)
        self.points.append(left_x.tolist())
        right_idx = len(self.points)
        self.points.append(right_x.tolist())

        return self.to_weights(left_x), self.to_weights(right_x), left_idx, right_idx

    def record_choice(self, left_idx: int, right_idx: int, winner: str) -> None:
        win = left_idx if winner == "left" else right_idx
        lose = right_idx if winner == "left" else left_idx
        self.pairs.append([win, lose])
        self.round += 1
        self._persist()

    def best_point(self) -> torch.Tensor | None:
        """Normalized [0,1]^dim posterior-mean optimum, or None with too few observations.

        Dimensions with little/no preference signal have a nearly-flat posterior
        mean, so a fresh random-pool argmax can land on very different (but
        near-equally-good) points from call to call — that's real model
        uncertainty, not noise to be smoothed away. What *should* be stable is
        showing the same answer for the same data: cache by observation count
        and only recompute once new choices actually change the posterior.
        """
        if not self.pairs:
            self._best_cache = None
            return None
        if self._best_cache is not None and self._best_cache[0] == len(self.pairs):
            return self._best_cache[1]
        X = torch.tensor(self.points)
        self.gp.fit(X, [tuple(p) for p in self.pairs])
        pool = torch.rand(max(self.pool_size, 1000), self.dim, generator=self.generator)
        mean, _ = self.gp.predict(pool)
        best_idx = int(torch.argmax(mean))

        x = pool[best_idx].clone().requires_grad_(True)
        opt = torch.optim.Adam([x], lr=0.03)
        for _ in range(150):
            opt.zero_grad()
            m, _ = self.gp.predict(x.unsqueeze(0))
            (-m.sum()).backward()
            opt.step()
            with torch.no_grad():
                x.clamp_(0.0, 1.0)
        result = x.detach()
        self._best_cache = (len(self.pairs), result)
        return result

    def best_weights(self) -> dict[str, float]:
        best_x = self.best_point()
        if best_x is None:
            return {tag: 1.0 for tag in self.tags}
        return self.to_weights(best_x)

    def confidence(self) -> dict:
        """How much to trust the current 'best' point: 1 - posterior std at
        that point (relative to the GP's prior/output scale). Low confidence
        means the model hasn't pinned this down yet — most credible early on,
        or for tags the user's choices haven't actually discriminated between.
        """
        best_x = self.best_point()
        if best_x is None:
            return {"confidence": 0.0, "std": 1.0, "observed_pairs": 0}
        _, var = self.gp.predict(best_x.unsqueeze(0))
        std = float(torch.sqrt(var[0]))
        conf = max(0.0, 1.0 - min(1.0, std / (self.gp.outputscale ** 0.5)))
        return {"confidence": conf, "std": std, "observed_pairs": len(self.pairs)}

    def landscape(self, resolution: int = 25) -> dict | None:
        """1D posterior-mean/std slice through each tag's weight axis, holding
        every other tag at the current best point. A cheap stand-in for a full
        d-dimensional loss surface."""
        best_x = self.best_point()
        if best_x is None:
            return None
        xs_unit = torch.linspace(0.0, 1.0, resolution)
        series = []
        for i, tag in enumerate(self.tags):
            batch = best_x.unsqueeze(0).repeat(resolution, 1)
            batch[:, i] = xs_unit
            mean, var = self.gp.predict(batch)
            series.append({
                "tag": tag,
                "xs": [round(self._denormalize(float(v)), 3) for v in xs_unit],
                "mean": [float(v) for v in mean],
                "std": [float(v) for v in torch.sqrt(var)],
                "best": round(self._denormalize(float(best_x[i])), 3),
            })
        return {"series": series, "best_weights": self.to_weights(best_x)}
