"""Run rebalancer and benchmark strategies for side-by-side comparison."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import List, Optional

from backtest.benchmarks import STRATEGY_CAP, STRATEGY_EQUAL, run_buy_and_hold
from backtest.cache import BarCache
from backtest.clock import filter_rth_timestamps
from backtest.config import BacktestConfig, ensure_parent_dir
from backtest.engine import run_backtest
from backtest.report import run_summary
from backtest.universe import load_symbols_from_file, load_weights_from_file


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

    timestamps = filter_rth_timestamps(cache.list_timestamps(range_start, range_end))
    if not timestamps:
        raise RuntimeError("No RTH bars in cache for the requested range")

    results: List[StrategyResult] = []

    ew = run_buy_and_hold(
        cache, symbols, timestamps, cash, weights=None, strategy_name=STRATEGY_EQUAL
    )
    results.append(_summary_to_result(ew))

    weights = load_weights_from_file(bt_cfg.weights_file)
    cap = run_buy_and_hold(
        cache,
        symbols,
        timestamps,
        cash,
        weights=weights if weights else None,
        strategy_name=STRATEGY_CAP,
    )
    results.append(_summary_to_result(cap))

    primary = primary_margin if primary_margin is not None else (margins[0] if margins else None)

    for margin in margins:
        equity_file = bt_cfg.equity_file
        trades_file = bt_cfg.trades_file
        if margin != primary:
            base, ext = os.path.splitext(bt_cfg.equity_file)
            equity_file = f"{base}_m{margin:g}{ext or '.csv'}"
            base_t, ext_t = os.path.splitext(bt_cfg.trades_file)
            trades_file = f"{base_t}_m{margin:g}{ext_t or '.jsonl'}"

        summary = run_backtest(
            bt_cfg,
            start=start,
            end=end,
            cash=cash,
            symbols=symbols,
            margin=margin,
            equity_file=equity_file,
            trades_file=trades_file,
            write_equity=(margin == primary),
        )
        summary["strategy"] = "Rebalancer"
        summary["margin"] = margin
        results.append(_summary_to_result(summary))

    write_comparison_csv(bt_cfg.comparison_file, results)
    return results
