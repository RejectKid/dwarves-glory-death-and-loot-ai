from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from dwarves_autoplayer.bot import load_config
from dwarves_autoplayer.learned_policy import LearnedPolicy
from dwarves_autoplayer.perception import PerceptionEngine
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
    strategy = KnowledgeStrategy(Path.cwd(), config)
    playbook = DwarvesPlaybook(config, strategy)
    perception = PerceptionEngine(Path.cwd(), config)
    state_hint = playbook.classify(image)
    observation = perception.observe(image, state_hint.value)
    action = playbook.choose_action(image, state_override=observation.state)
    learned_policy = LearnedPolicy(Path.cwd(), config.get("strategy", {}).get("learned_policy", {}))
    learned_proposal = learned_policy.propose(image, observation.state)

    print(f"image: {path}")
    print(f"state: {observation.state}")
    print(f"state_hint: {state_hint.value}")
    print(f"state_source: {observation.state_source}")
    print(f"state_confidence: {observation.state_confidence}")
    print(f"screen_id: {observation.screen_id}")
    print(f"ocr_available: {perception.ocr_available}")
    print(f"visible_keywords: {', '.join(observation.visible_keywords) or 'none'}")
    if observation.ocr_text:
        print(f"ocr_excerpt: {observation.ocr_text[:240]}")
    policy_summary = learned_policy.summary()
    print(
        "learned_policy: "
        f"available={policy_summary['available']} "
        f"screen_actions={policy_summary['screen_actions']} "
        f"state_actions={policy_summary['state_actions']}"
    )
    if learned_proposal:
        print(f"learned_match: {learned_proposal.name}")
        print(f"learned_match_label: {learned_proposal.action_label or 'unknown'}")
        print(f"learned_match_confidence: {learned_proposal.confidence}")
        print(f"learned_match_reason: {learned_proposal.reason}")
    if action:
        height, width = image.shape[:2]
        print(f"action: {action.name}")
        print(f"click: x={int(width * action.x_ratio)} y={int(height * action.y_ratio)}")
        print(f"cooldown: {action.cooldown_seconds}s")
        print(f"goal: {action.goal}")
        if action.confidence is not None or action.source:
            print(f"learned_source: {action.source or 'unknown'}")
            print(f"learned_confidence: {action.confidence}")
            print(f"learned_label: {action.action_label or 'unknown'}")
        print(f"rationale: {action.rationale}")
        if action.build_priorities:
            print("build_priorities:")
            for item in action.build_priorities:
                print(f"  - {item}")
        if action.risks:
            print("risks:")
            for item in action.risks:
                print(f"  - {item}")
        if action.source_basis:
            print("source_basis:")
            for item in action.source_basis:
                print(f"  - {item}")
    else:
        print("action: none")


if __name__ == "__main__":
    main()
