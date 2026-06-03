from unittest.mock import MagicMock, patch

import pytest

from alpaca_client import AlpacaAPIError, get_balances
from analytics import load_trades
from rebalance import (
    _limit_side_from_intent,
    _process_open_limit,
    _sync_volume_from_broker,
    rebalance_tick,
    sync_open_limit_orders,
)


def test_limit_side_from_intent_initial_buy():
    assert _limit_side_from_intent("initial buy") == "buy"
    assert _limit_side_from_intent("rebalance_initial") == "buy"
    assert _limit_side_from_intent("rebalance_sell") == "sell"


def test_sync_volume_from_broker_accepts_zero():
    account = MagicMock()
    ticker = {"ticker": "AAPL", "volume": 5.0}
    account.tickers = [ticker]

    session = MagicMock()
    config = MagicMock()

    with patch("rebalance.get_balances", return_value=0.0):
        _sync_volume_from_broker(session, config, account, 0, ticker)

    assert ticker["volume"] == 0.0


def test_process_open_limit_keeps_state_on_get_failure():
    account = MagicMock()
    account.serverTime = 1_700_000_000
    account.market = "extended"
    ticker = {
        "ticker": "AAPL",
        "volume": 1.0,
        "limitTrade": {
            "open": True,
            "id": "ord-1",
            "ts": 1,
            "side": "buy",
            "intent": "rebalance_buy",
            "notional": 100.0,
        },
    }
    account.tickers = [ticker]

    session = MagicMock()
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."

    failed = MagicMock(status_code=500, reason="Error")
    session.get.return_value = failed

    _process_open_limit(session, config, account, 0, ticker, {})
    assert ticker["limitTrade"]["open"] is True
    assert ticker["limitTrade"]["id"] == "ord-1"


def test_rebalance_tick_does_not_use_stale_price_when_bar_missing():
    account = MagicMock()
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 0,
            "price": 99.0,
            "difference": 0,
            "limitTrade": {
                "open": False,
                "id": "",
                "ts": 0,
                "side": "",
                "intent": "",
                "notional": None,
            },
        }
    ]
    account.margin = 0.05
    account.serverTime = 1_700_000_000

    broker = MagicMock()
    broker.get_equity.return_value = 100_000.0
    broker.place_market_notional = MagicMock()

    config = MagicMock()
    rebalance_tick(account, config, prices={"AAPL": 0.0}, broker=broker, session="open")

    broker.place_market_notional.assert_not_called()


@patch("rebalance.get_account")
def test_sync_open_limit_orders_attaches_unknown_order(mock_account):
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
    assert account.tickers[0]["limitTrade"]["open"] is True
    assert account.tickers[0]["limitTrade"]["id"] == "ord-1"


def test_get_balances_flat_position_returns_zero():
    session = MagicMock()
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."

    response = MagicMock(status_code=404, reason="Not Found")
    session.get.return_value = response

    assert get_balances(session, config, "AAPL") == 0.0


def test_get_account_raises_on_error():
    session = MagicMock()
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."

    response = MagicMock(status_code=401, reason="Unauthorized")
    session.get.return_value = response

    with pytest.raises(AlpacaAPIError):
        from alpaca_client import get_account

        get_account(session, config)


def test_load_trades_skips_malformed_lines(tmp_path):
    path = tmp_path / "trades.jsonl"
    path.write_text(
        '{"status":"filled","symbol":"AAPL","intent":"buy","ts":"2025-01-01T12:00:00Z"}\n'
        "not json\n",
        encoding="utf-8",
    )
    trades = load_trades(str(path))
    assert len(trades) == 1
    assert trades[0]["symbol"] == "AAPL"


@patch("config.dotenv_values")
def test_config_rejects_invalid_version(mock_env):
    mock_env.return_value = {
        "VERSION": "PAper",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
        "MARGIN": "0.05",
    }
    with pytest.raises(ValueError, match="VERSION"):
        from config import Config

        Config().update()
