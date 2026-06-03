"""Backtest simulation engine."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from backtest.broker import SimBroker
from backtest.cache import BarCache
from backtest.clock import filter_rth_timestamps, ts_to_epoch
from backtest.config import BacktestConfig, ensure_parent_dir, load_trading_config
from backtest.report import EquityPoint, run_summary, write_equity_csv
from backtest.universe import load_symbols_from_file
from rebalance import rebalance_tick
from state import Status

logger = logging.getLogger("alpaca_bot.backtest.engine")


def _empty_limit_trade() -> dict:
    return {
        "open": False,
        "id": "",
        "ts": 0,
        "side": "",
        "intent": "",
        "notional": None,
    }


def build_backtest_account(symbols: List[str], margin: float, initial_cash: float) -> Status:
    account = Status()
    account.margin = margin
    account.equity = initial_cash
    account.market = "open"
    account.serverTime = 0
    account.tickers = [
        {
            "ticker": sym,
            "volume": 0.0,
            "difference": 0.0,
            "price": 0.0,
            "limitTrade": _empty_limit_trade(),
        }
        for sym in symbols
    ]
    return account


def run_backtest(
    bt_cfg: BacktestConfig,
    *,
    start: str,
    end: str,
    cash: Optional[float] = None,
    symbols: Optional[List[str]] = None,
    margin: Optional[float] = None,
    equity_file: Optional[str] = None,
    trades_file: Optional[str] = None,
    write_equity: bool = True,
) -> dict:
    cache = BarCache(bt_cfg.bar_db)
    if symbols is None:
        symbols = load_symbols_from_file(bt_cfg.symbols_file)
    if not symbols:
        raise RuntimeError(f"No symbols; run fetch first or create {bt_cfg.symbols_file}")

    range_start = start if "T" in start else f"{start}T00:00:00Z"
    range_end = end if "T" in end else f"{end}T23:59:59Z"
    timestamps = filter_rth_timestamps(cache.list_timestamps(range_start, range_end))
    if not timestamps:
        raise RuntimeError("No RTH bars in cache for the requested range")

    trading_cfg = load_trading_config()
    use_margin = margin if margin is not None else trading_cfg.margin
    trading_cfg.margin = use_margin
    initial_cash = cash if cash is not None else bt_cfg.initial_cash
    out_equity = equity_file or bt_cfg.equity_file
    out_trades = trades_file or bt_cfg.trades_file
    out_decisions = bt_cfg.decisions_file
    account = build_backtest_account(symbols, use_margin, initial_cash)
    broker = SimBroker(initial_cash, trading_cfg, trades_path=out_trades)
    ensure_parent_dir(out_decisions)
    with open(out_decisions, "w", encoding="utf-8"):
        pass

    curve: List[EquityPoint] = []
    missing_warnings = 0
    decision_events = 0
    tick_summaries = 0
    total_attempts = 0
    total_fills = 0
    total_failures = 0
    skip_totals: dict[str, int] = {}

    def diagnostics(event: dict) -> None:
        nonlocal decision_events, tick_summaries, total_attempts, total_fills, total_failures
        decision_events += 1
        with open(out_decisions, "a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=True) + "\n")
        if event.get("event") == "tick_summary":
            tick_summaries += 1
            total_attempts += int(event.get("attempts", 0))
            total_fills += int(event.get("fills", 0))
            total_failures += int(event.get("failures", 0))
            skipped = event.get("skipped", {})
            if isinstance(skipped, dict):
                for key, value in skipped.items():
                    skip_totals[str(key)] = skip_totals.get(str(key), 0) + int(value)

    for ts in timestamps:
        prices = cache.prices_at(ts, symbols)
        missing = [s for s in symbols if s not in prices]
        if missing:
            missing_warnings += 1
            if missing_warnings <= 5:
                logger.warning("Missing bar at %s for %s symbols", ts, len(missing))

        account.serverTime = ts_to_epoch(ts)
        account.market = "open"
        for key, ticker in enumerate(account.tickers):
            sym = ticker["ticker"]
            if sym in prices and prices[sym] > 0:
                account.tickers[key]["price"] = prices[sym]

        account.equity = broker.get_equity(prices)
        rebalance_tick(
            account,
            trading_cfg,
            prices=prices,
            broker=broker,
            session="open",
            diagnostics=diagnostics,
        )
        for key, ticker in enumerate(account.tickers):
            sym = ticker["ticker"]
            ticker["volume"] = broker.get_qty(sym)

        equity = broker.get_equity(prices)
        account.equity = equity
        curve.append(
            EquityPoint(
                ts=ts,
                equity=equity,
                cash=broker.cash,
            )
        )

    if write_equity:
        write_equity_csv(out_equity, curve)
    summary = run_summary(curve, out_trades)
    summary["steps"] = len(timestamps)
    summary["missing_bar_warnings"] = missing_warnings
    summary["decisions_file"] = out_decisions
    summary["decision_events"] = decision_events
    summary["tick_summaries"] = tick_summaries
    summary["decision_attempts"] = total_attempts
    summary["decision_fills"] = total_fills
    summary["decision_failures"] = total_failures
    summary["decision_skipped"] = skip_totals
    return summary
