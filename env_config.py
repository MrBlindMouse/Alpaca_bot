"""Read/write .env values used by the TUI."""

import os
import re
from typing import Optional

from dotenv import dotenv_values

MARGIN_MIN = 0.02
MARGIN_MAX = 0.15
ENV_PATH = ".env"
MARGIN_LINE = re.compile(r"^MARGIN\s*=.*$", re.MULTILINE)


def read_margin(path: str = ENV_PATH) -> float:
    raw = dotenv_values(path)
    return float(raw["MARGIN"])


def validate_margin(value: float) -> None:
    if not MARGIN_MIN <= value <= MARGIN_MAX:
        raise ValueError(
            f"Margin must be between {MARGIN_MIN} and {MARGIN_MAX} (got {value})"
        )


def write_margin(value: float, path: str = ENV_PATH) -> None:
    validate_margin(value)
    margin_line = f"MARGIN={value:g}\n"

    if os.path.exists(path):
        with open(path, encoding="utf-8") as file:
            content = file.read()
        if MARGIN_LINE.search(content):
            content = MARGIN_LINE.sub(f"MARGIN={value:g}", content)
            if not content.endswith("\n"):
                content += "\n"
        else:
            content = content.rstrip() + "\n" + margin_line
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)
    else:
        raise FileNotFoundError(f"{path} not found")
