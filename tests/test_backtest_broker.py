import os
import tempfile

from backtest.broker import SimBroker
from config import Config


def _config():
    cfg = Config()
    cfg.paper = True
    return cfg


def test_sim_broker_buy_and_sell():
    with tempfile.TemporaryDirectory() as tmp:
        trades = os.path.join(tmp, "trades.jsonl")
        broker = SimBroker(10_000.0, _config(), trades_path=trades)
        buy = broker.place_market_notional(
            "AAPL",
            "buy",
            1000.0,
            100.0,
            intent="rebalance_buy",
            market_session="open",
        )
        assert buy.is_filled
        assert broker.get_qty("AAPL") == 10.0
        assert broker.cash == 9000.0

        sell = broker.place_market_notional(
            "AAPL",
            "sell",
            500.0,
            100.0,
            intent="rebalance_sell",
            market_session="open",
        )
        assert sell.is_filled
        assert broker.get_qty("AAPL") == 5.0
        assert broker.cash == 9500.0

        equity = broker.get_equity({"AAPL": 100.0})
        assert equity == 10_000.0


def test_sim_broker_caps_buy_to_available_cash():
    with tempfile.TemporaryDirectory() as tmp:
        trades = os.path.join(tmp, "trades.jsonl")
        broker = SimBroker(100.0, _config(), trades_path=trades)
        buy = broker.place_market_notional(
            "AAPL",
            "buy",
            500.0,
            50.0,
            intent="rebalance_buy",
            market_session="open",
        )
        assert buy.is_filled
        assert broker.cash == 0.0
        assert broker.get_qty("AAPL") > 0
