import logging
import sys
import time
import traceback

import remote
from config import log_remote_disabled_once
from market import MarketTracker, check_time
from rebalance import bot
from reporting import check_in, day_end

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
def bot_loop(session, account, config, tracker: MarketTracker):
    config.update()
    log_remote_disabled_once(config, logger)
    account.margin = config.margin
    check_time(session, account, config, tracker)
    if account.market in ("open", "extended"):
        bot(session, account, config)
    account.save_state()
    check_in(session, int(time.time()), account, config)


def check_balances(session, account, config):
    if account.market not in ("closed", "holiday"):
        from alpaca_client import get_balances

        positions = get_balances(session, config)
        if positions is not None:
            account.check_balances(session, positions, config)
