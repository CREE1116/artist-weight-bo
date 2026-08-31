from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
