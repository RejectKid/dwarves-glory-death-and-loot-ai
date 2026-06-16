from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import keyboard
import numpy as np
import pyautogui
import pygetwindow as gw
import yaml

from dwarves_autoplayer.playbook import DwarvesPlaybook
from dwarves_autoplayer.perception import PerceptionEngine
from dwarves_autoplayer.recorder import ScreenRecorder
from dwarves_autoplayer.strategy import KnowledgeStrategy
from dwarves_autoplayer.tooltip_reader import TooltipReader


ROOT = Path.cwd()
CONFIG_PATH = ROOT / "config.yaml"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def setup_logging(config: dict[str, Any]) -> None:
    log_path = ROOT / config.get("log_file", "bot.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def find_game_window(title_parts: list[str]):
    windows = [w for w in gw.getAllWindows() if w.title and w.width > 100 and w.height > 100]
    lowered_parts = [part.lower() for part in title_parts]
    for window in windows:
        title = window.title.lower()
        if any(part in title for part in lowered_parts):
            return window
    return None


def screenshot_window(window) -> np.ndarray:
    image = pyautogui.screenshot(region=(window.left, window.top, window.width, window.height))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def click_window_point(window, x: int, y: int, label: str) -> None:
    absolute_x = window.left + x
    absolute_y = window.top + y
    logging.info("Click %s at window=(%s,%s), screen=(%s,%s)", label, x, y, absolute_x, absolute_y)
    pyautogui.click(absolute_x, absolute_y)


def drag_window_point(window, x: int, y: int, target_x: int, target_y: int, label: str) -> None:
    start_x = window.left + x
    start_y = window.top + y
    end_x = window.left + target_x
    end_y = window.top + target_y
    logging.info(
        "Drag %s from window=(%s,%s), screen=(%s,%s) to window=(%s,%s), screen=(%s,%s)",
        label,
        x,
        y,
        start_x,
        start_y,
        target_x,
        target_y,
        end_x,
        end_y,
    )
    pyautogui.moveTo(start_x, start_y)
    pyautogui.dragTo(end_x, end_y, duration=0.35, button="left")


def click_pair_window_point(window, x: int, y: int, target_x: int, target_y: int, label: str) -> None:
    start_x = window.left + x
    start_y = window.top + y
    end_x = window.left + target_x
    end_y = window.top + target_y
    logging.info(
        "Click-pair %s source window=(%s,%s), screen=(%s,%s) target window=(%s,%s), screen=(%s,%s)",
        label,
        x,
        y,
        start_x,
        start_y,
        target_x,
        target_y,
        end_x,
        end_y,
    )
    pyautogui.click(start_x, start_y)
    time.sleep(0.18)
    pyautogui.moveTo(end_x, end_y)
    time.sleep(0.12)
    pyautogui.click(end_x, end_y)


class Bot:
    def __init__(self, config: dict[str, Any], print_mouse: bool = False, auto_start: bool = False) -> None:
        self.config = config
        self.print_mouse = print_mouse
        self.running = auto_start
        self.quit_requested = False
        self.strategy = KnowledgeStrategy(ROOT, config)
        self.playbook = DwarvesPlaybook(config, self.strategy)
        self.perception = PerceptionEngine(ROOT, config)
        self.recorder = ScreenRecorder(ROOT, config)
        self.tooltip_reader = TooltipReader(ROOT, config)

    def install_hotkeys(self) -> None:
        hotkeys = self.config.get("hotkeys", {})
        keyboard.add_hotkey(hotkeys.get("toggle", "ctrl+alt+s"), self.toggle)
        keyboard.add_hotkey(hotkeys.get("quit", "ctrl+alt+q"), self.quit)

    def toggle(self) -> None:
        self.running = not self.running
        logging.info("Bot %s", "running" if self.running else "paused")

    def quit(self) -> None:
        self.quit_requested = True
        logging.info("Quit requested")

    def step(self, window) -> bool:
        screen = screenshot_window(window)
        state_hint = self.playbook.classify(screen)
        observation = self.perception.observe(screen, state_hint.value)
        action = self.playbook.choose_action(screen, state_override=observation.state)
        self.recorder.observe(screen, observation.state, action.name if action else None, action.goal if action else None)

        if not action:
            logging.info(
                "No strategy action for state=%s source=%s confidence=%.2f keywords=%s",
                observation.state,
                observation.state_source,
                observation.state_confidence,
                ",".join(observation.visible_keywords) or "none",
            )
            return False

        self.log_decision(observation.state, action)
        self.deliberate_before_action(observation.state, action)
        x = int(window.width * action.x_ratio)
        y = int(window.height * action.y_ratio)
        tooltip = self.tooltip_reader.read_after_hover(window, x, y, action.name) if self.strategy.should_probe_tooltip(action.name) else None
        if tooltip and tooltip.text:
            self.strategy.note_tooltip(action.name, tooltip.text)
            matches = self.strategy.tooltip_matches_priorities(tooltip.text)
            if matches:
                logging.info("Tooltip priority matches: %s", " | ".join(matches))
            if self.strategy.should_skip_for_tooltip(action.name, tooltip.text):
                logging.info("Skipping action=%s after tooltip risk check", action.name)
                return True
        if action.action_type == "smart_equip":
            if not tooltip or not tooltip.text:
                logging.info("Skipping smart equip action=%s because no tooltip text was readable", action.name)
                return True
            plan = self.strategy.plan_smart_equip(tooltip.text)
            if plan is None:
                logging.info("Skipping smart equip action=%s because item did not match the current build plan", action.name)
                return True
            target_x = int(window.width * plan.target_x_ratio)
            target_y = int(window.height * plan.target_y_ratio)
            logging.info(
                "Smart equip action=%s kind=%s target=%s score=%.2f reasons=%s",
                action.name,
                plan.kind,
                plan.target_name,
                plan.score,
                " | ".join(plan.reasons) or "none",
            )
            click_pair_window_point(window, x, y, target_x, target_y, f"{action.name}_to_{plan.target_name}")
            time.sleep(action.after_delay_seconds)
            return True
        if action.action_type in {"drag", "click_pair"} and action.target_x_ratio is not None and action.target_y_ratio is not None:
            target_x = int(window.width * action.target_x_ratio)
            target_y = int(window.height * action.target_y_ratio)
            if action.action_type == "click_pair":
                click_pair_window_point(window, x, y, target_x, target_y, action.name)
            else:
                drag_window_point(window, x, y, target_x, target_y, action.name)
        else:
            click_window_point(window, x, y, action.name)
        time.sleep(action.after_delay_seconds)
        return True

    def run(self) -> None:
        pyautogui.FAILSAFE = True
        self.install_hotkeys()
        self.log_startup()

        title_parts = self.config.get("window_title_contains", ["Dwarves"])
        while not self.quit_requested:
            window = find_game_window(title_parts)
            if not window:
                logging.info("Waiting for game window containing one of: %s", ", ".join(title_parts))
                time.sleep(2)
                continue

            if self.print_mouse:
                x, y = pyautogui.position()
                logging.info("Mouse screen=(%s,%s), window=(%s,%s)", x, y, x - window.left, y - window.top)

            if self.running:
                try:
                    self.step(window)
                except pyautogui.FailSafeException:
                    logging.warning("PyAutoGUI failsafe triggered. Pausing.")
                    self.running = False

            time.sleep(float(self.config.get("loop_delay_seconds", 0.35)))

    def log_startup(self) -> None:
        summary = self.strategy.summary()
        logging.info("Knowledge sources loaded: %s", summary["sources"])
        logging.info("Knowledge coverage: %s", summary["source_coverage"])
        logging.info("S-tier set targets: %s", ", ".join(summary["s_tier_sets"]) or "none")
        logging.info("Chosen build archetype: %s", summary["chosen_build"])
        logging.info("Known roster size: %s", summary["roster_size"])
        learned = summary.get("learned_policy", {})
        logging.info(
            "Learned policy: available=%s clicks=%s screen_actions=%s state_actions=%s",
            learned.get("available"),
            learned.get("click_events"),
            learned.get("screen_actions"),
            learned.get("state_actions"),
        )
        logging.info("Video training samples: %s", summary["video_samples"])
        logging.info("Video state baseline: %s", summary["video_states"])
        logging.info("State playbook enabled: %s", self.playbook.enabled)
        logging.info("Perception OCR available: %s", self.perception.ocr_available)
        logging.info("Tooltip OCR available: %s", self.tooltip_reader.ocr_available)
        if not self.tooltip_reader.ocr_available:
            logging.info("Tesseract OCR engine is unavailable; tooltip crops will still be saved for later review")
        logging.info("Screenshots/timeline go to %s", self.recorder.data_dir)
        logging.info("Press %s to start/pause. Press %s to quit.", self.config["hotkeys"]["toggle"], self.config["hotkeys"]["quit"])

    def log_decision(self, state: str, action) -> None:
        logging.info("Decision state=%s action=%s goal=%s", state, action.name, action.goal)
        if action.confidence is not None or action.source:
            logging.info(
                "Decision learned source=%s confidence=%s label=%s",
                action.source or "unknown",
                action.confidence,
                action.action_label or "unknown",
            )
        logging.info("Decision rationale: %s", action.rationale)
        if action.build_priorities:
            logging.info("Decision build priorities: %s", " | ".join(action.build_priorities))
        if action.risks:
            logging.info("Decision risks: %s", " | ".join(action.risks))
        if action.source_basis:
            logging.info("Decision source basis: %s", " | ".join(action.source_basis))

    def deliberate_before_action(self, state: str, action) -> None:
        config = self.config.get("deliberation", {})
        if not config.get("enabled", True):
            return

        if action.action_type in {"drag", "click_pair", "smart_equip"} or action.name.startswith(("recruit_", "loot_", "forge_", "storage_", "tavern_", "equip_")):
            delay = float(config.get("risky_action_seconds", 1.6))
        elif action.name.startswith(("nav_recruit", "nav_loot", "nav_forge", "nav_storage", "nav_tavern", "nav_main_hall")):
            delay = float(config.get("economy_action_seconds", 1.2))
        elif state in {"battle_select", "battle_running", "battle_report"}:
            delay = float(config.get("battle_action_seconds", 0.35))
        else:
            delay = float(config.get("default_seconds", 0.6))

        if delay > 0:
            logging.info("Deliberating %.2fs before action=%s", delay, action.name)
            time.sleep(delay)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-mouse", action="store_true", help="Log mouse coordinates relative to the game window.")
    parser.add_argument("--auto-start", action="store_true", help="Start running immediately instead of waiting for the toggle hotkey.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config()
    setup_logging(config)
    bot = Bot(config, print_mouse=args.print_mouse, auto_start=args.auto_start)
    bot.run()


if __name__ == "__main__":
    main()
