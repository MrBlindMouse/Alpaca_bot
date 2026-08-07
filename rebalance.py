import datetime
import json
import logging
import os
import time
from typing import Any, Callable, Optional

from alpaca_client import AlpacaAPIError, alpaca_headers, get_account, get_balances
from live_broker import LiveBroker
from orders import log_limit_status
from trade_log import DEFAULT_ORDER_FILE, DEFAULT_TRADE_FILE
from utils import trunc

logger = logging.getLogger("alpaca_bot.rebalance")

# ponytail: this module owns tick + limit maintain + live bot (~1k lines).
# Extend carefully; split tick / limits / bot only when a feature forces it.
LIMIT_ORDER_MAX_AGE_SECONDS = 300
_LIMIT_TERMINAL = frozenset({"filled", "canceled", "expired", "rejected"})
_LIMIT_CANCELABLE = frozenset({"new", "accepted", "pending_new", "partially_filled"})
_INITIAL_SWING_PCT = 100.0


def _swing_pct(diff: float) -> float:
    return trunc(float(diff) * 100, 1)


def _apply_tradable_equity(account, raw: float) -> float:
    fn = getattr(account, "tradable_equity", None)
    return float(fn(raw)) if callable(fn) else float(raw)


def _limit_meta(ticker):
    lt = ticker.get("limitTrade") or {}
    return {
        "side": lt.get("side", "buy"),
        "intent": lt.get("intent", "rebalance"),
        "notional": lt.get("notional"),
        "swing_pct": lt.get("swing_pct"),
    }


def _limit_side_from_intent(intent: str) -> str:
    lowered = intent.lower()
    if "sell" in lowered and "buy" not in lowered:
        return "sell"
    return "buy"


def _empty_limit_trade(server_time: int) -> dict:
    return {
        "open": False,
        "id": "",
        "ts": server_time,
        "side": "",
        "intent": "",
        "notional": None,
        "swing_pct": None,
    }


def _log_skip(symbol: str, intent: str, reason: str, diff: Optional[float]) -> None:
    intent_label = intent or "-"
    if diff is None:
        logger.debug("Skip %s %s reason=%s swing=-", symbol, intent_label, reason)
        return
    logger.debug(
        "Skip %s %s reason=%s swing=%.1f%%",
        symbol,
        intent_label,
        reason,
        _swing_pct(diff),
    )


def _intent_from_jsonl(order_id: str, path: str) -> Optional[str]:
    if not order_id or not os.path.exists(path):
        return None
    intent = None
    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("order_id") == order_id and row.get("status") == "limit_placed":
                intent = row.get("intent")
    return intent


def _intent_from_limit_placed(
    order_id: str,
    orders_path: Optional[str] = None,
    trades_path: Optional[str] = None,
) -> Optional[str]:
    """Recover limit intent from orders.jsonl; fall back to legacy trades.jsonl."""
    intent = _intent_from_jsonl(order_id, orders_path or DEFAULT_ORDER_FILE)
    if intent is not None:
        return intent
    return _intent_from_jsonl(order_id, trades_path or DEFAULT_TRADE_FILE)


def _log_limit_terminal(intent: str, symbol: str, swing_pct: Optional[float], order_id: str, status: str) -> None:
    swing_label = f"{swing_pct:.1f}" if swing_pct is not None else "-"
    if status == "filled":
        logger.info(
            "Limit filled %s %s swing=%s%% id=%s",
            intent,
            symbol,
            swing_label,
            order_id,
        )
    else:
        logger.info(
            "Limit %s %s %s swing=%s%% id=%s",
            status,
            intent,
            symbol,
            swing_label,
            order_id,
        )


def _sync_volume_from_broker(session, config, account, key, ticker) -> None:
    new_volume = get_balances(session, config, ticker["ticker"])
    if new_volume is None:
        return
    if new_volume != ticker["volume"]:
        account.tickers[key]["volume"] = new_volume


