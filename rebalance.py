import datetime
import logging

import remote
from alpaca_client import alpaca_headers, get_account, get_balances
from orders import create_order, log_limit_status
from utils import trunc

logger = logging.getLogger("alpaca_bot.rebalance")

LIMIT_ORDER_MAX_AGE_SECONDS = 300


def _limit_meta(ticker):
    lt = ticker.get("limitTrade") or {}
    return {
        "side": lt.get("side", "buy"),
        "intent": lt.get("intent", "rebalance"),
        "notional": lt.get("notional"),
    }


def _set_limit_trade_fields(limit_trade: dict, side: str, intent: str, notional):
    limit_trade["side"] = side
    limit_trade["intent"] = intent
    limit_trade["notional"] = notional


def _handle_limit_update(session, config, account, key, ticker, json_result):
    order_id = ticker["limitTrade"]["id"]
    meta = _limit_meta(ticker)
    side = meta.get("side", "buy")
    intent = meta.get("intent", "rebalance")
    notional = meta.get("notional")
    limit_price = float(json_result.get("limit_price") or 0) or None
    filled_qty = json_result.get("filled_qty")
    filled_avg = json_result.get("filled_avg_price")
    fq = float(filled_qty) if filled_qty not in (None, "", "0") else None
    fap = float(filled_avg) if filled_avg not in (None, "", "0") else None

    log_limit_status(
        config,
        symbol=ticker["ticker"],
        side=side,
        intent=intent,
        market_session=account.market,
        order_id=order_id,
        alpaca_status=json_result["status"],
        notional=notional,
        limit_price=limit_price,
        filled_qty=fq,
        filled_avg_price=fap,
    )
    account.tickers[key]["limitTrade"] = {
        "open": False,
        "id": "",
        "ts": account.serverTime,
        "side": "",
        "intent": "",
        "notional": None,
    }
    new_volume = get_balances(session, config, ticker["ticker"])
    if new_volume and new_volume != ticker["volume"]:
        account.tickers[key]["volume"] = new_volume


def _apply_order_result(session, config, account, key, ticker, result, balance_value, intent: str):
    symbol = ticker["ticker"]
    if result.is_filled:
        logger.info("Filled %s $%s of %s", intent, balance_value, symbol)
        new_volume = get_balances(session, config, symbol)
        if new_volume and new_volume != ticker["volume"]:
            account.tickers[key]["volume"] = new_volume
    elif result.is_failed:
        logger.warning("Failed %s $%s of %s: %s", intent, balance_value, symbol, result.error)
    elif result.is_limit_placed:
        logger.info("Limit order placed %s $%s of %s id=%s", intent, balance_value, symbol, result.order_id)
        lt = {
            "open": True,
            "id": result.order_id,
            "ts": account.serverTime,
            "side": "buy" if "buy" in intent else "sell",
            "intent": intent,
            "notional": balance_value,
        }
        account.tickers[key]["limitTrade"] = lt


