import datetime
import logging
import time

import remote
from alpaca_client import alpaca_headers

logger = logging.getLogger("alpaca_bot.market")

HOLIDAY_SLEEP_SECONDS = 61200


class MarketTracker:
    def __init__(self):
        self.server = "closed"


def check_time(session, account, config, tracker: MarketTracker, *, stop_event=None) -> bool:
    """Return True if market clock was fetched successfully."""
    headers = alpaca_headers(config, json_content=True)
    url = f"{config.urlBase}markets/v2/clock"
    result = session.get(url, headers=headers)
    if result.status_code == 200:
        json_result = result.json()
        time_string = json_result["timestamp"][:19] + json_result["timestamp"][-6:]
        dt_object = datetime.datetime.strptime(time_string, "%Y-%m-%dT%H:%M:%S%z")
        account.serverTime = int(dt_object.timestamp())
        if json_result["is_open"]:
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
        elif 4 <= int(dt_object.hour) < 20:
            if tracker.server != "closed":
                tracker.server = "closed"
            if account.market == "closed":
                logger.info(
                    "Checking if %s-%s-%s is a holiday",
                    dt_object.year,
                    dt_object.month,
                    dt_object.day,
                )
                start_date = f"start={dt_object.year}-{dt_object.month}-{dt_object.day} 00:00:00"
                end_date = f"end={dt_object.year}-{dt_object.month}-{dt_object.day} 00:00:00"
                cal_url = f"{config.urlBase}markets/v2/calendar?{start_date}&{end_date}"
                cal_result = session.get(cal_url, headers=headers)
                if str(cal_result.status_code) == "200":
                    if len(cal_result.json()) < 1:
                        logger.info(
                            "%s:%s ~ Market closed for the day (holiday)",
                            dt_object.hour,
                            dt_object.minute,
                        )
                        account.market = "holiday"
                        account.save_state()
                        from reporting import check_in

                        check_in(session, int(time.time()), account, config)
                        # Sleep in small increments so stop_event can interrupt
                        sleep_remaining = HOLIDAY_SLEEP_SECONDS
                        if stop_event:
                            for _ in range(sleep_remaining):
                                if stop_event.is_set():
                                    return True
                                time.sleep(1)
                        else:
                            time.sleep(HOLIDAY_SLEEP_SECONDS)
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
        return True
    else:
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
    return False

