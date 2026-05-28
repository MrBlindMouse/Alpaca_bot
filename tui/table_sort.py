"""Numeric pre-sort helpers for TUI DataTables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from analytics import TickerStats


def _nullable_number(value: Optional[float], *, missing: float = float("-inf")) -> float:
    if value is None:
        return missing
    return float(value)


def analytics_sort_value(stats: TickerStats, column: str) -> Any:
    """Raw sort key for one analytics row."""
    if column == "symbol":
        return stats.symbol
    if column == "trades":
        return stats.trade_count
    if column == "filled":
        return stats.filled_count
    if column == "buy":
        return stats.buy_dollars
    if column == "sell":
        return stats.sell_dollars
    if column == "price":
        return _nullable_number(stats.current_price)
    if column == "trading_pl":
        return _nullable_number(stats.trading_pl)
    if column == "unreal_pl":
        return _nullable_number(stats.unrealized_pl)
    if column == "swing":
        return _nullable_number(stats.swing_pct)
    return stats.symbol


def sort_ticker_stats_items(
    stats: dict,
    column: str,
    *,
    reverse: bool = False,
) -> List[Tuple[str, TickerStats]]:
    items = list(stats.items())
    if not column:
        return sorted(items, key=lambda x: x[0])
    return sorted(
        items,
        key=lambda item: analytics_sort_value(item[1], column),
        reverse=reverse,
    )


def position_sort_value(ticker: dict, column: str) -> Any:
    if column == "symbol":
        return ticker.get("ticker", "")
    if column == "qty":
        return float(ticker.get("volume", 0))
    if column == "price":
        return float(ticker.get("price", 0))
    if column == "value":
        return float(ticker.get("volume", 0)) * float(ticker.get("price", 0))
    if column == "swing":
        return float(ticker.get("difference", 0))
    if column == "limit":
        return 1 if ticker.get("limitTrade", {}).get("open") else 0
    return ticker.get("ticker", "")


def sort_position_tickers(
    tickers: list,
    column: str,
    *,
    reverse: bool = False,
) -> list:
    if not column:
        return sorted(tickers, key=lambda t: -float(t.get("difference", 0)))
    return sorted(
        tickers,
        key=lambda t: position_sort_value(t, column),
        reverse=reverse,
    )


def _trade_ts_sort_key(ts: Optional[str]) -> float:
    if not ts:
        return 0.0
    raw = ts.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def trade_sort_value(row: dict, column: str) -> Any:
    if column == "time":
        return _trade_ts_sort_key(row.get("ts"))
    if column == "symbol":
        return row.get("symbol", "")
    if column == "side":
        return row.get("side", "")
    if column == "intent":
        return row.get("intent", "")
    if column == "status":
        return row.get("status", "")
    if column == "notional":
        val = row.get("notional")
        return float(val) if val is not None else 0.0
    if column == "filled":
        val = row.get("filled_qty")
        return float(val) if val is not None else 0.0
    if column == "price":
        val = row.get("filled_avg_price")
        return float(val) if val is not None else 0.0
    return _trade_ts_sort_key(row.get("ts"))


def sort_trades(
    trades: list,
    column: str,
    *,
    reverse: bool = False,
) -> list:
    if not column:
        return list(trades)
    return sorted(
        trades,
        key=lambda row: trade_sort_value(row, column),
        reverse=reverse,
    )
