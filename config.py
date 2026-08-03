import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

from dotenv import dotenv_values

from env_config import validate_margin

REQUIRED_KEYS = ("VERSION", "MARGIN")
ALLOWED_VERSIONS = frozenset({"PAPER", "LIVE"})
PAPER_KEYS = ("PAPER_KEY", "PAPER_SECRET")
LIVE_KEYS = ("API_KEY", "API_SECRET")


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self):
        self.remote_logging_enabled = False
        self.remote_base_url = ""
        self.remote_webhook_secret = ""
        self.log_level = "INFO"
        self.log_file = ""
        self.title = ""
        self.urlBase = ""
        self.apiKey = ""
        self.apiSecret = ""
        self.margin = 0.0
        self.paper = True
        self.dry_run = False
        self.slippage_guard_enabled = False
        self.max_slippage_pct = 0.02
        self.circuit_failure_threshold = 5
        self.circuit_backoff_seconds = 300
        self._remote_disabled_logged = False

    def update(self):
        raw = dotenv_values(".env")
        self._validate(raw)

        version = raw["VERSION"].strip()
        self.paper = version == "PAPER"
        self.title = "Alpaca Test" if self.paper else "Alpaca"
        self.urlBase = (
            "https://paper-api.alpaca."
            if self.paper
            else "https://api.alpaca."
        )
        self.apiKey = raw["PAPER_KEY"] if self.paper else raw["API_KEY"]
        self.apiSecret = raw["PAPER_SECRET"] if self.paper else raw["API_SECRET"]
        self.margin = float(raw["MARGIN"])

        self.remote_logging_enabled = _parse_bool(
            raw.get("REMOTE_LOGGING_ENABLED"), default=False
        )
        self.remote_base_url = (raw.get("REMOTE_BASE_URL") or "").strip().rstrip("/")
        self.remote_webhook_secret = (raw.get("REMOTE_WEBHOOK_SECRET") or "").strip()
        self.log_level = (raw.get("LOG_LEVEL") or "INFO").upper()
        self.log_file = (raw.get("LOG_FILE") or "").strip()

        self.slippage_guard_enabled = _parse_bool(
            raw.get("SLIPPAGE_GUARD_ENABLED"), default=False
        )
        try:
            self.max_slippage_pct = float(raw.get("MAX_SLIPPAGE_PCT") or "0.02")
        except (TypeError, ValueError) as exc:
            raise ValueError("MAX_SLIPPAGE_PCT must be a number") from exc

        try:
            self.circuit_failure_threshold = int(
                raw.get("CIRCUIT_FAILURE_THRESHOLD") or "5"
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("CIRCUIT_FAILURE_THRESHOLD must be an integer") from exc

        try:
            self.circuit_backoff_seconds = int(
                raw.get("CIRCUIT_BACKOFF_SECONDS") or "300"
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("CIRCUIT_BACKOFF_SECONDS must be an integer") from exc

    @staticmethod
    def _validate(raw: dict):
        missing = [k for k in REQUIRED_KEYS if not (raw.get(k) or "").strip()]
        if missing:
            raise ValueError(f"Missing required .env keys: {', '.join(missing)}")

        version = (raw.get("VERSION") or "").strip()
        if version not in ALLOWED_VERSIONS:
            raise ValueError(f"VERSION must be one of {sorted(ALLOWED_VERSIONS)} (got {version!r})")

        if version == "PAPER":
            missing = [k for k in PAPER_KEYS if not (raw.get(k) or "").strip()]
        else:
            missing = [k for k in LIVE_KEYS if not (raw.get(k) or "").strip()]
        if missing:
            raise ValueError(f"Missing required .env keys: {', '.join(missing)}")

        try:
            margin = float(raw["MARGIN"])
        except (TypeError, ValueError) as exc:
            raise ValueError("MARGIN must be a number") from exc
        validate_margin(margin)


def setup_logging(
    config: Config,
    *,
    console: bool = True,
    default_log_file: Optional[str] = None,
) -> logging.Logger:
    if not config.log_file and default_log_file:
        config.log_file = default_log_file

    from log_viewer import resolve_log_level

    level = resolve_log_level(config.log_level)
    root = logging.getLogger("alpaca_bot")
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if config.log_file:
        file_handler = RotatingFileHandler(
            config.log_file, maxBytes=5_000_000, backupCount=3
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if config.remote_logging_enabled and config.remote_base_url:
        from remote import WebhookLogHandler

        webhook_handler = WebhookLogHandler(config)
        root.addHandler(webhook_handler)

    return root


def log_remote_disabled_once(config: Config, logger: logging.Logger):
    if config.remote_logging_enabled or config._remote_disabled_logged:
        return
    config._remote_disabled_logged = True
    logger.debug("Remote logging disabled (REMOTE_LOGGING_ENABLED=false)")
