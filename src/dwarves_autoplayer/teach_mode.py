from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes
import logging
import queue
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import keyboard
import numpy as np

from dwarves_autoplayer.bot import CONFIG_PATH, ROOT, find_game_window, load_config, screenshot_window
from dwarves_autoplayer.ocr import load_pytesseract
from dwarves_autoplayer.perception import PerceptionEngine
from dwarves_autoplayer.playbook import DwarvesPlaybook
from dwarves_autoplayer.screen_features import fingerprint
from dwarves_autoplayer.strategy import KnowledgeStrategy


@dataclass(frozen=True)
class ClickEvent:
    x: int
    y: int
    button: str
    pressed: bool
    event_time: float


class DemoOcrReader:
    def __init__(self, enabled: bool, config: dict[str, Any]) -> None:
        self.enabled = enabled
        self._pytesseract = load_pytesseract(config)

    @property
    def available(self) -> bool:
        if not self.enabled or self._pytesseract is None:
            return False
        try:
            self._pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def read(self, screen: np.ndarray) -> str:
        if not self.available:
            return ""
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.bilateralFilter(gray, 5, 55, 55)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        try:
            text = self._pytesseract.image_to_string(thresh, config="--psm 11")
        except Exception as exc:
            logging.info("Teach-mode OCR failed: %s", exc)
            return ""
        return " ".join(text.split())


