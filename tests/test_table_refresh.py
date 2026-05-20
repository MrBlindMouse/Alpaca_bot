"""Tests for DataTable refresh signatures."""

from tui.table_refresh import (
    analytics_signature,
    positions_signature,
    trades_signature,
)


def test_positions_signature_stable():
    tickers = [{"ticker": "AAPL", "volume": 1.0, "price": 100.0, "difference": 0.01, "limitTrade": {"open": False}}]
    a = positions_signature(tickers, sort_column=None, sort_reverse=False)
    b = positions_signature(tickers, sort_column=None, sort_reverse=False)
    assert a == b


def test_positions_signature_changes_on_sort():
    tickers = [{"ticker": "AAPL", "volume": 1.0, "price": 100.0, "difference": 0.01, "limitTrade": {"open": False}}]
    a = positions_signature(tickers, sort_column="symbol", sort_reverse=False)
    b = positions_signature(tickers, sort_column="swing", sort_reverse=False)
    assert a != b


def test_trades_signature_changes_when_trade_added():
    base = [{"ts": "t1", "symbol": "A", "side": "buy", "status": "filled"}]
    a = trades_signature(base, sort_column=None, sort_reverse=False)
    extended = base + [{"ts": "t2", "symbol": "B", "side": "sell", "status": "filled"}]
    b = trades_signature(extended, sort_column=None, sort_reverse=False)
    assert a != b


def test_analytics_signature_includes_period():
    stats = {}
    a = analytics_signature(stats, period="all", sort_column=None, sort_reverse=False)
    b = analytics_signature(stats, period="7d", sort_column=None, sort_reverse=False)
    assert a != b
