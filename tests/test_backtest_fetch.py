from unittest.mock import MagicMock, patch

from backtest.cache import BarCache
from backtest.config import BacktestConfig
from backtest.fetch import fetch_symbol


def test_fetch_symbol_paginates(tmp_path):
    db = tmp_path / "bars.sqlite"
    cache = BarCache(str(db))
    bt_cfg = BacktestConfig(bar_db=str(db))

    pages = [
        [{"t": "2025-01-02T14:35:00Z", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 10, "vw": 1.4}],
        [{"t": "2025-01-02T14:40:00Z", "o": 1.5, "h": 2, "l": 1.4, "c": 1.6, "v": 12, "vw": 1.55}],
    ]

    config = MagicMock()
    session = MagicMock()

    with patch("backtest.fetch.fetch_stock_bars_pages", return_value=iter(pages)):
        count = fetch_symbol(
            session,
            config,
            cache,
            "AAPL",
            "2025-01-01T00:00:00Z",
            "2025-01-31T23:59:59Z",
            bt_cfg,
        )

    assert count == 2
    assert cache.is_fetched(
        "AAPL",
        "2025-01-01T00:00:00Z",
        "2025-01-31T23:59:59Z",
        timeframe=bt_cfg.timeframe,
    )
    prices = cache.prices_at("2025-01-02T14:40:00Z", ["AAPL"])
    assert prices["AAPL"] == 1.55
