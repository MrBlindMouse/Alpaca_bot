import datetime
import logging

import remote
from alpaca_client import alpaca_headers, get_account, get_balances
from utils import trunc

logger = logging.getLogger("alpaca_bot.reporting")


def day_end(session, account, config):
    if account.market == "holiday":
        return
    balances = get_balances(session, config)
    if balances is None:
        logger.warning("day_end skipped: could not load balances")
        return
    base = get_account(session, config)
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
    remote.post_record(config, payload)


def check_in(session, ts, account, config):
    remote.post_checkin(
        config,
        {
            "id": "02" if config.title == "Alpaca" else "03",
            "bot_name": config.title,
            "ts": str(ts),
            "status": account.market,
        },
    )

    high_ticker = {"ticker": "", "diff": 0, "val": 0}
    low_ticker = {"ticker": "", "diff": 0, "val": 0}
    general_swing = 0
    for ticker in account.tickers:
        general_swing += ticker["difference"]
        val = ticker["volume"] * ticker["price"]
        if high_ticker["val"] == 0 or val > high_ticker["val"]:
            high_ticker["ticker"] = ticker["ticker"]
            high_ticker["diff"] = ticker["difference"]
            high_ticker["val"] = val
        if low_ticker["val"] == 0 or val < low_ticker["val"]:
            low_ticker["ticker"] = ticker["ticker"]
            low_ticker["diff"] = ticker["difference"]
            low_ticker["val"] = val

    if not account.tickers:
        return

    general_swing = general_swing / len(account.tickers)
    balance_value = account.equity / (len(account.tickers) * (1 + account.margin))
    now = datetime.datetime.now()
    display_str = f"""
    <div style="padding:5px;">
    <p>{now}</p>
    <p>Highest Swing: {high_ticker["ticker"]}: {trunc(high_ticker["diff"]*100, 1)}% at ${trunc(high_ticker["val"],2)}</p>
    <p>Lowest Swing: {low_ticker["ticker"]}: {trunc(low_ticker["diff"]*100, 1)}% at ${trunc(low_ticker["val"],2)}</p>
    <p>Avg Swing size: {trunc(general_swing*100, 1)}% for {len(account.tickers)} tickers balancing to ${trunc(balance_value,2)}.</p>
    </div>
    """
    remote.post_dashboard(
        config,
        {
            "id": "02",
            "ts": str(ts),
            "name": "Alpaca",
            "json_string": display_str,
        },
    )
