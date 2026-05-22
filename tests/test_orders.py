from unittest.mock import MagicMock, patch

from orders import OrderResult, create_order


def test_order_result_helpers():
    filled = OrderResult(status="filled", order_id="1")
    assert filled.is_filled
    assert not filled.is_failed
    assert not filled.is_limit_placed

    limit = OrderResult(status="limit_placed", order_id="2")
    assert limit.is_limit_placed

    failed = OrderResult(status="failed", error="timeout")
    assert failed.is_failed


def test_market_order_poll_failure_not_filled():
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "k"
    config.apiSecret = "s"
    config.paper = True
    config.dry_run = False
    config.slippage_guard_enabled = False

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.json.return_value = {"id": "order-1", "status": "open"}

    poll_resp = MagicMock()
    poll_resp.status_code = 500
    poll_resp.reason = "Server Error"

    session = MagicMock()
    session.post.return_value = post_resp
    session.get.return_value = poll_resp

    with patch("orders.append_trade"), patch("orders.time.sleep"):
        result = create_order(
            session,
            config,
            100.0,
            "buy",
            "AAPL",
            intent="rebalance_buy",
            market_status="open",
            current_price=150.0,
        )

    assert result.is_failed
    assert not result.is_filled


def test_dry_run_skips_post():
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "k"
    config.apiSecret = "s"
    config.paper = True
    config.dry_run = True
    config.slippage_guard_enabled = False

    session = MagicMock()

    with patch("orders.append_trade"):
        result = create_order(
            session,
            config,
            50.0,
            "buy",
            "AAPL",
            intent="rebalance_buy",
            market_status="open",
            current_price=100.0,
        )

    session.post.assert_not_called()
    assert result.status == "filled"
    assert result.order_id == "dry-run"
