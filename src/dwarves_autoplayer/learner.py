from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class Candidate:
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def key(self) -> str:
        return f"{self.x},{self.y},{self.w},{self.h}"


class AutonomousLearner:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config.get("autonomous_learning", {})
        self.enabled = bool(self.config.get("enabled", False))
        self.data_dir = root / self.config.get("data_dir", "learning_data")
        self.screenshot_dir = self.data_dir / "screenshots"
        self.template_dir = self.data_dir / "templates"
        self.state_path = self.data_dir / "state.json"
        self.last_screenshot_at = 0.0
        self.last_click: dict[str, Any] | None = None
        self.state = self._load_state()

        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"screens": {}}

        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            logging.warning("Could not read learner state. Starting fresh.")
            return {"screens": {}}

    def save_state(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2, sort_keys=True)

    def fingerprint(self, screen: np.ndarray) -> str:
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        bits = small > small.mean()
        value = 0
        chars: list[str] = []
        for index, bit in enumerate(bits.flatten()):
            value = (value << 1) | int(bit)
            if index % 4 == 3:
                chars.append(f"{value:x}")
                value = 0
        return "".join(chars)

    def hash_distance(self, left: str, right: str) -> int:
        return sum(bin(int(a, 16) ^ int(b, 16)).count("1") for a, b in zip(left, right))

    def observe(self, screen: np.ndarray) -> str:
        screen_id = self.fingerprint(screen)
        self.update_click_probe(screen)
        screens = self.state.setdefault("screens", {})
        screen_state = screens.setdefault(
            screen_id,
            {
                "seen": 0,
                "candidates": {},
                "first_seen_at": time.time(),
                "last_seen_at": time.time(),
            },
        )
        screen_state["seen"] = int(screen_state.get("seen", 0)) + 1
        screen_state["last_seen_at"] = time.time()

        self._record_previous_click(screen_id)
        self._maybe_save_screenshot(screen, screen_id)
        self.save_state()
        return screen_id

    def _record_previous_click(self, current_screen_id: str) -> None:
        if not self.last_click:
            return

        min_delay = float(self.config.get("click_result_delay_seconds", 1.0))
        if time.monotonic() - float(self.last_click["clicked_at"]) < min_delay:
            return

        previous_screen_id = self.last_click["screen_id"]
        candidate_key = self.last_click["candidate_key"]
        previous_hash = self.last_click["screen_hash"]
        previous_probe = np.array(self.last_click.get("screen_probe", []), dtype=np.uint8)
        current_probe = np.array(self.last_click.get("current_probe", []), dtype=np.uint8)
        mean_absdiff = 0.0
        if previous_probe.size and current_probe.size and previous_probe.shape == current_probe.shape:
            mean_absdiff = float(np.mean(cv2.absdiff(previous_probe, current_probe)))

        changed = (
            self.hash_distance(previous_hash, current_screen_id) >= int(self.config.get("changed_hash_bits", 10))
            and mean_absdiff >= float(self.config.get("changed_mean_absdiff", 6.0))
        )

        candidate_state = self.state["screens"][previous_screen_id]["candidates"].setdefault(
            candidate_key,
            {"attempts": 0, "successes": 0, "last_clicked_at": 0},
        )
        candidate_state["attempts"] = int(candidate_state.get("attempts", 0)) + 1
        if changed:
            candidate_state["successes"] = int(candidate_state.get("successes", 0)) + 1
            logging.info(
                "Learner marked click successful: screen=%s candidate=%s diff=%.2f",
                previous_screen_id[:8],
                candidate_key,
                mean_absdiff,
            )
        else:
            logging.info(
                "Learner marked click unchanged: screen=%s candidate=%s diff=%.2f",
                previous_screen_id[:8],
                candidate_key,
                mean_absdiff,
            )

        self.last_click = None

    def _maybe_save_screenshot(self, screen: np.ndarray, screen_id: str) -> None:
        interval = float(self.config.get("screenshot_interval_seconds", 3.0))
        now = time.monotonic()
        if now - self.last_screenshot_at < interval:
            return

        self.last_screenshot_at = now
        path = self.screenshot_dir / f"{int(time.time())}_{screen_id[:12]}.png"
        cv2.imwrite(str(path), screen)

    def detect_candidates(self, screen: np.ndarray) -> list[Candidate]:
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 40, 120)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        dilated = cv2.dilate(edges, kernel, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        height, width = gray.shape
        candidates: list[Candidate] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not self._looks_clickable(width, height, x, y, w, h):
                continue

            roi = screen[y : y + h, x : x + w]
            score = self._candidate_score(width, height, roi, x, y, w, h)
            candidates.append(Candidate(x=x, y=y, w=w, h=h, score=score))

        candidates.sort(key=lambda item: item.score, reverse=True)
        return self._dedupe(candidates)[: int(self.config.get("max_candidates_per_screen", 12))]

    def _looks_clickable(self, screen_w: int, screen_h: int, x: int, y: int, w: int, h: int) -> bool:
        min_w = int(self.config.get("min_candidate_width", 60))
        min_h = int(self.config.get("min_candidate_height", 24))
        max_w = int(screen_w * float(self.config.get("max_candidate_screen_width", 0.65)))
        max_h = int(screen_h * float(self.config.get("max_candidate_screen_height", 0.22)))
        if self.config.get("ignore_bottom_toolbar", True) and y > int(screen_h * float(self.config.get("bottom_toolbar_cutoff", 0.90))):
            return False
        if w < min_w or h < min_h or w > max_w or h > max_h:
            return False

        aspect = w / max(h, 1)
        if aspect < 1.15 or aspect > 9.0:
            return False

        margin = int(self.config.get("edge_margin", 8))
        return margin <= x <= screen_w - margin and margin <= y <= screen_h - margin

    def _candidate_score(self, screen_w: int, screen_h: int, roi: np.ndarray, x: int, y: int, w: int, h: int) -> float:
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        saturation = float(hsv[:, :, 1].mean()) / 255.0
        brightness = float(hsv[:, :, 2].mean()) / 255.0
        area_score = min((w * h) / (screen_w * screen_h * 0.04), 1.0)
        bottom_bias = (y + h / 2) / screen_h
        center_bias = 1.0 - abs((x + w / 2) - screen_w / 2) / (screen_w / 2)
        return 0.30 * saturation + 0.25 * brightness + 0.20 * area_score + 0.15 * bottom_bias + 0.10 * center_bias

    def _dedupe(self, candidates: list[Candidate]) -> list[Candidate]:
        kept: list[Candidate] = []
        for candidate in candidates:
            if all(self._intersection_over_union(candidate, other) < 0.35 for other in kept):
                kept.append(candidate)
        return kept

    def _intersection_over_union(self, left: Candidate, right: Candidate) -> float:
        x1 = max(left.x, right.x)
        y1 = max(left.y, right.y)
        x2 = min(left.x + left.w, right.x + right.w)
        y2 = min(left.y + left.h, right.y + right.h)
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        union = left.w * left.h + right.w * right.h - inter
        return inter / union if union else 0.0

    def choose_candidate(self, screen: np.ndarray, screen_id: str) -> Candidate | None:
        candidates = self.detect_candidates(screen)
        if not candidates:
            return None

        screen_state = self.state["screens"].setdefault(screen_id, {"seen": 0, "candidates": {}})
        candidate_states = screen_state.setdefault("candidates", {})
        now = time.time()
        cooldown = float(self.config.get("candidate_cooldown_seconds", 4.0))

        ranked: list[tuple[float, Candidate]] = []
        for candidate in candidates:
            state = candidate_states.setdefault(
                candidate.key,
                {"attempts": 0, "successes": 0, "last_clicked_at": 0},
            )
            attempts = int(state.get("attempts", 0))
            successes = int(state.get("successes", 0))
            last_clicked_at = float(state.get("last_clicked_at", 0))
            failed_cooldown = float(self.config.get("failed_candidate_cooldown_seconds", 45.0))
            active_cooldown = cooldown if successes else failed_cooldown
            if now - last_clicked_at < active_cooldown:
                continue

            learned_bonus = (successes + 1) / (attempts + 2)
            explore_bonus = 0.25 if attempts == 0 else 0.0
            ranked.append((candidate.score + learned_bonus + explore_bonus, candidate))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def mark_clicked(self, screen_id: str, screen: np.ndarray, candidate: Candidate) -> None:
        candidate_states = self.state["screens"][screen_id].setdefault("candidates", {})
        state = candidate_states.setdefault(candidate.key, {"attempts": 0, "successes": 0, "last_clicked_at": 0})
        state["last_clicked_at"] = time.time()
        self.last_click = {
            "screen_id": screen_id,
            "screen_hash": screen_id,
            "candidate_key": candidate.key,
            "clicked_at": time.monotonic(),
            "screen_probe": self._screen_probe(screen).tolist(),
            "current_probe": self._screen_probe(screen).tolist(),
        }

        crop = screen[candidate.y : candidate.y + candidate.h, candidate.x : candidate.x + candidate.w]
        if crop.size:
            out_path = self.template_dir / f"{screen_id[:8]}_{candidate.x}_{candidate.y}_{candidate.w}_{candidate.h}.png"
            if not out_path.exists():
                cv2.imwrite(str(out_path), crop)

    def update_click_probe(self, screen: np.ndarray) -> None:
        if self.last_click:
            self.last_click["current_probe"] = self._screen_probe(screen).tolist()

    def _screen_probe(self, screen: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA)
