from backtest.config import BacktestConfig
from backtest.cache import BarCache
from backtest.service import (
    cache_status_dict,
    list_cached_datasets,
    parse_margins,
    summarize_decisions,
)


def test_parse_margins():
    assert parse_margins("0.03, 0.05, 0.1", default=0.02) == [0.03, 0.05, 0.1]


def test_cache_status_dict(tmp_path):
    db = tmp_path / "bars.sqlite"
    cfg = BacktestConfig(bar_db=str(db))
    st = cache_status_dict(cfg)
    assert st["db"] == str(db)
    assert st["bar_count"] == 0


def test_summarize_decisions(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"event":"rebalance_order_skipped","reason":"below_margin"}',
                '{"event":"tick_summary","attempts":3,"fills":2,"failures":1,"skipped":{"below_margin":4}}',
                '{"event":"tick_summary","attempts":1,"fills":1,"failures":0,"skipped":{"tracking_peak_diff":2}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = summarize_decisions(str(path))
    assert summary["events"] == 3
    assert summary["tick_summaries"] == 2
    assert summary["attempts"] == 4
    assert summary["fills"] == 3
    assert summary["failures"] == 1
    assert summary["skipped"]["below_margin"] == 4
    assert summary["skipped"]["tracking_peak_diff"] == 2


def test_list_cached_datasets(tmp_path):
    db = tmp_path / "bars.sqlite"
    cache = BarCache(str(db))
    cache.mark_fetched(
        "AAPL",
        "2025-01-01T00:00:00Z",
        "2025-01-31T23:59:59Z",
        100,
        timeframe="5Min",
    )
    cache.mark_fetched(
        "MSFT",
        "2025-01-01T00:00:00Z",
        "2025-01-31T23:59:59Z",
        95,
        timeframe="5Min",
    )
    cfg = BacktestConfig(bar_db=str(db))
    rows = list_cached_datasets(cfg)
    assert len(rows) == 1
    assert rows[0]["start"] == "2025-01-01T00:00:00Z"
    assert rows[0]["end"] == "2025-01-31T23:59:59Z"
    assert rows[0]["timeframe"] == "5Min"
    assert "2025-01-01T00:00:00Z - 2025-01-31T23:59:59Z - 5Min" == rows[0]["label"]
