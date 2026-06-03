from backtest.broker import SimBroker
from backtest.engine import build_backtest_account
from config import Config
from rebalance import rebalance_tick


def _config():
    cfg = Config()
    cfg.paper = True
    cfg.margin = 0.05
    return cfg


def test_rebalance_tick_initial_buy(tmp_path):
    import os

    trades = tmp_path / "trades.jsonl"
    cfg = _config()
    broker = SimBroker(50_000.0, cfg, trades_path=str(trades))
    account = build_backtest_account(["AAPL"], margin=0.05, initial_cash=50_000.0)
    prices = {"AAPL": 100.0}

    rebalance_tick(account, cfg, prices=prices, broker=broker, session="open")

    assert broker.get_qty("AAPL") > 0
    assert os.path.exists(trades)


def test_rebalance_tick_skips_when_closed():
    cfg = _config()
    broker = SimBroker(10_000.0, cfg, trades_path="/tmp/unused_trades.jsonl")
    account = build_backtest_account(["AAPL"], margin=0.05, initial_cash=10_000.0)

    rebalance_tick(account, cfg, prices={"AAPL": 100.0}, broker=broker, session="closed")

    assert broker.get_qty("AAPL") == 0