class TeachModeRecorder:
    def __init__(self, config: dict[str, Any], session_name: str | None = None) -> None:
        self.config = config
        teach_config = config.get("teach_mode", {})
        self.session_id = session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.data_dir = ROOT / str(teach_config.get("data_dir", "learning_data/demonstrations")) / self.session_id
        self.screenshot_dir = self.data_dir / "screenshots"
        self.events_path = self.data_dir / "events.csv"
        self.sample_interval = float(teach_config.get("screenshot_interval_seconds", 2.0))
        self.after_click_delay = float(teach_config.get("after_click_delay_seconds", 0.45))
        self.hover_enabled = bool(teach_config.get("hover_capture_enabled", True))
        self.hover_stable_seconds = float(teach_config.get("hover_stable_seconds", 1.1))
        self.hover_min_interval = float(teach_config.get("hover_min_interval_seconds", 3.0))
        self.label_hotkeys = dict(teach_config.get("label_hotkeys", {}))
        self.ocr = DemoOcrReader(bool(teach_config.get("ocr_enabled", True)), config)
        self.title_parts = config.get("window_title_contains", ["Dwarves"])
        self.playbook = DwarvesPlaybook(config, KnowledgeStrategy(ROOT, config))
        self.perception = PerceptionEngine(ROOT, config)
        self.click_queue: queue.Queue[ClickEvent] = queue.Queue()
        self.quit_requested = False
        self.paused = False
        self.last_sample_at = 0.0
        self.event_index = 0
        self.last_mouse_pressed = {"left": False, "right": False, "middle": False}
        self.last_cursor_position: tuple[int, int] | None = None
        self.cursor_stable_since = time.monotonic()
        self.last_hover_capture_at = 0.0

        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_events_header()

    def run(self) -> None:
        self._install_hotkeys()
        logging.info("Teach session: %s", self.session_id)
        logging.info("Writing demonstrations to %s", self.data_dir)
        logging.info("Teach OCR available: %s", self.ocr.available)
        logging.info("Play normally. Press Ctrl+Alt+S to pause/resume recording, Ctrl+Alt+Q to finish.")

        try:
            while not self.quit_requested:
                self._poll_mouse_clicks()
                self._process_click_queue()
                self._sample_screen_if_due()
                self._capture_hover_if_due()
                time.sleep(0.03)
        finally:
            logging.info("Teach session finished: %s", self.events_path)

    def _install_hotkeys(self) -> None:
        hotkeys = self.config.get("hotkeys", {})
        keyboard.add_hotkey(hotkeys.get("toggle", "ctrl+alt+s"), self._toggle_pause)
        keyboard.add_hotkey(hotkeys.get("quit", "ctrl+alt+q"), self._quit)
        for hotkey, label in self.label_hotkeys.items():
            keyboard.add_hotkey(str(hotkey), lambda value=str(label): self._record_label(value))

    def _poll_mouse_clicks(self) -> None:
        button_codes = {"left": 0x01, "right": 0x02, "middle": 0x04}
        for button, code in button_codes.items():
            pressed = bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)
            was_pressed = self.last_mouse_pressed.get(button, False)
            self.last_mouse_pressed[button] = pressed
            if pressed and not was_pressed:
                x, y = self._cursor_position()
                self.click_queue.put(ClickEvent(x=x, y=y, button=button, pressed=True, event_time=time.time()))

    def _cursor_position(self) -> tuple[int, int]:
        point = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return int(point.x), int(point.y)

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        logging.info("Teach mode %s", "paused" if self.paused else "recording")

    def _quit(self) -> None:
        self.quit_requested = True

    def _process_click_queue(self) -> None:
        while True:
            try:
                event = self.click_queue.get_nowait()
            except queue.Empty:
                return
            if self.paused:
                continue
            self._record_click(event)

    def _sample_screen_if_due(self) -> None:
        if self.paused:
            return
        now = time.monotonic()
        if now - self.last_sample_at < self.sample_interval:
            return
        self.last_sample_at = now
        window = find_game_window(self.title_parts)
        if not window:
            return
        screen = screenshot_window(window)
        observation = self.perception.observe(screen, self.playbook.classify(screen).value)
        state = observation.state
        screen_id = observation.screen_id
        image_path = self._save_screen(screen, f"sample_{state}_{screen_id[:12]}")
        self._append_event(
            {
                "event_type": "sample",
                "label": "",
                "button": "",
                "screen_x": "",
                "screen_y": "",
                "window_x": "",
                "window_y": "",
                "x_ratio": "",
                "y_ratio": "",
                "state_before": state,
                "state_after": state,
                "screen_id_before": screen_id,
                "screen_id_after": screen_id,
                "image_before": image_path,
                "image_after": image_path,
                "tooltip_image": "",
                "tooltip_text": "",
                "ocr_text": observation.ocr_text,
                "state_source": observation.state_source,
                "state_confidence": observation.state_confidence,
                "visible_keywords": "|".join(observation.visible_keywords),
            }
        )

    def _record_click(self, event: ClickEvent) -> None:
        window = find_game_window(self.title_parts)
        if not window or not self._inside_window(window, event.x, event.y):
            return

        before = screenshot_window(window)
        observation_before = self.perception.observe(before, self.playbook.classify(before).value)
        state_before = observation_before.state
        before_id = observation_before.screen_id
        before_path = self._save_screen(before, f"click_before_{state_before}_{before_id[:12]}")
        time.sleep(self.after_click_delay)
        after = screenshot_window(window)
        observation_after = self.perception.observe(after, self.playbook.classify(after).value)
        state_after = observation_after.state
        after_id = observation_after.screen_id
        after_path = self._save_screen(after, f"click_after_{state_after}_{after_id[:12]}")

        window_x = event.x - window.left
        window_y = event.y - window.top
        row = {
            "event_type": "click",
            "label": "",
            "button": event.button,
            "screen_x": event.x,
            "screen_y": event.y,
            "window_x": window_x,
            "window_y": window_y,
            "x_ratio": round(window_x / max(window.width, 1), 5),
            "y_ratio": round(window_y / max(window.height, 1), 5),
            "state_before": state_before,
            "state_after": state_after,
            "screen_id_before": before_id,
            "screen_id_after": after_id,
            "image_before": before_path,
            "image_after": after_path,
            "tooltip_image": "",
            "tooltip_text": "",
            "ocr_text": observation_before.ocr_text or self.ocr.read(before),
            "state_source": observation_before.state_source,
            "state_confidence": observation_before.state_confidence,
            "visible_keywords": "|".join(observation_before.visible_keywords),
        }
        self._append_event(row)
        logging.info(
            "Recorded click state=%s -> %s ratio=(%.3f, %.3f)",
            state_before,
            state_after,
            row["x_ratio"],
            row["y_ratio"],
        )

    def _capture_hover_if_due(self) -> None:
        if self.paused or not self.hover_enabled:
            return
        window = find_game_window(self.title_parts)
        if not window:
            return
        x, y = self._cursor_position()
        if not self._inside_window(window, x, y):
            self.last_cursor_position = None
            self.cursor_stable_since = time.monotonic()
            return

        now = time.monotonic()
        if self.last_cursor_position is None or abs(x - self.last_cursor_position[0]) > 4 or abs(y - self.last_cursor_position[1]) > 4:
            self.last_cursor_position = (x, y)
            self.cursor_stable_since = now
            return

        if now - self.cursor_stable_since < self.hover_stable_seconds:
            return
        if now - self.last_hover_capture_at < self.hover_min_interval:
            return

        self.last_hover_capture_at = now
        screen = screenshot_window(window)
        observation = self.perception.observe(screen, self.playbook.classify(screen).value)
        window_x = x - window.left
        window_y = y - window.top
        crop = self.perception.tooltip_crop(screen, window_x, window_y)
        tooltip_text = self.perception.ocr_image(crop)
        tooltip_path = self._save_screen(crop, f"hover_tooltip_{observation.state}_{observation.screen_id[:12]}")
        screen_path = self._save_screen(screen, f"hover_screen_{observation.state}_{observation.screen_id[:12]}")
        self._append_event(
            {
                "event_type": "hover",
                "label": "tooltip_hover",
                "button": "",
                "screen_x": x,
                "screen_y": y,
                "window_x": window_x,
                "window_y": window_y,
                "x_ratio": round(window_x / max(window.width, 1), 5),
                "y_ratio": round(window_y / max(window.height, 1), 5),
                "state_before": observation.state,
                "state_after": observation.state,
                "screen_id_before": observation.screen_id,
                "screen_id_after": observation.screen_id,
                "image_before": screen_path,
                "image_after": screen_path,
                "tooltip_image": tooltip_path,
                "tooltip_text": tooltip_text,
                "ocr_text": observation.ocr_text,
                "state_source": observation.state_source,
                "state_confidence": observation.state_confidence,
                "visible_keywords": "|".join(observation.visible_keywords),
            }
        )
        logging.info("Recorded hover state=%s tooltip_text=%s", observation.state, tooltip_text or "unreadable")

    def _record_label(self, label: str) -> None:
        if self.paused:
            return
        window = find_game_window(self.title_parts)
        if not window:
            return
        screen = screenshot_window(window)
        observation = self.perception.observe(screen, self.playbook.classify(screen).value)
        x, y = self._cursor_position()
        window_x = x - window.left
        window_y = y - window.top
        image_path = self._save_screen(screen, f"label_{label}_{observation.state}_{observation.screen_id[:12]}")
        self._append_event(
            {
                "event_type": "label",
                "label": label,
                "button": "",
                "screen_x": x,
                "screen_y": y,
                "window_x": window_x,
                "window_y": window_y,
                "x_ratio": round(window_x / max(window.width, 1), 5),
                "y_ratio": round(window_y / max(window.height, 1), 5),
                "state_before": observation.state,
                "state_after": observation.state,
                "screen_id_before": observation.screen_id,
                "screen_id_after": observation.screen_id,
                "image_before": image_path,
                "image_after": image_path,
                "tooltip_image": "",
                "tooltip_text": "",
                "ocr_text": observation.ocr_text,
                "state_source": observation.state_source,
                "state_confidence": observation.state_confidence,
                "visible_keywords": "|".join(observation.visible_keywords),
            }
        )
        logging.info("Recorded label=%s state=%s", label, observation.state)

    def _inside_window(self, window, x: int, y: int) -> bool:
        return window.left <= x <= window.left + window.width and window.top <= y <= window.top + window.height

    def _save_screen(self, screen: np.ndarray, label: str) -> str:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label)
        path = self.screenshot_dir / f"{int(time.time() * 1000)}_{safe_label}.png"
        cv2.imwrite(str(path), screen)
        return str(path.relative_to(ROOT))

    def _ensure_events_header(self) -> None:
        if self.events_path.exists():
            return
        with self.events_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._fieldnames())
            writer.writeheader()

    def _append_event(self, row: dict[str, Any]) -> None:
        self.event_index += 1
        payload = {
            "event_index": self.event_index,
            "time": int(time.time()),
            "session_id": self.session_id,
            **row,
        }
        with self.events_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._fieldnames())
            writer.writerow(payload)

    def _fieldnames(self) -> list[str]:
        return [
            "event_index",
            "time",
            "session_id",
            "event_type",
            "label",
            "button",
            "screen_x",
            "screen_y",
            "window_x",
            "window_y",
            "x_ratio",
            "y_ratio",
            "state_before",
            "state_after",
            "screen_id_before",
            "screen_id_after",
            "image_before",
            "image_after",
            "tooltip_image",
            "tooltip_text",
            "ocr_text",
            "state_source",
            "state_confidence",
            "visible_keywords",
        ]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(ROOT / "teach_mode.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-name", help="Optional folder name for this teaching session.")
    return parser.parse_args()


def main() -> None:
    if not CONFIG_PATH.exists():
        raise SystemExit("Missing config.yaml.")
    args = parse_args()
    config = load_config()
    setup_logging()
    TeachModeRecorder(config, session_name=args.session_name).run()


if __name__ == "__main__":
    main()
