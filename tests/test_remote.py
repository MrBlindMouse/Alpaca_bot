import hashlib
import hmac
import json
import logging
from unittest.mock import MagicMock, patch

import remote
from config import Config, setup_logging


@patch("remote.requests.post")
def test_remote_noop_when_disabled(mock_post):
    config = Config()
    config.remote_logging_enabled = False
    config.remote_base_url = "https://example.com/hook"
    assert remote.post_event(config, "log", {"message": "test"}) is False
    mock_post.assert_not_called()


@patch("remote.requests.post")
def test_remote_noop_when_url_empty(mock_post):
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = ""
    remote._EMPTY_URL_WARNED = False
    assert remote.post_event(config, "log", {"message": "test"}) is False
    mock_post.assert_not_called()


@patch("remote.requests.post")
def test_remote_posts_when_enabled(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com/hook"
    config.title = "Alpaca Test"
    config.remote_webhook_secret = ""
    assert remote.post_event(config, "log", {"code": "1", "snippet": "test"}) is True
    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == "https://example.com/hook"
    headers = mock_post.call_args[1]["headers"]
    assert headers["X-Event-Type"] == "log"
    assert headers["X-App"] == "Alpaca Test"
    assert "X-Signature-256" not in headers
    body = mock_post.call_args[1]["data"]
    payload = json.loads(body.decode("utf-8"))
    assert payload["code"] == "1"
    assert payload["snippet"] == "test"
    assert "ts" in payload


@patch("remote.requests.post")
def test_remote_hmac_signature(mock_post):
    mock_post.return_value = MagicMock(status_code=201)
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com/hook"
    config.title = "Alpaca"
    config.remote_webhook_secret = "s3cret"
    data = {"ts": "123", "equity": 1.0}
    assert remote.post_event(config, "day_end", data) is True
    body = mock_post.call_args[1]["data"]
    expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    headers = mock_post.call_args[1]["headers"]
    assert headers["X-Event-Type"] == "day_end"
    assert headers["X-Signature-256"] == f"sha256={expected}"


@patch("remote.requests.post")
def test_webhook_handler_posts_warning(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com/hook"
    config.title = "Alpaca Test"
    config.log_file = ""
    config.log_level = "WARNING"

    root = logging.getLogger("alpaca_bot")
    root.handlers.clear()
    handler = remote.WebhookLogHandler(config)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    try:
        logging.getLogger("alpaca_bot.rebalance").warning("order failed")
    finally:
        root.removeHandler(handler)

    mock_post.assert_called_once()
    headers = mock_post.call_args[1]["headers"]
    assert headers["X-Event-Type"] == "log"
    payload = json.loads(mock_post.call_args[1]["data"].decode("utf-8"))
    assert payload["level"] == "WARNING"
    assert "order failed" in payload["message"]


@patch("remote.requests.post")
def test_webhook_handler_skips_remote_logger(mock_post):
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com/hook"
    handler = remote.WebhookLogHandler(config)
    root = logging.getLogger("alpaca_bot")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    try:
        logging.getLogger("alpaca_bot.remote").warning("Remote POST failed")
    finally:
        root.removeHandler(handler)
    mock_post.assert_not_called()


@patch("remote.post_event")
def test_log_trade_filled_posts_event(mock_post):
    from orders import _log_trade

    config = MagicMock()
    config.paper = True
    with patch("orders.append_trade"):
        _log_trade(
            config,
            symbol="AAPL",
            side="buy",
            intent="rebalance_buy",
            order_type="market",
            market_session="open",
            status="filled",
            order_id="1",
            notional=100.0,
        )
    mock_post.assert_called_once()
    assert mock_post.call_args[0][1] == "trade"


@patch("remote.post_event")
def test_log_trade_non_filled_skips_event(mock_post):
    from orders import _log_trade

    config = MagicMock()
    config.paper = True
    with patch("orders.append_order_event") as mock_order:
        _log_trade(
            config,
            symbol="AAPL",
            side="buy",
            intent="rebalance_buy",
            order_type="limit",
            market_session="extended",
            status="limit_placed",
            order_id="1",
        )
    mock_post.assert_not_called()
    mock_order.assert_called_once()


@patch("remote.post_event")
def test_log_trade_filled_uses_trades_file(mock_post):
    from orders import _log_trade

    config = MagicMock()
    config.paper = True
    with patch("orders.append_trade") as mock_trade, patch(
        "orders.append_order_event"
    ) as mock_order:
        _log_trade(
            config,
            symbol="AAPL",
            side="buy",
            intent="rebalance_buy",
            order_type="market",
            market_session="open",
            status="filled",
            order_id="1",
            notional=100.0,
        )
    mock_trade.assert_called_once()
    mock_order.assert_not_called()
    mock_post.assert_called_once()


@patch("remote.requests.post")
def test_setup_logging_attaches_webhook_handler(mock_post):
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com/hook"
    config.log_level = "INFO"
    config.log_file = ""
    root = setup_logging(config, console=False)
    assert any(isinstance(h, remote.WebhookLogHandler) for h in root.handlers)
    root.handlers.clear()
