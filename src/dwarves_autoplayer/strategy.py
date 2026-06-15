from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dwarves_autoplayer.baseline import load_baseline


@dataclass(frozen=True)
class StrategyActionSpec:
    name: str
    x_ratio: float
    y_ratio: float
    cooldown_seconds: float
    after_delay_seconds: float = 0.75


class KnowledgeStrategy:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config.get("strategy", {})
        self.baseline = load_baseline()
        self.video_baseline = self._load_yaml(root / "knowledge" / "video_baseline.yaml")

    def summary(self) -> dict[str, Any]:
        sources = self.baseline.get("sources", [])
        sets = self.baseline.get("item_set_priorities", {})
        video_counts = self.video_baseline.get("aggregate_state_counts", {})
        return {
            "sources": len(sources),
            "source_coverage": self.baseline.get("source_coverage", {}),
            "s_tier_sets": sets.get("s_tier", []),
            "video_samples": self.video_baseline.get("total_samples", 0),
            "video_states": video_counts,
        }

    def actions_for_state(self, state: str, state_elapsed: float) -> list[StrategyActionSpec]:
        if state == "main_hall":
            return [
                StrategyActionSpec("open_battle_select_bottom", 0.660, 0.955, 3.0),
                StrategyActionSpec("open_battle_select_swords", 0.500, 0.555, 4.0),
                StrategyActionSpec("open_battle_select_right", 0.890, 0.555, 4.0),
            ]

        if state == "shop_menu":
            return [
                StrategyActionSpec("shop_to_battle_tab", 0.600, 0.955, 3.0),
                StrategyActionSpec("shop_to_battle_right_nav", 0.930, 0.500, 4.0),
            ]

        if state == "battle_select":
            return self._battle_select_actions()

        if state == "battle_running":
            return [StrategyActionSpec("battle_speed_up", 0.945, 0.965, 12.0, 0.35)]

        if state == "battle_report":
            return [
                StrategyActionSpec("battle_report_next", 0.925, 0.875, 1.5, 1.0),
                StrategyActionSpec("battle_report_next_low", 0.925, 0.940, 1.5, 1.0),
            ]

        return []

    def force_rotate_after(self, state: str) -> float:
        return {
            "main_hall": 8.0,
            "shop_menu": 6.0,
            "battle_select": 8.0,
            "battle_report": 5.0,
        }.get(state, 9999.0)

    def _battle_select_actions(self) -> list[StrategyActionSpec]:
        preference = self.config.get("battle_card_preference", "center_left_right")
        cards = {
            "left": StrategyActionSpec("choose_left_battle", 0.245, 0.285, 2.5, 1.2),
            "center": StrategyActionSpec("choose_center_battle", 0.500, 0.285, 2.5, 1.2),
            "right": StrategyActionSpec("choose_right_battle", 0.755, 0.285, 2.5, 1.2),
        }
        orders = {
            "center_left_right": ["center", "left", "right"],
            "left_center_right": ["left", "center", "right"],
            "right_center_left": ["right", "center", "left"],
        }
        return [cards[name] for name in orders.get(preference, orders["center_left_right"])]

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
            return value if isinstance(value, dict) else {}

