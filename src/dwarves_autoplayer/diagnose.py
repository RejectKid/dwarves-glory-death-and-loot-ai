from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from dwarves_autoplayer.bot import load_config
from dwarves_autoplayer.playbook import DwarvesPlaybook
from dwarves_autoplayer.strategy import KnowledgeStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", help="Screenshot to diagnose. Defaults to latest learning screenshot.")
    return parser.parse_args()


def latest_screenshot() -> Path:
    screenshot_dir = Path.cwd() / "learning_data" / "screenshots"
    files = sorted(screenshot_dir.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit("No screenshots found in learning_data/screenshots.")
    return files[0]


def main() -> None:
    args = parse_args()
    path = Path(args.image) if args.image else latest_screenshot()
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"Could not read image: {path}")

    config = load_config()
    playbook = DwarvesPlaybook(config, KnowledgeStrategy(Path.cwd(), config))
    state = playbook.classify(image)
    action = playbook.choose_action(image)

    print(f"image: {path}")
    print(f"state: {state.value}")
    if action:
        height, width = image.shape[:2]
        print(f"action: {action.name}")
        print(f"click: x={int(width * action.x_ratio)} y={int(height * action.y_ratio)}")
        print(f"cooldown: {action.cooldown_seconds}s")
    else:
        print("action: none")


if __name__ == "__main__":
    main()
