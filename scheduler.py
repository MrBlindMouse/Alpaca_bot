import logging
import sys
import time
import traceback
from typing import Optional, Tuple

import remote
from config import log_remote_disabled_once
from market import ClockSnapshot, MarketTracker, check_time
from rebalance import bot, maintain_open_limits
from reporting import check_in

logger = logging.getLogger("alpaca_bot.scheduler")


def bmd_logger(function):
    def wrapper(session, account, config, *args, **kwargs):
        try:
            return function(session, account, config, *args, **kwargs)
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            tb = traceback.extract_tb(exc_traceback)
            post_message = f"Exception raised during {function.__name__}<br>"
            for line in traceback.format_list(tb):
                post_message += line.replace("\n", "<br>") + "<br>"
            post_message += f"{exc_type}<br>{exc_value}"
            logger.exception("Unhandled error in %s", function.__name__)
            remote.post_log(config, post_message, config.title, "2")
            raise

    return wrapper


@bmd_logger
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
    config.update()
    log_remote_disabled_once(config, logger)
    account.margin = config.margin
    clock_ok, snapshot = check_time(session, account, config, tracker)
    if circuit:
        if clock_ok:
            circuit.record_success()
        else:
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
    check_in(session, int(time.time()), account, config)
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
