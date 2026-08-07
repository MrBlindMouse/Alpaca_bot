import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from alpaca_client import alpaca_headers
from ticker_source import (
    find_tickers,
    get_cached_valid_tickers,
    is_permanently_untradable,
)
from trade_log import append_order_event, append_trade, build_trade_record

logger = logging.getLogger("alpaca_bot.state")


def _position_market_value(item: dict) -> float:
    try:
        return float(item.get("market_value") or 0)
    except (TypeError, ValueError):
        return 0.0


def _liquidate_fill_fields(qty: float, market_value: float) -> dict:
    """Pre-close mark for orphan liquidate logs (no fill poll)."""
    avg = (market_value / qty) if qty > 0 else None
    return {
        "filled_qty": qty,
        "notional": market_value if market_value > 0 else None,
        "filled_avg_price": avg,
    }


class Status:
    STATE_FILE = "trading_state.json"

    @classmethod
    def state_exists(cls, path: Optional[str] = None) -> bool:
        return os.path.exists(path or cls.STATE_FILE)

    @classmethod
    def bootstrap(cls, margin: float, path: Optional[str] = None) -> "Status":
        """Create a fresh trading_state.json for first-time setup."""
        account = cls()
        account.margin = margin
        account.save_state(path=path)
        logger.info("Created initial state file %s", path or cls.STATE_FILE)
        return account

    def __init__(self):
        logger.info("Initializing state")
        self.tickers = []
        self.equity = 0
        self.cash = 0
        self.market = "closed"
        self.serverTime = 0
        self.margin = 0
        self.quarantined: list[dict] = []

    def is_quarantined(self, symbol: str) -> bool:
        sym = (symbol or "").upper()
        return any(q.get("symbol") == sym for q in self.quarantined)

    def quarantine(
        self, symbol: str, reason: str, market_value: float = 0.0
    ) -> None:
        sym = (symbol or "").strip().upper()
        if not sym:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for entry in self.quarantined:
            if entry.get("symbol") == sym:
                entry["reason"] = reason
                entry["market_value"] = float(market_value or 0)
                if not entry.get("since"):
                    entry["since"] = now
                return
        self.quarantined.append(
            {
                "symbol": sym,
                "reason": reason,
                "since": now,
                "market_value": float(market_value or 0),
            }
        )
        logger.warning("Quarantined %s (%s)", sym, reason)

    def clear_quarantine(self, symbol: str) -> bool:
        sym = (symbol or "").strip().upper()
        before = len(self.quarantined)
        self.quarantined = [q for q in self.quarantined if q.get("symbol") != sym]
        return len(self.quarantined) < before

    def tradable_equity(self, raw: float) -> float:
        trapped = sum(float(q.get("market_value") or 0) for q in self.quarantined)
        return max(0.0, float(raw) - trapped)

    def check_balances(self, session, positions, config):
        """Update ticker quantities or liquidate orphans not in the universe."""
        cached = get_cached_valid_tickers()
        if cached:
            local = {t["ticker"] for t in self.tickers}
            if local != set(cached):
                logger.info(
                    "Universe stale vs cache (%d local, %d cached); refreshing",
                    len(local),
                    len(cached),
                )
                self.check_ticker(session, config)

        held: dict[str, float] = {}
        held_mv: dict[str, float] = {}
        for item in positions:
            symbol = item["symbol"]
            qty = float(item["qty"])
            held[symbol] = qty
            held_mv[symbol] = _position_market_value(item)
            found = False
            for key, ticker in enumerate(self.tickers):
                if ticker["ticker"] == symbol:
                    found = True
                    if float(ticker["volume"]) != qty:
                        self.tickers[key]["volume"] = qty
                    break
            if not found:
                if self.is_quarantined(symbol):
                    for entry in self.quarantined:
                        if entry.get("symbol") == symbol:
                            entry["market_value"] = held_mv[symbol]
                            break
                    continue
                if getattr(config, "dry_run", False):
                    logger.info("Dry-run: would liquidate orphan %s", symbol)
                    append_trade(
                        build_trade_record(
                            symbol=symbol,
                            side="sell",
                            intent="liquidate",
                            order_type="market",
                            market_session=self.market,
                            status="filled",
                            paper=config.paper,
                            order_id="dry-run",
                            error=None,
                            **_liquidate_fill_fields(qty, held_mv[symbol]),
                        )
                    )
                    continue
                logger.info("Attempt liquidate %s", symbol)
                close_url = (
                    f"{config.urlBase}markets/v2/positions/{symbol}?percentage=100"
                )
                result = session.delete(
                    close_url, headers=alpaca_headers(config, json_content=True)
                )
                if result.status_code == 200:
                    logger.info("Filled liquidate %s", symbol)
                    append_trade(
                        build_trade_record(
                            symbol=symbol,
                            side="sell",
                            intent="liquidate",
                            order_type="market",
                            market_session=self.market,
                            status="filled",
                            paper=config.paper,
                            error=None,
                            **_liquidate_fill_fields(qty, held_mv[symbol]),
                        )
                    )
                else:
                    err = f"{result.status_code} {result.reason}"
                    logger.error("Failed liquidate %s: %s", symbol, err)
                    append_order_event(
                        build_trade_record(
                            symbol=symbol,
                            side="sell",
                            intent="liquidate",
                            order_type="market",
                            market_session=self.market,
                            status="failed",
                            paper=config.paper,
                            error=err,
                        )
                    )
                    permanent = is_permanently_untradable(session, config, symbol)
                    if permanent is True:
                        self.quarantine(
                            symbol,
                            reason=f"untradable after liquidate fail: {err}",
                            market_value=held_mv[symbol],
                        )

        # Drop quarantine once the broker no longer holds the symbol (CA settled).
        for sym in [q.get("symbol") for q in list(self.quarantined)]:
            if sym and sym not in held:
                self.clear_quarantine(sym)
                logger.info("Cleared quarantine for %s (no longer held)", sym)

        # Universe symbols flat at the broker must not keep a stale local volume.
        for key, ticker in enumerate(self.tickers):
            if ticker["ticker"] not in held and float(ticker.get("volume") or 0) != 0:
                self.tickers[key]["volume"] = 0.0

        self.save_state()

    def check_ticker(self, session, config):
        """Update equity list for NASDAQ100 changes."""
        tickers = find_tickers(session, config)
        if not tickers:
            fallback = get_cached_valid_tickers()
            if fallback:
                logger.warning(
                    "Ticker scrape failed; using cached list (%d tickers)", len(fallback)
                )
                tickers = fallback
        if tickers:
            # Build fresh ticker entries with preserved old state
            old_map = {t["ticker"]: t for t in self.tickers}
            new_list = []
            for item in tickers:
                new_ticker = {
                    "ticker": item,
                    "volume": 0,
                    "difference": 0,
                    "price": 0,
                    "limitTrade": {
                        "open": False,
                        "id": "",
                        "ts": 0,
                        "side": "",
                        "intent": "",
                        "notional": None,
                        "swing_pct": None,
                    },
                }
                if item in old_map:
                    old = old_map[item]
                    # Preserve volume, price, difference, and limitTrade for unchanged tickers
                    new_ticker["volume"] = old.get("volume", 0)
                    new_ticker["price"] = old.get("price", 0)
                    new_ticker["difference"] = old.get("difference", 0)
                    new_ticker["limitTrade"] = old.get(
                        "limitTrade", new_ticker["limitTrade"]
                    )
                new_list.append(new_ticker)
            self.tickers = new_list
            self.save_state()
            logger.info("Tickers updated (%d symbols)", len(new_list))
        else:
            if self.tickers:
                logger.warning(
                    "Keeping previous ticker list (%d tickers)", len(self.tickers)
                )
            else:
                logger.warning("Ticker list empty; will retry on next tick")

    def save_state(self, path: Optional[str] = None):
        target = path or self.STATE_FILE
        payload = {
            "tickers": self.tickers,
            "equity": self.equity,
            "cash": self.cash,
            "market": self.market,
            "serverTime": self.serverTime,
            "margin": self.margin,
            "quarantined": self.quarantined,
        }
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{target}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file)
        os.replace(tmp_path, target)

    def load_state(self):
        if os.path.exists(self.STATE_FILE):
            with open(self.STATE_FILE, "r", encoding="utf-8") as file:
                state = json.load(file)
                self.tickers = state["tickers"]
                self.equity = state["equity"]
                self.cash = float(state.get("cash") or 0)
                self.market = state["market"]
                self.serverTime = state["serverTime"]
                self.margin = state["margin"]
                self.quarantined = state.get("quarantined") or []
        else:
            raise FileNotFoundError(
                f"State file {self.STATE_FILE} not found. "
                "Use the TUI Settings tab (Initialize state), run "
                "`python bot.py --init`, or call Status.bootstrap(margin)."
            )
