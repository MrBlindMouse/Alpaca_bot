from unittest.mock import MagicMock, patch

from alpaca_client import AlpacaAPIError
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


@patch("rebalance.rebalance_tick")
@patch("rebalance.get_account")
def test_bot_soft_fails_on_account_api_error(mock_account, mock_tick):
    account = MagicMock()
    account.equity = 1000.0
    account.market = "open"
    account.tickers = [{"ticker": "AAPL"}]
    mock_account.side_effect = AlpacaAPIError(
        "account request failed: 500 Internal Server Error",
        status_code=500,
    )
    circuit = MagicMock()

    bot(MagicMock(), account, MagicMock(), circuit=circuit)

    mock_tick.assert_not_called()
    circuit.record_failure.assert_called_once()


@patch("rebalance.sync_open_limit_orders")
@patch("rebalance.get_account")
def test_bot_bootstrap_soft_fails_on_account_api_error(mock_account, mock_sync):
    account = MagicMock()
    account.equity = 0
    account.market = "open"
    account.tickers = []
    mock_account.side_effect = AlpacaAPIError(
        "account request failed: 500 Internal Server Error",
        status_code=500,
    )
    circuit = MagicMock()

    bot(MagicMock(), account, MagicMock(), circuit=circuit)

    account.check_ticker.assert_not_called()
    mock_sync.assert_not_called()
    circuit.record_failure.assert_called_once()
