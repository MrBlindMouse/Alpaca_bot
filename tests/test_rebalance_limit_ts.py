from unittest.mock import MagicMock, patch

from rebalance import bot


@patch("rebalance.get_balances")
@patch("rebalance.get_account")
@patch("rebalance.alpaca_headers")
def test_synced_limit_order_gets_nonzero_ts(mock_headers, mock_account, mock_balances):
    account = MagicMock()
    account.equity = 0
    account.market = "closed"
    account.margin = 0.05
    account.serverTime = 1_700_000_000
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 1,
            "difference": 0,
            "price": 100,
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

    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    session = MagicMock()

    mock_account.return_value = {"equity": "1000"}
    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.json.return_value = [
        {"symbol": "AAPL", "id": "ord-1", "side": "buy"},
    ]
    session.get.return_value = orders_resp

    bot(session, account, config)
    assert account.tickers[0]["limitTrade"]["ts"] == account.serverTime