def _handle_limit_update(session, config, account, key, ticker, json_result):
    order_id = ticker["limitTrade"]["id"]
    meta = _limit_meta(ticker)
    side = meta.get("side", "buy")
    intent = meta.get("intent", "rebalance")
    notional = meta.get("notional")
    swing_pct = meta.get("swing_pct")
    limit_price = float(json_result.get("limit_price") or 0) or None
    filled_qty = json_result.get("filled_qty")
    filled_avg = json_result.get("filled_avg_price")
    fq = float(filled_qty) if filled_qty not in (None, "", "0") else None
    fap = float(filled_avg) if filled_avg not in (None, "", "0") else None
    alpaca_status = json_result["status"]

    log_limit_status(
        config,
        symbol=ticker["ticker"],
        side=side,
        intent=intent,
        market_session=account.market,
        order_id=order_id,
        alpaca_status=alpaca_status,
        notional=notional,
        limit_price=limit_price,
        filled_qty=fq,
        filled_avg_price=fap,
    )
    if alpaca_status in ("filled", "canceled", "expired"):
        _log_limit_terminal(intent, ticker["ticker"], swing_pct, order_id, alpaca_status)
    account.tickers[key]["limitTrade"] = _empty_limit_trade(account.serverTime)
    _sync_volume_from_broker(session, config, account, key, ticker)


def _apply_order_result(
    account,
    key,
    ticker,
    result,
    balance_value,
    intent: str,
    *,
    swing_pct: float,
    broker,
):
    symbol = ticker["ticker"]
    if result.is_filled:
        logger.info(
            "Filled %s %s $%s swing=%.1f%%",
            intent,
            symbol,
            balance_value,
            swing_pct,
        )
        # ponytail: live uses state volume + post-fill sync (not get_qty each symbol);
        # upgrade: refresh all qtys from Alpaca at start of bot() if drift appears.
        if isinstance(broker, LiveBroker):
            _sync_volume_from_broker(broker.session, broker.config, account, key, ticker)
        else:
            account.tickers[key]["volume"] = broker.get_qty(symbol)
    elif result.is_failed:
        logger.warning(
            "Failed %s %s $%s swing=%.1f%%: %s",
            intent,
            symbol,
            balance_value,
            swing_pct,
            result.error,
        )
    elif result.is_limit_placed:
        # ponytail: limits are live-only; SimBroker never returns limit_placed.
        # Upgrade: Broker.supports_limits flag if a second limit-capable broker appears.
        if not isinstance(broker, LiveBroker):
            logger.warning(
                "Limit placed for %s in non-live broker; ignoring", symbol
            )
            return
        logger.info(
            "Limit placed %s %s $%s swing=%.1f%% id=%s",
            intent,
            symbol,
            balance_value,
            swing_pct,
            result.order_id,
        )
        account.tickers[key]["limitTrade"] = {
            "open": True,
            "id": result.order_id,
            "ts": account.serverTime,
            "side": _limit_side_from_intent(intent),
            "intent": intent,
            "notional": balance_value,
            "swing_pct": swing_pct,
        }


def _emit_diagnostic(
    diagnostics: Optional[Callable[[dict[str, Any]], None]],
    event: str,
    **payload,
) -> None:
    if diagnostics is None:
        return
    diagnostics({"event": event, **payload})


