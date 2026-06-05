"""Simulated broker for backtests."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from config import Config
from orders import OrderResult
from trade_log import append_trade, build_trade_record
from utils import trunc

logger = logging.getLogger("alpaca_bot.backtest.broker")

_QTY_DECIMALS = 4


def _truncate_qty(qty: float) -> float:
    scale = 10**_QTY_DECIMALS
    return int(qty * scale) / scale


class SimBroker:
    def __init__(self, cash: float, config: Config, trades_path: str = "backtest_trades.jsonl"):
        self.cash = float(cash)
        self.positions: Dict[str, float] = {}
        self.config = config
        self.trades_path = trades_path

    def get_qty(self, symbol: str) -> float:
        return self.positions.get(symbol, 0.0)

    def get_equity(self, prices: dict[str, float]) -> float:
        invested = sum(
            self.positions.get(sym, 0.0) * prices.get(sym, 0.0) for sym in self.positions
        )
        return self.cash + invested

    def _log_fill(
        self,
        *,
        symbol: str,
        side: str,
        intent: str,
        market_session: str,
        notional: float,
        filled_qty: float,
        filled_avg_price: float,
    ) -> None:
        record = build_trade_record(
            symbol=symbol,
            side=side,
            intent=intent,
            order_type="market",
            market_session=market_session,
            status="filled",
            paper=self.config.paper,
            order_id="backtest",
            notional=notional,
            filled_qty=filled_qty,
            filled_avg_price=filled_avg_price,
        )
        append_trade(record, path=self.trades_path)

    def _log_failure(
        self,
        *,
        symbol: str,
        side: str,
        intent: str,
        market_session: str,
        notional: float,
        error: str,
    ) -> None:
        record = build_trade_record(
            symbol=symbol,
            side=side,
            intent=intent,
            order_type="market",
            market_session=market_session,
            status="failed",
            paper=self.config.paper,
            order_id="backtest",
            notional=notional,
            error=error,
        )
        append_trade(record, path=self.trades_path)

    def place_market_notional(
        self,
        symbol: str,
        side: str,
        notional: float,
        price: float,
        *,
        intent: str,
        market_session: str,
    ) -> OrderResult:
        notional = trunc(float(notional), 2)
        if notional <= 0 or price <= 0:
            error = "invalid notional or price"
            self._log_failure(
                symbol=symbol,
                side=side,
                intent=intent,
                market_session=market_session,
                notional=notional,
                error=error,
            )
            return OrderResult(status="failed", error=error)

        qty = _truncate_qty(notional / price)
        if side == "buy":
            if notional > self.cash + 1e-6:
                notional = trunc(self.cash, 2)
                qty = _truncate_qty(notional / price)
                if notional <= 0 or qty <= 0:
                    error = "insufficient cash"
                    self._log_failure(
                        symbol=symbol,
                        side=side,
                        intent=intent,
                        market_session=market_session,
                        notional=notional,
                        error=error,
                    )
                    return OrderResult(status="failed", error=error)
            self.cash -= notional
            self.positions[symbol] = self.positions.get(symbol, 0.0) + qty
        elif side == "sell":
            held = self.positions.get(symbol, 0.0)
            if qty > held + 1e-9:
                qty = _truncate_qty(held)
                notional = trunc(qty * price, 2)
            if qty <= 0:
                error = "no shares to sell"
                self._log_failure(
                    symbol=symbol,
                    side=side,
                    intent=intent,
                    market_session=market_session,
                    notional=notional,
                    error=error,
                )
                return OrderResult(status="failed", error=error)
            self.positions[symbol] = held - qty
            if self.positions[symbol] < 1e-12:
                del self.positions[symbol]
            self.cash += notional
        else:
            error = f"unknown side {side}"
            self._log_failure(
                symbol=symbol,
                side=side,
                intent=intent,
                market_session=market_session,
                notional=notional,
                error=error,
            )
            return OrderResult(status="failed", error=error)

        self._log_fill(
            symbol=symbol,
            side=side,
            intent=intent,
            market_session=market_session,
            notional=notional,
            filled_qty=qty,
            filled_avg_price=price,
        )
        return OrderResult(
            status="filled",
            order_id="backtest",
            filled_qty=qty,
            filled_avg_price=price,
        )
