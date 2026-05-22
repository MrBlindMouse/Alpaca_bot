import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

from ticker_source import (
    SLICKCHARTS_HEADERS,
    _load_ticker_cache,
    _parse_slickcharts_html,
    _save_ticker_cache,
    find_tickers,
)

SAMPLE_HTML = """
<html><body><table><tbody>
<tr><td>1</td><td>Nvidia Corp</td><td>NVDA</td><td>13%</td></tr>
<tr><td>2</td><td>Apple Inc</td><td>AAPL</td><td>10%</td></tr>
</tbody></table></body></html>
"""


def test_parse_slickcharts_html_legacy_and_modern():
    assert _parse_slickcharts_html(SAMPLE_HTML.encode()) == ["NVDA", "AAPL"]


def test_slickcharts_headers_include_accept():
    assert "Accept" in SLICKCHARTS_HEADERS
    assert "Chrome" in SLICKCHARTS_HEADERS["User-Agent"]


@patch("ticker_source.requests.get")
def test_find_tickers_uses_cache_when_composition_unchanged(mock_get):
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = os.path.join(tmp, ".ticker_cache.json")
        now = time.time()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"NVDA": now, "AAPL": now}, f)

        scrape_resp = MagicMock()
        scrape_resp.status_code = 200
        scrape_resp.content = SAMPLE_HTML.encode()
        mock_get.return_value = scrape_resp

        config = MagicMock()
        config.urlBase = "https://paper-api.alpaca."
        config.apiKey = "k"
        config.apiSecret = "s"
        session = MagicMock()

        with patch("ticker_source._TICKER_CACHE_FILE", cache_path):
            with patch("ticker_source._load_ticker_cache", return_value={"NVDA": now, "AAPL": now}):
                result = find_tickers(session, config)

        assert result == ["AAPL", "NVDA"]
        session.get.assert_not_called()