def rebalance_tick(
    account,
    config,
    *,
    prices: dict,
    broker,
    session: str = "open",
    diagnostics: Optional[Callable[[dict[str, Any]], None]] = None,
    log_summary: bool = False,
):
    """
    One rebalance pass using pre-fetched prices and a Broker (live or simulated).
    Skips limit-order lifecycle (backtest / RTH market only).
    """
    high_ticker = {"ticker": "", "diff": 0}
    base_balance = 0.0

    if session not in ("open", "extended"):
        return

    total_pos = len(account.tickers)
    if total_pos == 0:
        return

    account.equity = _apply_tradable_equity(account, broker.get_equity(prices))
    base_balance = account.equity / (total_pos + ((total_pos * account.margin) / 2))

    tick_stats = {
        "symbols_evaluated": 0,
        "attempts": 0,
        "fills": 0,
        "failures": 0,
        "skipped": {},
    }

    ts_iso = datetime.datetime.fromtimestamp(account.serverTime, datetime.timezone.utc).isoformat()

    def _record_skip(reason: str) -> None:
        skipped = tick_stats["skipped"]
        skipped[reason] = int(skipped.get(reason, 0)) + 1

    for key, ticker in enumerate(account.tickers):
        sym = ticker["ticker"]
        if sym in prices:
            price = float(prices[sym])
        else:
            price = float(ticker.get("price") or 0.0)
        tick_stats["symbols_evaluated"] += 1
        if price > 0:
            ticker["price"] = float(price)
        else:
            _record_skip("price_missing_or_zero")
            _emit_diagnostic(
                diagnostics,
                "rebalance_order_skipped",
                ts=ts_iso,
                symbol=sym,
                reason="price_missing_or_zero",
                side="",
                intent="",
                price=price,
                volume=float(ticker["volume"]),
                current_value=0.0,
                target_value=base_balance,
                diff=0.0,
                previous_diff=float(ticker.get("difference", 0.0)),
                margin=float(account.margin),
                trigger_threshold=float(account.margin),
                notional=0.0,
            )
            _log_skip(sym, "", "price_missing_or_zero", None)
            continue

        balance_value = base_balance
        previous_diff = float(ticker.get("difference", 0.0))

        if ticker["volume"] == 0 and not ticker["limitTrade"]["open"]:
            logger.info(
                "Attempt rebalance_initial %s $%s swing=%.1f%%",
                sym,
                balance_value,
                _INITIAL_SWING_PCT,
            )
            tick_stats["attempts"] += 1
            _emit_diagnostic(
                diagnostics,
                "initial_buy_attempt",
                ts=ts_iso,
                symbol=sym,
                side="buy",
                intent="rebalance_initial",
                price=float(ticker["price"]),
                volume=float(ticker["volume"]),
                current_value=0.0,
                target_value=balance_value,
                diff=1.0,
                previous_diff=previous_diff,
                margin=float(account.margin),
                trigger_threshold=float(account.margin),
                notional=balance_value,
            )
            order_result = broker.place_market_notional(
                sym,
                "buy",
                balance_value,
                ticker["price"],
                intent="rebalance_initial",
                market_session=session,
            )
            _apply_order_result(
                account,
                key,
                ticker,
                order_result,
                balance_value,
                "rebalance_initial",
                swing_pct=_INITIAL_SWING_PCT,
                broker=broker,
            )
            if order_result.is_filled:
                tick_stats["fills"] += 1
                _emit_diagnostic(
                    diagnostics,
                    "initial_buy_filled",
                    ts=ts_iso,
                    symbol=sym,
                    side="buy",
                    intent="rebalance_initial",
                    price=float(ticker["price"]),
                    volume=float(ticker["volume"]),
                    current_value=float(ticker["volume"]) * float(ticker["price"]),
                    target_value=balance_value,
                    diff=1.0,
                    previous_diff=previous_diff,
                    margin=float(account.margin),
                    trigger_threshold=float(account.margin),
                    notional=balance_value,
                )
            elif order_result.is_failed:
                tick_stats["failures"] += 1
                _emit_diagnostic(
                    diagnostics,
                    "initial_buy_failed",
                    ts=ts_iso,
                    symbol=sym,
                    side="buy",
                    intent="rebalance_initial",
                    price=float(ticker["price"]),
                    volume=float(ticker["volume"]),
                    current_value=0.0,
                    target_value=balance_value,
                    diff=1.0,
                    previous_diff=previous_diff,
                    margin=float(account.margin),
                    trigger_threshold=float(account.margin),
                    notional=balance_value,
                    error=order_result.error or "",
                )

        if not ticker["limitTrade"]["open"] and ticker["price"] > 0:
            current_value = ticker["volume"] * ticker["price"]
            if current_value > balance_value:
                diff = (current_value - balance_value) / balance_value
                if diff < account.margin:
                    account.tickers[key]["difference"] = diff
                    _record_skip("below_margin")
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_order_skipped",
                        ts=ts_iso,
                        symbol=sym,
                        reason="below_margin",
                        side="sell",
                        intent="rebalance_sell",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(account.margin),
                        notional=0.0,
                    )
                    _log_skip(sym, "rebalance_sell", "below_margin", diff)
                elif diff > ticker["difference"]:
                    account.tickers[key]["difference"] = diff
                    _record_skip("tracking_peak_diff")
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_order_skipped",
                        ts=ts_iso,
                        symbol=sym,
                        reason="tracking_peak_diff",
                        side="sell",
                        intent="rebalance_sell",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(account.margin),
                        notional=0.0,
                    )
                    _log_skip(sym, "rebalance_sell", "tracking_peak_diff", diff)
                elif (
                    diff
                    < (ticker["difference"] * (1 - ((ticker["difference"] + account.margin) / 2)))
                    and diff > account.margin
                ):
                    sell_value = current_value - balance_value
                    sell_swing = _swing_pct(diff)
                    tick_stats["attempts"] += 1
                    logger.info(
                        "Attempt rebalance_sell %s $%s swing=%.1f%%",
                        sym,
                        sell_value,
                        sell_swing,
                    )
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_sell_attempt",
                        ts=ts_iso,
                        symbol=sym,
                        side="sell",
                        intent="rebalance_sell",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(
                            ticker["difference"]
                            * (1 - ((ticker["difference"] + account.margin) / 2))
                        ),
                        notional=sell_value,
                    )
                    order_result = broker.place_market_notional(
                        sym,
                        "sell",
                        sell_value,
                        ticker["price"],
                        intent="rebalance_sell",
                        market_session=session,
                    )
                    _apply_order_result(
                        account,
                        key,
                        ticker,
                        order_result,
                        sell_value,
                        "rebalance_sell",
                        swing_pct=sell_swing,
                        broker=broker,
                    )
                    if order_result.is_filled:
                        tick_stats["fills"] += 1
                        _emit_diagnostic(
                            diagnostics,
                            "rebalance_sell_filled",
                            ts=ts_iso,
                            symbol=sym,
                            side="sell",
                            intent="rebalance_sell",
                            price=float(ticker["price"]),
                            volume=float(ticker["volume"]),
                            current_value=current_value,
                            target_value=balance_value,
                            diff=diff,
                            previous_diff=previous_diff,
                            margin=float(account.margin),
                            trigger_threshold=float(
                                ticker["difference"]
                                * (1 - ((ticker["difference"] + account.margin) / 2))
                            ),
                            notional=sell_value,
                        )
                    elif order_result.is_failed:
                        tick_stats["failures"] += 1
                        _emit_diagnostic(
                            diagnostics,
                            "rebalance_sell_failed",
                            ts=ts_iso,
                            symbol=sym,
                            side="sell",
                            intent="rebalance_sell",
                            price=float(ticker["price"]),
                            volume=float(ticker["volume"]),
                            current_value=current_value,
                            target_value=balance_value,
                            diff=diff,
                            previous_diff=previous_diff,
                            margin=float(account.margin),
                            trigger_threshold=float(
                                ticker["difference"]
                                * (1 - ((ticker["difference"] + account.margin) / 2))
                            ),
                            notional=sell_value,
                            error=order_result.error or "",
                        )
                else:
                    _record_skip("hysteresis_not_retraced")
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_order_skipped",
                        ts=ts_iso,
                        symbol=sym,
                        reason="hysteresis_not_retraced",
                        side="sell",
                        intent="rebalance_sell",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(
                            ticker["difference"]
                            * (1 - ((ticker["difference"] + account.margin) / 2))
                        ),
                        notional=0.0,
                    )
                    _log_skip(sym, "rebalance_sell", "hysteresis_not_retraced", diff)
            elif current_value < balance_value:
                diff = (balance_value - current_value) / balance_value
                if diff < account.margin:
                    account.tickers[key]["difference"] = diff
                    _record_skip("below_margin")
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_order_skipped",
                        ts=ts_iso,
                        symbol=sym,
                        reason="below_margin",
                        side="buy",
                        intent="rebalance_buy",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(account.margin),
                        notional=0.0,
                    )
                    _log_skip(sym, "rebalance_buy", "below_margin", diff)
                elif diff > ticker["difference"]:
                    account.tickers[key]["difference"] = diff
                    _record_skip("tracking_peak_diff")
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_order_skipped",
                        ts=ts_iso,
                        symbol=sym,
                        reason="tracking_peak_diff",
                        side="buy",
                        intent="rebalance_buy",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(account.margin),
                        notional=0.0,
                    )
                    _log_skip(sym, "rebalance_buy", "tracking_peak_diff", diff)
                elif (
                    diff
                    < (ticker["difference"] * (1 - ((ticker["difference"] + account.margin) / 2)))
                    and diff > account.margin
                ):
                    buy_value = balance_value - current_value
                    buy_swing = _swing_pct(diff)
                    tick_stats["attempts"] += 1
                    logger.info(
                        "Attempt rebalance_buy %s $%s swing=%.1f%%",
                        sym,
                        buy_value,
                        buy_swing,
                    )
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_buy_attempt",
                        ts=ts_iso,
                        symbol=sym,
                        side="buy",
                        intent="rebalance_buy",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(
                            ticker["difference"]
                            * (1 - ((ticker["difference"] + account.margin) / 2))
                        ),
                        notional=buy_value,
                    )
                    order_result = broker.place_market_notional(
                        sym,
                        "buy",
                        buy_value,
                        ticker["price"],
                        intent="rebalance_buy",
                        market_session=session,
                    )
                    _apply_order_result(
                        account,
                        key,
                        ticker,
                        order_result,
                        buy_value,
                        "rebalance_buy",
                        swing_pct=buy_swing,
                        broker=broker,
                    )
                    if order_result.is_filled:
                        tick_stats["fills"] += 1
                        _emit_diagnostic(
                            diagnostics,
                            "rebalance_buy_filled",
                            ts=ts_iso,
                            symbol=sym,
                            side="buy",
                            intent="rebalance_buy",
                            price=float(ticker["price"]),
                            volume=float(ticker["volume"]),
                            current_value=current_value,
                            target_value=balance_value,
                            diff=diff,
                            previous_diff=previous_diff,
                            margin=float(account.margin),
                            trigger_threshold=float(
                                ticker["difference"]
                                * (1 - ((ticker["difference"] + account.margin) / 2))
                            ),
                            notional=buy_value,
                        )
                    elif order_result.is_failed:
                        tick_stats["failures"] += 1
                        _emit_diagnostic(
                            diagnostics,
                            "rebalance_buy_failed",
                            ts=ts_iso,
                            symbol=sym,
                            side="buy",
                            intent="rebalance_buy",
                            price=float(ticker["price"]),
                            volume=float(ticker["volume"]),
                            current_value=current_value,
                            target_value=balance_value,
                            diff=diff,
                            previous_diff=previous_diff,
                            margin=float(account.margin),
                            trigger_threshold=float(
                                ticker["difference"]
                                * (1 - ((ticker["difference"] + account.margin) / 2))
                            ),
                            notional=buy_value,
                            error=order_result.error or "",
                        )
                else:
                    _record_skip("hysteresis_not_retraced")
                    _emit_diagnostic(
                        diagnostics,
                        "rebalance_order_skipped",
                        ts=ts_iso,
                        symbol=sym,
                        reason="hysteresis_not_retraced",
                        side="buy",
                        intent="rebalance_buy",
                        price=float(ticker["price"]),
                        volume=float(ticker["volume"]),
                        current_value=current_value,
                        target_value=balance_value,
                        diff=diff,
                        previous_diff=previous_diff,
                        margin=float(account.margin),
                        trigger_threshold=float(
                            ticker["difference"]
                            * (1 - ((ticker["difference"] + account.margin) / 2))
                        ),
                        notional=0.0,
                    )
                    _log_skip(sym, "rebalance_buy", "hysteresis_not_retraced", diff)
            else:
                account.tickers[key]["difference"] = 0
        else:
            _record_skip("limit_trade_open")
            limit_diff = float(ticker.get("difference", 0.0))
            _emit_diagnostic(
                diagnostics,
                "rebalance_order_skipped",
                ts=ts_iso,
                symbol=sym,
                reason="limit_trade_open",
                side="",
                intent="",
                price=float(ticker.get("price") or 0.0),
                volume=float(ticker["volume"]),
                current_value=float(ticker["volume"]) * float(ticker.get("price") or 0.0),
                target_value=balance_value,
                diff=limit_diff,
                previous_diff=previous_diff,
                margin=float(account.margin),
                trigger_threshold=float(account.margin),
                notional=0.0,
            )
            _log_skip(sym, "", "limit_trade_open", limit_diff)

        if ticker["difference"] > high_ticker["diff"]:
            high_ticker["diff"] = ticker["difference"]
            high_ticker["ticker"] = ticker["ticker"]

    dt_object = datetime.datetime.fromtimestamp(
        account.serverTime or int(time.time()), datetime.timezone.utc
    )
    swing = trunc(high_ticker["diff"] * 100, 1) if high_ticker["ticker"] else 0
    summary_msg = (
        "%s:%s:%s ~ %s trade, equity=$%s, highest swing %s:%s%%, balance=$%s"
    )
    summary_args = (
        dt_object.hour,
        dt_object.minute,
        dt_object.second,
        session.upper(),
        account.equity,
        high_ticker["ticker"],
        swing,
        trunc(base_balance, 2),
    )
    if log_summary:
        logger.info(summary_msg, *summary_args)
    else:
        logger.debug(summary_msg, *summary_args)
    _emit_diagnostic(
        diagnostics,
        "tick_summary",
        ts=ts_iso,
        session=session,
        equity=float(account.equity),
        cash=float(getattr(broker, "cash", 0.0)),
        base_balance=float(base_balance),
        symbols_evaluated=int(tick_stats["symbols_evaluated"]),
        attempts=int(tick_stats["attempts"]),
        fills=int(tick_stats["fills"]),
        failures=int(tick_stats["failures"]),
        skipped=tick_stats["skipped"],
    )


