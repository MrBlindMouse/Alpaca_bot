"""Dedicated file logging for backtest fetch/run (keeps alpaca_bot.log clean)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from typing import Iterator, List, Optional, Tuple

from backtest.config import BacktestConfig, ensure_parent_dir
from log_viewer import resolve_log_level

BACKTEST_LOGGERS = (
    "alpaca_bot.backtest",
    "alpaca_bot.rebalance",
    "alpaca_bot.ticker_source",
)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _log_formatter() -> logging.Formatter:
    return logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)


def _is_backtest_logger(name: str) -> bool:
    if name == "alpaca_bot.backtest" or name.startswith("alpaca_bot.backtest."):
        return True
    return name in ("alpaca_bot.rebalance", "alpaca_bot.ticker_source")


class _BacktestLogFilter(logging.Filter):
    """Drop backtest-related records from the main bot log file while a session is active."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _is_backtest_logger(record.name)


def _root_file_handlers() -> List[Tuple[logging.Handler, Optional[_BacktestLogFilter]]]:
    root = logging.getLogger("alpaca_bot")
    out: List[Tuple[logging.Handler, Optional[_BacktestLogFilter]]] = []
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            out.append((handler, None))
    return out


def _make_file_handler(path: str, level: int) -> RotatingFileHandler:
    ensure_parent_dir(path)
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3)
    handler.setFormatter(_log_formatter())
    handler.setLevel(level)
    return handler


@contextmanager
def backtest_logging_session(
    cfg: BacktestConfig,
    *,
    label: str = "backtest",
) -> Iterator[None]:
    """
    Route backtest/rebalance/ticker_source logs to cfg.log_file and exclude them
    from alpaca_bot root file handlers for the duration of the session.
    """
    level = resolve_log_level(cfg.log_level)
    file_handler = _make_file_handler(cfg.log_file, level)
    session_logger = logging.getLogger("alpaca_bot.backtest.session")
    session_logger.setLevel(level)

    attached: List[logging.Logger] = []
    for name in BACKTEST_LOGGERS:
        logger = logging.getLogger(name)
        logger.addHandler(file_handler)
        logger.setLevel(level)
        attached.append(logger)

    root_filters: List[Tuple[logging.Handler, _BacktestLogFilter]] = []
    for handler, _ in _root_file_handlers():
        filt = _BacktestLogFilter()
        handler.addFilter(filt)
        root_filters.append((handler, filt))

    session_logger.info("Backtest log session start (%s) -> %s", label, cfg.log_file)
    try:
        yield
    finally:
        session_logger.info("Backtest log session end (%s)", label)
        for handler, filt in root_filters:
            handler.removeFilter(filt)
        for logger in attached:
            logger.removeHandler(file_handler)
        file_handler.close()


def setup_backtest_cli_logging(cfg: BacktestConfig, *, verbose: bool = False) -> None:
    """CLI backtest: stderr for immediate feedback; file via backtest_logging_session in service."""
    level_name = "DEBUG" if verbose else cfg.log_level
    level = resolve_log_level(level_name)
    formatter = _log_formatter()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    root.addHandler(stream_handler)

    for name in BACKTEST_LOGGERS:
        logging.getLogger(name).setLevel(level)
