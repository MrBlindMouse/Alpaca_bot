"""Trade and portfolio analytics for the TUI (no UI dependencies)."""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from trade_log import DEFAULT_TRADE_FILE

PERIOD_DAYS = {"today": 1, "7d": 7, "30d": 30, "all": None}

TRADING_INTENTS = frozenset({"rebalance_buy", "rebalance_sell", "rebalance"})


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
    most_active_symbol: str = ""
    largest_swing_symbol: str = ""
    largest_swing_pct: float = 0.0
    intent_counts: Dict[str, int] = field(default_factory=dict)


def _is_trading_intent(intent: Optional[str]) -> bool:
    return (intent or "") in TRADING_INTENTS


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


def _position_qty_price(pos: dict) -> Tuple[float, Optional[float]]:
    qty = float(pos.get("qty", 0) or 0)
    mv = float(pos.get("market_value", 0) or 0)
    if qty > 0 and mv > 0:
        return qty, mv / qty
    return qty, None


def load_trades(
    path: str = DEFAULT_TRADE_FILE,
    period: str = "all",
) -> List[dict]:
    since = PERIOD_DAYS.get(period)
    cutoff = None
    if since is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since)

    trades = []
    try:
        with open(path, encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if cutoff is not None:
                    ts = _parse_ts(row.get("ts", ""))
                    if ts is None or ts < cutoff:
                        continue
                trades.append(row)
    except FileNotFoundError:
        pass
    return trades


def aggregate_by_ticker(
    trades: List[dict],
    state_tickers: Optional[List[dict]] = None,
    positions: Optional[List[dict]] = None,
    account_equity: float = 0.0,
) -> Dict[str, TickerStats]:
    stats: Dict[str, TickerStats] = {}
    position_by_symbol: Dict[str, dict] = {}
    if positions:
        for pos in positions:
            sym = pos.get("symbol", "")
            if sym:
                position_by_symbol[sym] = pos

    for row in trades:
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        if symbol not in stats:
            stats[symbol] = TickerStats(symbol=symbol)
        s = stats[symbol]
        s.trade_count += 1
        status = row.get("status", "")
        if status == "filled":
            s.filled_count += 1
            dollars = _fill_dollars(row)
            if dollars is not None:
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
        elif status == "failed":
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
            if sym not in stats:
                stats[sym] = TickerStats(symbol=sym)
            stats[sym].swing_pct = float(t.get("difference", 0)) * 100
            if sym not in position_by_symbol:
                stats[sym].held_qty = float(t.get("volume", 0) or 0)
                price = float(t.get("price", 0) or 0)
                stats[sym].current_price = price if price > 0 else None

    for sym, pos in position_by_symbol.items():
        if sym not in stats:
            stats[sym] = TickerStats(symbol=sym)
        qty, price = _position_qty_price(pos)
        stats[sym].held_qty = qty
        if price is not None:
            stats[sym].current_price = price
        mv = float(pos.get("market_value", 0))
        cb = float(pos.get("cost_basis", 0))
        stats[sym].unrealized_pl = mv - cb
        stats[sym].market_value = mv
        if account_equity > 0:
            stats[sym].weight_pct = (mv / account_equity) * 100

    for s in stats.values():
        s.trading_pl = compute_trading_pl(
            s._trading_buy_dollars,
            s._trading_sell_dollars,
            s._trading_buy_qty,
            s._trading_sell_qty,
            s.current_price,
        )

    return stats


def portfolio_summary(
    trades: List[dict],
    state: Optional[dict] = None,
    account: Optional[dict] = None,
    positions: Optional[List[dict]] = None,
    ticker_stats: Optional[Dict[str, TickerStats]] = None,
) -> PortfolioSummary:
    summary = PortfolioSummary()
    summary.trade_count = len(trades)
    summary.filled_count = sum(1 for t in trades if t.get("status") == "filled")
    if summary.trade_count:
        summary.fill_rate = summary.filled_count / summary.trade_count

    if ticker_stats:
        summary.trading_pl = sum(
            s.trading_pl for s in ticker_stats.values() if s.trading_pl is not None
        )

    intent_counts: Dict[str, int] = defaultdict(int)
    symbol_counts: Dict[str, int] = defaultdict(int)
    for row in trades:
        intent = row.get("intent") or "unknown"
        intent_counts[intent] += 1
        sym = row.get("symbol", "")
        if sym:
            symbol_counts[sym] += 1
    summary.intent_counts = dict(intent_counts)
    if symbol_counts:
        summary.most_active_symbol = max(symbol_counts, key=symbol_counts.get)

    if account:
        summary.equity = float(account.get("equity", 0))
        summary.cash = float(account.get("cash", 0))

    if positions:
        for pos in positions:
            summary.invested += float(pos.get("cost_basis", 0))
            summary.unrealized_pl += float(pos.get("market_value", 0)) - float(
                pos.get("cost_basis", 0)
            )

    if state and state.get("tickers"):
        best = max(state["tickers"], key=lambda t: float(t.get("difference", 0)))
        summary.largest_swing_symbol = best.get("ticker", "")
        summary.largest_swing_pct = float(best.get("difference", 0)) * 100

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
