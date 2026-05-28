"""Skip DataTable rebuilds when data unchanged; preserve scroll on rebuild."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Optional

from textual.widgets import DataTable


def _digest(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def positions_signature(
    tickers: list,
    *,
    sort_column: Optional[str],
    sort_reverse: bool,
) -> str:
    rows = []
    for t in sorted(tickers, key=lambda x: x.get("ticker", "")):
        rows.append(
            (
                t.get("ticker"),
                round(float(t.get("volume", 0)), 6),
                round(float(t.get("price", 0)), 4),
                round(float(t.get("difference", 0)), 6),
                bool(t.get("limitTrade", {}).get("open")),
            )
        )
    return _digest((rows, sort_column, sort_reverse))


def trades_signature(
    trades: list,
    *,
    sort_column: Optional[str],
    sort_reverse: bool,
) -> str:
    rows = []
    for row in trades[-100:]:
        rows.append(
            (
                row.get("ts"),
                row.get("symbol"),
                row.get("side"),
                row.get("status"),
                row.get("notional"),
                row.get("filled_qty"),
            )
        )
    return _digest((rows, sort_column, sort_reverse))


def analytics_signature(
    stats: dict,
    *,
    period: str,
    sort_column: Optional[str],
    sort_reverse: bool,
) -> str:
    rows = []
    for sym in sorted(stats.keys()):
        s = stats[sym]
        rows.append(
            (
                sym,
                s.trade_count,
                s.filled_count,
                round(s.buy_dollars, 2),
                round(s.sell_dollars, 2),
                None if s.current_price is None else round(s.current_price, 4),
                None if s.trading_pl is None else round(s.trading_pl, 2),
                None if s.unrealized_pl is None else round(s.unrealized_pl, 2),
                None if s.swing_pct is None else round(s.swing_pct, 2),
            )
        )
    return _digest((period, rows, sort_column, sort_reverse))


def refresh_datatable_if_changed(
    table: DataTable,
    signature: str,
    last_signature: Optional[str],
    populate: Callable[[], None],
) -> Optional[str]:
    """
    Rebuild table only when signature differs. Returns new signature if rebuilt.
    Preserves vertical scroll and cursor row index when rebuilding.
    """
    if signature == last_signature:
        return last_signature

    scroll_y = table.scroll_y
    cursor_row = table.cursor_row if table.row_count else 0

    table.clear()
    populate()

    if table.row_count:
        table.move_cursor(row=min(cursor_row, table.row_count - 1), scroll=False)
    table.scroll_y = scroll_y
    return signature
