import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("alpaca_bot.remote")

TIMEOUT_SECONDS = 10
_EMPTY_URL_WARNED = False


def _warn_empty_url_once() -> None:
    global _EMPTY_URL_WARNED
    if _EMPTY_URL_WARNED:
        return
    _EMPTY_URL_WARNED = True
    logger.warning(
        "Remote logging enabled but REMOTE_BASE_URL is empty; webhook posts skipped"
    )


def post_event(config, event: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """POST JSON to REMOTE_BASE_URL with X-Event-Type / optional HMAC. Never raises."""
    if getattr(config, "remote_logging_enabled", False) is not True:
        return False
    url = getattr(config, "remote_base_url", None)
    if not isinstance(url, str):
        url = ""
    url = url.strip()
    if not url:
        _warn_empty_url_once()
        return False

    payload = dict(data or {})
    if "ts" not in payload:
        payload["ts"] = str(int(time.time()))

    body = json.dumps(payload, separators=(",", ":"), default=str)
    body_bytes = body.encode("utf-8")
    title = getattr(config, "title", "")
    if not isinstance(title, str):
        title = ""
    headers = {
        "Content-Type": "application/json",
        "X-Event-Type": event,
        "X-App": title,
    }
    secret = getattr(config, "remote_webhook_secret", "")
    if not isinstance(secret, str):
        secret = ""
    if secret:
        digest = hmac.new(
            secret.encode("utf-8"), body_bytes, hashlib.sha256
        ).hexdigest()
        headers["X-Signature-256"] = f"sha256={digest}"

    try:
        result = requests.post(
            url, data=body_bytes, headers=headers, timeout=TIMEOUT_SECONDS
        )
        if not (200 <= result.status_code < 300):
            logger.warning(
                "Remote POST event=%s failed: status=%s body=%s",
                event,
                result.status_code,
                result.text[:500],
            )
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("Remote POST event=%s failed: %s", event, exc)
        return False


class WebhookLogHandler(logging.Handler):
    """Forward WARNING+ records to the remote webhook as event type ``log``."""

    def __init__(self, config):
        super().__init__(level=logging.WARNING)
        self.config = config

    def emit(self, record: logging.LogRecord) -> None:
        name = record.name
        if name == "alpaca_bot.remote" or name.startswith("alpaca_bot.remote."):
            return
        if name == "alpaca_bot.backtest" or name.startswith("alpaca_bot.backtest."):
            return
        try:
            post_event(
                self.config,
                "log",
                {
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "pathname": record.pathname,
                    "lineno": record.lineno,
                },
            )
        except Exception:
            self.handleError(record)
