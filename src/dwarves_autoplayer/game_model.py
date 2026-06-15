from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Unit:
    name: str = ""
    profession: str = "unknown"
    role: str = "unknown"
    level: int = 1
    equipped_sets: list[str] = field(default_factory=list)


@dataclass
class GearItem:
    name: str = ""
    slot: str = "unknown"
    set_name: str = ""
    role_hint: str = "unknown"
    score: float = 0.0


@dataclass
class RelicItem:
    name: str = ""
    role_hint: str = "unknown"
    effect_text: str = ""
    score: float = 0.0


@dataclass
class RunMemory:
    victories: int = 0
    gold: int = 0
    units: list[Unit] = field(default_factory=list)
    gear_seen: list[GearItem] = field(default_factory=list)
    relics_seen: list[RelicItem] = field(default_factory=list)
    tooltip_text_seen: list[str] = field(default_factory=list)
    chosen_build: str = "balanced_core"
    updated_at: float = field(default_factory=time.time)


class GameMemory:
    def __init__(self, root: Path) -> None:
        self.path = root / "learning_data" / "game_memory.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.memory = self._load()

    def snapshot(self) -> RunMemory:
        return self.memory

    def note_goal(self, goal: str) -> None:
        self.memory.updated_at = time.time()
        self._save()

    def _load(self) -> RunMemory:
        if not self.path.exists():
            return RunMemory()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return RunMemory(
                victories=int(data.get("victories", 0)),
                gold=int(data.get("gold", 0)),
                units=[Unit(**item) for item in data.get("units", [])],
                gear_seen=[GearItem(**item) for item in data.get("gear_seen", [])],
                relics_seen=[RelicItem(**item) for item in data.get("relics_seen", [])],
                tooltip_text_seen=[str(item) for item in data.get("tooltip_text_seen", [])],
                chosen_build=str(data.get("chosen_build", "balanced_core")),
                updated_at=float(data.get("updated_at", time.time())),
            )
        except (OSError, ValueError, TypeError):
            return RunMemory()

    def _save(self) -> None:
        self.path.write_text(json.dumps(asdict(self.memory), indent=2, sort_keys=True), encoding="utf-8")

    def note_tooltip(self, text: str) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        if cleaned not in self.memory.tooltip_text_seen:
            self.memory.tooltip_text_seen.append(cleaned)
            self.memory.tooltip_text_seen = self.memory.tooltip_text_seen[-200:]
        if self._looks_like_relic(cleaned):
            self._note_relic(cleaned)
        elif self._looks_like_gear(cleaned):
            self._note_gear(cleaned)
        self.memory.updated_at = time.time()
        self._save()

    def _looks_like_relic(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ("relic", "artifact", "artifacts", "trinket"))

    def _looks_like_gear(self, text: str) -> bool:
        lowered = text.lower()
        gear_words = (
            "helmet",
            "armor",
            "gloves",
            "boots",
            "weapon",
            "axe",
            "sword",
            "staff",
            "bow",
            "shield",
            "set",
            "damage",
            "health",
            "armor",
            "strength",
            "intelligence",
            "dexterity",
        )
        return any(word in lowered for word in gear_words)

    def _note_relic(self, text: str) -> None:
        if any(item.effect_text == text for item in self.memory.relics_seen):
            return
        self.memory.relics_seen.append(RelicItem(name="", effect_text=text))
        self.memory.relics_seen = self.memory.relics_seen[-100:]

    def _note_gear(self, text: str) -> None:
        if any(item.name == text for item in self.memory.gear_seen):
            return
        self.memory.gear_seen.append(GearItem(name=text))
        self.memory.gear_seen = self.memory.gear_seen[-150:]


@dataclass(frozen=True)
class ItemEvaluation:
    kind: str
    role_hint: str
    score: float
    reasons: tuple[str, ...]
    matched_sets: tuple[str, ...]


