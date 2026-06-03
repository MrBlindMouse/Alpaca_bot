"""Backtest output reports."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

from backtest.config import ensure_parent_dir


@dataclass
class EquityPoint:
    ts: str
    equity: float
    cash: float


def write_equity_csv(path: str, curve: List[EquityPoint]) -> None:
    ensure_parent_dir(path)
    peak = 0.0
    with open(path, "w", encoding="utf-8") as file:
        file.write("ts,equity,cash,drawdown_pct\n")
        for point in curve:
            peak = max(peak, point.equity)
            dd = 0.0
            if peak > 0:
                dd = (point.equity - peak) / peak * 100.0
            file.write(f"{point.ts},{point.equity:.2f},{point.cash:.2f},{dd:.4f}\n")


def _count_trades(path: str) -> int:
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path, encoding="utf-8") as file:
        for line in file:
            if line.strip():
                count += 1
    return count


def run_summary(curve: List[EquityPoint], trades_path: str) -> dict:
    if not curve:
        return {"total_return_pct": 0.0, "max_drawdown_pct": 0.0, "trade_count": 0}

    start_eq = curve[0].equity
    end_eq = curve[-1].equity
    total_return = 0.0
    if start_eq > 0:
        total_return = (end_eq - start_eq) / start_eq * 100.0

    peak = curve[0].equity
    max_dd = 0.0
    for point in curve:
        peak = max(peak, point.equity)
        if peak > 0:
            dd = (point.equity - peak) / peak * 100.0
            max_dd = min(max_dd, dd)

    return {
        "start_equity": start_eq,
        "end_equity": end_eq,
        "total_return_pct": total_return,
        "max_drawdown_pct": max_dd,
        "trade_count": _count_trades(trades_path),
        "start_ts": curve[0].ts,
        "end_ts": curve[-1].ts,
    }
