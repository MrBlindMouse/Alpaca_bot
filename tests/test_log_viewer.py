from log_viewer import (
    filter_lines_by_level,
    format_log_line_rich,
    parse_log_line,
    resolve_log_level,
)
import logging


def test_parse_log_line():
    line = "2026-05-20 14:30:00 INFO alpaca_bot.runner: Bot started"
    parsed = parse_log_line(line)
    assert parsed == ("2026-05-20 14:30:00", "INFO", "alpaca_bot.runner", "Bot started")


def test_filter_by_level():
    lines = [
        "2026-05-20 14:30:00 DEBUG alpaca_bot: detail",
        "2026-05-20 14:30:01 INFO alpaca_bot: ok",
        "2026-05-20 14:30:02 WARNING alpaca_bot: warn",
    ]
    info_only = filter_lines_by_level(lines, "INFO")
    assert len(info_only) == 2
    assert "DEBUG" not in info_only[0]


def test_resolve_log_level():
    assert resolve_log_level("DEBUG") == logging.DEBUG
    assert resolve_log_level("unknown") == logging.INFO


def test_format_log_line_rich_contains_level():
    line = "2026-05-20 14:30:00 ERROR alpaca_bot: failed"
    assert "ERROR" in format_log_line_rich(line)
