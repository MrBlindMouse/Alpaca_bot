"""Reusable TUI helpers."""

import os
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from rich.text import Text

from analytics import TickerStats
from log_viewer import format_log_line_rich, read_log_lines

SYMBOL_WIDTH = 6
BAR_WIDTH = 12

# Muted tints — color key columns only, not full rows
TRADE_STYLE_BUY = "rgb(106,158,110)"
TRADE_STYLE_SELL = "rgb(106,140,173)"
TRADE_STYLE_DEFAULT = ""

ANALYTICS_STYLE_POSITIVE = "rgb(106,158,110)"
ANALYTICS_STYLE_NEGATIVE = "rgb(180,120,120)"
ANALYTICS_STYLE_DEFAULT = ""


def use_ascii_charts() -> bool:
    """Use ASCII bar chars when ALPACA_TUI_ASCII=1 (SSH/tmux without UTF-8)."""
    return os.environ.get("ALPACA_TUI_ASCII", "").lower() in ("1", "true", "yes")


def format_money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def format_pl(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}${value:,.2f}"


def format_pl_rich(value: Optional[float]) -> str:
    """Rich markup for P/L values (green/red/dim)."""
    if value is None:
        return "—"
    text = format_pl(value)
    if value > 0:
        return f"[green]{text}[/green]"
    if value < 0:
        return f"[red]{text}[/red]"
    return f"[dim]{text}[/dim]"


def format_swing_plain(swing_pct: float) -> str:
    return f"{swing_pct:.1f}%"


def format_swing_rich(swing_pct: float, margin_pct: float) -> str:
    """Color swing when outside rebalance margin band."""
    text = f"{swing_pct:.1f}%"
    band = margin_pct * 100
    if swing_pct > band:
        return f"[yellow]{text}[/yellow]"
    return text


def format_trade_ts(ts: Optional[str]) -> str:
    if not ts:
        return "—"
    raw = ts.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw[:16] if len(raw) > 16 else raw


def cash_display_value(
    account: Optional[dict],
    state: Optional[dict],
) -> tuple[str, bool]:
    """Return (display cash, needs_alpaca_refresh)."""
    if account and account.get("cash") is not None:
        return format_money(float(account["cash"])), False
    st = state or {}
    equity = float(st.get("equity", 0))
    if equity <= 0:
        return "—", True
    invested = sum(
        float(t.get("volume", 0)) * float(t.get("price", 0))
        for t in st.get("tickers", [])
    )
    estimate = max(0.0, equity - invested)
    return f"{format_money(estimate)} [dim](est.)[/dim]", True


def dashboard_metrics_markup(
    *,
    equity: str,
    cash: str,
    tickers: int,
    margin_pct: float,
    open_limits: int,
    highest_swing: str,
) -> str:
    """Single-panel dashboard summary (Rich markup)."""
    return (
        f"[dim]Equity[/dim]  [b]{equity}[/b]   "
        f"[dim]Cash[/dim]  [b]{cash}[/b]   "
        f"[dim]Tickers[/dim]  [b]{tickers}[/b]\n"
        f"[dim]Margin[/dim]  [b]{margin_pct:.1f}%[/b]   "
        f"[dim]Open limits[/dim]  [b]{open_limits}[/b]   "
        f"[dim]Highest swing[/dim]  [b]{highest_swing}[/b]"
    )


def _trade_row_style(side: str) -> str:
    s = (side or "").lower()
    if s == "buy":
        return TRADE_STYLE_BUY
    if s == "sell":
        return TRADE_STYLE_SELL
    return TRADE_STYLE_DEFAULT


def _analytics_row_style(trading_pl: Optional[float]) -> str:
    if trading_pl is None or trading_pl == 0:
        return ANALYTICS_STYLE_DEFAULT
    if trading_pl > 0:
        return ANALYTICS_STYLE_POSITIVE
    return ANALYTICS_STYLE_NEGATIVE


def _styled_cell(value: Any, style: str) -> Text | str:
    text = str(value)
    if not style:
        return text
    return Text(text, style=style)


