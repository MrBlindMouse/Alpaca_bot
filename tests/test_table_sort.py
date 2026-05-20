"""Tests for TUI table pre-sort helpers."""

from analytics import TickerStats

from tui.table_sort import (
    analytics_sort_value,
    sort_ticker_stats_items,
    sort_trades,
    trade_sort_value,
)


def _stats(trades: int, filled: int) -> TickerStats:
    s = TickerStats(symbol="X")
    s.trade_count = trades
    s.filled_count = filled
    s.buy_dollars = float(trades)
    return s


def test_sort_ticker_stats_numeric_not_lexical():
    stats = {
        "a": _stats(3, 0),
        "b": _stats(23, 0),
    }
    ordered = sort_ticker_stats_items(stats, "trades", reverse=False)
    assert [sym for sym, _ in ordered] == ["a", "b"]


def test_sort_ticker_stats_reverse():
    stats = {"a": _stats(3, 0), "b": _stats(23, 0)}
    ordered = sort_ticker_stats_items(stats, "trades", reverse=True)
    assert [sym for sym, _ in ordered] == ["b", "a"]


def test_analytics_sort_value_net():
    s = TickerStats(symbol="A")
    s.buy_notional = 20.0
    s.sell_notional = 30.5
    assert analytics_sort_value(s, "net") == -10.5


def test_sort_trades_by_notional():
    rows = [
        {"symbol": "A", "notional": 100},
        {"symbol": "B", "notional": 20},
    ]
    ordered = sort_trades(rows, "notional", reverse=False)
    assert ordered[0]["symbol"] == "B"


def test_trade_sort_value_time():
    row = {"ts": "2024-06-02T10:00:00Z"}
    assert trade_sort_value(row, "time") > trade_sort_value({"ts": "2024-06-01T10:00:00Z"}, "time")
