from unittest.mock import MagicMock, patch

from rebalance import LIMIT_ORDER_MAX_AGE_SECONDS, _process_open_limit


@patch("rebalance._sync_volume_from_broker")
def test_partially_filled_syncs_volume_keeps_limit_open(mock_sync):
    account = MagicMock()
    account.serverTime = 1_700_000_000
    account.market = "extended"
    ticker = {
        "ticker": "AAPL",
        "volume": 1.0,
        "limitTrade": {
            "open": True,
            "id": "ord-1",
            "ts": 1_700_000_000,
            "side": "buy",
            "intent": "rebalance_buy",
            "notional": 100.0,
        },
    }
    account.tickers = [ticker]

    session = MagicMock()
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."

    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status": "partially_filled", "filled_qty": "0.5"}
    session.get.return_value = resp

    _process_open_limit(session, config, account, 0, ticker, {})
    mock_sync.assert_called_once()
    assert ticker["limitTrade"]["open"] is True


@patch("rebalance._sync_volume_from_broker")
@patch("rebalance.log_limit_status")
def test_aged_partially_filled_cancels(mock_log, mock_sync):
    now = 1_700_000_000
    account = MagicMock()
    account.serverTime = now
    account.market = "extended"
    ticker = {
        "ticker": "AAPL",
        "volume": 1.0,
        "limitTrade": {
            "open": True,
            "id": "ord-1",
            "ts": now - LIMIT_ORDER_MAX_AGE_SECONDS - 1,
            "side": "buy",
            "intent": "rebalance_buy",
            "notional": 100.0,
        },
    }
    account.tickers = [ticker]

    session = MagicMock()
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.paper = True

    get_partial = MagicMock(status_code=200)
    get_partial.json.return_value = {"status": "partially_filled", "filled_qty": "0.5"}
    cancel_check = MagicMock(status_code=200)
    cancel_check.json.return_value = {"status": "partially_filled"}
    session.get.side_effect = [get_partial, cancel_check]
    session.delete.return_value = MagicMock(status_code=204)

    _process_open_limit(session, config, account, 0, ticker, {})

    session.delete.assert_called_once()
    assert account.tickers[0]["limitTrade"]["open"] is False
    assert mock_sync.call_count >= 2


@patch("rebalance._sync_volume_from_broker")
def test_process_open_limit_clears_on_404(mock_sync):
    account = MagicMock()
    account.serverTime = 1_700_000_000
    account.market = "extended"
    ticker = {
        "ticker": "AAPL",
        "volume": 1.0,
        "limitTrade": {
            "open": True,
            "id": "ord-gone",
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
    session.get.return_value = MagicMock(status_code=404, reason="Not Found")

    _process_open_limit(session, config, account, 0, ticker, {})

    assert account.tickers[0]["limitTrade"]["open"] is False
    mock_sync.assert_called_once()
