from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from core.bo_loop import BOSession
from core.genome import ArtistTag, render_prompt
from core.provider import MockProvider, NovelAIProvider
from core.wiki import DanbooruWiki
from core.prompt_parser import classify_prompt_genes
from core import store as config_store

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_WIKI_DB_PATH = Path(__file__).parent.parent / "data" / "danbooru-wiki.sqlite3"
WIKI_DB_PATH = Path(os.environ["ARTISTBO_WIKI_DB"]) if os.environ.get("ARTISTBO_WIKI_DB") else DEFAULT_WIKI_DB_PATH

MODELS = [
    {"id": "nai-diffusion-5-full", "label": "V5 Full"},
    {"id": "nai-diffusion-5-curated", "label": "V5 Curated"},
    {"id": "nai-diffusion-4-5-full", "label": "V4.5 Full"},
    {"id": "nai-diffusion-4-5-curated", "label": "V4.5 Curated"},
]
SAMPLERS = ["k_euler_ancestral", "k_euler", "k_dpmpp_2s_ancestral", "k_dpmpp_2m_sde", "k_dpmpp_2m", "k_dpmpp_sde", "ddim"]
NOISE_SCHEDULES = ["karras", "native", "exponential", "polyexponential"]


class AppState:
    def __init__(self, config: dict, config_path: Path, work_dir: Path, images_dir: Path):
        self.config_path = config_path
        self.work_dir = work_dir
        self.images_dir = images_dir
        self.lock = threading.Lock()
        self.status = "idle"  # needs_config | idle | generating | ready | done | error
        self.progress = 0.0
        self.left: dict | None = None
        self.right: dict | None = None
        self.left_idx: int | None = None
        self.right_idx: int | None = None
        self.error_message = ""
        self.best_snapshot: dict | None = None
        self.config = config
        self.session = self._build_session(config)
        self.provider = self._build_provider(config)
        self.wiki = DanbooruWiki(WIKI_DB_PATH) if WIKI_DB_PATH.exists() else None

    def _build_session(self, config: dict) -> BOSession:
        return BOSession(
            tags=config.get("artist_tags", []),
            weight_bounds=tuple(config.get("weight_bounds", [0.2, 1.6])),
            work_dir=self.work_dir,
            max_rounds=int(config.get("max_rounds", 25)),
            pool_size=int(config.get("candidate_pool", 300)),
        )

    def _build_provider(self, config: dict):
        if config.get("use_live_novelai", False) and config.get("novelai_token", "").startswith("pst-"):
            return NovelAIProvider(config["novelai_token"], config, config.get("negative_prompt", ""))
        return MockProvider()

    def reconfigure(self, new_config: dict) -> None:
        with self.lock:
            self.config = new_config
            self.session = self._build_session(new_config)
            self.provider = self._build_provider(new_config)
            self.status = "idle"
            self.left = self.right = None
            self.left_idx = self.right_idx = None
            self.error_message = ""
            self.best_snapshot = None
        config_store.save(self.config_path, new_config)
        self.refresh_status()

    def refresh_status(self) -> None:
        """Re-evaluate readiness without kicking off generation — used after
        boot and after a settings save. Actually starting the duel loop is a
        separate, explicit action (see `start`)."""
        with self.lock:
            if not self.session.tags:
                self.status = "needs_config"
                self.error_message = ""
                return
            if self.config.get("use_live_novelai", False) and not isinstance(self.provider, NovelAIProvider):
                self.status = "needs_config"
                self.error_message = "live NovelAI 켰지만 유효한 pst- 토큰이 없습니다."
                return
            if self.session.is_done():
                weights = self.session.best_weights()
                self.status = "done"
                self.error_message = ""
                self.best_snapshot = weights
                return
            self.status = "idle"
            self.error_message = ""

    def start(self) -> None:
        with self.lock:
            if self.status not in ("idle", "error"):
                return
        threading.Thread(target=self.advance, daemon=True).start()

    def prompt_for(self, weights: dict[str, float]) -> str:
        tags = [ArtistTag(tag, weight) for tag, weight in weights.items()]
        return render_prompt(self.config.get("base_prompt", ""), tags, self.config.get("quality_prompt", ""))

    def advance(self) -> None:
        with self.lock:
            if not self.session.tags:
                self.status = "needs_config"
                return
            if self.config.get("use_live_novelai", False) and not isinstance(self.provider, NovelAIProvider):
                self.status = "needs_config"
                self.error_message = "live NovelAI 켰지만 유효한 pst- 토큰이 없습니다."
                return
            if self.session.is_done():
                self.status = "done"
                self.best_snapshot = self.session.best_weights()
                return
            self.status = "generating"
            self.progress = 0.0
        try:
            left_w, right_w, left_idx, right_idx = self.session.propose_duel()
            seed = int(self.config.get("seed", 42))
            left_path = self.images_dir / f"r{self.session.round}-left.png"
            right_path = self.images_dir / f"r{self.session.round}-right.png"
            self.provider.generate(self.prompt_for(left_w), seed, left_path)
            with self.lock:
                self.progress = 0.5
            self.provider.generate(self.prompt_for(right_w), seed, right_path)
            with self.lock:
                self.left = {"weights": left_w, "image": f"/images/{left_path.name}"}
                self.right = {"weights": right_w, "image": f"/images/{right_path.name}"}
                self.left_idx, self.right_idx = left_idx, right_idx
                self.status = "ready"
                self.progress = 1.0
        except Exception as error:  # noqa: BLE001
            with self.lock:
                self.status = "error"
                self.error_message = str(error)

    def choose(self, winner: str) -> None:
        with self.lock:
            if self.status != "ready" or self.left_idx is None or self.right_idx is None:
                return
            self.session.history.append({
                "round": self.session.round,
                "left": self.left["weights"],
                "right": self.right["weights"],
                "winner": winner,
            })
            self.session.record_choice(self.left_idx, self.right_idx, winner)
            self.status = "generating"
        threading.Thread(target=self.advance, daemon=True).start()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "status": self.status,
                "progress": self.progress,
                "round": self.session.round,
                "max_rounds": self.session.max_rounds,
                "left": self.left,
                "right": self.right,
                "error": self.error_message,
                "best": self.best_snapshot,
                "history": self.session.history[-10:],
            }

    def config_snapshot(self) -> dict:
        with self.lock:
            return {"config": self.config, "models": MODELS, "samplers": SAMPLERS, "noise_schedules": NOISE_SCHEDULES}

    def history_full(self) -> list[dict]:
        with self.lock:
            entries = list(self.session.history)
        out = []
        for entry in entries:
            r = entry["round"]
            out.append({
                **entry,
                "left_image": f"/images/r{r}-left.png",
                "right_image": f"/images/r{r}-right.png",
            })
        return out

    def best(self) -> dict:
        with self.lock:
            weights = self.session.best_weights()
            prompt = self.prompt_for(weights)
            artist_prompt = render_prompt("", [ArtistTag(tag, w) for tag, w in weights.items()], "")
            observed = len(self.session.pairs)
        return {"weights": weights, "prompt": prompt, "artist_prompt": artist_prompt, "observed_pairs": observed}

    def landscape(self) -> dict:
        with self.lock:
            result = self.session.landscape()
            observed = len(self.session.pairs)
        if result is None:
            return {"ready": False, "observed_pairs": observed}
        return {"ready": True, "observed_pairs": observed, **result}

    def cutoff_preview(self, threshold: float) -> dict:
        with self.lock:
            return self.session.preview_cutoff(threshold)

    def cutoff_apply(self, threshold: float) -> dict:
        with self.lock:
            result = self.session.prune(threshold)
            if result["removed"]:
                self.config["artist_tags"] = list(self.session.tags)
                self.left = self.right = None
                self.left_idx = self.right_idx = None
                self.status = "idle"
                self.error_message = ""
        if result["removed"]:
            config_store.save(self.config_path, self.config)
        return result

    def wiki_search(self, query: str, category: str) -> list[dict]:
        if self.wiki is None or not query.strip():
            return []
        return self.wiki.search(query, category, limit=24)

    def parse_prompt(self, text: str) -> dict:
        with self.lock:
            configured_quality = re.split(r"[,\n]", self.config.get("quality_prompt", ""))
        result = classify_prompt_genes(text, self.wiki, [t.strip() for t in configured_quality if t.strip()])
        seen = set()
        artists = []
        for item in result["artists"]:
            key = item["tag"].casefold()
            if key in seen:
                continue
            seen.add(key)
            artists.append(item)
        return {"artists": artists, "qualities": result["qualities"], "ignored": result["ignored"], "wiki_available": self.wiki is not None}