def _log_order_api_failure(message: str, *args, status_code: int, reason: str) -> None:
    """Log order API failures; WARNING for transient 5xx, ERROR otherwise."""
    log = logger.warning if 500 <= status_code <= 599 else logger.error
    log(message, *args, status_code, reason)


def sync_open_limit_orders(session, account, config) -> None:
    """Reconcile local limitTrade state with Alpaca open orders."""
    headers = alpaca_headers(config, json_content=True)
    orders_url = f"{config.urlBase}markets/v2/orders"
    result = session.get(orders_url, headers=headers)
    if result.status_code != 200:
        _log_order_api_failure(
            "Failed to list open orders: %s %s",
            status_code=result.status_code,
            reason=result.reason,
        )
        return
    limit_ts = account.serverTime or int(time.time())
    for item in result.json():
        sym = item.get("symbol")
        if not sym:
            continue
        for key, ticker in enumerate(account.tickers):
            if ticker["ticker"] != sym or ticker["limitTrade"]["open"]:
                continue
            side = item.get("side", "buy")
            order_id = item["id"]
            recovered_intent = _intent_from_limit_placed(order_id)
            intent = recovered_intent or (
                "rebalance_buy" if side == "buy" else "rebalance_sell"
            )
            account.tickers[key]["limitTrade"] = {
                "open": True,
                "id": order_id,
                "ts": limit_ts,
                "side": side,
                "intent": intent,
                "notional": None,
                "swing_pct": None,
            }
            logger.info("Synced open limit order for %s id=%s", sym, order_id)
            break


