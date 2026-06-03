import datetime
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import remote
from alpaca_client import alpaca_headers

logger = logging.getLogger("alpaca_bot.market")

TICK_SLEEP_OPEN_SECONDS = 60
TICK_SLEEP_CLOSED_MAX_SECONDS = 30 * 60
TICK_SLEEP_CLOCK_FAIL_SECONDS = 5 * 60
TICK_SLEEP_MIN_SECONDS = 10


@dataclass(frozen=True)
class ClockSnapshot:
    server_epoch: int
    is_open: bool
    next_open_epoch: Optional[int]
    next_close_epoch: Optional[int]


class MarketTracker:
    def __init__(self):
        self.server = "closed"
        self.last_snapshot: Optional[ClockSnapshot] = None


def parse_alpaca_timestamp(iso: str) -> datetime.datetime:
    """Parse Alpaca ISO-8601 timestamps (fractional seconds, Z or offset)."""
    if not iso:
        raise ValueError("empty timestamp")
    normalized = iso.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(normalized)
    except ValueError:
        pass
    if "." in normalized:
        head, tail = normalized.split(".", 1)
        offset = ""
        for idx, ch in enumerate(tail):
            if ch in "+-":
                offset = tail[idx:]
                frac = tail[:idx]
                break
        else:
            frac = tail
            offset = "+00:00"
        trimmed = (frac + "000000")[:6]
        normalized = f"{head}.{trimmed}{offset}"
    return datetime.datetime.fromisoformat(normalized)


def parse_clock_response(payload: dict) -> ClockSnapshot:
    ts = parse_alpaca_timestamp(payload["timestamp"])
    next_open = payload.get("next_open")
    next_close = payload.get("next_close")
    return ClockSnapshot(
        server_epoch=int(ts.timestamp()),
        is_open=bool(payload.get("is_open")),
        next_open_epoch=(
            int(parse_alpaca_timestamp(next_open).timestamp()) if next_open else None
        ),
        next_close_epoch=(
            int(parse_alpaca_timestamp(next_close).timestamp()) if next_close else None
        ),
    )


def compute_tick_sleep_seconds(
    snapshot: Optional[ClockSnapshot],
    market: str,
    clock_ok: bool,
) -> int:
    if not clock_ok:
        return TICK_SLEEP_CLOCK_FAIL_SECONDS
    if market in ("open", "extended"):
        return TICK_SLEEP_OPEN_SECONDS
    if snapshot and snapshot.next_open_epoch:
        until_open = snapshot.next_open_epoch - int(time.time())
        if until_open > 0:
            return max(
                TICK_SLEEP_MIN_SECONDS,
                min(TICK_SLEEP_CLOSED_MAX_SECONDS, until_open),
            )
    return TICK_SLEEP_CLOSED_MAX_SECONDS


def _apply_market_state(
    session,
    account,
    config,
    tracker: MarketTracker,
    snapshot: ClockSnapshot,
    dt_object: datetime.datetime,
) -> None:
    if snapshot.is_open:
        if tracker.server != "open":
            logger.info("Updating equity list")
            account.check_ticker(session, config)
            tracker.server = "open"
        if account.market == "extended":
            logger.info(
                "Trade start for %s-%s-%s",
                dt_object.year,
                dt_object.month,
                dt_object.day,
            )
        account.market = "open"
        return

    if account.market == "holiday":
        account.market = "closed"

    if 4 <= int(dt_object.hour) < 20:
        if tracker.server != "closed":
            tracker.server = "closed"
        if account.market == "closed":
            logger.info(
                "Checking calendar for %s-%s-%s",
                dt_object.year,
                dt_object.month,
                dt_object.day,
            )
            headers = alpaca_headers(config, json_content=True)
            start_date = f"start={dt_object.year}-{dt_object.month}-{dt_object.day} 00:00:00"
            end_date = f"end={dt_object.year}-{dt_object.month}-{dt_object.day} 00:00:00"
            cal_url = f"{config.urlBase}markets/v2/calendar?{start_date}&{end_date}"
            cal_result = session.get(cal_url, headers=headers)
            if str(cal_result.status_code) == "200":
                if len(cal_result.json()) < 1:
                    logger.info(
                        "%s:%s ~ No trading session today",
                        dt_object.hour,
                        dt_object.minute,
                    )
                    account.market = "closed"
                else:
                    logger.info(
                        "Extended hours trade start for %s-%s-%s",
                        dt_object.year,
                        dt_object.month,
                        dt_object.day,
                    )
                    account.market = "extended"
            else:
                logger.error(
                    "Calendar lookup failed: %s %s",
                    cal_result.reason,
                    cal_result.text[:200],
                )
        elif account.market == "open":
            logger.info("Market closed, extended hours trade until 20:00")
            account.market = "extended"
    else:
        if tracker.server != "closed":
            tracker.server = "closed"
        if account.market == "closed":
            logger.info(
                "%s:%s:%s ~ Market closed, equity=$%s",
                dt_object.hour,
                dt_object.minute,
                dt_object.second,
                account.equity,
            )
        else:
            account.market = "closed"


def check_time(
    session,
    account,
    config,
    tracker: MarketTracker,
    *,
    stop_event=None,
) -> Tuple[bool, Optional[ClockSnapshot]]:
    """Return (clock_ok, snapshot). On failure serverTime is cleared."""
    del stop_event  # kept for API compatibility
    headers = alpaca_headers(config, json_content=True)
    url = f"{config.urlBase}markets/v2/clock"
    result = session.get(url, headers=headers)
    if result.status_code != 200:
        account.serverTime = 0
        remote.post_log(
            config,
            f"Error finding server time:<br> {result.text[:500]}",
            config.title,
        )
        logger.error(
            "Error finding server time: %s %s",
            result.reason,
            result.text[:200],
        )
        tracker.last_snapshot = None
        return False, None

    try:
        json_result = result.json()
        snapshot = parse_clock_response(json_result)
        dt_object = parse_alpaca_timestamp(json_result["timestamp"])
    except (KeyError, ValueError, TypeError) as exc:
        account.serverTime = 0
        logger.error("Invalid clock response: %s", exc)
        tracker.last_snapshot = None
        return False, None

    account.serverTime = snapshot.server_epoch
    tracker.last_snapshot = snapshot
    _apply_market_state(session, account, config, tracker, snapshot, dt_object)
    return True, snapshot
