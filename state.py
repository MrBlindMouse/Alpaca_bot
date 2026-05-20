import json
import logging
import os
import time
from typing import Optional

import remote
from ticker_source import find_tickers
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
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                    "APCA-API-KEY-ID": config.apiKey,
                    "APCA-API-SECRET-KEY": config.apiSecret,
                }
                result = session.delete(close_url, headers=headers)
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
        if tickers:
            new_list = [
                {
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
                for item in tickers
            ]
            new_list = [
                old_ticker if old_ticker["ticker"] == new_ticker["ticker"] else new_ticker
                for new_ticker in new_list
                for old_ticker in self.tickers
                if old_ticker["ticker"] == new_ticker["ticker"]
            ] or new_list
            self.tickers = new_list
            self.save_state()
            remote.post_log(config, "Tickers updated", config.title, "1")
        else:
            remote.post_log(config, "Tickers not scraped!", config.title, "3")
            time.sleep(5 * 60)

    def save_state(self, path: Optional[str] = None):
        target = path or self.STATE_FILE
        with open(target, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "tickers": self.tickers,
                    "equity": self.equity,
                    "market": self.market,
                    "serverTime": self.serverTime,
                    "margin": self.margin,
                },
                file,
            )

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
