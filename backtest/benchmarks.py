"""Buy-and-hold benchmark simulations on cached bars."""

from __future__ import annotations

from typing import Dict, List, Optional

from backtest.cache import BarCache
from backtest.report import EquityPoint, run_summary

STRATEGY_EQUAL = "Equal-wt B&H"
STRATEGY_CAP = "Cap-wt B&H (static NDX wt)"


def _normalize_weights(weights: Dict[str, float], symbols: List[str]) -> Dict[str, float]:
    subset = {s: weights[s] for s in symbols if s in weights and weights[s] > 0}
    if not subset:
        n = len(symbols)
        return {s: 1.0 / n for s in symbols} if n else {}
    total = sum(subset.values())
    return {s: w / total for s, w in subset.items()}


def run_buy_and_hold(
    cache: BarCache,
    symbols: List[str],
    timestamps: List[str],
    initial_cash: float,
    *,
    weights: Optional[Dict[str, float]] = None,
    strategy_name: str = STRATEGY_EQUAL,
) -> dict:
    if not timestamps:
        raise RuntimeError("No timestamps for buy-and-hold")

    t0 = timestamps[0]
    prices0 = cache.prices_at(t0, symbols)
    investable = [s for s in symbols if prices0.get(s, 0) > 0]
    if not investable:
        raise RuntimeError("No investable symbols at first bar")

    if weights:
        alloc = _normalize_weights(weights, investable)
        missing = [s for s in investable if s not in alloc]
        if missing:
            equal_w = (1.0 - sum(alloc.values())) / len(missing) if missing else 0.0
            for sym in missing:
                alloc[sym] = equal_w
            total = sum(alloc.values())
            if total > 0:
                alloc = {s: w / total for s, w in alloc.items()}
    else:
        share = 1.0 / len(investable)
        alloc = {s: share for s in investable}

    positions: Dict[str, float] = {}
    cash = float(initial_cash)
    for sym in investable:
        notional = initial_cash * alloc[sym]
        price = prices0[sym]
        qty = notional / price
        positions[sym] = qty
        cash -= notional

    curve: List[EquityPoint] = []
    for ts in timestamps:
        prices = cache.prices_at(ts, symbols)
        equity = cash + sum(
            positions[sym] * prices.get(sym, 0.0) for sym in positions
        )
        curve.append(EquityPoint(ts=ts, equity=equity, cash=cash))

    summary = run_summary(curve, trades_path="")
    summary["strategy"] = strategy_name
    summary["margin"] = None
    summary["trade_count"] = len(investable)
    return summary
