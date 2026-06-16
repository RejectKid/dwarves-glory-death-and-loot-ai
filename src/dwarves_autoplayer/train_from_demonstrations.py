from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path.cwd()


@dataclass(frozen=True)
class DemoClick:
    session_id: str
    state: str
    screen_id: str
    x_ratio: float
    y_ratio: float
    image_before: str
    ocr_text: str
    label: str
    tooltip_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="learning_data/demonstrations", help="Directory containing teach-mode sessions.")
    parser.add_argument("--output", default="knowledge/learned_policy.yaml", help="Policy YAML path to write.")
    parser.add_argument("--grid-size", type=int, default=24, help="Click clustering grid size for state fallback.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = ROOT / args.data_dir
    output = ROOT / args.output
    clicks = load_clicks(data_dir)
    metadata = load_metadata(data_dir)
    if not clicks:
        raise SystemExit(f"No teach-mode click events found under {data_dir}. Run teach_mode.bat and play first.")

    policy = build_policy(clicks, metadata, grid_size=args.grid_size)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(policy, sort_keys=False, allow_unicode=False), encoding="utf-8")

    print(f"wrote: {output}")
    print(f"sessions: {len(policy['sessions'])}")
    print(f"click events: {policy['click_events']}")
    print(f"screen actions: {len(policy['screen_actions'])}")
    print(f"state actions: {len(policy['state_actions'])}")


def load_clicks(data_dir: Path) -> list[DemoClick]:
    clicks: list[DemoClick] = []
    for events_path in sorted(data_dir.glob("*/events.csv")):
        with events_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("event_type") != "click":
                    continue
                state = str(row.get("state_before", "")).strip()
                screen_id = str(row.get("screen_id_before", "")).strip()
                x_ratio = _safe_float(row.get("x_ratio"))
                y_ratio = _safe_float(row.get("y_ratio"))
                if not state or not screen_id or x_ratio is None or y_ratio is None:
                    continue
                if not (0 <= x_ratio <= 1 and 0 <= y_ratio <= 1):
                    continue
                clicks.append(
                    DemoClick(
                        session_id=str(row.get("session_id", events_path.parent.name)),
                        state=state,
                        screen_id=screen_id,
                        x_ratio=x_ratio,
                        y_ratio=y_ratio,
                        image_before=str(row.get("image_before", "")),
                        ocr_text=str(row.get("ocr_text", "")),
                        label=str(row.get("label", "")),
                        tooltip_text=str(row.get("tooltip_text", "")),
                    )
                )
    return clicks


def load_metadata(data_dir: Path) -> dict[str, Any]:
    labels: dict[str, int] = defaultdict(int)
    tooltip_examples: list[dict[str, str]] = []
    for events_path in sorted(data_dir.glob("*/events.csv")):
        with events_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                label = str(row.get("label", "")).strip()
                if label:
                    labels[label] += 1
                tooltip_text = str(row.get("tooltip_text", "")).strip()
                if tooltip_text:
                    tooltip_examples.append(
                        {
                            "session_id": str(row.get("session_id", events_path.parent.name)),
                            "state": str(row.get("state_before", "")),
                            "label": label,
                            "tooltip_text": _excerpt(tooltip_text, limit=240),
                            "tooltip_image": str(row.get("tooltip_image", "")),
                        }
                    )
    return {
        "labels": dict(sorted(labels.items())),
        "tooltip_examples": tooltip_examples[-100:],
    }