def _cancel_aged_limit(session, config, account, key, ticker, headers, open_url) -> None:
    cancel_result = session.get(open_url, headers=headers)
    if cancel_result.status_code != 200:
        logger.error(
            "Failed to re-check order %s before cancel: %s",
            ticker["limitTrade"]["id"],
            cancel_result.reason,
        )
        return

    current_status = cancel_result.json().get("status", "")
    if current_status in _LIMIT_TERMINAL:
        _handle_limit_update(session, config, account, key, ticker, cancel_result.json())
        return

    if current_status in _LIMIT_CANCELABLE:
        delete_url = f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
        delete_result = session.delete(delete_url, headers=headers)
        if delete_result.status_code == 204:
            meta = _limit_meta(ticker)
            order_id = ticker["limitTrade"]["id"]
            log_limit_status(
                config,
                symbol=ticker["ticker"],
                side=meta.get("side", "buy"),
                intent=meta.get("intent", "rebalance"),
                market_session=account.market,
                order_id=order_id,
                alpaca_status="canceled",
                notional=meta.get("notional"),
            )
            _log_limit_terminal(
                meta.get("intent", "rebalance"),
                ticker["ticker"],
                meta.get("swing_pct"),
                order_id,
                "canceled",
            )
            account.tickers[key]["limitTrade"] = _empty_limit_trade(account.serverTime)
            _sync_volume_from_broker(session, config, account, key, ticker)
        else:
            logger.error(
                "Failed to cancel limit order %s: %s",
                ticker["limitTrade"]["id"],
                delete_result.status_code,
            )
        return

    logger.info(
        "Keeping open limit for %s: status=%s (not cancelable yet)",
        ticker["ticker"],
        current_status,
    )


