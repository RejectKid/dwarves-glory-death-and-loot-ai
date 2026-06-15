from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import keyboard
import numpy as np
import pyautogui
import pygetwindow as gw
import yaml

from dwarves_autoplayer.baseline import load_baseline
from dwarves_autoplayer.learner import AutonomousLearner


ROOT = Path.cwd()
CONFIG_PATH = ROOT / "config.yaml"


@dataclass
class Match:
    name: str
    score: float
    center_x: int
    center_y: int
    rect: tuple[int, int, int, int]


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


def load_templates(template_dir: Path) -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    if not template_dir.exists():
        template_dir.mkdir(parents=True, exist_ok=True)
        return templates

    for path in template_dir.rglob("*.png"):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            logging.warning("Could not read template %s", path)
            continue
        templates[path.stem] = image

    return templates


def locate_template(screen: np.ndarray, template: np.ndarray, name: str, threshold: float) -> Match | None:
    if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
        return None

    screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return None

    x, y = max_loc
    h, w = template_gray.shape
    return Match(
        name=name,
        score=float(max_val),
        center_x=x + w // 2,
        center_y=y + h // 2,
        rect=(x, y, w, h),
    )


def best_match_for_action(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    action: dict[str, Any],
    threshold: float,
) -> Match | None:
    matches: list[Match] = []
    for template_name in action.get("templates", []):
        template = templates.get(template_name)
        if template is None:
            continue
        match = locate_template(screen, template, template_name, threshold)
        if match:
            matches.append(match)

    if not matches:
        return None

    return max(matches, key=lambda item: item.score)


def click_window_point(window, x: int, y: int, label: str) -> None:
    absolute_x = window.left + x
    absolute_y = window.top + y
    logging.info("Click %s at window=(%s,%s), screen=(%s,%s)", label, x, y, absolute_x, absolute_y)
    pyautogui.click(absolute_x, absolute_y)


def perform_shop_cycle(window, config: dict[str, Any], templates: dict[str, np.ndarray], threshold: float) -> None:
    shop = config.get("shop_strategy", {})
    delay = float(shop.get("delay_between_clicks_seconds", 0.25))
    clicks_per_slot = int(shop.get("clicks_per_slot", 1))

    for index, slot in enumerate(shop.get("buy_slots") or [], start=1):
        x, y = int(slot[0]), int(slot[1])
        for _ in range(clicks_per_slot):
            click_window_point(window, x, y, f"shop slot {index}")
            time.sleep(delay)

    reroll = shop.get("reroll_button")
    if reroll:
        click_window_point(window, int(reroll[0]), int(reroll[1]), "reroll")
        time.sleep(delay)

    start_template_name = shop.get("start_after_shop_template")
    if start_template_name and start_template_name in templates:
        screen = screenshot_window(window)
        match = locate_template(screen, templates[start_template_name], start_template_name, threshold)
        if match:
            click_window_point(window, match.center_x, match.center_y, start_template_name)


class Bot:
    def __init__(self, config: dict[str, Any], print_mouse: bool = False, auto_start: bool = False) -> None:
        self.config = config
        self.print_mouse = print_mouse
        self.running = auto_start
        self.quit_requested = False
        self.last_action_at: dict[str, float] = {}
        self.templates = load_templates(ROOT / config.get("template_dir", "templates"))
        self.baseline = load_baseline()
        self.learner = AutonomousLearner(ROOT, config)

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

    def action_ready(self, action: dict[str, Any]) -> bool:
        name = action["name"]
        cooldown = float(action.get("cooldown_seconds", 0))
        return time.monotonic() - self.last_action_at.get(name, 0) >= cooldown

    def mark_action(self, action: dict[str, Any]) -> None:
        self.last_action_at[action["name"]] = time.monotonic()

    def step(self, window) -> bool:
        threshold = float(self.config.get("match_threshold", 0.87))
        screen = screenshot_window(window)
        screen_id = self.learner.observe(screen) if self.learner.enabled else ""
        actions = sorted(self.config.get("actions", []), key=lambda item: int(item.get("priority", 0)), reverse=True)

        for action in actions:
            if not self.action_ready(action):
                continue

            match = best_match_for_action(screen, self.templates, action, threshold)
            if not match:
                continue

            logging.info(
                "Matched action=%s template=%s score=%.3f",
                action["name"],
                match.name,
                match.score,
            )

            click_mode = action.get("click", "best")
            if click_mode == "shop_slots":
                perform_shop_cycle(window, self.config, self.templates, threshold)
            else:
                click_window_point(window, match.center_x, match.center_y, action["name"])

            self.mark_action(action)
            time.sleep(float(self.config.get("after_click_delay_seconds", 0.75)))
            return True

        if self.learner.enabled:
            candidate = self.learner.choose_candidate(screen, screen_id)
            if candidate:
                x, y = candidate.center
                logging.info(
                    "Learner exploring screen=%s candidate=(%s,%s,%s,%s) score=%.3f",
                    screen_id[:8],
                    candidate.x,
                    candidate.y,
                    candidate.w,
                    candidate.h,
                    candidate.score,
                )
                self.learner.mark_clicked(screen_id, screen, candidate)
                click_window_point(window, x, y, "learner candidate")
                time.sleep(float(self.config.get("after_click_delay_seconds", 0.75)))
                return True

        return False

    def run(self) -> None:
        pyautogui.FAILSAFE = True
        self.install_hotkeys()

        title_parts = self.config.get("window_title_contains", ["Dwarves"])
        logging.info("Loaded %s templates: %s", len(self.templates), ", ".join(sorted(self.templates)) or "none")
        if self.baseline:
            sources = self.baseline.get("sources", [])
            set_names = self.baseline.get("item_set_priorities", {}).get("s_tier", [])
            logging.info("Loaded baseline knowledge from %s sources", len(sources))
            logging.info("Baseline S-tier set targets: %s", ", ".join(set_names) if set_names else "none")
        else:
            logging.info("No baseline knowledge found. Run run_bootstrap_knowledge.bat to seed it.")
        if self.learner.enabled:
            logging.info("Autonomous learner enabled. Screenshots/state go to %s", self.learner.data_dir)
        logging.info("Press %s to start/pause. Press %s to quit.", self.config["hotkeys"]["toggle"], self.config["hotkeys"]["quit"])

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
                    acted = self.step(window)
                    if not acted:
                        logging.debug("No action matched")
                except pyautogui.FailSafeException:
                    logging.warning("PyAutoGUI failsafe triggered. Pausing.")
                    self.running = False

            time.sleep(float(self.config.get("loop_delay_seconds", 0.35)))


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