def build_policy(clicks: list[DemoClick], metadata: dict[str, Any], grid_size: int) -> dict[str, Any]:
    screen_groups: dict[tuple[str, str], list[DemoClick]] = defaultdict(list)
    state_groups: dict[tuple[str, int, int], list[DemoClick]] = defaultdict(list)
    state_totals: dict[str, int] = defaultdict(int)

    for click in clicks:
        screen_groups[(click.state, click.screen_id)].append(click)
        grid_x = min(grid_size - 1, max(0, int(click.x_ratio * grid_size)))
        grid_y = min(grid_size - 1, max(0, int(click.y_ratio * grid_size)))
        state_groups[(click.state, grid_x, grid_y)].append(click)
        state_totals[click.state] += 1

    screen_actions = [_screen_action(state, screen_id, group) for (state, screen_id), group in screen_groups.items()]
    state_actions = [
        _state_action(state, grid_x, grid_y, group, state_totals[state])
        for (state, grid_x, grid_y), group in state_groups.items()
    ]
    click_heatmaps = _click_heatmaps(state_actions)

    screen_actions.sort(key=lambda item: (item["state"], -item["confidence"], -item["count"]))
    state_actions.sort(key=lambda item: (item["state"], -item["confidence"], -item["count"]))

    sessions = sorted({click.session_id for click in clicks})
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "Learned click policy from human teach-mode demonstrations.",
        "sessions": sessions,
        "click_events": len(clicks),
        "states": dict(sorted(state_totals.items())),
        "labels": metadata.get("labels", {}),
        "tooltip_examples": metadata.get("tooltip_examples", []),
        "click_heatmaps": click_heatmaps,
        "screen_actions": screen_actions,
        "state_actions": state_actions,
    }


def _screen_action(state: str, screen_id: str, group: list[DemoClick]) -> dict[str, Any]:
    count = len(group)
    return {
        "state": state,
        "screen_id": screen_id,
        "x_ratio": round(sum(item.x_ratio for item in group) / count, 5),
        "y_ratio": round(sum(item.y_ratio for item in group) / count, 5),
        "count": count,
        "confidence": round(min(0.95, 0.58 + 0.08 * (count - 1)), 3),
        "action_label": _best_label(group) or _infer_action_label(state, group[0].x_ratio, group[0].y_ratio),
        "example_image": group[0].image_before,
        "ocr_excerpt": _excerpt(group[0].ocr_text or group[0].tooltip_text),
    }


def _state_action(state: str, grid_x: int, grid_y: int, group: list[DemoClick], state_total: int) -> dict[str, Any]:
    count = len(group)
    share = count / max(state_total, 1)
    return {
        "state": state,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "x_ratio": round(sum(item.x_ratio for item in group) / count, 5),
        "y_ratio": round(sum(item.y_ratio for item in group) / count, 5),
        "count": count,
        "state_share": round(share, 3),
        "confidence": round(min(0.78, 0.30 + share * 0.75 + min(count, 12) * 0.025), 3),
        "action_label": _best_label(group) or _infer_action_label(state, group[0].x_ratio, group[0].y_ratio),
        "example_image": group[0].image_before,
        "ocr_excerpt": _excerpt(group[0].ocr_text or group[0].tooltip_text),
    }


def _click_heatmaps(state_actions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    heatmaps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in state_actions:
        heatmaps[str(action["state"])].append(
            {
                "grid_x": action["grid_x"],
                "grid_y": action["grid_y"],
                "count": action["count"],
                "confidence": action["confidence"],
                "action_label": action.get("action_label", ""),
            }
        )
    return {state: sorted(items, key=lambda item: (-item["count"], -item["confidence"])) for state, items in sorted(heatmaps.items())}


def _best_label(group: list[DemoClick]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for click in group:
        if click.label:
            counts[click.label] += 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: item[1])[0]


def _infer_action_label(state: str, x_ratio: float, y_ratio: float) -> str:
    if y_ratio > 0.92:
        if x_ratio < 0.38:
            return "bottom_nav_tavern_storage"
        if x_ratio < 0.53:
            return "bottom_nav_forge_main_hall"
        if x_ratio < 0.62:
            return "bottom_nav_recruit_loot"
        return "bottom_nav_battle_raid"
    if state == "battle_select":
        if x_ratio < 0.38:
            return "choose_left_battle"
        if x_ratio < 0.62:
            return "choose_center_battle"
        return "choose_right_battle"
    if state in {"loot", "shop_menu"}:
        return "shop_or_loot_choice"
    if state == "recruit_dwarves":
        return "recruit_choice"
    if y_ratio > 0.62:
        return "inventory_or_action_bar"
    return "screen_click"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _excerpt(text: str, limit: int = 180) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


if __name__ == "__main__":
    main()
