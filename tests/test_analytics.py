import json
import os
import tempfile

import pytest

from analytics import (
    _fill_dollars,
    _fill_qty,
    activity_bars,
    aggregate_by_ticker,
    compute_balance_target,
    compute_trading_pl,
    load_trades,
    portfolio_summary,
)


def test_load_trades_and_aggregate():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "trades.jsonl")
        rows = [
            {"ts": "2026-05-20T12:00:00Z", "symbol": "AAPL", "side": "buy", "status": "filled", "notional": 100},
            {"ts": "2026-05-20T13:00:00Z", "symbol": "AAPL", "side": "sell", "status": "filled", "notional": 50},
            {"ts": "2026-05-20T14:00:00Z", "symbol": "MSFT", "side": "buy", "status": "failed", "notional": 200},
        ]
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        trades = load_trades(path=path, period="all")
        assert len(trades) == 3
        stats = aggregate_by_ticker(trades)
        assert stats["AAPL"].trade_count == 2
        assert stats["AAPL"].filled_count == 2
        assert stats["AAPL"].buy_dollars == 100
        assert stats["AAPL"].sell_dollars == 50
        assert stats["AAPL"].net_flow == 50
        assert stats["MSFT"].failed_count == 1


def test_compute_balance_target_matches_rebalance():
    # equity / (n + n*margin/2) for n=100, margin=0.05
    target = compute_balance_target(100_000.0, 100, 0.05)
    assert target == pytest.approx(100_000.0 / (100 + 2.5))


def test_portfolio_summary_avg_balance_target():
    state = {
        "equity": 100_000.0,
        "margin": 0.05,
        "tickers": [{"ticker": f"T{i}", "difference": 0} for i in range(100)],
    }
    summary = portfolio_summary([], state=state)
    assert summary.avg_balance_target == pytest.approx(100_000.0 / 102.5)


def test_portfolio_summary():
    trades = [
        {"status": "filled", "symbol": "AAPL", "intent": "rebalance_buy"},
        {"status": "failed", "symbol": "MSFT", "intent": "rebalance_sell"},
    ]
    summary = portfolio_summary(trades)
    assert summary.trade_count == 2
    assert summary.filled_count == 1
    assert summary.fill_rate == 0.5


def test_fill_dollars_from_qty_price():
    row = {"notional": None, "filled_qty": "10", "filled_avg_price": "100.5"}
    assert _fill_dollars(row) == 1005.0


def test_fill_qty_from_notional_and_price():
    row = {"notional": 500, "filled_avg_price": "100"}
    assert _fill_qty(row) == 5.0


def test_compute_trading_pl_round_trip():
    # buy $500, sell $200, net +3 @ $100 -> (200-500) + 300 = 0
    assert compute_trading_pl(500.0, 200.0, 5.0, 2.0, 100.0) == 0.0


def test_compute_trading_pl_no_rebalance_fills():
    assert compute_trading_pl(0.0, 0.0, 0.0, 0.0, 50.0) is None


def test_aggregate_trading_pl_excludes_initial_and_liquidate():
    trades = [
        {
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "intent": "rebalance_initial",
            "notional": 1000,
        },
        {
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "intent": "rebalance_buy",
            "notional": 500,
            "filled_qty": "5",
            "filled_avg_price": "100",
        },
        {
            "symbol": "AAPL",
            "side": "sell",
            "status": "filled",
            "intent": "liquidate",
            "notional": 1100,
        },
    ]
    state_tickers = [{"ticker": "AAPL", "volume": 10, "price": 110, "difference": 0.05}]
    stats = aggregate_by_ticker(trades, state_tickers=state_tickers)
    assert stats["AAPL"].buy_dollars == 1500
    assert stats["AAPL"].trading_pl == 50.0


def test_aggregate_trading_pl_with_sell():
    trades = [
        {
            "symbol": "NVDA",
            "side": "buy",
            "status": "filled",
            "intent": "rebalance_buy",
            "notional": 500,
            "filled_qty": "5",
            "filled_avg_price": "100",
        },
        {
            "symbol": "NVDA",
            "side": "sell",
            "status": "filled",
            "intent": "rebalance_sell",
            "notional": 200,
            "filled_qty": "2",
            "filled_avg_price": "100",
        },
    ]
    stats = aggregate_by_ticker(trades, state_tickers=[{"ticker": "NVDA", "volume": 3, "price": 100}])
    assert stats["NVDA"].trading_pl == 0.0


def test_portfolio_summary_trading_pl():
    trades = [
        {
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "intent": "rebalance_buy",
            "notional": 100,
            "filled_qty": "1",
            "filled_avg_price": "100",
        },
    ]
    stats = aggregate_by_ticker(trades)
    summary = portfolio_summary(trades, ticker_stats=stats)
    assert summary.trading_pl == -100.0


def test_activity_bars_uses_filled_count():
    from analytics import TickerStats

    high_fails = TickerStats(symbol="FAIL")
    high_fails.trade_count = 10
    high_fails.filled_count = 1
    many_fills = TickerStats(symbol="FILL")
    many_fills.trade_count = 3
    many_fills.filled_count = 3
    bars = activity_bars({"FAIL": high_fails, "FILL": many_fills}, width=2)
    assert bars[0][0] == "FILL"
    assert bars[0][2] == 3
