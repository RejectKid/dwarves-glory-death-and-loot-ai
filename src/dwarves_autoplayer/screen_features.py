from __future__ import annotations

import cv2
import numpy as np


def fingerprint(screen: np.ndarray) -> str:
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


def hamming_hex(left: str, right: str) -> int:
    if len(left) != len(right):
        return 9999
    distance = 0
    for left_char, right_char in zip(left, right):
        distance += (int(left_char, 16) ^ int(right_char, 16)).bit_count()
    return distance
