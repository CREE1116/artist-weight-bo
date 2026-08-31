from __future__ import annotations

import torch

torch.set_default_dtype(torch.float64)


def _rbf_kernel(x1: torch.Tensor, x2: torch.Tensor, lengthscale: torch.Tensor, outputscale: float) -> torch.Tensor:
    diff = (x1.unsqueeze(1) - x2.unsqueeze(0)) / lengthscale
    sqdist = (diff ** 2).sum(-1)
    return outputscale * torch.exp(-0.5 * sqdist)


class GPPreferenceModel:
    """Preference-learning GP (Chu & Ghahramani, 2005) fit by Laplace approximation.

    Observations are pairwise duels (winner index, loser index) over points in
    [0, 1]^d. Predicts a posterior mean/variance "goodness" score anywhere in
    that cube, used to drive Thompson-sampling based duel proposals.
    """

    def __init__(self, dim: int, lengthscale_frac: float = 0.3, outputscale: float = 1.0,
                 noise_scale: float = 0.6, jitter: float = 1e-6):
        self.dim = dim
        self.lengthscale = torch.full((dim,), lengthscale_frac)
        self.outputscale = outputscale
        self.noise_scale = noise_scale  # combined probit scale (larger = more tolerant of noisy choices)
        self.jitter = jitter
        self.X: torch.Tensor | None = None
        self.f_hat: torch.Tensor | None = None
        self.Kinv_fhat: torch.Tensor | None = None
        self.M_chol: torch.Tensor | None = None

    def fit(self, X: torch.Tensor, pairs: list[tuple[int, int]], steps: int = 300, lr: float = 0.05) -> None:
        n = X.shape[0]
        K = _rbf_kernel(X, X, self.lengthscale, self.outputscale)
        K = K + self.jitter * torch.eye(n)
        K_chol = torch.linalg.cholesky(K)

        win = torch.tensor([p[0] for p in pairs], dtype=torch.long)
        lose = torch.tensor([p[1] for p in pairs], dtype=torch.long)
        normal = torch.distributions.Normal(0.0, 1.0)

        def data_loglik(f: torch.Tensor) -> torch.Tensor:
            z = (f[win] - f[lose]) / self.noise_scale
            return normal.cdf(z).clamp_min(1e-12).log().sum()

        f = torch.zeros(n, requires_grad=True)
        opt = torch.optim.Adam([f], lr=lr)
        for _ in range(steps):
            opt.zero_grad()
            Kinv_f = torch.cholesky_solve(f.unsqueeze(1), K_chol).squeeze(1)
            log_post = -0.5 * torch.dot(f, Kinv_f) + data_loglik(f)
            loss = -log_post
            loss.backward()
            opt.step()

        f_hat = f.detach()

        def data_loglik_plain(fv: torch.Tensor) -> torch.Tensor:
            z = (fv[win] - fv[lose]) / self.noise_scale
            return normal.cdf(z).clamp_min(1e-12).log().sum()

        H = torch.func.hessian(data_loglik_plain)(f_hat)
        W = -H
        W = 0.5 * (W + W.T)

        Winv = torch.linalg.solve(W + 1e-6 * torch.eye(n), torch.eye(n))
        M = K + Winv
        M_chol = torch.linalg.cholesky(M + 1e-6 * torch.eye(n))

        self.X = X
        self.f_hat = f_hat
        self.Kinv_fhat = torch.cholesky_solve(f_hat.unsqueeze(1), K_chol).squeeze(1)
        self.M_chol = M_chol

    def predict(self, Xstar: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if self.X is None:
            mean = torch.zeros(Xstar.shape[0])
            var = torch.full((Xstar.shape[0],), self.outputscale)
            return mean, var
        Kstar = _rbf_kernel(Xstar, self.X, self.lengthscale, self.outputscale)  # (m, n)
        mean = Kstar @ self.Kinv_fhat
        v = torch.cholesky_solve(Kstar.T, self.M_chol)  # (n, m)
        var = self.outputscale - (Kstar.T * v).sum(0)
        var = var.clamp_min(1e-8)
        return mean, var
