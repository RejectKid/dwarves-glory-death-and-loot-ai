from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pyautogui


@dataclass(frozen=True)
class TooltipObservation:
    action_name: str
    text: str
    image_path: str
    ocr_available: bool


class TooltipReader:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        tooltip_config = config.get("tooltip_reader", {})
        self.enabled = bool(tooltip_config.get("enabled", True))
        self.hover_seconds = float(tooltip_config.get("hover_seconds", 0.45))
        self.data_dir = root / tooltip_config.get("data_dir", "learning_data/tooltips")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._pytesseract = self._load_pytesseract()

    @property
    def ocr_available(self) -> bool:
        if self._pytesseract is None:
            return False
        try:
            self._pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def read_after_hover(self, window, x: int, y: int, action_name: str) -> TooltipObservation:
        if not self.enabled:
            return TooltipObservation(action_name, "", "", False)

        pyautogui.moveTo(window.left + x, window.top + y)
        time.sleep(self.hover_seconds)
        image = pyautogui.screenshot(region=(window.left, window.top, window.width, window.height))
        screen = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        crop = self._tooltip_crop(screen, x, y)
        image_path = self._save_crop(crop, action_name)
        text = self._ocr(crop)
        if text:
            logging.info("Tooltip action=%s text=%s", action_name, text)
        else:
            logging.info(
                "Tooltip action=%s text unavailable; saved=%s ocr_available=%s",
                action_name,
                image_path,
                self.ocr_available,
            )
        return TooltipObservation(action_name, text, image_path, self.ocr_available)

    def _tooltip_crop(self, screen: np.ndarray, x: int, y: int) -> np.ndarray:
        height, width = screen.shape[:2]
        pad_x = int(width * 0.36)
        pad_y = int(height * 0.26)
        left = max(0, x - pad_x // 2)
        right = min(width, x + pad_x)
        top = max(0, y - pad_y)
        bottom = min(height, y + pad_y)
        return screen[top:bottom, left:right]

    def _save_crop(self, crop: np.ndarray, action_name: str) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", action_name)
        path = self.data_dir / f"{int(time.time() * 1000)}_{safe_name}.png"
        cv2.imwrite(str(path), crop)
        return str(path)

    def _ocr(self, crop: np.ndarray) -> str:
        if not self._pytesseract:
            return ""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.bilateralFilter(gray, 5, 55, 55)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        try:
            text = self._pytesseract.image_to_string(thresh, config="--psm 6")
        except Exception as exc:
            logging.info("Tooltip OCR unavailable at runtime: %s", exc)
            return ""
        return " ".join(text.split())

    def _load_pytesseract(self):
        try:
            import pytesseract

            return pytesseract
        except ImportError:
            return None
