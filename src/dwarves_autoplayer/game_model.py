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
class RunMemory:
    victories: int = 0
    gold: int = 0
    units: list[Unit] = field(default_factory=list)
    gear_seen: list[GearItem] = field(default_factory=list)
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
                chosen_build=str(data.get("chosen_build", "balanced_core")),
                updated_at=float(data.get("updated_at", time.time())),
            )
        except (OSError, ValueError, TypeError):
            return RunMemory()

    def _save(self) -> None:
        self.path.write_text(json.dumps(asdict(self.memory), indent=2, sort_keys=True), encoding="utf-8")


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

    def action_guidance(self, action_name: str, memory: RunMemory) -> list[str]:
        if action_name.startswith(("nav_recruit", "recruit_")):
            return self.roster_needs(memory)
        if action_name.startswith(("nav_loot", "loot_", "nav_storage", "storage_")):
            targets = ", ".join(self.gear_targets(memory))
            return [
                "equip set pieces on units that match their role",
                f"prefer set targets when visible: {targets}",
                "avoid breaking useful partial sets unless replacing with a stronger role fit",
            ]
        if action_name.startswith(("nav_forge", "forge_")):
            return [
                "upgrade gear already equipped on core frontline, healer, or carry units",
                "prefer set pieces over isolated filler gear",
            ]
        return []

