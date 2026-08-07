"""Trade and portfolio analytics for the TUI (no UI dependencies)."""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from trade_log import DEFAULT_ORDER_FILE, DEFAULT_TRADE_FILE

PERIOD_DAYS = {"today": 1, "7d": 7, "30d": 30, "all": None}

TRADING_INTENTS = frozenset({"rebalance_buy", "rebalance_sell", "rebalance"})
# Excluded from Buy$/Sell$ display columns (still in Unreal cashflow).
FLOW_EXCLUDED_INTENTS = frozenset({"rebalance_initial", "liquidate"})


@dataclass
class TickerStats:
    symbol: str
    trade_count: int = 0
    filled_count: int = 0
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    buy_dollars: float = 0.0
    sell_dollars: float = 0.0
    held_qty: float = 0.0
    current_price: Optional[float] = None
    trading_pl: Optional[float] = None
    failed_count: int = 0
    limit_placed_count: int = 0
    last_trade_ts: Optional[str] = None
    unrealized_pl: Optional[float] = None
    market_value: Optional[float] = None
    weight_pct: Optional[float] = None
    swing_pct: Optional[float] = None
    _trading_buy_dollars: float = 0.0
    _trading_sell_dollars: float = 0.0
    _trading_buy_qty: float = 0.0
    _trading_sell_qty: float = 0.0
    _cashflow_buy_dollars: float = 0.0
    _cashflow_sell_dollars: float = 0.0

    @property
    def net_flow(self) -> float:
        return self.buy_notional - self.sell_notional


@dataclass
class PortfolioSummary:
    equity: float = 0.0
    cash: float = 0.0
    invested: float = 0.0
    unrealized_pl: float = 0.0
    trade_count: int = 0
    filled_count: int = 0
    fill_rate: float = 0.0
    trading_pl: float = 0.0
    avg_balance_target: Optional[float] = None
    most_active_symbol: str = ""
    largest_swing_symbol: str = ""
    largest_swing_pct: float = 0.0
    intent_counts: Dict[str, int] = field(default_factory=dict)
    alpaca_unrealized_pl: Optional[float] = None
    alpaca_cash: Optional[float] = None


def _is_trading_intent(intent: Optional[str]) -> bool:
    return (intent or "") in TRADING_INTENTS


def _counts_toward_flow(intent: Optional[str]) -> bool:
    return (intent or "") not in FLOW_EXCLUDED_INTENTS


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        if ts.endswith("Z"):
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _fill_dollars(row: dict) -> Optional[float]:
    """Dollar value of a filled trade: notional, or qty × price."""
    notional = row.get("notional")
    if notional is not None and notional != "":
        try:
            return float(notional)
        except (TypeError, ValueError):
            pass
    qty = row.get("filled_qty")
    price = row.get("filled_avg_price")
    if qty not in (None, "", "0") and price not in (None, "", "0"):
        try:
            return float(qty) * float(price)
        except (TypeError, ValueError):
            pass
    return None


def _fill_qty(row: dict) -> Optional[float]:
    """Share quantity of a filled trade: filled_qty, or notional / price."""
    qty = row.get("filled_qty")
    if qty not in (None, "", "0"):
        try:
            return float(qty)
        except (TypeError, ValueError):
            pass
    dollars = _fill_dollars(row)
    price = row.get("filled_avg_price")
    if dollars is not None and price not in (None, "", "0"):
        try:
            p = float(price)
            if p > 0:
                return dollars / p
        except (TypeError, ValueError):
            pass
    return None


def compute_balance_target(
    equity: float,
    ticker_count: int,
    margin: float,
) -> Optional[float]:
    """Per-ticker $ target the bot rebalances toward (matches rebalance.py base_balance)."""
    if equity <= 0 or ticker_count <= 0:
        return None
    return equity / (ticker_count + (ticker_count * margin) / 2)


def compute_trading_pl(
    buy_dollars: float,
    sell_dollars: float,
    buy_qty: float,
    sell_qty: float,
    current_price: Optional[float],
) -> Optional[float]:
    """(sell $ − buy $) + (net rebalance qty × price). None if no rebalance fills."""
    if buy_dollars == 0 and sell_dollars == 0 and buy_qty == 0 and sell_qty == 0:
        return None
    net_qty = buy_qty - sell_qty
    price = current_price or 0.0
    return (sell_dollars - buy_dollars) + (net_qty * price)


