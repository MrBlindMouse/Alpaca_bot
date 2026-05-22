import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

from alpaca_client import get_snapshot_vwap
from trade_log import append_trade, build_trade_record
from utils import trunc

logger = logging.getLogger("alpaca_bot.orders")

OrderStatus = Literal[
    "filled", "failed", "limit_placed", "limit_canceled", "limit_expired"
]


@dataclass
class OrderResult:
    status: OrderStatus
    order_id: str = ""
    filled_qty: Optional[float] = None
    filled_avg_price: Optional[float] = None
    error: Optional[str] = None

    @property
    def is_filled(self) -> bool:
        return self.status == "filled"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @property
    def is_limit_placed(self) -> bool:
        return self.status == "limit_placed"


def _log_trade(config, **kwargs):
    append_trade(build_trade_record(paper=config.paper, **kwargs))


def _sanitize_error(response) -> str:
    return f"{response.status_code} {response.reason}"


def _filled_from_response(data: dict):
    qty = data.get("filled_qty")
    price = data.get("filled_avg_price")
    return (
        float(qty) if qty not in (None, "", "0") else None,
        float(price) if price not in (None, "", "0") else None,
    )


def log_limit_status(
    config,
    *,
    symbol: str,
    side: str,
    intent: str,
    market_session: str,
    order_id: str,
    alpaca_status: str,
    notional: Optional[float] = None,
    limit_price: Optional[float] = None,
    filled_qty: Optional[float] = None,
    filled_avg_price: Optional[float] = None,
):
    status_map = {
        "filled": "filled",
        "canceled": "limit_canceled",
        "expired": "limit_expired",
    }
    status = status_map.get(alpaca_status)
    if not status:
        return
    _log_trade(
        config,
        symbol=symbol,
        side=side,
        intent=intent,
        order_type="limit",
        market_session=market_session,
        status=status,
        order_id=order_id,
        notional=notional,
        limit_price=limit_price,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
    )


def _check_slippage(session, config, symbol: str, current_price: float) -> Optional[str]:
    """Return error message if price moved beyond max slippage, else None."""
    latest = get_snapshot_vwap(session, config, symbol)
    if latest is None or current_price <= 0:
        return None
    move = abs(latest - current_price) / current_price
    if move > config.max_slippage_pct:
        return (
            f"slippage {move:.4f} exceeds max {config.max_slippage_pct:g} "
            f"(ref={current_price}, latest={latest})"
        )
    return None


