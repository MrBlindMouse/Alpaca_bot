"""Parse and filter bot log files for CLI and TUI."""

import logging
import re
from typing import List, Optional, Tuple

LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"([\w.]+): (.*)$"
)

LEVEL_COLORS = {
    "DEBUG": "dim",
    "INFO": "cyan",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold red",
}


def resolve_log_level(name: str) -> int:
    """Map level name to logging module constant; default INFO."""
    return getattr(logging, name.upper(), logging.INFO)


def level_rank(name: str) -> int:
    try:
        return LOG_LEVEL_NAMES.index(name.upper())
    except ValueError:
        return LOG_LEVEL_NAMES.index("INFO")


def parse_log_line(line: str) -> Optional[Tuple[str, str, str, str]]:
    """Return (timestamp, level, logger_name, message) or None."""
    match = LOG_LINE_RE.match(line.strip())
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3), match.group(4)


def filter_lines_by_level(lines: List[str], min_level: str = "INFO") -> List[str]:
    """Keep lines at min_level and above (standard logging semantics)."""
    if min_level.upper() == "ALL":
        return [ln for ln in lines if ln.strip()]
    min_rank = level_rank(min_level)
    result = []
    for line in lines:
        parsed = parse_log_line(line)
        if parsed is None:
            if result:
                result.append(line.rstrip())
            continue
        if level_rank(parsed[1]) >= min_rank:
            result.append(line.rstrip())
    return result


def read_log_lines(
    path: str,
    *,
    min_level: str = "INFO",
    max_lines: int = 500,
) -> List[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            lines = file.readlines()
    except OSError:
        return []
    filtered = filter_lines_by_level(lines, min_level)
    return filtered[-max_lines:]


def format_log_line_rich(line: str) -> str:
    """Rich markup for one log line."""
    parsed = parse_log_line(line)
    if not parsed:
        return f"[dim]{line}[/dim]"
    ts, level, name, msg = parsed
    color = LEVEL_COLORS.get(level, "white")
    return f"[dim]{ts}[/dim] [{color}]{level:8}[/] [dim]{name}:[/dim] {msg}"


def add_log_level_args(parser) -> None:
    group = parser.add_argument_group("logging")
    group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log at DEBUG (overrides LOG_LEVEL in .env)",
    )
    group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Log at WARNING and above only",
    )
    group.add_argument(
        "--log-level",
        choices=[n.lower() for n in LOG_LEVEL_NAMES],
        metavar="LEVEL",
        help="Log level: debug, info, warning, error, critical",
    )
    group.add_argument(
        "--log-file",
        metavar="PATH",
        help="Write logs to this file (default: console only for bot.py)",
    )


def apply_log_level_args(config, args) -> None:
    if getattr(args, "verbose", False) and getattr(args, "quiet", False):
        raise ValueError("Use only one of --verbose and --quiet")
    if getattr(args, "verbose", False):
        config.log_level = "DEBUG"
    elif getattr(args, "quiet", False):
        config.log_level = "WARNING"
    elif getattr(args, "log_level", None):
        config.log_level = args.log_level.upper()
    if getattr(args, "log_file", None):
        config.log_file = args.log_file
