from unittest.mock import MagicMock, patch

from live_broker import LiveBroker
from orders import OrderResult


def test_live_broker_place_delegates_to_create_order():
    session = MagicMock()
    config = MagicMock()
    account = MagicMock()
    account.equity = 50_000.0
    account.tickers = []

    broker = LiveBroker(session, config, account)
    with patch("live_broker.create_order", return_value=OrderResult(status="filled")) as mock_create:
        result = broker.place_market_notional(
            "AAPL",
            "buy",
            100.0,
            150.0,
            intent="rebalance_buy",
            market_session="open",
        )

    assert result.is_filled
    mock_create.assert_called_once_with(
        session,
        config,
        100.0,
        "buy",
        "AAPL",
        intent="rebalance_buy",
        market_status="open",
        current_price=150.0,
        circuit=None,
    )


def test_live_broker_get_equity_uses_account():
    session = MagicMock()
    config = MagicMock()
    account = MagicMock()
    account.equity = 42_000.0
    account.tickers = []

    broker = LiveBroker(session, config, account)
    assert broker.get_equity({}) == 42_000.0
