from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


BASELINE_PATH = Path.cwd() / "knowledge" / "baseline.yaml"


def load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.exists():
        return {}

    with BASELINE_PATH.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
        return value if isinstance(value, dict) else {}


def keyword_priority_words(baseline: dict[str, Any]) -> list[str]:
    words: list[str] = []
    ui = baseline.get("ui_priorities", {})
    for group in ("high", "medium", "avoid"):
        words.extend(str(item).lower() for item in ui.get(group, []))
    return words

