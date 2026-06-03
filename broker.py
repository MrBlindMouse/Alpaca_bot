"""Broker protocol for live and simulated rebalancing."""

from __future__ import annotations

from typing import Protocol

from orders import OrderResult


class Broker(Protocol):
    def get_equity(self, prices: dict[str, float]) -> float: ...

    def get_qty(self, symbol: str) -> float: ...

    def place_market_notional(
        self,
        symbol: str,
        side: str,
        notional: float,
        price: float,
        *,
        intent: str,
        market_session: str,
    ) -> OrderResult: ...
