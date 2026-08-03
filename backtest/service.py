"""Backtest operations for CLI and TUI."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import replace
from typing import Callable, List, Optional, Tuple

from backtest.compare import StrategyResult, run_comparisons
from backtest.config import BacktestConfig
from backtest.cache import BarCache
from backtest.fetch import fetch_all
from backtest.logging_setup import backtest_logging_session
from env_config import read_margin


def parse_margins(raw: str, *, default: Optional[float] = None) -> List[float]:
    if not raw or not raw.strip():
        if default is not None:
            return [default]
        return [read_margin()]
    parts = []
    for piece in raw.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        parts.append(float(piece))
    if not parts:
        if default is not None:
            return [default]
        return [read_margin()]
    return parts


def apply_ui_overrides(
    cfg: BacktestConfig,
    *,
    start: str,
    end: str,
    cash: float,
    timeframe: str,
    feed: str,
    adjustment: str,
    margins: str,
) -> Tuple[BacktestConfig, List[float]]:
    updated = replace(
        cfg,
        start=start.strip(),
        end=end.strip(),
        initial_cash=cash,
        timeframe=timeframe.strip() or cfg.timeframe,
        feed=feed.strip() or cfg.feed,
        adjustment=adjustment.strip() or cfg.adjustment,
    )
    margin_list = parse_margins(margins)
    return updated, margin_list


def cache_status_dict(cfg: BacktestConfig) -> dict:
    return {"db": cfg.bar_db, **BarCache(cfg.bar_db).status()}


def list_cached_datasets(cfg: BacktestConfig) -> List[dict]:
    datasets = []
    for row in BarCache(cfg.bar_db).list_fetch_datasets():
        start = row.get("start", "")
        end = row.get("end", "")
        timeframe = row.get("timeframe", "") or cfg.timeframe
        label = f"{start} - {end} - {timeframe}"
        datasets.append(
            {
                "label": label,
                "start": start,
                "end": end,
                "timeframe": timeframe,
                "symbols": int(row.get("symbols", 0)),
                "fetched_at": row.get("fetched_at", ""),
            }
        )
    return datasets


def execute_fetch(
    cfg: BacktestConfig,
    start: str,
    end: str,
    *,
    force: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    with backtest_logging_session(cfg, label=f"fetch {start} .. {end}"):
        return fetch_all(cfg, start=start, end=end, force=force, on_progress=on_progress)


def _comparison_artifact_files(
    cfg: BacktestConfig,
    margins: List[float],
    primary: Optional[float],
) -> List[str]:
    paths = [cfg.trades_file, cfg.decisions_file, cfg.equity_file]
    for margin in margins:
        if primary is not None and margin == primary:
            continue
        for path in (cfg.trades_file, cfg.decisions_file, cfg.equity_file):
            base, ext = os.path.splitext(path)
            paths.append(f"{base}_m{margin:g}{ext or ''}")
    return paths


def execute_comparisons(
    cfg: BacktestConfig,
    start: str,
    end: str,
    cash: float,
    margins: List[float],
    *,
    primary_margin: Optional[float] = None,
    reset_trades: bool = True,
) -> List[StrategyResult]:
    primary = primary_margin if primary_margin is not None else (margins[0] if margins else None)
    if reset_trades:
        for path in _comparison_artifact_files(cfg, margins, primary):
            if os.path.exists(path):
                os.remove(path)
    with backtest_logging_session(cfg, label=f"comparison {start} .. {end}"):
        return run_comparisons(
            cfg,
            start=start,
            end=end,
            cash=cash,
            margins=margins,
            primary_margin=primary,
        )


def load_comparison_rows(path: str) -> List[tuple]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            rows.append(
                (
                    row.get("strategy", ""),
                    row.get("margin", "—"),
                    row.get("total_return_pct", ""),
                    row.get("max_drawdown_pct", ""),
                    row.get("trade_count", ""),
                    row.get("end_equity", ""),
                )
            )
    return rows


def load_equity_preview(path: str, limit: int = 20) -> List[tuple]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()
    if len(lines) <= 1:
        return []
    data_rows = lines[1:][-limit:]
    rows = []
    for line in data_rows:
        parts = line.strip().split(",")
        if len(parts) >= 4:
            rows.append(tuple(parts[:4]))
    return rows


def load_trades_preview(path: str, limit: int = 50) -> List[dict]:
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            if line.strip():
                lines.append(line)
    rows = []
    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def summarize_decisions(path: str) -> dict:
    summary = {
        "events": 0,
        "tick_summaries": 0,
        "attempts": 0,
        "fills": 0,
        "failures": 0,
        "skipped": {},
    }
    if not os.path.exists(path):
        return summary
    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            summary["events"] += 1
            if row.get("event") != "tick_summary":
                continue
            summary["tick_summaries"] += 1
            summary["attempts"] += int(row.get("attempts", 0))
            summary["fills"] += int(row.get("fills", 0))
            summary["failures"] += int(row.get("failures", 0))
            skipped = row.get("skipped", {})
            if isinstance(skipped, dict):
                for key, value in skipped.items():
                    key_str = str(key)
                    summary["skipped"][key_str] = summary["skipped"].get(key_str, 0) + int(value)
    return summary