def bot(session, account, config, circuit=None):
    headers = alpaca_headers(config, json_content=True)
    dt_object = datetime.datetime.fromtimestamp(account.serverTime, datetime.timezone.utc)
    high_ticker = {"ticker": "", "diff": 0}
    base_balance = 0.0

    if account.equity == 0:
        logger.info("Loading Alpaca account data")
        account_data = get_account(session, config)
        account.equity = float(account_data["equity"])
        logger.info("Updating tickers")
        account.check_ticker(session, config)
        logger.info("Finding open limit orders")
        orders_url = f"{config.urlBase}markets/v2/orders"
        result = session.get(orders_url, headers=headers)
        if result.status_code == 200:
            for item in result.json():
                for key, ticker in enumerate(account.tickers):
                    if item["symbol"] == ticker["ticker"] and not ticker["limitTrade"]["open"]:
                        side = item.get("side", "buy")
                        account.tickers[key]["limitTrade"] = {
                            "open": True,
                            "id": item["id"],
                            "ts": 0,
                            "side": side,
                            "intent": "rebalance_buy" if side == "buy" else "rebalance_sell",
                            "notional": None,
                        }
                        break

    if account.market not in ["closed", "holiday"]:
        account_data = get_account(session, config)
        total_pos = len(account.tickers)
        account.equity = float(account_data["equity"])
        base_balance = account.equity / (total_pos + ((total_pos * account.margin) / 2))
        ticker_list = [ticker["ticker"] for ticker in account.tickers]
        tickers_str = "%2C".join(ticker_list)
        snapshot_url = (
            f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={tickers_str}&feed=iex"
        )
        result = session.get(snapshot_url, headers=headers)
        if result.status_code == 200:
            json_result = result.json()
            for key, ticker in enumerate(account.tickers):
                sym = ticker["ticker"]
                if sym in json_result and json_result[sym].get("minuteBar"):
                    account.tickers[key]["price"] = float(json_result[sym]["minuteBar"]["vw"])
                else:
                    logger.warning("No snapshot data for %s", sym)
        else:
            remote.post_log(
                config,
                f"Error calling new snapshot:<br>{result.text[:500]}",
                config.title,
            )
            logger.error(
                "Snapshot error: %s %s",
                result.status_code,
                result.reason,
            )

        for key, ticker in enumerate(account.tickers):
            balance_value = base_balance
            if ticker["limitTrade"]["open"]:
                open_url = f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
                result = session.get(open_url, headers=headers)
                if str(result.status_code) == "200":
                    json_result = result.json()
                    if json_result["status"] in ["filled", "canceled", "expired"]:
                        _handle_limit_update(session, config, account, key, ticker, json_result)
                    elif (account.serverTime - ticker["limitTrade"]["ts"]) > LIMIT_ORDER_MAX_AGE_SECONDS:
                        # Re-fetch status right before cancelling to avoid fill-cancel race
                        cancel_result = session.get(open_url, headers=headers)
                        if str(cancel_result.status_code) == "200":
                            current_status = cancel_result.json().get("status", "")
                            if current_status in ("new", "accepted"):
                                delete_url = (
                                    f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
                                )
                                result = session.delete(delete_url, headers=headers)
                                if str(result.status_code) == "204":
                                    logger.info("Cancelled old limit order for %s", ticker["ticker"])
                                    log_limit_status(
                                        config,
                                        symbol=ticker["ticker"],
                                        side=_limit_meta(ticker).get("side", "buy"),
                                        intent=_limit_meta(ticker).get("intent", "rebalance"),
                                        market_session=account.market,
                                        order_id=ticker["limitTrade"]["id"],
                                        alpaca_status="canceled",
                                        notional=_limit_meta(ticker).get("notional"),
                                    )
                                else:
                                    logger.error(
                                        "Failed to cancel limit order %s: %s",
                                        ticker["limitTrade"]["id"],
                                        result.status_code,
                                    )
                            else:
                                # Order filled/cancelled/expired — don't attempt cancellation
                                logger.info(
                                    "Skipping cancel for %s: status=%s",
                                    ticker["ticker"],
                                    current_status,
                                )
                                _handle_limit_update(session, config, account, key, ticker, cancel_result.json())
                        else:
                            logger.error(
                                "Failed to re-check order %s before cancel: %s",
                                ticker["limitTrade"]["id"],
                                cancel_result.reason,
                            )
                        account.tickers[key]["limitTrade"] = {
                            "open": False,
                            "id": "",
                            "ts": account.serverTime,
                            "side": "",
                            "intent": "",
                            "notional": None,
                        }
                        new_volume = get_balances(session, config, ticker["ticker"])
                        if new_volume and new_volume != ticker["volume"]:
                            account.tickers[key]["volume"] = new_volume
                else:
                    logger.error(
                        "Failed to check open order %s: %s",
                        ticker["limitTrade"]["id"],
                        result.reason,
                    )
                    account.tickers[key]["limitTrade"] = {
                        "open": False,
                        "id": "",
                        "ts": account.serverTime,
                        "side": "",
                        "intent": "",
                        "notional": None,
                    }
                    new_volume = get_balances(session, config, ticker["ticker"])
                    if new_volume and new_volume != ticker["volume"]:
                        account.tickers[key]["volume"] = new_volume

            if ticker["volume"] == 0 and not ticker["limitTrade"]["open"]:
                logger.info("Buying initial %s", ticker["ticker"])
                order_result = create_order(
                    session,
                    config,
                    balance_value,
                    "buy",
                    ticker["ticker"],
                    intent="rebalance_initial",
                    market_status=account.market,
                    current_price=ticker["price"],
                    circuit=circuit,
                )
                _apply_order_result(
                    session, config, account, key, ticker, order_result, balance_value, "initial buy"
                )

            if not ticker["limitTrade"]["open"]:
                current_value = ticker["volume"] * ticker["price"]
                if current_value > balance_value:
                    diff = (current_value - balance_value) / balance_value
                    if diff < account.margin:
                        account.tickers[key]["difference"] = diff
                    elif diff > ticker["difference"]:
                        account.tickers[key]["difference"] = diff
                    elif (
                        diff
                        < (ticker["difference"] * (1 - ((ticker["difference"] + account.margin) / 2)))
                        and diff > account.margin
                    ):
                        sell_value = current_value - balance_value
                        order_result = create_order(
                            session,
                            config,
                            sell_value,
                            "sell",
                            ticker["ticker"],
                            intent="rebalance_sell",
                            market_status=account.market,
                            current_price=ticker["price"],
                            circuit=circuit,
                        )
                        _apply_order_result(
                            session, config, account, key, ticker, order_result, sell_value, "sell"
                        )
                elif current_value < balance_value:
                    diff = (balance_value - current_value) / balance_value
                    if diff < account.margin:
                        account.tickers[key]["difference"] = diff
                    elif diff > ticker["difference"]:
                        account.tickers[key]["difference"] = diff
                    elif (
                        diff
                        < (ticker["difference"] * (1 - ((ticker["difference"] + account.margin) / 2)))
                        and diff > account.margin
                    ):
                        buy_value = balance_value - current_value
                        order_result = create_order(
                            session,
                            config,
                            buy_value,
                            "buy",
                            ticker["ticker"],
                            intent="rebalance_buy",
                            market_status=account.market,
                            current_price=ticker["price"],
                            circuit=circuit,
                        )
                        _apply_order_result(
                            session, config, account, key, ticker, order_result, buy_value, "buy"
                        )
                else:
                    account.tickers[key]["difference"] = 0

            if ticker["difference"] > high_ticker["diff"]:
                high_ticker["diff"] = ticker["difference"]
                high_ticker["ticker"] = ticker["ticker"]

    swing = trunc(high_ticker["diff"] * 100, 1) if high_ticker["ticker"] else 0
    logger.info(
        "%s:%s:%s ~ %s trade, equity=$%s, highest swing %s:%s%%, balance=$%s",
        dt_object.hour,
        dt_object.minute,
        dt_object.second,
        account.market.upper(),
        account.equity,
        high_ticker["ticker"],
        swing,
        trunc(base_balance, 2),
    )
