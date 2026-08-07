import json
import logging
import os
from unittest.mock import MagicMock

import pytest

from backtest.broker import SimBroker
from config import Config
from orders import OrderResult
from rebalance import (
    _apply_order_result,
    _intent_from_limit_placed,
    _log_skip,
    rebalance_tick,
    sync_open_limit_orders,
)
from state import Status


def _ticker(sym: str, volume: float, price: float, diff: float = 0.05):
    return {
        "ticker": sym,
        "volume": volume,
        "price": price,
        "difference": diff,
        "limitTrade": {
            "open": False,
            "id": "",
            "ts": 0,
            "side": "",
            "intent": "",
            "notional": None,
            "swing_pct": None,
        },
    }


def test_apply_order_result_logs_structured_intent_and_swing(caplog):
    account = MagicMock()
    account.serverTime = 1_700_000_000
    ticker = {"ticker": "AAPL", "volume": 0.0, "limitTrade": {"open": False}}
    account.tickers = [ticker]
    broker = MagicMock()
    broker.get_qty.return_value = 10.0
    result = OrderResult(status="filled", order_id="bt")

    with caplog.at_level(logging.INFO, logger="alpaca_bot.rebalance"):
        _apply_order_result(
            account,
            0,
            ticker,
            result,
            1000.0,
            "rebalance_initial",
            swing_pct=100.0,
            broker=broker,
        )

    assert "Filled rebalance_initial AAPL $1000.0 swing=100.0%" in caplog.text


def test_apply_order_result_stores_swing_on_limit_trade(caplog):
    from live_broker import LiveBroker

    account = MagicMock()
    account.serverTime = 1_700_000_000
    ticker = {"ticker": "AAPL", "volume": 1.0, "limitTrade": {"open": False}}
    account.tickers = [ticker]
    broker = MagicMock(spec=LiveBroker)
    result = OrderResult(status="limit_placed", order_id="ord-99")

    with caplog.at_level(logging.INFO, logger="alpaca_bot.rebalance"):
        _apply_order_result(
            account,
            0,
            ticker,
            result,
            500.0,
            "rebalance_buy",
            swing_pct=4.2,
            broker=broker,
        )

    assert account.tickers[0]["limitTrade"]["swing_pct"] == 4.2
    assert "Limit placed rebalance_buy AAPL $500.0 swing=4.2% id=ord-99" in caplog.text


def test_log_skip_uses_swing_pct(caplog):
    with caplog.at_level(logging.DEBUG, logger="alpaca_bot.rebalance"):
        _log_skip("MSFT", "rebalance_buy", "below_margin", 0.032)

    assert "Skip MSFT rebalance_buy reason=below_margin swing=3.2%" in caplog.text


def test_log_skip_missing_price_uses_dash(caplog):
    with caplog.at_level(logging.DEBUG, logger="alpaca_bot.rebalance"):
        _log_skip("MSFT", "", "price_missing_or_zero", None)

    assert "Skip MSFT - reason=price_missing_or_zero swing=-" in caplog.text


def test_rebalance_tick_attempt_and_skip_logging(caplog):
    cfg = Config()
    cfg.paper = True
    cfg.margin = 0.05

    class Account:
        tickers = [_ticker("AAPL", 10.0, 100.0, diff=0.02)]
        margin = 0.05
        equity = 0.0
        serverTime = 1_700_000_000
        market = "open"

    account = Account()
    broker = SimBroker(0.0, cfg)
    broker.positions["AAPL"] = 10.0

    with caplog.at_level(logging.DEBUG, logger="alpaca_bot.rebalance"):
        rebalance_tick(
            account,
            cfg,
            prices={"AAPL": 100.0},
            broker=broker,
            session="open",
        )

    assert "Skip AAPL rebalance_sell reason=below_margin swing=" in caplog.text


def test_intent_from_limit_placed_reads_orders_jsonl(tmp_path):
    orders = tmp_path / "orders.jsonl"
    rows = [
        {
            "order_id": "ord-1",
            "status": "limit_placed",
            "intent": "rebalance_initial",
            "symbol": "AAPL",
        },
        {
            "order_id": "ord-1",
            "status": "filled",
            "intent": "rebalance_initial",
            "symbol": "AAPL",
        },
    ]
    with open(orders, "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")

    assert _intent_from_limit_placed("ord-1", orders_path=str(orders)) == "rebalance_initial"
    assert _intent_from_limit_placed("missing", orders_path=str(orders)) is None