def _process_open_limit(session, config, account, key, ticker, headers) -> None:
    open_url = f"{config.urlBase}markets/v2/orders/{ticker['limitTrade']['id']}"
    result = session.get(open_url, headers=headers)
    if result.status_code != 200:
        if result.status_code == 404:
            logger.info(
                "Limit order %s gone (404); clearing local state for %s",
                ticker["limitTrade"]["id"],
                ticker["ticker"],
            )
            account.tickers[key]["limitTrade"] = _empty_limit_trade(
                account.serverTime or int(time.time())
            )
            _sync_volume_from_broker(session, config, account, key, ticker)
            return
        _log_order_api_failure(
            "Failed to check open order %s: %s %s",
            ticker["limitTrade"]["id"],
            status_code=result.status_code,
            reason=result.reason,
        )
        return

    json_result = result.json()
    status = json_result.get("status", "")
    if status in _LIMIT_TERMINAL:
        _handle_limit_update(session, config, account, key, ticker, json_result)
        return

    if status == "partially_filled":
        logger.debug(
            "Limit partially filled %s id=%s; syncing volume",
            ticker["ticker"],
            ticker["limitTrade"]["id"],
        )
        _sync_volume_from_broker(session, config, account, key, ticker)

    now = account.serverTime or int(time.time())
    if now - int(ticker["limitTrade"]["ts"]) <= LIMIT_ORDER_MAX_AGE_SECONDS:
        return

    _cancel_aged_limit(session, config, account, key, ticker, headers, open_url)


