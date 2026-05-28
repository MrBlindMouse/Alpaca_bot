"""Tests for TUI helper modules (no Textual runtime required)."""

import json
from pathlib import Path

import pytest

from tui.log_tail import (
    LogTailState,
    read_initial_log_lines,
    read_new_log_lines,
    reset_log_tail,
)
from rich.text import Text

from tui.widgets import (
    analytics_row_cells,
    dashboard_metrics_markup,
    format_activity_chart,
    format_pl_rich,
    format_trade_ts,
    tail_log_rich_lines,
    trade_row_cells,
)
from analytics import TickerStats


def test_dashboard_metrics_markup():
    text = dashboard_metrics_markup(
        equity="$1,000.00",
        cash="$200.00",
        tickers=50,
        margin_pct=5.0,
        open_limits=2,
        highest_swing="AAPL 3.2%",
    )
    assert "$1,000.00" in text
    assert "Tickers" in text
    assert "AAPL 3.2%" in text


def test_trade_row_cells_buy_row_tint():
    cells = trade_row_cells({"side": "buy", "symbol": "AAPL", "ts": "2024-01-01T00:00:00Z"})
    assert isinstance(cells[0], Text)
    assert "106,158,110" in str(cells[0].style)


def test_trade_row_cells_sell_row_tint():
    cells = trade_row_cells({"side": "sell", "symbol": "MSFT"})
    assert isinstance(cells[0], Text)
    assert "106,140,173" in str(cells[0].style)


def test_analytics_row_cells_positive_liq_row_tint():
    s = TickerStats(symbol="X")
    s.trade_count = 1
    s.trading_pl = 10.0
    s.buy_dollars = 100
    cells = analytics_row_cells("X", s)
    assert isinstance(cells[0], Text)
    assert "106,158,110" in str(cells[0].style)


def test_analytics_row_cells_negative_liq_row_tint():
    s = TickerStats(symbol="Y")
    s.trading_pl = -5.0
    cells = analytics_row_cells("Y", s)
    assert isinstance(cells[0], Text)
    assert "180,120,120" in str(cells[0].style)


def test_format_activity_chart():
    chart = format_activity_chart([("NVDA", 12), ("AAPL", 6)])
    assert "NVDA" in chart
    assert "█" in chart
    assert "12" in chart


def test_format_pl_rich_positive():
    assert "[green]+$10.00[/green]" == format_pl_rich(10.0)


def test_format_pl_rich_negative():
    assert "[red]$-5.50[/red]" == format_pl_rich(-5.5)


def test_format_pl_rich_zero():
    assert "[dim]+$0.00[/dim]" == format_pl_rich(0.0)


def test_format_pl_rich_none():
    assert format_pl_rich(None) == "—"


def test_format_trade_ts_iso():
    assert format_trade_ts("2024-06-01T14:30:00Z") == "2024-06-01 14:30"


def test_format_trade_ts_empty():
    assert format_trade_ts(None) == "—"


def test_tail_log_rich_lines(tmp_path):
    log = tmp_path / "bot.log"
    log.write_text(
        "2024-01-01 12:00:00 INFO root: hello\n"
        "2024-01-01 12:00:01 WARNING root: alert\n"
    )
    lines = tail_log_rich_lines(str(log), lines=5, min_level="WARNING")
    assert len(lines) == 1
    assert "WARNING" in lines[0]
    assert "alert" in lines[0]


def test_log_tail_incremental(tmp_path):
    log = tmp_path / "bot.log"
    log.write_text("2024-01-01 12:00:00 INFO root: first\n")
    lines, state = read_initial_log_lines(str(log), min_level="INFO", max_lines=10)
    assert len(lines) == 1
    assert "first" in lines[0]

    with open(log, "a", encoding="utf-8") as file:
        file.write("2024-01-01 12:00:01 ERROR root: second\n")

    new_lines, state = read_new_log_lines(state)
    assert len(new_lines) == 1
    assert "second" in new_lines[0]

    more, state = read_new_log_lines(state)
    assert more == []


def test_reset_log_tail():
    state = LogTailState(path="a.log", min_level="INFO", byte_offset=99)
    reset = reset_log_tail(state, path="b.log", min_level="WARNING")
    assert reset.path == "b.log"
    assert reset.min_level == "WARNING"
    assert reset.byte_offset == 0


def test_tab_keys_logs_before_settings():
    import asyncio

    pytest.importorskip("textual")
    from textual.widgets import TabbedContent

    from tui.app import AlpacaApp

    async def run():
        app = AlpacaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            pilot.app.action_tab_logs()
            await pilot.pause()
            assert pilot.app.query_one(TabbedContent).active == "tab_logs"
            pilot.app.action_tab_settings()
            await pilot.pause()
            assert pilot.app.query_one(TabbedContent).active == "tab_settings"

    asyncio.run(run())
