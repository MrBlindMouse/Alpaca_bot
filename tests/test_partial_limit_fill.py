from unittest.mock import MagicMock, patch

from rebalance import _process_open_limit


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
