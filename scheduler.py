import logging
from typing import Optional, Tuple

from config import log_remote_disabled_once
from market import ClockSnapshot, MarketTracker, check_time
from rebalance import bot, maintain_open_limits

logger = logging.getLogger("alpaca_bot.scheduler")


def bot_loop(
    session,
    account,
    config,
    tracker: MarketTracker,
    *,
    stop_event=None,
    circuit=None,
) -> Tuple[bool, Optional[ClockSnapshot]]:
    del stop_event
    try:
        return _bot_loop_body(session, account, config, tracker, circuit=circuit)
    except Exception:
        logger.exception("Unhandled error in bot_loop")
        raise


def _bot_loop_body(
    session,
    account,
    config,
    tracker: MarketTracker,
    *,
    circuit=None,
) -> Tuple[bool, Optional[ClockSnapshot]]:
    config.update()
    log_remote_disabled_once(config, logger)
    account.margin = config.margin
    clock_ok, snapshot = check_time(session, account, config, tracker)
    # ponytail: clock health is not an order success — only record_failure here so
    # consecutive API/order failures can open the breaker across ticks.
    if circuit and not clock_ok:
        circuit.record_failure()
        logger.warning("Market clock stale; skipping state persist this tick")
    if account.market in ("open", "extended"):
        maintain_open_limits(session, account, config)
        if circuit and circuit.is_paused():
            logger.warning("Circuit breaker open; skipping rebalance this tick")
        else:
            bot(session, account, config, circuit=circuit)
    if clock_ok:
        account.save_state()
    return clock_ok, snapshot


def check_balances(session, account, config, circuit=None):
    if account.market not in ("closed", "holiday"):
        from alpaca_client import get_balances

        positions = get_balances(session, config)
        if positions is None:
            logger.warning("check_balances skipped: could not load positions")
            if circuit:
                circuit.record_failure()
        else:
            account.check_balances(session, positions, config)
            if circuit:
                circuit.record_success()
