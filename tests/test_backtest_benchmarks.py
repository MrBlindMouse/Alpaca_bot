from backtest.benchmarks import run_buy_and_hold
from backtest.cache import BarCache


def test_equal_and_cap_buy_hold_same_when_equal_weights(tmp_path):
    db = tmp_path / "bars.sqlite"
    cache = BarCache(str(db))
    rows = [
        ("A", "2025-01-02T14:35:00Z", 10, 11, 9, 10, 100, 10.0),
        ("B", "2025-01-02T14:35:00Z", 20, 21, 19, 20, 100, 20.0),
        ("A", "2025-01-02T14:40:00Z", 10, 12, 9, 11, 110, 11.0),
        ("B", "2025-01-02T14:40:00Z", 20, 22, 19, 21, 110, 21.0),
    ]
    cache.upsert_bars(rows)
    ts = ["2025-01-02T14:35:00Z", "2025-01-02T14:40:00Z"]
    ew = run_buy_and_hold(cache, ["A", "B"], ts, 1000.0, weights=None)
    cap = run_buy_and_hold(
        cache,
        ["A", "B"],
        ts,
        1000.0,
        weights={"A": 0.5, "B": 0.5},
    )
    assert ew["end_equity"] == cap["end_equity"]
    assert ew["trade_count"] == 2
