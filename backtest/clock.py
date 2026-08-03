"""RTH timestamp filtering for backtest steps.

ponytail: weekend + 09:30–16:00 ET only (no holidays/early closes).
Upgrade to Alpaca calendar if half-day accuracy matters.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import List
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def _parse_ts(ts: str) -> datetime:
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def is_rth_timestamp(ts: str) -> bool:
    dt = _parse_ts(ts).astimezone(NY)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    return RTH_OPEN <= t < RTH_CLOSE


def filter_rth_timestamps(timestamps: List[str]) -> List[str]:
    return [ts for ts in timestamps if is_rth_timestamp(ts)]


def ts_to_epoch(ts: str) -> int:
    return int(_parse_ts(ts).timestamp())