def trade_row_cells(row: dict) -> Tuple[Any, ...]:
    """Full row tint: muted green (buy) / blue-gray (sell)."""
    style = _trade_row_style(row.get("side", ""))
    return (
        _styled_cell(format_trade_ts(row.get("ts")), style),
        _styled_cell(row.get("symbol", ""), style),
        _styled_cell(row.get("side", ""), style),
        _styled_cell(row.get("intent", ""), style),
        _styled_cell(row.get("status", ""), style),
        _styled_cell(format_money(row.get("notional")), style),
        _styled_cell(str(row.get("filled_qty") or "—"), style),
        _styled_cell(str(row.get("filled_avg_price") or "—"), style),
    )


def analytics_row_cells(
    sym: str,
    stats: TickerStats,
) -> Tuple[Any, ...]:
    """Full row tint by trading P/L sign (muted green / red)."""
    style = _analytics_row_style(stats.trading_pl)
    trading = stats.trading_pl
    unreal = stats.unrealized_pl
    swing_txt = (
        format_swing_plain(stats.swing_pct)
        if stats.swing_pct is not None
        else "—"
    )
    return (
        _styled_cell(sym, style),
        _styled_cell(stats.trade_count, style),
        _styled_cell(stats.filled_count, style),
        _styled_cell(format_money(stats.buy_dollars), style),
        _styled_cell(format_money(stats.sell_dollars), style),
        _styled_cell(
            format_money(stats.current_price) if stats.current_price is not None else "—",
            style,
        ),
        _styled_cell(format_pl(trading) if trading is not None else "—", style),
        _styled_cell(format_pl(unreal) if unreal is not None else "—", style),
        _styled_cell(swing_txt, style),
    )


def format_activity_chart(
    items: Sequence[Tuple[str, int]],
    *,
    title: str = "Trade activity",
    ascii_bars: Optional[bool] = None,
) -> str:
    """Aligned bar chart for analytics footer (Unicode or ASCII)."""
    if not items:
        return "[dim](no filled trades in period)[/dim]"
    if ascii_bars is None:
        ascii_bars = use_ascii_charts()
    fill_ch = "#" if ascii_bars else "█"
    empty_ch = "-" if ascii_bars else "░"
    max_count = max(cnt for _, cnt in items) or 1
    lines = [
        f"[b]{title}[/b] [dim](top {len(items)} by filled count)[/dim]",
        f"[dim]{'SYMBOL'.ljust(SYMBOL_WIDTH)}  {'BAR'.ljust(BAR_WIDTH)}  COUNT[/dim]",
    ]
    for sym, cnt in items:
        filled = int((cnt / max_count) * BAR_WIDTH) if cnt else 0
        if cnt > 0 and filled == 0:
            filled = 1
        bar_display = (fill_ch * filled + empty_ch * (BAR_WIDTH - filled))[:BAR_WIDTH]
        lines.append(
            f"{sym[:SYMBOL_WIDTH].ljust(SYMBOL_WIDTH)}  "
            f"[#58a6ff]{bar_display}[/]  {cnt:>4}"
        )
    return "\n".join(lines)


def server_time_label(server_time: int) -> str:
    if not server_time:
        return "—"
    dt = datetime.fromtimestamp(server_time, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def tail_log_rich_lines(path: str, lines: int = 5, min_level: str = "WARNING") -> List[str]:
    """Last N log lines as Rich markup strings."""
    filtered = read_log_lines(path, min_level=min_level, max_lines=lines)
    if not filtered:
        return ["[dim](no log lines at this level)[/dim]"]
    return [format_log_line_rich(line) for line in filtered]


def tail_log_file(path: str, lines: int = 5, min_level: str = "INFO") -> str:
    filtered = read_log_lines(path, min_level=min_level, max_lines=lines)
    if not filtered:
        return "(no log lines at this level)"
    return "\n".join(filtered)


def ticker_table_rows(stats: dict, margin: float) -> List[tuple]:
    rows = []
    for sym in sorted(stats.keys()):
        s: TickerStats = stats[sym]
        rows.append(
            (
                sym,
                str(s.trade_count),
                str(s.filled_count),
                format_money(s.buy_notional),
                format_money(s.sell_notional),
                format_money(s.current_price),
                format_pl(s.unrealized_pl),
                format_pct(s.swing_pct),
            )
        )
    return rows