def _validate_config(body: dict) -> dict:
    tags = [t.strip() for t in body.get("artist_tags", []) if t.strip()]
    lo = float(body.get("weight_min", 0.2))
    hi = float(body.get("weight_max", 1.6))
    if hi <= lo:
        raise ValueError("weight_max must be greater than weight_min")
    use_live = bool(body.get("use_live_novelai", False))
    token = str(body.get("novelai_token", "")).strip()
    if use_live and not token.startswith("pst-"):
        raise ValueError("live NovelAI를 켜려면 pst- 로 시작하는 토큰이 필요합니다.")
    return {
        "novelai_token": token,
        "use_live_novelai": use_live,
        "model": body.get("model", "nai-diffusion-4-5-full"),
        "base_prompt": body.get("base_prompt", ""),
        "negative_prompt": body.get("negative_prompt", ""),
        "quality_prompt": body.get("quality_prompt", ""),
        "width": int(body.get("width", 832)),
        "height": int(body.get("height", 1216)),
        "steps": int(body.get("steps", 28)),
        "scale": float(body.get("scale", 5.0)),
        "cfg_rescale": float(body.get("cfg_rescale", 0.0)),
        "sampler": body.get("sampler", "k_euler_ancestral"),
        "noise_schedule": body.get("noise_schedule", "karras"),
        "variety_plus": bool(body.get("variety_plus", False)),
        "seed": int(body.get("seed", 42)),
        "artist_tags": tags,
        "weight_bounds": [lo, hi],
        "max_rounds": int(body.get("max_rounds", 25)),
        "candidate_pool": int(body.get("candidate_pool", 300)),
        "port": int(body.get("port", 8787)),
    }


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A003
            pass

        def _send_json(self, payload: dict, code: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_html(self, name: str) -> None:
            data = (STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            parsed = urlsplit(self.path)
            path, query = parsed.path, parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self._serve_html("index.html")
                return
            if path == "/state":
                self._send_json(state.snapshot())
                return
            if path == "/config":
                self._send_json(state.config_snapshot())
                return
            if path == "/history":
                self._send_json({"history": state.history_full()})
                return
            if path == "/best":
                self._send_json(state.best())
                return
            if path == "/landscape":
                self._send_json(state.landscape())
                return
            if path == "/cutoff-preview":
                try:
                    threshold = float((query.get("threshold") or ["0"])[0])
                except ValueError:
                    threshold = 0.0
                self._send_json(state.cutoff_preview(threshold))
                return
            if path == "/wiki/search":
                q = (query.get("q") or [""])[0]
                category = (query.get("category") or [""])[0]
                self._send_json({"results": state.wiki_search(q, category), "available": state.wiki is not None})
                return
            if path.startswith("/images/"):
                name = path[len("/images/"):]
                img_path = state.images_dir / name
                if ".." in name or not img_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                data = img_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not path.startswith("/") or ".." in path:
                self.send_response(404)
                self.end_headers()
                return
            static_path = STATIC_DIR / path.lstrip("/")
            if static_path.is_file() and static_path.parent == STATIC_DIR:
                data = static_path.read_bytes()
                mime = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):  # noqa: N802
            if self.path == "/choose":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                winner = body.get("winner")
                if winner in ("left", "right"):
                    state.choose(winner)
                self._send_json({"ok": True})
                return
            if self.path == "/config":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                try:
                    new_config = _validate_config(body)
                except ValueError as error:
                    self._send_json({"ok": False, "error": str(error)}, code=400)
                    return
                state.reconfigure(new_config)
                self._send_json({"ok": True})
                return
            if self.path == "/parse-prompt":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._send_json(state.parse_prompt(str(body.get("text", ""))))
                return
            if self.path == "/cutoff-apply":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                try:
                    threshold = float(body.get("threshold", 0))
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "invalid threshold"}, code=400)
                    return
                self._send_json({"ok": True, **state.cutoff_apply(threshold)})
                return
            if self.path == "/start":
                state.start()
                self._send_json({"ok": True})
                return
            self.send_response(404)
            self.end_headers()

    return Handler


def run(state: AppState, port: int) -> None:
    state.refresh_status()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    print(f"Artist Weight BO running at http://127.0.0.1:{port}")
    server.serve_forever()
