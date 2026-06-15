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


@dataclass(frozen=True)
class StrategyDecision:
    state: str
    action: StrategyActionSpec
    goal: str
    rationale: str
    risks: list[str]
    build_priorities: list[str]
    source_basis: list[str]


class KnowledgeStrategy:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config.get("strategy", {})
        self.baseline = load_baseline()
        self.video_baseline = self._load_yaml(root / "knowledge" / "video_baseline.yaml")
        self.macro_enabled = bool(self.config.get("economy_cycle_enabled", True))
        self.macro_index = 0
        self.macro_sequence = self._build_macro_sequence()

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
        if self.macro_enabled and state in {"main_hall", "shop_menu", "unknown"}:
            return [self.current_macro_action()]

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

    def consult(self, state: str, state_elapsed: float, action: StrategyActionSpec) -> StrategyDecision:
        return StrategyDecision(
            state=state,
            action=action,
            goal=self._goal_for_action(action.name, state),
            rationale=self._rationale_for_action(action.name, state, state_elapsed),
            risks=self._risks_for_action(action.name, state),
            build_priorities=self._build_priorities_for_action(action.name, state),
            source_basis=self._source_basis_for_state(state),
        )

    def note_action_chosen(self, action_name: str, state: str) -> None:
        if not self.macro_enabled:
            return
        current = self.current_macro_action()
        if action_name == current.name and state in {"main_hall", "shop_menu", "unknown"}:
            self.macro_index = (self.macro_index + 1) % len(self.macro_sequence)

    def force_rotate_after(self, state: str) -> float:
        return {
            "main_hall": 8.0,
            "shop_menu": 6.0,
            "battle_select": 8.0,
            "battle_report": 5.0,
        }.get(state, 9999.0)

    def current_macro_action(self) -> StrategyActionSpec:
        return self.macro_sequence[self.macro_index % len(self.macro_sequence)]

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

    def _goal_for_action(self, action_name: str, state: str) -> str:
        if action_name.startswith("nav_recruit") or action_name.startswith("recruit_"):
            return "increase roster size and role coverage"
        if action_name.startswith("nav_loot") or action_name.startswith("loot_"):
            return "buy or equip gear that improves profession/build power"
        if action_name.startswith("nav_forge") or action_name.startswith("forge_"):
            return "upgrade useful gear before pushing harder fights"
        if action_name.startswith("nav_storage") or action_name.startswith("storage_"):
            return "equip stored gear and preserve set-building options"
        if action_name.startswith("nav_tavern") or action_name.startswith("tavern_"):
            return "check long-term run/economy upgrades"
        if "battle" in action_name or state == "battle_select":
            return "advance the battle loop for gold, experience, and rewards"
        if state == "battle_report":
            return "claim rewards and return to run management"
        return "continue safe autonomous progression"

    def _rationale_for_action(self, action_name: str, state: str, state_elapsed: float) -> str:
        strategy = self.baseline.get("strategy_model", {})
        automation = strategy.get("automation_translation", [])
        shopping = strategy.get("shopping", [])
        early = strategy.get("early_game", [])

        if state == "battle_select":
            return "Video baseline shows battle cards as the normal transition into combat; baseline policy favors battle-loop progress when no OCR choice is available."
        if action_name.startswith(("nav_recruit", "recruit_")):
            return "Strategy baseline says early runs need enough dwarves and role coverage before loot optimization."
        if action_name.startswith(("nav_loot", "loot_", "nav_storage", "storage_", "nav_forge", "forge_")):
            return "Strategy baseline prioritizes buy/equip/upgrade actions and set-piece preservation before harder fights."
        if state == "battle_running":
            return "Battle is automated by the game; keeping speed high improves loop throughput while waiting for report/reward screens."
        if state == "battle_report":
            return "Rewards must be claimed to return to economy and battle selection."

        supporting = automation[:1] or early[:1] or shopping[:1]
        return supporting[0] if supporting else f"State {state} has been stable for {state_elapsed:.1f}s; use configured safe progression action."

    def _risks_for_action(self, action_name: str, state: str) -> list[str]:
        risks = ["no OCR yet, so exact item/unit quality cannot be verified"]
        if action_name.startswith(("loot_", "forge_", "storage_", "recruit_", "tavern_")):
            risks.append("broad click may select a suboptimal item/unit or miss the intended button")
        if action_name.startswith("nav_raid"):
            risks.append("raid content may be harder than regular battles")
        if state == "battle_select":
            risks.append("battle card difficulty/reward is not read yet")
        return risks

    def _build_priorities_for_action(self, action_name: str, state: str) -> list[str]:
        sets = self.baseline.get("item_set_priorities", {})
        professions = self.baseline.get("professions", {})
        strategy = self.baseline.get("strategy_model", {})
        priorities = []

        if action_name.startswith(("nav_recruit", "recruit_")):
            priorities.extend(professions.get("baseline_priority", [])[:3])
        elif action_name.startswith(("nav_loot", "loot_", "nav_forge", "forge_", "nav_storage", "storage_")):
            priorities.extend(sets.get("notes", [])[:2])
            priorities.append("target S-tier sets: " + ", ".join(sets.get("s_tier", [])[:6]))
        elif state in {"battle_select", "battle_running", "battle_report"}:
            priorities.extend(strategy.get("early_game", [])[:2])
        else:
            priorities.extend(strategy.get("team_baseline", [])[:2])

        return [item for item in priorities if item]

    def _source_basis_for_state(self, state: str) -> list[str]:
        coverage = self.baseline.get("source_coverage", {})
        video_samples = self.video_baseline.get("total_samples", 0)
        return [
            f"{sum(coverage.values())} web/wiki/reddit/Steam sources",
            f"{video_samples} sampled tutorial-video frames",
            f"state={state}",
        ]

    def _build_macro_sequence(self) -> list[StrategyActionSpec]:
        configured_nav = self.config.get("bottom_menu", {})
        nav = {
            "tavern": float(configured_nav.get("tavern_3", 0.347)),
            "storage": float(configured_nav.get("storage_4", 0.400)),
            "forge": float(configured_nav.get("forge_5", 0.452)),
            "main_hall": float(configured_nav.get("main_hall_6", 0.505)),
            "recruit": float(configured_nav.get("recruit_dwarves_7", 0.556)),
            "loot": float(configured_nav.get("loot_8", 0.608)),
            "battle": float(configured_nav.get("battle_9", 0.660)),
            "raid": float(configured_nav.get("raid_0", 0.714)),
        }
        return [
            StrategyActionSpec("nav_recruit_dwarves", nav["recruit"], 0.955, 1.0, 0.8),
            StrategyActionSpec("recruit_try_left", 0.300, 0.500, 1.0, 0.5),
            StrategyActionSpec("recruit_try_center", 0.500, 0.500, 1.0, 0.5),
            StrategyActionSpec("recruit_try_right", 0.700, 0.500, 1.0, 0.5),
            StrategyActionSpec("nav_loot", nav["loot"], 0.955, 1.0, 0.8),
            StrategyActionSpec("loot_try_left", 0.320, 0.500, 1.0, 0.5),
            StrategyActionSpec("loot_try_center", 0.500, 0.500, 1.0, 0.5),
            StrategyActionSpec("loot_try_right", 0.680, 0.500, 1.0, 0.5),
            StrategyActionSpec("nav_forge", nav["forge"], 0.955, 1.0, 0.8),
            StrategyActionSpec("forge_try_upgrade_center", 0.500, 0.520, 1.0, 0.5),
            StrategyActionSpec("forge_try_upgrade_right", 0.680, 0.520, 1.0, 0.5),
            StrategyActionSpec("nav_storage", nav["storage"], 0.955, 1.0, 0.8),
            StrategyActionSpec("storage_try_equip_left", 0.350, 0.500, 1.0, 0.5),
            StrategyActionSpec("storage_try_equip_center", 0.500, 0.500, 1.0, 0.5),
            StrategyActionSpec("nav_tavern", nav["tavern"], 0.955, 1.0, 0.8),
            StrategyActionSpec("tavern_try_middle", 0.500, 0.500, 1.0, 0.5),
            StrategyActionSpec("nav_main_hall", nav["main_hall"], 0.955, 1.0, 0.8),
            StrategyActionSpec("nav_battle", nav["battle"], 0.955, 1.0, 0.8),
            StrategyActionSpec("open_battle_select_swords", 0.500, 0.555, 1.0, 0.8),
            StrategyActionSpec("nav_raid_probe", nav["raid"], 0.955, 1.0, 0.8),
            StrategyActionSpec("nav_battle_again", nav["battle"], 0.955, 1.0, 0.8),
        ]

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
            return value if isinstance(value, dict) else {}
