import json
import os
import tempfile

from analytics import (
    _fill_dollars,
    aggregate_by_ticker,
    compute_liquidation_pl,
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


def test_compute_liquidation_pl_hold_only():
    assert compute_liquidation_pl(1000.0, 0.0, 10.0, 110.0) == 100.0


def test_compute_liquidation_pl_partial_sell():
    # buy $1000, sell $315, hold 7 @ $110 -> 315 + 770 - 1000 = 85
    assert compute_liquidation_pl(1000.0, 315.0, 7.0, 110.0) == 85.0


def test_compute_liquidation_pl_no_buys():
    assert compute_liquidation_pl(0.0, 100.0, 5.0, 50.0) is None


def test_aggregate_liquidation_from_trades_and_state():
    trades = [
        {
            "ts": "2026-05-20T12:00:00Z",
            "symbol": "AAPL",
            "side": "buy",
            "status": "filled",
            "notional": 1000,
        },
    ]
    state_tickers = [
        {"ticker": "AAPL", "volume": 10, "price": 110, "difference": 0.05},
    ]
    stats = aggregate_by_ticker(trades, state_tickers=state_tickers)
    assert stats["AAPL"].liquidation_pl == 100.0
