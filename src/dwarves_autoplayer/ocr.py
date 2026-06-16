from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def resolve_tesseract_cmd(config: dict[str, Any] | None = None) -> str:
    candidates: list[str] = []
    if config:
        ocr_config = config.get("ocr", {})
        if isinstance(ocr_config, dict):
            candidates.append(str(ocr_config.get("tesseract_cmd", "") or ""))
        for section_name in ("perception", "tooltip_reader", "teach_mode"):
            section = config.get(section_name, {})
            if isinstance(section, dict):
                candidates.append(str(section.get("tesseract_cmd", "") or ""))
    candidates.append(os.environ.get("TESSERACT_CMD", ""))
    candidates.extend(DEFAULT_TESSERACT_PATHS)

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def load_pytesseract(config: dict[str, Any] | None = None):
    try:
        import pytesseract
    except ImportError:
        return None

    tesseract_cmd = resolve_tesseract_cmd(config)
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    return pytesseract
