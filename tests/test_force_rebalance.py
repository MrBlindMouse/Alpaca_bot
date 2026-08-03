"""force_rebalance_symbol: RTH one-shot past hysteresis."""

from backtest.broker import SimBroker
from config import Config
from rebalance import force_rebalance_symbol


def _ticker(sym: str, volume: float, price: float, diff: float = 0.12):
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


def _account(tickers, *, margin=0.05):
    class Account:
        pass

    account = Account()
    account.tickers = tickers
    account.margin = margin
    account.equity = 0.0
    account.serverTime = 1_700_000_000
    account.market = "open"
    return account


def _config():
    cfg = Config()
    cfg.paper = True
    cfg.margin = 0.05
    cfg.dry_run = True
    return cfg


def test_force_sells_overweight_past_hysteresis(tmp_path):
    cfg = _config()
    # base_balance = equity / (2 + 2*0.05/2) = equity / 2.05
    # AAPL 15.8 @ 100, MSFT 8 @ 100 → equity = cash + 2380
    # With cash 0: equity=2380, target≈1160.98; AAPL current=1580 → sell
    account = _account(
        [
            _ticker("AAPL", 15.8, 100.0, diff=0.12),
            _ticker("MSFT", 8.0, 100.0, diff=0.0),
        ]
    )
    broker = SimBroker(0.0, cfg, trades_path=str(tmp_path / "trades.jsonl"))
    broker.positions["AAPL"] = 15.8
    broker.positions["MSFT"] = 8.0
    prices = {"AAPL": 100.0, "MSFT": 100.0}

    ok, message = force_rebalance_symbol(
        account,
        cfg,
        symbol="aapl",
        prices=prices,
        broker=broker,
        session="open",
    )

    assert ok, message
    assert "sell" in message.lower()
    assert account.tickers[0]["difference"] == 0.0
    assert broker.get_qty("AAPL") < 15.8


def test_force_refuses_closed_session():
    cfg = _config()
    account = _account([_ticker("AAPL", 10.0, 100.0)])
    broker = SimBroker(0.0, cfg, trades_path="/tmp/unused_force_trades.jsonl")
    broker.positions["AAPL"] = 10.0

    ok, message = force_rebalance_symbol(
        account,
        cfg,
        symbol="AAPL",
        prices={"AAPL": 100.0},
        broker=broker,
        session="closed",
    )

    assert not ok
    assert "RTH" in message or "not open" in message.lower()
    assert broker.get_qty("AAPL") == 10.0


def test_force_refuses_extended_session():
    cfg = _config()
    account = _account([_ticker("AAPL", 10.0, 100.0)])
    broker = SimBroker(0.0, cfg, trades_path="/tmp/unused_force_trades.jsonl")
    broker.positions["AAPL"] = 10.0

    ok, message = force_rebalance_symbol(
        account,
        cfg,
        symbol="AAPL",
        prices={"AAPL": 100.0},
        broker=broker,
        session="extended",
    )

    assert not ok
    assert broker.get_qty("AAPL") == 10.0