class BuildPlanner:
    def __init__(self, baseline: dict[str, Any]) -> None:
        self.baseline = baseline

    def roster_needs(self, memory: RunMemory) -> list[str]:
        units = memory.units
        roles = [unit.role for unit in units]
        needs: list[str] = []
        if len(units) < 3:
            needs.append("recruit additional dwarves until the roster has at least three units")
        if "frontline" not in roles:
            needs.append("add or protect a durable frontline unit")
        if "support" not in roles:
            needs.append("add healer/support sustain before longer fights")
        if "damage" not in roles:
            needs.append("add a clear physical or magical damage carry")
        return needs or ["improve current roster quality through gear and set synergy"]

    def gear_targets(self, memory: RunMemory) -> list[str]:
        sets = self.baseline.get("item_set_priorities", {})
        role_targets = sets.get("role_targets", {})
        chosen = memory.chosen_build
        if chosen == "sustain_core":
            return role_targets.get("tank", []) + role_targets.get("healer", [])
        if chosen == "mage_fire_core":
            return role_targets.get("mage", [])
        return sets.get("s_tier", [])[:6]

    def relic_targets(self, memory: RunMemory) -> list[str]:
        return [
            "damage scaling relics for carry units",
            "health/armor/block relics for frontline units",
            "healing, mana, cooldown, or support relics for sustain units",
            "set-synergy relics or artifacts that reinforce the chosen build",
        ]

    def evaluate_tooltip(self, text: str, memory: RunMemory) -> ItemEvaluation:
        lowered = text.lower()
        reasons: list[str] = []
        matched_sets: list[str] = []
        score = 0.0

        kind = "unknown"
        if any(word in lowered for word in ("relic", "artifact", "artifacts", "trinket")):
            kind = "relic"
            score += 2.0
            reasons.append("tooltip looks like a relic/artifact")
        elif any(
            word in lowered
            for word in (
                "helmet",
                "armor",
                "gloves",
                "boots",
                "weapon",
                "axe",
                "sword",
                "staff",
                "bow",
                "shield",
                "set",
            )
        ):
            kind = "gear"
            score += 1.5
            reasons.append("tooltip looks like equippable gear")

        role_hint = self._role_hint(lowered)
        if role_hint != "unknown":
            score += 1.0
            reasons.append(f"role fit: {role_hint}")

        sets = self.baseline.get("item_set_priorities", {})
        for tier_name, tier_score in (("s_tier", 4.0), ("a_tier", 2.0)):
            for set_name in sets.get(tier_name, []):
                if set_name.lower() in lowered:
                    matched_sets.append(set_name)
                    score += tier_score
                    reasons.append(f"{tier_name.replace('_', '-')} set: {set_name}")

        for set_name in self.gear_targets(memory):
            if set_name.lower() in lowered:
                score += 2.0
                reasons.append(f"current build target: {set_name}")

        if any(word in lowered for word in ("common", "broken", "rusty", "cracked")):
            score -= 1.0
            reasons.append("low-quality wording")

        if any(word in lowered for word in ("remove", "unequip", "empty", "sell")):
            score -= 10.0
            reasons.append("dangerous/destructive wording")

        return ItemEvaluation(
            kind=kind,
            role_hint=role_hint,
            score=score,
            reasons=tuple(reasons),
            matched_sets=tuple(matched_sets),
        )

    def target_role_order(self, role_hint: str) -> list[str]:
        if role_hint in {"tank", "frontline"}:
            return ["tank", "frontline", "healer", "carry", "support", "flex"]
        if role_hint in {"healer", "support", "sustain"}:
            return ["healer", "support", "tank", "frontline", "flex", "carry"]
        if role_hint in {"mage", "magic"}:
            return ["magic_carry", "carry", "support", "flex", "frontline"]
        if role_hint in {"archer", "thief", "damage", "carry"}:
            return ["carry", "magic_carry", "support", "flex", "frontline"]
        return ["frontline", "carry", "healer", "support", "magic_carry", "flex"]

    def _role_hint(self, lowered: str) -> str:
        if any(word in lowered for word in ("block", "armor", "health", "defense", "taunt", "shield")):
            return "tank"
        if any(word in lowered for word in ("heal", "healing", "priest", "support", "mana", "cooldown")):
            return "healer"
        if any(word in lowered for word in ("spell", "magic", "intelligence", "fire", "storm", "frost", "mage")):
            return "mage"
        if any(word in lowered for word in ("critical", "crit", "bleed", "assassin", "thief", "dexterity")):
            return "carry"
        if any(word in lowered for word in ("damage", "strength", "executioner", "warrior", "attack")):
            return "damage"
        return "unknown"

    def action_guidance(self, action_name: str, memory: RunMemory) -> list[str]:
        if action_name.startswith(("nav_recruit", "recruit_")):
            return self.roster_needs(memory)
        if action_name.startswith(("nav_loot", "loot_", "nav_storage", "storage_")):
            targets = ", ".join(self.gear_targets(memory))
            return [
                "equip set pieces on units that match their role",
                "fill both relic/artifact slots on each core dwarf when useful relics are visible",
                f"prefer set targets when visible: {targets}",
                "avoid breaking useful partial sets unless replacing with a stronger role fit",
            ]
        if action_name.startswith(("nav_forge", "forge_")):
            return [
                "upgrade gear already equipped on core frontline, healer, or carry units",
                "upgrade or preserve impactful relic/artifact bonuses when available",
                "prefer set pieces over isolated filler gear",
            ]
        return []