def compute_unrealized_pl(
    buy_dollars: float,
    sell_dollars: float,
    held_qty: float,
    price: Optional[float],
) -> float:
    """held×price − (buy$ − sell$) over all fills (mark vs cashflow)."""
    mark = held_qty * (price or 0.0)
    return mark - (buy_dollars - sell_dollars)


def alpaca_unrealized_total(positions: Optional[List[dict]]) -> Optional[float]:
    if not positions:
        return None
    total = 0.0
    for pos in positions:
        total += float(pos.get("market_value", 0) or 0) - float(
            pos.get("cost_basis", 0) or 0
        )
    return total


def _load_jsonl(
    path: str,
    *,
    period: str = "all",
    status_filter: Optional[frozenset] = None,
) -> List[dict]:
    since = PERIOD_DAYS.get(period)
    cutoff = None
    if since is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since)

    rows: List[dict] = []
    try:
        with open(path, encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if status_filter is not None and row.get("status") not in status_filter:
                    continue
                if cutoff is not None:
                    ts = _parse_ts(row.get("ts", ""))
                    if ts is None or ts < cutoff:
                        continue
                rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def load_trades(
    path: str = DEFAULT_TRADE_FILE,
    period: str = "all",
) -> List[dict]:
    """Load filled trades only (legacy non-fills in trades.jsonl are ignored)."""
    return _load_jsonl(path, period=period, status_filter=frozenset({"filled"}))


def load_order_events(
    path: str = DEFAULT_ORDER_FILE,
    period: str = "all",
) -> List[dict]:
    return _load_jsonl(path, period=period)


def aggregate_by_ticker(
    trades: List[dict],
    state_tickers: Optional[List[dict]] = None,
    positions: Optional[List[dict]] = None,
    account_equity: float = 0.0,
    order_events: Optional[List[dict]] = None,
    all_time_fills: Optional[List[dict]] = None,
) -> Dict[str, TickerStats]:
    """Build per-ticker stats.

    Trading P/L uses ``trades`` (period-filtered fills).
    Unreal cashflow uses ``all_time_fills`` if given, else ``trades``.
    ``positions`` is unused (Alpaca accuracy check lives in portfolio_summary).
    """
    _ = positions
    stats: Dict[str, TickerStats] = {}

    def _ensure(sym: str) -> TickerStats:
        if sym not in stats:
            stats[sym] = TickerStats(symbol=sym)
        return stats[sym]

    for row in trades:
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        s = _ensure(symbol)
        s.trade_count += 1
        if row.get("status") != "filled":
            continue
        s.filled_count += 1
        dollars = _fill_dollars(row)
        if dollars is not None and _counts_toward_flow(row.get("intent")):
            if row.get("side") == "buy":
                s.buy_dollars += dollars
                s.buy_notional += dollars
            elif row.get("side") == "sell":
                s.sell_dollars += dollars
                s.sell_notional += dollars
        if _is_trading_intent(row.get("intent")):
            if dollars is not None:
                if row.get("side") == "buy":
                    s._trading_buy_dollars += dollars
                elif row.get("side") == "sell":
                    s._trading_sell_dollars += dollars
            qty = _fill_qty(row)
            if qty is not None:
                if row.get("side") == "buy":
                    s._trading_buy_qty += qty
                elif row.get("side") == "sell":
                    s._trading_sell_qty += qty
        ts = row.get("ts")
        if ts and (s.last_trade_ts is None or ts > s.last_trade_ts):
            s.last_trade_ts = ts

    cashflow_rows = all_time_fills if all_time_fills is not None else trades
    for row in cashflow_rows:
        if row.get("status") != "filled":
            continue
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        s = _ensure(symbol)
        dollars = _fill_dollars(row)
        if dollars is None:
            continue
        if row.get("side") == "buy":
            s._cashflow_buy_dollars += dollars
        elif row.get("side") == "sell":
            s._cashflow_sell_dollars += dollars

    if order_events:
        for row in order_events:
            symbol = row.get("symbol", "")
            if not symbol:
                continue
            s = _ensure(symbol)
            s.trade_count += 1
            status = row.get("status", "")
            if status == "failed":
                s.failed_count += 1
            elif status == "limit_placed":
                s.limit_placed_count += 1
            ts = row.get("ts")
            if ts and (s.last_trade_ts is None or ts > s.last_trade_ts):
                s.last_trade_ts = ts

    if state_tickers:
        for t in state_tickers:
            sym = t.get("ticker", "")
            if not sym:
                continue
            s = _ensure(sym)
            s.swing_pct = float(t.get("difference", 0)) * 100
            s.held_qty = float(t.get("volume", 0) or 0)
            price = float(t.get("price", 0) or 0)
            s.current_price = price if price > 0 else None
            if s.current_price is not None:
                s.market_value = s.held_qty * s.current_price
            if account_equity > 0 and s.market_value is not None:
                s.weight_pct = (s.market_value / account_equity) * 100

    for s in stats.values():
        s.trading_pl = compute_trading_pl(
            s._trading_buy_dollars,
            s._trading_sell_dollars,
            s._trading_buy_qty,
            s._trading_sell_qty,
            s.current_price,
        )
        has_cashflow = s._cashflow_buy_dollars > 0 or s._cashflow_sell_dollars > 0
        if has_cashflow or s.held_qty > 0:
            s.unrealized_pl = compute_unrealized_pl(
                s._cashflow_buy_dollars,
                s._cashflow_sell_dollars,
                s.held_qty,
                s.current_price,
            )

    return stats


def portfolio_summary(
    trades: List[dict],
    state: Optional[dict] = None,
    account: Optional[dict] = None,
    positions: Optional[List[dict]] = None,
    ticker_stats: Optional[Dict[str, TickerStats]] = None,
    order_events: Optional[List[dict]] = None,
) -> PortfolioSummary:
    summary = PortfolioSummary()
    events = order_events or []
    summary.filled_count = sum(1 for t in trades if t.get("status") == "filled")
    summary.trade_count = summary.filled_count + len(events)
    if summary.trade_count:
        summary.fill_rate = summary.filled_count / summary.trade_count

    if ticker_stats:
        summary.trading_pl = sum(
            s.trading_pl for s in ticker_stats.values() if s.trading_pl is not None
        )
        summary.unrealized_pl = sum(
            s.unrealized_pl for s in ticker_stats.values() if s.unrealized_pl is not None
        )
        summary.invested = sum(
            (s.market_value or 0.0) for s in ticker_stats.values()
        )

    intent_counts: Dict[str, int] = defaultdict(int)
    symbol_counts: Dict[str, int] = defaultdict(int)
    for row in list(trades) + list(events):
        intent = row.get("intent") or "unknown"
        intent_counts[intent] += 1
        sym = row.get("symbol", "")
        if sym:
            symbol_counts[sym] += 1
    summary.intent_counts = dict(intent_counts)
    if symbol_counts:
        summary.most_active_symbol = max(symbol_counts, key=symbol_counts.get)

    if state:
        summary.equity = float(state.get("equity", 0) or 0)
        if state.get("cash") is not None:
            summary.cash = float(state.get("cash") or 0)

    if account:
        if summary.equity <= 0 and account.get("equity") is not None:
            summary.equity = float(account.get("equity", 0))
        if account.get("cash") is not None:
            summary.alpaca_cash = float(account["cash"])
            if state is None or state.get("cash") is None:
                summary.cash = summary.alpaca_cash

    summary.alpaca_unrealized_pl = alpaca_unrealized_total(positions)

    if state and state.get("tickers"):
        tickers = state["tickers"]
        best = max(tickers, key=lambda t: float(t.get("difference", 0)))
        summary.largest_swing_symbol = best.get("ticker", "")
        summary.largest_swing_pct = float(best.get("difference", 0)) * 100
        summary.avg_balance_target = compute_balance_target(
            summary.equity,
            len(tickers),
            float(state.get("margin", 0) or 0),
        )

    return summary


def activity_bars(ticker_stats: Dict[str, TickerStats], width: int = 20) -> List[tuple]:
    """Unicode block bars for relative filled-trade activity."""
    if not ticker_stats:
        return []
    items = sorted(
        ticker_stats.values(),
        key=lambda s: s.filled_count,
        reverse=True,
    )[:width]
    max_count = max(s.filled_count for s in items) or 1
    blocks = " ▁▂▃▄▅▆▇"
    result = []
    for s in items:
        level = int((s.filled_count / max_count) * (len(blocks) - 1))
        bar = blocks[level] * 8 if level else blocks[0]
        result.append((s.symbol, bar, s.filled_count))
    return result


def load_state_snapshot(path: str = "trading_state.json") -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
