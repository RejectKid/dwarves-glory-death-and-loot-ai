from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from dwarves_autoplayer.screen_features import fingerprint


class ScreenRecorder:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        recorder_config = config.get("screen_recorder", {})
        self.enabled = bool(recorder_config.get("enabled", True))
        self.data_dir = root / recorder_config.get("data_dir", "learning_data")
        self.screenshot_dir = self.data_dir / "screenshots"
        self.timeline_path = self.data_dir / "runtime_timeline.csv"
        self.interval = float(recorder_config.get("screenshot_interval_seconds", 3.0))
        self.last_screenshot_at = 0.0
        self.timeline_initialized = False

        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fingerprint(self, screen: np.ndarray) -> str:
        return fingerprint(screen)

    def observe(self, screen: np.ndarray, state: str, action: str | None, goal: str | None = None) -> str:
        screen_id = self.fingerprint(screen)
        if not self.enabled:
            return screen_id

        now = time.monotonic()
        if now - self.last_screenshot_at >= self.interval:
            self.last_screenshot_at = now
            path = self.screenshot_dir / f"{int(time.time())}_{state}_{screen_id[:12]}.png"
            cv2.imwrite(str(path), screen)

        self._append_timeline(screen_id, state, action, goal)
        return screen_id

    def _append_timeline(self, screen_id: str, state: str, action: str | None, goal: str | None) -> None:
        exists = self.timeline_path.exists()
        with self.timeline_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "screen_id", "state", "action", "goal"])
            if not exists:
                writer.writeheader()
            writer.writerow(
                {
                    "time": int(time.time()),
                    "screen_id": screen_id,
                    "state": state,
                    "action": action or "",
                    "goal": goal or "",
                }
            )
