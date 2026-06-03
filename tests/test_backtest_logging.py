import logging
from logging.handlers import RotatingFileHandler

from backtest.config import BacktestConfig
from backtest.logging_setup import (
    _BacktestLogFilter,
    backtest_logging_session,
    setup_backtest_cli_logging,
)


def test_backtest_session_routes_rebalance_to_backtest_log(tmp_path):
    bot_log = tmp_path / "alpaca_bot.log"
    backtest_log = tmp_path / "backtest.log"
    cfg = BacktestConfig(log_file=str(backtest_log), log_level="INFO")

    root = logging.getLogger("alpaca_bot")
    root.handlers.clear()
    root.setLevel(logging.INFO)
    bot_handler = RotatingFileHandler(bot_log, maxBytes=1_000_000, backupCount=1)
    bot_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(bot_handler)

    with backtest_logging_session(cfg, label="test"):
        logging.getLogger("alpaca_bot.rebalance").info("rebalance-msg")
        logging.getLogger("alpaca_bot.backtest.engine").warning("engine-msg")
        logging.getLogger("alpaca_bot.scheduler").info("scheduler-msg")

    assert "rebalance-msg" in backtest_log.read_text(encoding="utf-8")
    assert "engine-msg" in backtest_log.read_text(encoding="utf-8")
    bot_text = bot_log.read_text(encoding="utf-8")
    assert "rebalance-msg" not in bot_text
    assert "engine-msg" not in bot_text
    assert "scheduler-msg" in bot_text


def test_backtest_log_filter():
    filt = _BacktestLogFilter()
    record = logging.LogRecord(
        "alpaca_bot.rebalance",
        logging.INFO,
        "",
        0,
        "x",
        (),
        None,
    )
    assert filt.filter(record) is False
    record.name = "alpaca_bot.scheduler"
    assert filt.filter(record) is True


def test_cli_setup_writes_via_session(tmp_path):
    backtest_log = tmp_path / "bt.log"
    cfg = BacktestConfig(log_file=str(backtest_log), log_level="INFO")
    setup_backtest_cli_logging(cfg, verbose=False)
    with backtest_logging_session(cfg, label="cli-test"):
        logging.getLogger("alpaca_bot.backtest.fetch").info("fetch-line")
    assert "fetch-line" in backtest_log.read_text(encoding="utf-8")