def maintain_open_limits(session, account, config) -> None:
    """Poll and cancel stale limit orders; runs even when circuit breaker pauses new trades."""
    if account.market in ("closed", "holiday"):
        return
    sync_open_limit_orders(session, account, config)
    headers = alpaca_headers(config, json_content=True)
    for key, ticker in enumerate(account.tickers):
        if ticker["limitTrade"]["open"]:
            _process_open_limit(session, config, account, key, ticker, headers)


def _fetch_snapshot_prices(session, config, account, headers) -> dict[str, float]:
    ticker_list = [ticker["ticker"] for ticker in account.tickers]
    if not ticker_list:
        return {}
    tickers_str = "%2C".join(ticker_list)
    snapshot_url = (
        f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={tickers_str}&feed=iex"
    )
    result = session.get(snapshot_url, headers=headers)
    prices: dict[str, float] = {}
    if result.status_code == 200:
        json_result = result.json()
        for key, ticker in enumerate(account.tickers):
            sym = ticker["ticker"]
            if sym in json_result and json_result[sym].get("minuteBar"):
                vw = float(json_result[sym]["minuteBar"]["vw"])
                account.tickers[key]["price"] = vw
                prices[sym] = vw
            else:
                # ponytail: omit missing symbols (tick skips price<=0); do not
                # rehydrate stale ticker["price"] into the order path.
                logger.warning("No snapshot data for %s", sym)
    else:
        logger.error(
            "Snapshot error: %s %s",
            result.status_code,
            result.reason,
        )
        # Fail closed for this tick: empty prices → no new trades on stale VWAP.
    return prices


