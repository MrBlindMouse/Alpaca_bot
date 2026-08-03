"""Run rebalancer and benchmark strategies for side-by-side comparison."""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

from backtest.benchmarks import STRATEGY_CAP, STRATEGY_EQUAL, run_buy_and_hold
from backtest.cache import BarCache
from backtest.clock import filter_rth_timestamps
from backtest.config import BacktestConfig, ensure_parent_dir
from backtest.engine import run_backtest
from backtest.universe import load_symbols_from_file, load_weights_from_file

logger = logging.getLogger("alpaca_bot.backtest.compare")


@dataclass
class StrategyResult:
    strategy: str
    margin: Optional[float]
    total_return_pct: float
    max_drawdown_pct: float
    trade_count: int
    end_equity: float
    start_equity: float = 0.0

    def margin_label(self) -> str:
        if self.margin is None:
            return "—"
        return f"{self.margin:g}"


def _normalize_range(start: str, end: str) -> tuple[str, str]:
    range_start = start if "T" in start else f"{start}T00:00:00Z"
    range_end = end if "T" in end else f"{end}T23:59:59Z"
    return range_start, range_end


def _summary_to_result(summary: dict) -> StrategyResult:
    return StrategyResult(
        strategy=summary.get("strategy", "Rebalancer"),
        margin=summary.get("margin"),
        total_return_pct=float(summary.get("total_return_pct", 0)),
        max_drawdown_pct=float(summary.get("max_drawdown_pct", 0)),
        trade_count=int(summary.get("trade_count", 0)),
        end_equity=float(summary.get("end_equity", 0)),
        start_equity=float(summary.get("start_equity", 0)),
    )


def write_comparison_csv(path: str, results: List[StrategyResult]) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "strategy",
                "margin",
                "total_return_pct",
                "max_drawdown_pct",
                "trade_count",
                "end_equity",
            ]
        )
        for row in results:
            writer.writerow(
                [
                    row.strategy,
                    row.margin_label(),
                    f"{row.total_return_pct:.4f}",
                    f"{row.max_drawdown_pct:.4f}",
                    row.trade_count,
                    f"{row.end_equity:.2f}",
                ]
            )


def _margin_artifact(path: str, margin: float, primary: Optional[float]) -> str:
    if primary is not None and margin == primary:
        return path
    base, ext = os.path.splitext(path)
    return f"{base}_m{margin:g}{ext or ''}"


def run_comparisons(
    bt_cfg: BacktestConfig,
    *,
    start: str,
    end: str,
    cash: float,
    margins: List[float],
    symbols: Optional[List[str]] = None,
    primary_margin: Optional[float] = None,
) -> List[StrategyResult]:
    range_start, range_end = _normalize_range(start, end)
    cache = BarCache(bt_cfg.bar_db)
    if symbols is None:
        symbols = load_symbols_from_file(bt_cfg.symbols_file)
    if not symbols:
        raise RuntimeError(f"No symbols in {bt_cfg.symbols_file}")

    timeframe = bt_cfg.timeframe or "5Min"
    timestamps = filter_rth_timestamps(
        cache.list_timestamps(range_start, range_end, timeframe=timeframe)
    )
    if not timestamps:
        raise RuntimeError("No RTH bars in cache for the requested range")

    results: List[StrategyResult] = []

    ew = run_buy_and_hold(
        cache,
        symbols,
        timestamps,
        cash,
        weights=None,
        strategy_name=STRATEGY_EQUAL,
        timeframe=timeframe,
    )
    results.append(_summary_to_result(ew))

    weights = load_weights_from_file(bt_cfg.weights_file)
    if not weights:
        logger.warning(
            "No cap-weights in %s; Cap-wt B&H falls back to equal weight",
            bt_cfg.weights_file,
        )
    cap = run_buy_and_hold(
        cache,
        symbols,
        timestamps,
        cash,
        weights=weights if weights else None,
        strategy_name=STRATEGY_CAP,
        timeframe=timeframe,
    )
    results.append(_summary_to_result(cap))

    primary = primary_margin if primary_margin is not None else (margins[0] if margins else None)

    for margin in margins:
        equity_file = _margin_artifact(bt_cfg.equity_file, margin, primary)
        trades_file = _margin_artifact(bt_cfg.trades_file, margin, primary)
        decisions_file = _margin_artifact(bt_cfg.decisions_file, margin, primary)

        summary = run_backtest(
            bt_cfg,
            start=start,
            end=end,
            cash=cash,
            symbols=symbols,
            margin=margin,
            equity_file=equity_file,
            trades_file=trades_file,
            decisions_file=decisions_file,
            write_equity=True,
        )
        summary["strategy"] = "Rebalancer"
        summary["margin"] = margin
        results.append(_summary_to_result(summary))

    write_comparison_csv(bt_cfg.comparison_file, results)
    return results
