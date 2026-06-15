from __future__ import annotations

from pathlib import Path

from dwarves_autoplayer.game_model import BuildPlanner, GameMemory
from dwarves_autoplayer.baseline import load_baseline


def main() -> None:
    memory = GameMemory(Path.cwd()).snapshot()
    planner = BuildPlanner(load_baseline())
    print(f"chosen_build: {memory.chosen_build}")
    print(f"victories: {memory.victories}")
    print(f"gold: {memory.gold}")
    print(f"units: {len(memory.units)}")
    for unit in memory.units:
        print(f"  - {unit.name or '(unknown)'} {unit.profession} {unit.role} sets={', '.join(unit.equipped_sets) or 'none'}")

    print("roster_needs:")
    for item in planner.roster_needs(memory):
        print(f"  - {item}")

    print("gear_targets:")
    for item in planner.gear_targets(memory):
        print(f"  - {item}")

    print("relic_targets:")
    for item in planner.relic_targets(memory):
        print(f"  - {item}")

    print(f"relics_seen: {len(memory.relics_seen)}")
    for item in memory.relics_seen[-10:]:
        print(f"  - {item.name or '(unknown relic)'} {item.effect_text[:120]}")

    print("recent_tooltips:")
    for item in memory.tooltip_text_seen[-10:]:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
