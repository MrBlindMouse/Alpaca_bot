from unittest.mock import patch

from backtest.compare import run_comparisons
from backtest.config import BacktestConfig
from backtest.universe import save_symbols


def test_run_comparisons_row_count(tmp_path):
    db = tmp_path / "bars.sqlite"
    symbols_file = tmp_path / "symbols.json"
    save_symbols(["A"], str(symbols_file))

    from backtest.cache import BarCache

    cache = BarCache(str(db))
    cache.upsert_bars(
        [
            ("A", "2025-01-02T14:35:00Z", 100, 101, 99, 100, 1000, 100.0),
            ("A", "2025-01-02T14:40:00Z", 100, 102, 99, 101, 1100, 101.0),
        ]
    )

    bt_cfg = BacktestConfig(
        bar_db=str(db),
        symbols_file=str(symbols_file),
        weights_file=str(tmp_path / "weights.json"),
        comparison_file=str(tmp_path / "compare.csv"),
        equity_file=str(tmp_path / "equity.csv"),
        trades_file=str(tmp_path / "trades.jsonl"),
    )

    with patch("backtest.compare.run_backtest") as mock_bt:
        mock_bt.return_value = {
            "start_equity": 1000.0,
            "end_equity": 1010.0,
            "total_return_pct": 1.0,
            "max_drawdown_pct": -0.5,
            "trade_count": 3,
            "steps": 2,
        }
        results = run_comparisons(
            bt_cfg,
            start="2025-01-02",
            end="2025-01-02",
            cash=1000.0,
            margins=[0.03, 0.05],
        )

    assert len(results) == 4
    strategies = [r.strategy for r in results]
    assert strategies.count("Rebalancer") == 2
