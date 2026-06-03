"""Live Alpaca broker adapter for rebalance_tick."""

from __future__ import annotations

from typing import Optional

from alpaca_client import get_account, get_balances
from orders import OrderResult, create_order


class LiveBroker:
    def __init__(self, session, config, account, *, circuit=None):
        self.session = session
        self.config = config
        self.account = account
        self.circuit = circuit

    def get_qty(self, symbol: str) -> float:
        qty = get_balances(self.session, self.config, symbol)
        if qty is None:
            return float(self._ticker_volume(symbol))
        return float(qty)

    def _ticker_volume(self, symbol: str) -> float:
        for ticker in self.account.tickers:
            if ticker["ticker"] == symbol:
                return float(ticker.get("volume", 0) or 0)
        return 0.0

    def get_equity(self, prices: dict[str, float]) -> float:
        if self.account.equity > 0:
            return float(self.account.equity)
        data = get_account(self.session, self.config)
        return float(data["equity"])

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
        return create_order(
            self.session,
            self.config,
            notional,
            side,
            symbol,
            intent=intent,
            market_status=market_session,
            current_price=price,
            circuit=self.circuit,
        )