def test_intent_from_limit_placed_falls_back_to_trades(tmp_path):
    trades = tmp_path / "trades.jsonl"
    trades.write_text(
        json.dumps(
            {
                "order_id": "ord-legacy",
                "status": "limit_placed",
                "intent": "rebalance_buy",
                "symbol": "MSFT",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    missing_orders = tmp_path / "orders.jsonl"
    assert (
        _intent_from_limit_placed(
            "ord-legacy",
            orders_path=str(missing_orders),
            trades_path=str(trades),
        )
        == "rebalance_buy"
    )


def test_sync_open_limit_orders_recovers_intent_from_orders(tmp_path, monkeypatch):
    orders_path = tmp_path / "orders.jsonl"
    orders_path.write_text(
        json.dumps(
            {
                "order_id": "ord-1",
                "status": "limit_placed",
                "intent": "rebalance_initial",
                "symbol": "AAPL",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("rebalance.DEFAULT_ORDER_FILE", str(orders_path))

    account = MagicMock()
    account.serverTime = 1_700_000_000
    account.tickers = [
        {
            "ticker": "AAPL",
            "limitTrade": {
                "open": False,
                "id": "",
                "ts": 0,
                "side": "",
                "intent": "",
                "notional": None,
                "swing_pct": None,
            },
        }
    ]

    session = MagicMock()
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."

    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.json.return_value = [{"symbol": "AAPL", "id": "ord-1", "side": "buy"}]
    session.get.return_value = orders_resp

    sync_open_limit_orders(session, account, config)
    assert account.tickers[0]["limitTrade"]["intent"] == "rebalance_initial"


def test_sim_broker_failure_writes_trades_jsonl(tmp_path):
    trades = os.path.join(tmp_path, "trades.jsonl")
    cfg = Config()
    cfg.paper = True
    broker = SimBroker(0.0, cfg, trades_path=trades)

    result = broker.place_market_notional(
        "AAPL",
        "sell",
        100.0,
        50.0,
        intent="rebalance_sell",
        market_session="open",
    )
    assert result.is_failed

    with open(trades, encoding="utf-8") as file:
        row = json.loads(file.readline())

    assert row["status"] == "failed"
    assert row["intent"] == "rebalance_sell"
    assert row["error"] == "no shares to sell"


def test_rebalance_tick_emits_buy_sell_outcome_diagnostics():
    cfg = Config()
    cfg.paper = True
    cfg.margin = 0.03

    class Account:
        tickers = [_ticker("AAPL", 5.0, 100.0, diff=0.08)]
        margin = 0.03
        equity = 0.0
        serverTime = 1_700_000_000
        market = "open"

    account = Account()
    broker = SimBroker(50_000.0, cfg)
    broker.positions["AAPL"] = 5.0
    events = []

    # Under-weight enough to trigger hysteresis sell is not the case here.
    # Over-weight: 5 * 100 = 500 vs base ~ 50000/101 ~ 495 -> below margin
    rebalance_tick(
        account,
        cfg,
        prices={"AAPL": 100.0},
        broker=broker,
        session="open",
        diagnostics=events.append,
    )

    assert any(e.get("event") == "tick_summary" for e in events)


def test_liquidation_log_messages(caplog):
    from unittest.mock import patch

    cfg = Config()
    cfg.paper = True
    cfg.urlBase = "https://paper-api.alpaca."
    cfg.apiKey = "key"
    cfg.apiSecret = "secret"

    account = Status()
    account.market = "open"
    account.tickers = []

    session = MagicMock()
    close_resp = MagicMock()
    close_resp.status_code = 200
    close_resp.json.return_value = {"status": "filled"}
    session.delete.return_value = close_resp

    positions = [{"symbol": "ORPH", "qty": "1"}]

    with patch("state.append_trade"), patch(
        "state.get_cached_valid_tickers", return_value=[]
    ), patch.object(account, "save_state"):
        with caplog.at_level(logging.INFO, logger="alpaca_bot.state"):
            account.check_balances(session, positions, cfg)

    assert "Attempt liquidate ORPH" in caplog.text
    assert "Filled liquidate ORPH" in caplog.text
