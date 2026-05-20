"""Incremental log file tailing for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from log_viewer import filter_lines_by_level, read_log_lines


@dataclass
class LogTailState:
    """Tracks how much of a log file has been shown in the UI."""

    path: str = ""
    min_level: str = "INFO"
    byte_offset: int = 0

    def key(self) -> Tuple[str, str]:
        return (self.path, self.min_level)


def reset_log_tail(state: LogTailState, *, path: str, min_level: str) -> LogTailState:
    return LogTailState(path=path, min_level=min_level, byte_offset=0)


def read_initial_log_lines(
    path: str,
    *,
    min_level: str = "INFO",
    max_lines: int = 400,
) -> Tuple[List[str], LogTailState]:
    """Load the tail window and set byte offset to end of file."""
    lines = read_log_lines(path, min_level=min_level, max_lines=max_lines)
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            file.seek(0, 2)
            offset = file.tell()
    except OSError:
        offset = 0
    return lines, LogTailState(path=path, min_level=min_level, byte_offset=offset)


def read_new_log_lines(state: LogTailState) -> Tuple[List[str], LogTailState]:
    """Return new lines since last tail; updates byte offset."""
    path = state.path
    if not path:
        return [], state
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            file.seek(state.byte_offset)
            chunk = file.read()
            new_offset = file.tell()
    except OSError:
        return [], state
    if not chunk:
        return [], LogTailState(
            path=path, min_level=state.min_level, byte_offset=new_offset
        )
    raw_lines = [ln.rstrip("\n\r") for ln in chunk.splitlines() if ln.strip()]
    filtered = filter_lines_by_level(raw_lines, state.min_level)
    return filtered, LogTailState(
        path=path, min_level=state.min_level, byte_offset=new_offset
    )
