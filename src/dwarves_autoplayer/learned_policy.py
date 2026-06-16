from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from dwarves_autoplayer.screen_features import fingerprint, hamming_hex


@dataclass(frozen=True)
class LearnedActionProposal:
    name: str
    x_ratio: float
    y_ratio: float
    confidence: float
    source: str
    reason: str
    action_label: str = ""


class LearnedPolicy:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root
        self.enabled = bool(config.get("enabled", True))
        self.policy_path = root / str(config.get("policy_path", "knowledge/learned_policy.yaml"))
        self.min_confidence = float(config.get("min_confidence", 0.55))
        self.max_hamming_distance = int(config.get("max_hamming_distance", 42))
        self.state_fallback_enabled = bool(config.get("state_fallback_enabled", True))
        self.state_fallback_min_count = int(config.get("state_fallback_min_count", 3))
        self.policy = self._load_policy()
        self.screen_actions = self.policy.get("screen_actions", [])
        self.state_actions = self.policy.get("state_actions", [])

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.screen_actions or self.state_actions)

    def summary(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "path": str(self.policy_path),
            "click_events": int(self.policy.get("click_events", 0) or 0),
            "screen_actions": len(self.screen_actions),
            "state_actions": len(self.state_actions),
        }

    def propose(self, screen: np.ndarray, state: str) -> LearnedActionProposal | None:
        if not self.available:
            return None

        screen_id = fingerprint(screen)
        screen_match = self._screen_match(screen_id, state)
        if screen_match and screen_match.confidence >= self.min_confidence:
            return screen_match

        state_match = self._state_match(state)
        if state_match and state_match.confidence >= self.min_confidence:
            return state_match

        return None

    def _screen_match(self, screen_id: str, state: str) -> LearnedActionProposal | None:
        best: tuple[int, dict[str, Any]] | None = None
        for action in self.screen_actions:
            if action.get("state") != state:
                continue
            distance = hamming_hex(screen_id, str(action.get("screen_id", "")))
            if distance <= self.max_hamming_distance and (best is None or distance < best[0]):
                best = (distance, action)

        if best is None:
            return None

        distance, action = best
        base_confidence = float(action.get("confidence", 0.0))
        distance_penalty = min(0.45, distance / max(self.max_hamming_distance, 1) * 0.45)
        confidence = max(0.0, base_confidence - distance_penalty)
        return LearnedActionProposal(
            name=f"learned_screen_{state}_{str(action.get('screen_id', ''))[:8]}",
            x_ratio=float(action.get("x_ratio", 0.5)),
            y_ratio=float(action.get("y_ratio", 0.5)),
            confidence=confidence,
            source="screen_demonstration",
            reason=f"matched taught screen at hamming distance {distance}",
            action_label=str(action.get("action_label", "")),
        )

    def _state_match(self, state: str) -> LearnedActionProposal | None:
        if not self.state_fallback_enabled:
            return None

        candidates = [
            action
            for action in self.state_actions
            if action.get("state") == state and int(action.get("count", 0) or 0) >= self.state_fallback_min_count
        ]
        if not candidates:
            return None

        action = max(candidates, key=lambda item: (float(item.get("confidence", 0.0)), int(item.get("count", 0) or 0)))
        return LearnedActionProposal(
            name=f"learned_state_{state}_{action.get('grid_x')}_{action.get('grid_y')}",
            x_ratio=float(action.get("x_ratio", 0.5)),
            y_ratio=float(action.get("y_ratio", 0.5)),
            confidence=float(action.get("confidence", 0.0)),
            source="state_demonstration",
            reason=f"using common taught click for state={state} count={action.get('count')}",
            action_label=str(action.get("action_label", "")),
        )

    def _load_policy(self) -> dict[str, Any]:
        if not self.enabled or not self.policy_path.exists():
            return {}
        with self.policy_path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
            return value if isinstance(value, dict) else {}
