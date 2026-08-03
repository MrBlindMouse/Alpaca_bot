"""Spot-check that rebalance_tick updates difference the same way for a simple over-weight case."""

from rebalance import rebalance_tick
from backtest.broker import SimBroker
from config import Config


def _ticker(sym: str, volume: float, price: float, diff: float = 0.05):
    return {
        "ticker": sym,
        "volume": volume,
        "price": price,
        "difference": diff,
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


def test_rebalance_tick_tracks_difference_below_margin():
    cfg = Config()
    cfg.paper = True
    cfg.margin = 0.05

    class Account:
        tickers = [_ticker("AAPL", 10.0, 100.0, diff=0.02)]
        margin = 0.05
        equity = 0.0
        serverTime = 1_700_000_000
        market = "open"

    account = Account()
    broker = SimBroker(0.0, cfg)
    broker.positions["AAPL"] = 10.0

    rebalance_tick(
        account,
        cfg,
        prices={"AAPL": 100.0},
        broker=broker,
        session="open",
    )

    # Over weight vs base_balance but diff below margin -> stores diff without trading
    assert 0 < account.tickers[0]["difference"] < account.margin


def test_rebalance_tick_hysteresis_fires_sell():
    cfg = Config()
    cfg.paper = True
    cfg.margin = 0.05
    cfg.dry_run = True

    class Account:
        tickers = [
            _ticker("AAPL", 15.8, 100.0, diff=0.12),
            _ticker("MSFT", 8.0, 100.0, diff=0.0),
        ]
        margin = 0.05
        equity = 0.0
        serverTime = 1_700_000_000
        market = "open"

    account = Account()
    broker = SimBroker(600.0, cfg)
    broker.positions["AAPL"] = 15.8
    broker.positions["MSFT"] = 8.0

    rebalance_tick(
        account,
        cfg,
        prices={"AAPL": 100.0, "MSFT": 100.0},
        broker=broker,
        session="open",
    )

    assert broker.positions["AAPL"] < 15.8
