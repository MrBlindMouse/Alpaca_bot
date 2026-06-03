import json
import logging
import os
from typing import Optional

import remote
from alpaca_client import alpaca_headers
from ticker_source import find_tickers, get_cached_valid_tickers
from trade_log import append_trade, build_trade_record

logger = logging.getLogger("alpaca_bot.state")


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
        self.market = "closed"
        self.serverTime = 0
        self.margin = 0

    def check_balances(self, session, positions, config):
        """Update ticker quantities or liquidate if not found."""
        for item in positions:
            found = False
            for key, ticker in enumerate(self.tickers):
                if ticker["ticker"] == item["symbol"]:
                    found = True
                    if ticker["volume"] != item["qty"]:
                        self.tickers[key]["volume"] = float(item["qty"])
                    break
            if not found:
                symbol = item["symbol"]
                logger.info("Liquidating %s", symbol)
                close_url = (
                    f"{config.urlBase}markets/v2/positions/{symbol}?percentage=100"
                )
                result = session.delete(
                    close_url, headers=alpaca_headers(config, json_content=True)
                )
                if str(result.status_code) == "200":
                    status = result.json().get("status", "unknown")
                    logger.info("Liquidated %s; status=%s", symbol, status)
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
                        )
                    )
                else:
                    err = f"{result.status_code} {result.reason}"
                    logger.error("Liquidation failed for %s: %s", symbol, err)
                    append_trade(
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
                    },
                }
                if item in old_map:
                    old = old_map[item]
                    # Preserve volume, price, difference, and limitTrade for unchanged tickers
                    new_ticker["volume"] = old.get("volume", 0)
                    new_ticker["price"] = old.get("price", 0)
                    new_ticker["difference"] = old.get("difference", 0)
                    new_ticker["limitTrade"] = old.get("limitTrade", new_ticker["limitTrade"])
                new_list.append(new_ticker)
            self.tickers = new_list
            self.save_state()
            remote.post_log(config, "Tickers updated", config.title, "1")
        else:
            remote.post_log(config, "Tickers not scraped!", config.title, "3")
            if self.tickers:
                logger.warning("Keeping previous ticker list (%d tickers)", len(self.tickers))
            else:
                logger.warning("Ticker list empty; will retry on next tick")

    def save_state(self, path: Optional[str] = None):
        target = path or self.STATE_FILE
        payload = {
            "tickers": self.tickers,
            "equity": self.equity,
            "market": self.market,
            "serverTime": self.serverTime,
            "margin": self.margin,
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
                self.market = state["market"]
                self.serverTime = state["serverTime"]
                self.margin = state["margin"]
        else:
            raise FileNotFoundError(
                f"State file {self.STATE_FILE} not found. "
                "Use the TUI Settings tab (Initialize state), run "
                "`python bot.py --init`, or call Status.bootstrap(margin)."
            )
