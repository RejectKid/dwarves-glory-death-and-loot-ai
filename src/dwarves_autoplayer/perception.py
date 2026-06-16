from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from dwarves_autoplayer.ocr import load_pytesseract
from dwarves_autoplayer.screen_features import fingerprint


@dataclass(frozen=True)
class ScreenRegion:
    name: str
    kind: str
    x_ratio: float
    y_ratio: float
    width_ratio: float = 0.04
    height_ratio: float = 0.04


@dataclass(frozen=True)
class GameObservation:
    state: str
    state_confidence: float
    state_source: str
    screen_id: str
    ocr_text: str = ""
    visible_keywords: tuple[str, ...] = ()
    regions: dict[str, list[ScreenRegion]] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["regions"] = {
            key: [asdict(region) for region in regions]
            for key, regions in self.regions.items()
        }
        return value


class PerceptionEngine:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config
        perception_config = config.get("perception", {})
        self.ocr_enabled = bool(perception_config.get("ocr_enabled", True))
        self.keyword_state_detection = bool(perception_config.get("keyword_state_detection", True))
        self.ocr_cache_size = int(perception_config.get("ocr_cache_size", 100))
        self._pytesseract = load_pytesseract(config)
        self._ocr_cache: dict[str, str] = {}

    @property
    def ocr_available(self) -> bool:
        if not self.ocr_enabled or self._pytesseract is None:
            return False
        try:
            self._pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def observe(self, screen: np.ndarray, state_hint: str = "unknown") -> GameObservation:
        screen_id = fingerprint(screen)
        text = self._ocr_screen(screen, screen_id)
        state, confidence, source = self._refine_state(state_hint, text)
        return GameObservation(
            state=state,
            state_confidence=confidence,
            state_source=source,
            screen_id=screen_id,
            ocr_text=text,
            visible_keywords=self._visible_keywords(text),
            regions=self._regions(),
        )

    def tooltip_crop(self, screen: np.ndarray, x: int, y: int) -> np.ndarray:
        height, width = screen.shape[:2]
        pad_x = int(width * 0.36)
        pad_y = int(height * 0.26)
        left = max(0, x - pad_x // 2)
        right = min(width, x + pad_x)
        top = max(0, y - pad_y)
        bottom = min(height, y + pad_y)
        return screen[top:bottom, left:right]

    def ocr_image(self, image: np.ndarray) -> str:
        if not self.ocr_available:
            return ""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.bilateralFilter(gray, 5, 55, 55)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        try:
            text = self._pytesseract.image_to_string(thresh, config="--psm 6")
        except Exception:
            return ""
        return " ".join(text.split())

    def _ocr_screen(self, screen: np.ndarray, screen_id: str) -> str:
        if screen_id in self._ocr_cache:
            return self._ocr_cache[screen_id]
        if not self.ocr_available:
            return ""

        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.bilateralFilter(gray, 5, 55, 55)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        try:
            text = self._pytesseract.image_to_string(thresh, config="--psm 11")
        except Exception:
            text = ""

        cleaned = " ".join(text.split())
        self._ocr_cache[screen_id] = cleaned
        if len(self._ocr_cache) > self.ocr_cache_size:
            oldest_key = next(iter(self._ocr_cache))
            self._ocr_cache.pop(oldest_key, None)
        return cleaned

    def _refine_state(self, state_hint: str, text: str) -> tuple[str, float, str]:
        if not self.keyword_state_detection or not text:
            return state_hint, 0.55 if state_hint != "unknown" else 0.25, "visual_classifier"

        lowered = text.lower()
        keyword_states = [
            ("defeat", ("defeat", "defeated", "game over", "retry", "restart run")),
            ("tavern", ("tavern", "drink", "inn")),
            ("storage", ("storage", "inventory", "stash")),
            ("forge", ("forge", "upgrade", "blacksmith")),
            ("recruit_dwarves", ("recruit", "hire", "available dwar")),
            ("loot", ("loot", "shop", "buy", "reroll")),
            ("raid", ("raid", "boss")),
            ("battle_report", ("victory", "rewards", "claim", "continue")),
            ("battle_select", ("choose battle", "select battle", "fight")),
        ]
        for state, keywords in keyword_states:
            if any(keyword in lowered for keyword in keywords):
                return state, 0.78, "ocr_keywords"
        return state_hint, 0.55 if state_hint != "unknown" else 0.25, "visual_classifier"

    def _visible_keywords(self, text: str) -> tuple[str, ...]:
        lowered = text.lower()
        words = (
            "start",
            "fight",
            "continue",
            "claim",
            "retry",
            "upgrade",
            "buy",
            "equip",
            "reroll",
            "recruit",
            "loot",
            "storage",
            "forge",
            "tavern",
            "raid",
            "sell",
            "delete",
            "retire",
            "reset",
            "remove",
            "relic",
            "artifact",
            "set",
        )
        return tuple(word for word in words if word in lowered)

    def _regions(self) -> dict[str, list[ScreenRegion]]:
        strategy = self.config.get("strategy", {})
        bottom_menu = [
            ScreenRegion(name=name, kind="bottom_menu", x_ratio=float(x_ratio), y_ratio=0.955)
            for name, x_ratio in strategy.get("bottom_menu", {}).items()
        ]
        inventory_slots = [
            ScreenRegion(
                name=f"inventory_row1_slot_{index}",
                kind="inventory_slot",
                x_ratio=float(coords[0]),
                y_ratio=float(coords[1]),
            )
            for index, coords in enumerate(strategy.get("inventory_slots", {}).get("row1", []), start=1)
            if len(coords) >= 2
        ]
        dwarf_cards = [
            ScreenRegion(name=name, kind="dwarf_card", x_ratio=float(coords[0]), y_ratio=float(coords[1]), width_ratio=0.07, height_ratio=0.16)
            for name, coords in strategy.get("equip_targets", {}).items()
            if len(coords) >= 2
        ]
        relic_slots = [
            ScreenRegion(name=name, kind="relic_slot", x_ratio=float(coords[0]), y_ratio=float(coords[1]), width_ratio=0.03, height_ratio=0.04)
            for name, coords in strategy.get("relic_targets", {}).items()
            if len(coords) >= 2
        ]
        battle_cards = [
            ScreenRegion(name="battle_card_left", kind="battle_card", x_ratio=0.245, y_ratio=0.285, width_ratio=0.22, height_ratio=0.35),
            ScreenRegion(name="battle_card_center", kind="battle_card", x_ratio=0.500, y_ratio=0.285, width_ratio=0.22, height_ratio=0.35),
            ScreenRegion(name="battle_card_right", kind="battle_card", x_ratio=0.755, y_ratio=0.285, width_ratio=0.22, height_ratio=0.35),
        ]
        resources = [
            ScreenRegion(name="top_resources", kind="resources", x_ratio=0.500, y_ratio=0.075, width_ratio=0.80, height_ratio=0.11),
        ]
        return {
            "bottom_menu": bottom_menu,
            "inventory_slots": inventory_slots,
            "dwarf_cards": dwarf_cards,
            "relic_slots": relic_slots,
            "battle_cards": battle_cards,
            "resources": resources,
        }
