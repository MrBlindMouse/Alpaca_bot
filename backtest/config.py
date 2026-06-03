"""Backtest configuration from environment."""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import dotenv_values

from config import Config


@dataclass
class BacktestConfig:
    bar_db: str = "data/bars.sqlite"
    symbols_file: str = "data/backtest_symbols.json"
    weights_file: str = "data/backtest_weights.json"
    comparison_file: str = "backtest_comparison.csv"
    margins: str = ""
    timeframe: str = "5Min"
    feed: str = "iex"
    adjustment: str = "all"
    data_rpm: int = 150
    symbol_delay_ms: int = 0
    start: str = ""
    end: str = ""
    initial_cash: float = 100_000.0
    trades_file: str = "backtest_trades.jsonl"
    equity_file: str = "backtest_equity.csv"
    decisions_file: str = "backtest_decisions.jsonl"
    log_file: str = "backtest.log"
    log_level: str = "INFO"


def load_backtest_config() -> BacktestConfig:
    raw = dotenv_values(".env")
    cfg = BacktestConfig()
    cfg.bar_db = (raw.get("BACKTEST_BAR_DB") or cfg.bar_db).strip()
    cfg.symbols_file = (raw.get("BACKTEST_SYMBOLS_FILE") or cfg.symbols_file).strip()
    cfg.weights_file = (raw.get("BACKTEST_WEIGHTS_FILE") or cfg.weights_file).strip()
    cfg.comparison_file = (raw.get("BACKTEST_COMPARISON_FILE") or cfg.comparison_file).strip()
    cfg.margins = (raw.get("BACKTEST_MARGINS") or raw.get("MARGIN") or "").strip()
    cfg.timeframe = (raw.get("BACKTEST_TIMEFRAME") or cfg.timeframe).strip()
    cfg.feed = (raw.get("BACKTEST_FEED") or cfg.feed).strip()
    cfg.adjustment = (raw.get("BACKTEST_ADJUSTMENT") or cfg.adjustment).strip()
    cfg.start = (raw.get("BACKTEST_START") or "").strip()
    cfg.end = (raw.get("BACKTEST_END") or "").strip()
    cfg.trades_file = (raw.get("BACKTEST_TRADES_FILE") or cfg.trades_file).strip()
    cfg.equity_file = (raw.get("BACKTEST_EQUITY_FILE") or cfg.equity_file).strip()
    cfg.decisions_file = (raw.get("BACKTEST_DECISIONS_FILE") or cfg.decisions_file).strip()
    cfg.log_file = (raw.get("BACKTEST_LOG_FILE") or cfg.log_file).strip()
    cfg.log_level = (raw.get("BACKTEST_LOG_LEVEL") or cfg.log_level).strip().upper()
    try:
        cfg.data_rpm = int(raw.get("BACKTEST_DATA_RPM") or "150")
    except (TypeError, ValueError):
        cfg.data_rpm = 150
    try:
        cfg.symbol_delay_ms = int(raw.get("BACKTEST_SYMBOL_DELAY_MS") or "0")
    except (TypeError, ValueError):
        cfg.symbol_delay_ms = 0
    try:
        cfg.initial_cash = float(raw.get("BACKTEST_INITIAL_CASH") or "100000")
    except (TypeError, ValueError):
        cfg.initial_cash = 100_000.0
    return cfg


def load_trading_config() -> Config:
    config = Config()
    config.update()
    config.dry_run = True
    return config


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
