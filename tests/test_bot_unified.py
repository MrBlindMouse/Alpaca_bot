from unittest.mock import MagicMock, patch

from rebalance import bot


@patch("rebalance.rebalance_tick")
@patch("rebalance.get_account")
@patch("rebalance._fetch_snapshot_prices")
def test_bot_calls_rebalance_tick(mock_prices, mock_account, mock_tick):
    account = MagicMock()
    account.equity = 1000.0
    account.market = "open"
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 1,
            "price": 100,
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

    mock_account.return_value = {"equity": "1000"}
    mock_prices.return_value = {"AAPL": 100.0}

    session = MagicMock()
    config = MagicMock()

    bot(session, account, config)

    mock_tick.assert_called_once()
    _, kwargs = mock_tick.call_args
    assert kwargs["log_summary"] is True
    assert kwargs["session"] == "open"
    assert kwargs["prices"] == {"AAPL": 100.0}
