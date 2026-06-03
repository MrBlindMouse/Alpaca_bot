from backtest.cache import BarCache, bar_price


def test_bar_price_prefers_vwap():
    assert bar_price(10.5, 10.0) == 10.5
    assert bar_price(None, 10.0) == 10.0


def test_cache_upsert_and_prices_at(tmp_path):
    db = tmp_path / "bars.sqlite"
    cache = BarCache(str(db))
    cache.upsert_bars(
        [
            ("AAPL", "2025-01-02T14:35:00Z", 1, 2, 0.5, 1.5, 100, 1.4),
            ("MSFT", "2025-01-02T14:35:00Z", 2, 3, 1.5, 2.5, 200, 2.4),
        ]
    )
    prices = cache.prices_at("2025-01-02T14:35:00Z", ["AAPL", "MSFT"])
    assert prices["AAPL"] == 1.4
    assert prices["MSFT"] == 2.4


def test_fetch_log_skip(tmp_path):
    db = tmp_path / "bars.sqlite"
    cache = BarCache(str(db))
    cache.mark_fetched(
        "AAPL", "2025-01-01T00:00:00Z", "2025-01-31T23:59:59Z", 10, timeframe="5Min"
    )
    assert cache.is_fetched(
        "AAPL", "2025-01-01T00:00:00Z", "2025-01-31T23:59:59Z", timeframe="5Min"
    )
    assert not cache.is_fetched(
        "MSFT", "2025-01-01T00:00:00Z", "2025-01-31T23:59:59Z", timeframe="5Min"
    )


def test_list_timestamps(tmp_path):
    db = tmp_path / "bars.sqlite"
    cache = BarCache(str(db))
    cache.upsert_bars(
        [
            ("AAPL", "2025-01-02T14:35:00Z", 1, 2, 0.5, 1.5, 100, 1.4),
            ("AAPL", "2025-01-02T14:40:00Z", 1, 2, 0.5, 1.6, 100, 1.5),
        ]
    )
    ts = cache.list_timestamps("2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
    assert ts == ["2025-01-02T14:35:00Z", "2025-01-02T14:40:00Z"]
