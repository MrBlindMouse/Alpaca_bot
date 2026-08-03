from unittest.mock import MagicMock, patch

from orders import create_order
from reporting import day_end


def test_slippage_guard_rejects_large_move():
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "k"
    config.apiSecret = "s"
    config.paper = True
    config.dry_run = False
    config.slippage_guard_enabled = True
    config.max_slippage_pct = 0.02

    session = MagicMock()
    with patch("orders.get_snapshot_vwap", return_value=110.0), patch(
        "orders.append_trade"
    ):
        result = create_order(
            session,
            config,
            100.0,
            "buy",
            "AAPL",
            intent="rebalance_buy",
            market_status="open",
            current_price=100.0,
        )

    session.post.assert_not_called()
    assert result.is_failed
    assert "slippage" in (result.error or "")


def test_day_end_posts_equity_payload():
    account = MagicMock()
    account.market = "closed"
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "k"
    config.apiSecret = "s"
    config.paper = True
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com/hook"
    config.remote_webhook_secret = ""
    config.title = "Alpaca Test"

    session = MagicMock()
    activities = MagicMock(status_code=200)
    activities.json.return_value = [
        {"activity_type": "CSD", "net_amount": "1000"},
        {"activity_type": "CSW", "net_amount": "100"},
    ]
    session.get.return_value = activities

    with patch(
        "reporting.get_balances",
        return_value=[{"market_value": "500", "cost_basis": "400"}],
    ), patch(
        "reporting.get_account",
        return_value={"cash": "200"},
    ), patch("reporting.remote.post_event") as mock_post:
        day_end(session, account, config)

    mock_post.assert_called_once()
    event_type, payload = mock_post.call_args[0][1], mock_post.call_args[0][2]
    assert event_type == "day_end"
    assert payload["equity"] == 700.0  # 200 cash + 500 market
    assert payload["cost"] == 600.0  # 200 cash + 400 cost
    assert payload["investment"] == 900.0  # 1000 - 100
