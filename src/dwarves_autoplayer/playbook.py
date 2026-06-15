from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import cv2
import numpy as np

from dwarves_autoplayer.strategy import KnowledgeStrategy, StrategyDecision


class GameState(str, Enum):
    MAIN_HALL = "main_hall"
    SHOP_MENU = "shop_menu"
    BATTLE_SELECT = "battle_select"
    BATTLE_RUNNING = "battle_running"
    BATTLE_REPORT = "battle_report"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PlaybookAction:
    name: str
    x_ratio: float
    y_ratio: float
    cooldown_seconds: float
    after_delay_seconds: float = 0.75
    goal: str = ""
    rationale: str = ""
    risks: tuple[str, ...] = ()
    build_priorities: tuple[str, ...] = ()
    source_basis: tuple[str, ...] = ()


class DwarvesPlaybook:
    def __init__(self, config: dict[str, Any], strategy: KnowledgeStrategy) -> None:
        self.config = config.get("state_playbook", {})
        self.enabled = bool(self.config.get("enabled", True))
        self.strategy = strategy
        self.last_action_at: dict[str, float] = {}
        self.last_state: GameState | None = None
        self.state_seen_at = time.monotonic()
        self.state_action_index: dict[GameState, int] = {}

    def classify(self, screen: np.ndarray) -> GameState:
        if self._looks_like_battle_report(screen):
            return GameState.BATTLE_REPORT
        if self._looks_like_battle_select(screen):
            return GameState.BATTLE_SELECT
        if self._looks_like_battle_running(screen):
            return GameState.BATTLE_RUNNING
        if self._looks_like_shop_menu(screen):
            return GameState.SHOP_MENU
        if self._looks_like_main_hall(screen):
            return GameState.MAIN_HALL
        return GameState.UNKNOWN

    def choose_action(self, screen: np.ndarray) -> PlaybookAction | None:
        if not self.enabled:
            return None

        state = self.classify(screen)
        if state != self.last_state:
            logging.info("State changed: %s -> %s", self.last_state.value if self.last_state else "none", state.value)
            self.last_state = state
            self.state_seen_at = time.monotonic()

        action = self._action_for_state(screen, state)
        if not action:
            return None

        now = time.monotonic()
        if now - self.last_action_at.get(action.name, 0.0) < action.cooldown_seconds:
            return None

        self.last_action_at[action.name] = now
        self.strategy.note_action_chosen(action.name, state.value)
        return action

    def _action_for_state(self, screen: np.ndarray, state: GameState) -> PlaybookAction | None:
        state_elapsed = time.monotonic() - self.state_seen_at
        specs = self.strategy.actions_for_state(state.value, state_elapsed)
        if not specs:
            return None
        decisions = [self.strategy.consult(state.value, state_elapsed, spec) for spec in specs]
        return self._rotate(
            state,
            [self._to_playbook_action(decision) for decision in decisions],
            force_rotate=state_elapsed > self.strategy.force_rotate_after(state.value),
        )

    def _rotate(self, state: GameState, actions: list[PlaybookAction], force_rotate: bool = False) -> PlaybookAction:
        index = self.state_action_index.get(state, 0)
        if force_rotate:
            index += 1
        action = actions[index % len(actions)]
        self.state_action_index[state] = index + 1
        return action

    def _to_playbook_action(self, decision: StrategyDecision) -> PlaybookAction:
        spec = decision.action
        return PlaybookAction(
            name=spec.name,
            x_ratio=spec.x_ratio,
            y_ratio=spec.y_ratio,
            cooldown_seconds=spec.cooldown_seconds,
            after_delay_seconds=spec.after_delay_seconds,
            goal=decision.goal,
            rationale=decision.rationale,
            risks=tuple(decision.risks),
            build_priorities=tuple(decision.build_priorities),
            source_basis=tuple(decision.source_basis),
        )

    def _looks_like_main_hall(self, screen: np.ndarray) -> bool:
        height, _ = screen.shape[:2]
        upper = screen[int(height * 0.18) : int(height * 0.52), :]
        lower = screen[int(height * 0.58) : int(height * 0.90), :]
        if upper.size == 0 or lower.size == 0:
            return False

        upper_edges = self._edge_mean(upper)
        lower_edges = self._edge_mean(lower)
        green_ratio = self._color_ratio(screen, lower_hsv=(40, 30, 30), upper_hsv=(95, 255, 255))
        return upper_edges > 12 and lower_edges > 10 and green_ratio < 0.28

    def _looks_like_battle_select(self, screen: np.ndarray) -> bool:
        height, width = screen.shape[:2]
        middle = screen[int(height * 0.22) : int(height * 0.86), int(width * 0.08) : int(width * 0.92)]
        top = screen[int(height * 0.05) : int(height * 0.20), int(width * 0.25) : int(width * 0.75)]
        red_header = self._color_ratio(middle, lower_hsv=(0, 35, 45), upper_hsv=(12, 190, 190))
        gold = self._color_ratio(middle, lower_hsv=(15, 80, 90), upper_hsv=(45, 255, 255))
        top_blue_gray = self._color_ratio(top, lower_hsv=(90, 20, 50), upper_hsv=(115, 160, 210))
        card_edges = self._edge_mean(middle)
        normal_cards = top_blue_gray > 0.35 and red_header > 0.055 and gold > 0.030 and card_edges > 11
        tooltip_cards = top_blue_gray > 0.35 and red_header > 0.008 and gold > 0.080 and card_edges > 20
        return normal_cards or tooltip_cards

    def _looks_like_shop_menu(self, screen: np.ndarray) -> bool:
        height, width = screen.shape[:2]
        top = screen[int(height * 0.05) : int(height * 0.20), int(width * 0.25) : int(width * 0.75)]
        middle = screen[int(height * 0.22) : int(height * 0.86), int(width * 0.08) : int(width * 0.92)]
        bottom = screen[int(height * 0.88) :, :]
        top_blue_gray = self._color_ratio(top, lower_hsv=(90, 20, 50), upper_hsv=(115, 160, 210))
        mid_edges = self._edge_mean(middle)
        mid_gold = self._color_ratio(middle, lower_hsv=(15, 80, 90), upper_hsv=(45, 255, 255))
        bottom_gold = self._color_ratio(bottom, lower_hsv=(15, 80, 90), upper_hsv=(45, 255, 255))
        return top_blue_gray > 0.45 and mid_edges < 10.0 and mid_gold < 0.025 and bottom_gold > 0.015

    def _looks_like_battle_running(self, screen: np.ndarray) -> bool:
        height, width = screen.shape[:2]
        center = screen[int(height * 0.18) : int(height * 0.78), int(width * 0.10) : int(width * 0.90)]
        top = screen[int(height * 0.05) : int(height * 0.20), int(width * 0.25) : int(width * 0.75)]
        bottom = screen[int(height * 0.82) :, :]
        green = self._color_ratio(center, lower_hsv=(35, 35, 25), upper_hsv=(95, 255, 230))
        top_green = self._color_ratio(top, lower_hsv=(35, 35, 25), upper_hsv=(95, 255, 230))
        panel_dark = self._color_ratio(center, lower_hsv=(0, 0, 0), upper_hsv=(179, 90, 90))
        bottom_gold = self._color_ratio(bottom, lower_hsv=(15, 80, 90), upper_hsv=(45, 255, 255))
        return top_green > 0.25 and green > 0.35 and panel_dark < 0.45 and bottom_gold > 0.005

    def _looks_like_battle_report(self, screen: np.ndarray) -> bool:
        height, width = screen.shape[:2]
        right_panel = screen[int(height * 0.20) : int(height * 0.82), int(width * 0.48) : int(width * 0.98)]
        lower_right = screen[int(height * 0.80) :, int(width * 0.82) :]
        dark_panel = self._color_ratio(right_panel, lower_hsv=(0, 0, 20), upper_hsv=(179, 90, 105))
        gold_button = self._color_ratio(lower_right, lower_hsv=(15, 80, 90), upper_hsv=(45, 255, 255))
        right_edges = self._edge_mean(right_panel)
        return dark_panel > 0.50 and gold_button > 0.020 and right_edges > 4

    def _edge_mean(self, image: np.ndarray) -> float:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return float(cv2.Canny(gray, 40, 120).mean())

    def _color_ratio(
        self,
        image: np.ndarray,
        lower_hsv: tuple[int, int, int],
        upper_hsv: tuple[int, int, int],
    ) -> float:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lower_hsv, dtype=np.uint8), np.array(upper_hsv, dtype=np.uint8))
        return float(np.count_nonzero(mask)) / float(mask.size)
