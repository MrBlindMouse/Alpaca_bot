import datetime
import logging

import remote
from alpaca_client import AlpacaAPIError, alpaca_headers, get_account, get_balances
from utils import trunc

logger = logging.getLogger("alpaca_bot.reporting")


def day_end(session, account, config):
    if account.market == "holiday":
        return
    balances = get_balances(session, config)
    if balances is None:
        logger.warning("day_end skipped: could not load balances")
        return
    try:
        base = get_account(session, config)
    except AlpacaAPIError as exc:
        logger.warning("day_end skipped: %s", exc)
        return
    cash = float(base["cash"])
    cost = cash
    equity = cash
    investment = 0
    for entry in balances:
        equity += float(entry["market_value"])
        cost += float(entry["cost_basis"])
    url = (
        f"{config.urlBase}markets/v2/account/activities"
        "?activity_types=CSD,CSW&direction=desc&page_size=100"
    )
    response = session.get(url, headers=alpaca_headers(config))
    if response.status_code == 200:
        for entry in response.json():
            if entry["activity_type"] == "CSD":
                investment += float(entry["net_amount"])
            elif entry["activity_type"] == "CSW":
                investment -= float(entry["net_amount"])
    else:
        logger.warning("day_end activities fetch failed: %s", response.status_code)

    payload = {
        "ts": str(int(datetime.datetime.now().timestamp())),
        "equity": trunc(equity, 2),
        "cost": trunc(cost, 2),
        "investment": trunc(investment, 2),
    }
    remote.post_event(config, "day_end", payload)
