from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dwarves_autoplayer.baseline import load_baseline
from dwarves_autoplayer.game_model import BuildPlanner, GameMemory


@dataclass(frozen=True)
class StrategyActionSpec:
    name: str
    x_ratio: float
    y_ratio: float
    cooldown_seconds: float
    after_delay_seconds: float = 0.75
    action_type: str = "click"
    target_x_ratio: float | None = None
    target_y_ratio: float | None = None


@dataclass(frozen=True)
class StrategyDecision:
    state: str
    action: StrategyActionSpec
    goal: str
    rationale: str
    risks: list[str]
    build_priorities: list[str]
    source_basis: list[str]


@dataclass(frozen=True)
class SmartEquipPlan:
    target_name: str
    target_x_ratio: float
    target_y_ratio: float
    kind: str
    score: float
    reasons: tuple[str, ...]


class KnowledgeStrategy:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config.get("strategy", {})
        self.baseline = load_baseline()
        self.video_baseline = self._load_yaml(root / "knowledge" / "video_baseline.yaml")
        self.memory = GameMemory(root)
        self.planner = BuildPlanner(self.baseline)
        self.macro_enabled = bool(self.config.get("economy_cycle_enabled", True))
        self.macro_index = 0
        self.target_cursors: dict[str, int] = {}
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
            "chosen_build": self.memory.snapshot().chosen_build,
            "roster_size": len(self.memory.snapshot().units),
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
        self.memory.note_goal(self._goal_for_action(action_name, state))
        if not self.macro_enabled:
            return
        current = self.current_macro_action()
        if action_name == current.name and state in {"main_hall", "shop_menu", "unknown"}:
            self.macro_index = (self.macro_index + 1) % len(self.macro_sequence)

    def should_probe_tooltip(self, action_name: str) -> bool:
        return action_name.startswith(
            (
                "equip_",
                "recruit_",
                "loot_",
                "forge_",
                "storage_",
                "tavern_",
                "nav_recruit",
                "nav_loot",
                "nav_forge",
                "nav_storage",
            )
        )

    def note_tooltip(self, action_name: str, text: str) -> None:
        self.memory.note_tooltip(text)

    def should_skip_for_tooltip(self, action_name: str, text: str) -> bool:
        lowered = text.lower()
        avoid_words = self.baseline.get("ui_priorities", {}).get("avoid", [])
        hard_avoid = set(avoid_words) | {"sell", "delete", "retire", "reset", "remove", "discard", "new clan"}
        return any(word in lowered for word in hard_avoid)

    def tooltip_matches_priorities(self, text: str) -> list[str]:
        lowered = text.lower()
        matches: list[str] = []
        if any(word in lowered for word in ("relic", "artifact", "artifacts", "trinket")):
            matches.append("relic/artifact candidate")
        sets = self.baseline.get("item_set_priorities", {})
        for set_name in sets.get("s_tier", []) + sets.get("a_tier", []):
            if set_name.lower() in lowered:
                matches.append(f"set target: {set_name}")
        for role, role_sets in sets.get("role_targets", {}).items():
            for set_name in role_sets:
                if set_name.lower() in lowered:
                    matches.append(f"{role} set target: {set_name}")
        for profession in self.baseline.get("professions", {}).get("advanced_targets", []):
            if profession.lower() in lowered:
                matches.append(f"advanced profession target: {profession}")
        return matches

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
            return "buy or equip gear/relics that improve profession/build power"
        if action_name.startswith("nav_forge") or action_name.startswith("forge_"):
            return "upgrade useful gear before pushing harder fights"
        if action_name.startswith("nav_storage") or action_name.startswith("storage_"):
            return "equip stored gear/relics and preserve set-building options"
        if action_name.startswith("equip_"):
            return "equip gear or relics onto dwarves to activate stats, roles, and set bonuses"
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
        if action_name.startswith(("nav_loot", "loot_", "nav_storage", "storage_", "nav_forge", "forge_", "equip_")):
            return "Strategy baseline prioritizes buy/equip/upgrade actions, relic/artifact slots, and set-piece preservation before harder fights; tooltips are probed before risky gear clicks."
        if state == "battle_running":
            return "Battle is automated by the game; keeping speed high improves loop throughput while waiting for report/reward screens."
        if state == "battle_report":
            return "Rewards must be claimed to return to economy and battle selection."

        supporting = automation[:1] or early[:1] or shopping[:1]
        return supporting[0] if supporting else f"State {state} has been stable for {state_elapsed:.1f}s; use configured safe progression action."

    def _risks_for_action(self, action_name: str, state: str) -> list[str]:
        risks = ["OCR quality controls whether item/unit choices can be trusted"]
        if action_name.startswith(("loot_", "forge_", "storage_", "recruit_", "tavern_", "equip_")):
            risks.append("bot skips smart equip when tooltip text is missing or scores below threshold")
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

        memory = self.memory.snapshot()
        priorities.extend(self.planner.action_guidance(action_name, memory))

        if action_name.startswith(("nav_recruit", "recruit_")):
            priorities.extend(professions.get("baseline_priority", [])[:3])
        elif action_name.startswith(("nav_loot", "loot_", "nav_forge", "forge_", "nav_storage", "storage_", "equip_")):
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
            StrategyActionSpec("nav_main_hall_for_equipping", nav["main_hall"], 0.955, 1.0, 0.8),
            *self._smart_equip_actions(),
            StrategyActionSpec("nav_tavern", nav["tavern"], 0.955, 1.0, 0.8),
            StrategyActionSpec("tavern_try_middle", 0.500, 0.500, 1.0, 0.5),
            StrategyActionSpec("nav_main_hall", nav["main_hall"], 0.955, 1.0, 0.8),
            StrategyActionSpec("nav_battle", nav["battle"], 0.955, 1.0, 0.8),
            StrategyActionSpec("open_battle_select_swords", 0.500, 0.555, 1.0, 0.8),
            StrategyActionSpec("nav_raid_probe", nav["raid"], 0.955, 1.0, 0.8),
            StrategyActionSpec("nav_battle_again", nav["battle"], 0.955, 1.0, 0.8),
        ]

    def plan_smart_equip(self, tooltip_text: str) -> SmartEquipPlan | None:
        if not tooltip_text:
            return None

        memory = self.memory.snapshot()
        evaluation = self.planner.evaluate_tooltip(tooltip_text, memory)
        min_score = float(self.config.get("min_equip_score", 2.0))
        if evaluation.kind not in {"gear", "relic"} or evaluation.score < min_score:
            return None

        target = self._best_target_for_evaluation(evaluation.kind, evaluation.role_hint)
        if target is None:
            return None

        target_name, coords = target
        return SmartEquipPlan(
            target_name=target_name,
            target_x_ratio=float(coords[0]),
            target_y_ratio=float(coords[1]),
            kind=evaluation.kind,
            score=evaluation.score,
            reasons=evaluation.reasons,
        )

    def _smart_equip_actions(self) -> list[StrategyActionSpec]:
        inventory_slots = self.config.get("inventory_slots", {}).get("row1", [])
        actions: list[StrategyActionSpec] = []
        for index, slot in enumerate(inventory_slots, start=1):
            if len(slot) < 2:
                break
            actions.append(
                StrategyActionSpec(
                    f"equip_inventory_slot_{index}_smart",
                    float(slot[0]),
                    float(slot[1]),
                    1.0,
                    0.6,
                    "smart_equip",
                )
            )
        return actions

    def _best_target_for_evaluation(self, kind: str, role_hint: str) -> tuple[str, list[float]] | None:
        if kind == "relic":
            return self._best_relic_target(role_hint)
        return self._best_gear_target(role_hint)

    def _best_gear_target(self, role_hint: str) -> tuple[str, list[float]] | None:
        equip_targets = self.config.get("equip_targets", {})
        roles = self.config.get("dwarf_roles", {})
        ordered_roles = self.planner.target_role_order(role_hint)
        return self._first_target_by_role(equip_targets, roles, ordered_roles)

    def _best_relic_target(self, role_hint: str) -> tuple[str, list[float]] | None:
        relic_targets = self.config.get("relic_targets", {})
        roles = self.config.get("dwarf_roles", {})
        ordered_roles = self.planner.target_role_order(role_hint)
        return self._first_target_by_role(relic_targets, roles, ordered_roles, relic=True)

    def _first_target_by_role(
        self,
        targets: dict[str, Any],
        roles: dict[str, str],
        ordered_roles: list[str],
        relic: bool = False,
    ) -> tuple[str, list[float]] | None:
        ordered_targets = self._ordered_targets(targets, "dwarf_")
        for role in ordered_roles:
            candidates = [
                (target_name, coords)
                for target_name, coords in ordered_targets
                if roles.get(target_name.split("_relic_", maxsplit=1)[0] if relic else target_name, "flex") == role
            ]
            if candidates:
                cursor_key = f"{'relic' if relic else 'gear'}:{role}"
                cursor = self.target_cursors.get(cursor_key, 0)
                self.target_cursors[cursor_key] = cursor + 1
                return candidates[cursor % len(candidates)]
        return ordered_targets[0] if ordered_targets else None

    def _ordered_targets(self, targets: dict[str, Any], prefix: str) -> list[tuple[str, list[float]]]:
        def sort_key(item: tuple[str, Any]) -> tuple[int, int]:
            name = item[0]
            parts = name.replace(prefix, "").split("_relic_")
            try:
                dwarf_index = int(parts[0])
            except ValueError:
                dwarf_index = 999
            relic_index = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            return dwarf_index, relic_index

        return [(name, value) for name, value in sorted(targets.items(), key=sort_key) if name.startswith(prefix)]

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
            return value if isinstance(value, dict) else {}
