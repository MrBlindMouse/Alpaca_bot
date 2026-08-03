import json
import os

from backtest.cache import BarCache
from backtest.config import BacktestConfig
from backtest.engine import run_backtest
from backtest.service import summarize_decisions
from backtest.universe import save_symbols


def test_run_backtest_smoke(tmp_path):
    db = tmp_path / "bars.sqlite"
    symbols_file = tmp_path / "symbols.json"
    save_symbols(["AAPL"], str(symbols_file))

    cache = BarCache(str(db))
    cache.upsert_bars(
        [
            ("AAPL", "2025-01-02T14:35:00Z", 100, 101, 99, 100.5, 1000, 100.2),
            ("AAPL", "2025-01-02T14:40:00Z", 100.5, 102, 100, 101.0, 1100, 100.8),
        ]
    )

    bt_cfg = BacktestConfig(
        bar_db=str(db),
        symbols_file=str(symbols_file),
        trades_file=str(tmp_path / "trades.jsonl"),
        equity_file=str(tmp_path / "equity.csv"),
        decisions_file=str(tmp_path / "decisions.jsonl"),
        initial_cash=10_000.0,
    )

    summary = run_backtest(
        bt_cfg,
        start="2025-01-02",
        end="2025-01-02",
        cash=10_000.0,
    )

    assert summary["steps"] == 2
    assert os.path.exists(bt_cfg.equity_file)
    assert os.path.exists(bt_cfg.trades_file)
    assert os.path.exists(bt_cfg.decisions_file)
    assert summary["decisions_file"] == bt_cfg.decisions_file
    assert summary["decision_events"] > 0
    assert summary["tick_summaries"] == 2

    with open(bt_cfg.equity_file, encoding="utf-8") as file:
        lines = file.readlines()
    assert len(lines) == 3  # header + 2 rows

    with open(bt_cfg.decisions_file, encoding="utf-8") as file:
        events = [json.loads(line) for line in file if line.strip()]
    event_types = {row.get("event") for row in events}
    assert "tick_summary" in event_types
    assert "initial_buy_attempt" in event_types
    assert "initial_buy_filled" in event_types

    diag = summarize_decisions(bt_cfg.decisions_file)
    assert diag["events"] == len(events)
    assert diag["tick_summaries"] == 2


def test_run_backtest_carries_forward_missing_bar_price(tmp_path):
    db = tmp_path / "bars.sqlite"
    symbols_file = tmp_path / "symbols.json"
    save_symbols(["AAPL"], str(symbols_file))

    cache = BarCache(str(db))
    # First RTH bar only — second timestamp missing from cache.
    cache.upsert_bars(
        [
            ("AAPL", "2025-01-02T14:35:00Z", 100, 101, 99, 100.5, 1000, 100.0),
        ]
    )
    # Inject a second timestamp row for another symbol so the step exists,
    # then AAPL is missing at that ts and must carry forward.
    cache.upsert_bars(
        [
            ("MSFT", "2025-01-02T14:40:00Z", 200, 201, 199, 200.5, 1000, 200.0),
        ]
    )
    save_symbols(["AAPL", "MSFT"], str(symbols_file))
    cache.upsert_bars(
        [
            ("AAPL", "2025-01-02T14:35:00Z", 100, 101, 99, 100.5, 1000, 100.0),
            ("MSFT", "2025-01-02T14:35:00Z", 200, 201, 199, 200.5, 1000, 200.0),
            ("MSFT", "2025-01-02T14:40:00Z", 200, 201, 199, 200.5, 1000, 200.0),
        ]
    )

    bt_cfg = BacktestConfig(
        bar_db=str(db),
        symbols_file=str(symbols_file),
        trades_file=str(tmp_path / "trades.jsonl"),
        equity_file=str(tmp_path / "equity.csv"),
        decisions_file=str(tmp_path / "decisions.jsonl"),
        initial_cash=10_000.0,
    )

    summary = run_backtest(bt_cfg, start="2025-01-02", end="2025-01-02", cash=10_000.0)
    assert summary["steps"] == 2
    # Equity must not collapse to cash-only from a $0 AAPL mark.
    assert summary["end_equity"] > 1000
