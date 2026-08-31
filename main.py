from __future__ import annotations

import argparse
import json
import os
import webbrowser
from pathlib import Path
from threading import Timer

from web.server import AppState, run

ROOT = Path(__file__).parent

DEFAULT_CONFIG = {
    "novelai_token": "",
    "use_live_novelai": False,
    "model": "nai-diffusion-4-5-full",
    "base_prompt": "1girl, solo, looking at viewer",
    "negative_prompt": "worst quality, low quality, blurry",
    "quality_prompt": "very aesthetic, masterpiece, no text",
    "width": 832,
    "height": 1216,
    "steps": 28,
    "scale": 5.0,
    "cfg_rescale": 0.0,
    "sampler": "k_euler_ancestral",
    "noise_schedule": "karras",
    "variety_plus": False,
    "seed": 42,
    "artist_tags": [],
    "initial_weights": {},
    "weight_bounds": [0.2, 1.6],
    "prompt_cutoff": 0.0,
    "weight_budget_per_tag": 1.0,
    "reuse_threshold": 0.03,
    "max_rounds": 25,
    "candidate_pool": 300,
    "port": 8787,
}


def load_or_init_config(path: Path) -> dict:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))
        print(f"created blank {path} -> open the app and fill in Settings")
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--work", default="work")
    args = parser.parse_args()

    config_path = ROOT / args.config
    config = load_or_init_config(config_path)
    work_dir = ROOT / args.work
    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    state = AppState(config, config_path, work_dir, images_dir)
    port = int(config.get("port", 8787))

    if not os.environ.get("NO_BROWSER"):
        Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    run(state, port)


if __name__ == "__main__":
    main()