def force_rebalance_symbol(
    account,
    config,
    *,
    symbol: str,
    prices: dict,
    broker,
    session: str = "open",
) -> tuple[bool, str]:
    """One-shot: trade symbol to equal-$ target, ignoring hysteresis. RTH only."""
    from analytics import compute_balance_target

    sym = symbol.strip().upper()
    if not sym:
        return False, "Symbol required"

    if session != "open":
        return False, f"Market not open (session={session}); force balance is RTH-only"

    total_pos = len(account.tickers)
    if total_pos == 0:
        return False, "No tickers loaded"

    key = None
    ticker = None
    for i, row in enumerate(account.tickers):
        if row["ticker"] == sym:
            key = i
            ticker = row
            break
    if ticker is None:
        return False, f"{sym} not in portfolio"

    if ticker.get("limitTrade", {}).get("open"):
        return False, f"{sym} has an open limit order; cancel or wait before force balance"

    if sym in prices:
        price = float(prices[sym])
    else:
        price = float(ticker.get("price") or 0.0)
    if price <= 0:
        return False, f"No price for {sym}"

    ticker["price"] = price
    account.equity = _apply_tradable_equity(account, broker.get_equity(prices))
    target = compute_balance_target(account.equity, total_pos, float(account.margin))
    if target is None or target <= 0:
        return False, "Cannot compute balance target"

    current_value = float(ticker["volume"]) * price
    gap = current_value - target
    notional = trunc(abs(gap), 2)
    if notional <= 0:
        account.tickers[key]["difference"] = 0.0
        return True, f"{sym} already balanced"

    side = "sell" if gap > 0 else "buy"
    intent = "rebalance_force"
    swing = _swing_pct(abs(gap) / target) if target else 0.0
    logger.info(
        "Attempt %s %s %s $%s swing=%.1f%%",
        intent,
        side,
        sym,
        notional,
        swing,
    )
    result = broker.place_market_notional(
        sym,
        side,
        notional,
        price,
        intent=intent,
        market_session=session,
    )
    _apply_order_result(
        account,
        key,
        ticker,
        result,
        notional,
        intent,
        swing_pct=swing,
        broker=broker,
    )
    if result.is_filled:
        account.tickers[key]["difference"] = 0.0
        return True, f"Force {side} {sym} ${notional}"
    if result.is_failed:
        return False, result.error or f"Force {side} {sym} failed"
    if result.is_limit_placed:
        return False, f"Unexpected limit for {sym} during RTH force balance"
    return False, f"Force {side} {sym} incomplete"


def bot(session, account, config, circuit=None):
    headers = alpaca_headers(config, json_content=True)

    if account.equity == 0:
        logger.info("Loading Alpaca account data")
        try:
            account_data = get_account(session, config)
        except AlpacaAPIError as exc:
            logger.warning("bot skipped: %s", exc)
            if circuit:
                circuit.record_failure()
            return
        account.equity = float(account_data["equity"])
        account.cash = float(account_data.get("cash") or 0)
        logger.info("Updating tickers")
        account.check_ticker(session, config)
        sync_open_limit_orders(session, account, config)

    if account.market in ("closed", "holiday"):
        return

    if len(account.tickers) == 0:
        logger.warning("No tickers loaded; skipping rebalance")
        return

    try:
        account_data = get_account(session, config)
    except AlpacaAPIError as exc:
        logger.warning("bot skipped: %s", exc)
        if circuit:
            circuit.record_failure()
        return
    account.equity = float(account_data["equity"])
    account.cash = float(account_data.get("cash") or 0)
    prices = _fetch_snapshot_prices(session, config, account, headers)
    broker = LiveBroker(session, config, account, circuit=circuit)
    rebalance_tick(
        account,
        config,
        prices=prices,
        broker=broker,
        session=account.market,
        log_summary=True,
    )
    if circuit:
        circuit.record_success()