def create_order(
    session,
    config,
    volume,
    direction: str,
    symbol: str,
    *,
    intent: str,
    market_status: str = "open",
    current_price: float = 0,
    order_value_type: str = "value",
    circuit=None,
) -> OrderResult:
    from alpaca_client import alpaca_headers

    headers = alpaca_headers(config, json_content=True)
    notional = None if order_value_type == "qty" else trunc(volume, 2)
    qty = volume if order_value_type == "qty" else None
    limit_price = None

    if getattr(config, "dry_run", False):
        _log_trade(
            config,
            symbol=symbol,
            side=direction,
            intent=intent,
            order_type="market" if market_status == "open" else "limit",
            market_session=market_status,
            status="filled",
            order_id="dry-run",
            notional=notional,
            qty=qty,
            limit_price=limit_price,
        )
        return OrderResult(status="filled", order_id="dry-run")

    if market_status == "open":
        if config.slippage_guard_enabled and current_price > 0:
            slip_err = _check_slippage(session, config, symbol, current_price)
            if slip_err:
                logger.warning("Slippage guard rejected %s: %s", symbol, slip_err)
                _log_trade(
                    config,
                    symbol=symbol,
                    side=direction,
                    intent=intent,
                    order_type="market",
                    market_session=market_status,
                    status="failed",
                    notional=notional,
                    qty=qty,
                    error=slip_err,
                )
                if circuit:
                    circuit.record_failure()
                return OrderResult(status="failed", error=slip_err)

    if market_status == "open":
        payload = {
            "side": direction,
            "type": "market",
            "time_in_force": "day",
            "symbol": symbol,
            "qty" if order_value_type == "qty" else "notional": str(
                volume if order_value_type == "qty" else trunc(volume, 2)
            ),
        }
        order_type = "market"
    else:
        limit_price = trunc(float(current_price) * (1.005 if direction == "buy" else 0.995), 2)
        payload = {
            "side": direction,
            "type": "limit",
            "limit_price": str(limit_price),
            "time_in_force": "day",
            "symbol": symbol,
            "qty" if order_value_type == "qty" else "notional": str(
                volume if order_value_type == "qty" else trunc(volume, 2)
            ),
            "extended_hours": True,
        }
        order_type = "limit"

    url = f"{config.urlBase}markets/v2/orders"
    response = session.post(url, json=payload, headers=headers)

    if market_status == "open":
        if str(response.status_code) != "200":
            err = _sanitize_error(response)
            logger.error("Order failed for %s: %s", symbol, err)
            if circuit:
                circuit.record_failure()
            _log_trade(
                config,
                symbol=symbol,
                side=direction,
                intent=intent,
                order_type=order_type,
                market_session=market_status,
                status="failed",
                notional=notional,
                qty=qty,
                error=err,
            )
            return OrderResult(status="failed", error=err)

        json_response = response.json()
        order_id = json_response["id"]
        poll_status = "open"
        timeout = 60  # Allow up to 60s for market orders to fill
        start_time = time.time()
        while poll_status == "open" and time.time() - start_time < timeout:
            poll_url = f"{config.urlBase}markets/v2/orders/{order_id}"
            response = session.get(poll_url, headers=headers)
            if str(response.status_code) == "200":
                json_response = response.json()
                if json_response["status"] in ["filled", "canceled", "expired"]:
                    poll_status = "closed"
                else:
                    time.sleep(1)
            else:
                err = _sanitize_error(response)
                logger.error("Order poll failed for %s: %s", symbol, err)
                poll_status = "close"
                json_response = {"status": "error", "message": err}
                if circuit:
                    circuit.record_failure()
                break

        if poll_status == "open":
            poll_url = f"{config.urlBase}markets/v2/orders/{order_id}"
            final_resp = session.get(poll_url, headers=headers)
            if str(final_resp.status_code) == "200":
                json_response = final_resp.json()

        final = json_response.get("status", "")
        if final == "filled":
            filled_qty, filled_avg = _filled_from_response(json_response)
            _log_trade(
                config,
                symbol=symbol,
                side=direction,
                intent=intent,
                order_type=order_type,
                market_session=market_status,
                status="filled",
                order_id=order_id,
                notional=notional,
                qty=qty,
                filled_qty=filled_qty,
                filled_avg_price=filled_avg,
            )
            if circuit:
                circuit.record_success()
            return OrderResult(
                status="filled",
                order_id=order_id,
                filled_qty=filled_qty,
                filled_avg_price=filled_avg,
            )

        err = f"market order ended as {final}"
        if circuit:
            circuit.record_failure()
        _log_trade(
            config,
            symbol=symbol,
            side=direction,
            intent=intent,
            order_type=order_type,
            market_session=market_status,
            status="failed",
            order_id=order_id,
            notional=notional,
            qty=qty,
            error=err,
        )
        return OrderResult(status="failed", order_id=order_id, error=err)

    if str(response.status_code) == "200":
        order_id = str(response.json()["id"])
        _log_trade(
            config,
            symbol=symbol,
            side=direction,
            intent=intent,
            order_type=order_type,
            market_session=market_status,
            status="limit_placed",
            order_id=order_id,
            notional=notional,
            qty=qty,
            limit_price=limit_price,
        )
        return OrderResult(status="limit_placed", order_id=order_id)

    err = _sanitize_error(response)
    logger.error("Limit order failed for %s: %s", symbol, err)
    if circuit:
        circuit.record_failure()
    _log_trade(
        config,
        symbol=symbol,
        side=direction,
        intent=intent,
        order_type="limit",
        market_session=market_status,
        status="failed",
        notional=notional,
        qty=qty,
        limit_price=limit_price,
        error=err,
    )
    return OrderResult(status="failed", error=err)
