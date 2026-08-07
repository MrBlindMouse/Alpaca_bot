import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_TRADE_FILE = "trades.jsonl"
DEFAULT_ORDER_FILE = "orders.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_jsonl(record: dict[str, Any], path: str) -> None:
    row = {"ts": utc_now_iso(), **record}
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(row, default=str) + "\n")
        file.flush()
        os.fsync(file.fileno())


def append_trade(record: dict[str, Any], path: str = DEFAULT_TRADE_FILE) -> None:
    """Append a filled trade to the long-term P/L log."""
    _append_jsonl(record, path)


def append_order_event(record: dict[str, Any], path: str = DEFAULT_ORDER_FILE) -> None:
    """Append a non-fill order lifecycle event (failed, limit_*, …)."""
    _append_jsonl(record, path)


def build_trade_record(
    *,
    symbol: str,
    side: str,
    intent: str,
    order_type: str,
    market_session: str,
    status: str,
    paper: bool,
    order_id: str = "",
    notional: Optional[float] = None,
    qty: Optional[float] = None,
    limit_price: Optional[float] = None,
    filled_qty: Optional[float] = None,
    filled_avg_price: Optional[float] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "intent": intent,
        "order_type": order_type,
        "market_session": market_session,
        "notional": notional,
        "qty": qty,
        "limit_price": limit_price,
        "order_id": order_id,
        "status": status,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "paper": paper,
        "error": error,
    }
