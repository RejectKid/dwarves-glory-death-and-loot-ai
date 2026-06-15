from __future__ import annotations

import re
from pathlib import Path

import pyautogui


ROOT = Path.cwd()
TEMPLATE_DIR = ROOT / "templates"


def clean_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    return value.strip("_")


def wait_for_point(prompt: str) -> tuple[int, int]:
    input(prompt)
    return pyautogui.position()


def main() -> None:
    TEMPLATE_DIR.mkdir(exist_ok=True)
    print("Template capture for Dwarves Autoplayer")
    print("Keep the game visible. Capture only a tight button/label area.")
    print("Press Ctrl+C to exit.")

    while True:
        name = clean_name(input("\nTemplate name: "))
        if not name:
            print("Skipped empty name.")
            continue

        x1, y1 = wait_for_point("Move mouse to TOP-LEFT of the target, then press Enter here.")
        x2, y2 = wait_for_point("Move mouse to BOTTOM-RIGHT of the target, then press Enter here.")

        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        width = max(1, right - left)
        height = max(1, bottom - top)

        image = pyautogui.screenshot(region=(left, top, width, height))
        out_path = TEMPLATE_DIR / f"{name}.png"
        image.save(out_path)
        print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
