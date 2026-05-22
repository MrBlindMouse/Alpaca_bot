import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup

from alpaca_client import alpaca_headers

logger = logging.getLogger("alpaca_bot.ticker_source")

# Cache of last known valid tickers and their timestamp (seconds)
_TICKER_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".ticker_cache.json")
_TICKER_CACHE_TTL = 3600  # 1 hour — NASDAQ100 composition rarely changes

SLICKCHARTS_URL = "https://www.slickcharts.com/nasdaq100"
# Minimal User-Agent gets 403; use a normal browser profile.
SLICKCHARTS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.slickcharts.com/",
}


def _symbols_from_rows(rows) -> list:
    symbols = []
    for line in rows:
        cells = line.find_all("td")
        if len(cells) > 2:
            symbol = cells[2].get_text(strip=True)
            if symbol.isalpha() and 1 <= len(symbol) <= 5:
                symbols.append(symbol)
    return symbols


def _parse_slickcharts_html(html: bytes) -> list:
    """Extract ticker symbols from SlickCharts NASDAQ-100 HTML."""
    parsed = BeautifulSoup(html, "html.parser")
    table_body = parsed.find("tbody", id="companyListComponent")
    if table_body is not None:
        return _symbols_from_rows(table_body.find_all("tr"))

    best: list = []
    for tbody in parsed.find_all("tbody"):
        symbols = _symbols_from_rows(tbody.find_all("tr"))
        if len(symbols) > len(best):
            best = symbols
    return best if len(best) >= 50 else best


def _load_ticker_cache() -> Dict[str, float]:
    """Load cached {ticker: timestamp} from disk. Returns {} on miss."""
    try:
        with open(_TICKER_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and all(isinstance(v, (int, float)) for v in data.values()):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def _save_ticker_cache(cache: Dict[str, float]) -> None:
    """Persist {ticker: timestamp} to disk."""
    try:
        with open(_TICKER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError as exc:
        logger.warning("Failed to save ticker cache: %s", exc)


def get_cached_valid_tickers() -> list:
    """Return sorted valid tickers from disk cache, or empty list."""
    cache = _load_ticker_cache()
    now = time.time()
    valid = [t for t, ts in cache.items() if (now - ts) < _TICKER_CACHE_TTL]
    return sorted(valid)


def _asset_passes(info: dict) -> bool:
    attrs = info.get("attributes") or []
    return (
        info.get("tradable")
        and info.get("fractionable")
        and info.get("status") == "active"
        and "ptp_no_exception" not in attrs
        and "ptp_with_exception" not in attrs
    )


def _validate_via_batch(session, config, scraped: list) -> list:
    """Validate scraped symbols via one assets list request."""
    url = (
        f"{config.urlBase}markets/v2/assets"
        "?status=active&asset_class=us_equity"
    )
    try:
        result = session.get(url, headers=alpaca_headers(config), timeout=30)
    except requests.RequestException as exc:
        logger.warning("Batch asset fetch failed: %s", exc)
        return []

    if str(result.status_code) != "200":
        logger.warning("Batch asset fetch HTTP %s", result.status_code)
        return []

    wanted = set(scraped)
    valid = []
    for info in result.json():
        symbol = info.get("symbol")
        if symbol in wanted and _asset_passes(info):
            valid.append(symbol)
    return valid


def _check_single_asset(session, config, ticker: str) -> bool:
    """Return True if a single ticker passes Alpaca asset checks."""
    try:
        asset_url = f"{config.urlBase}markets/v2/assets/{ticker}"
        asset_result = session.get(
            asset_url, headers=alpaca_headers(config), timeout=10
        )
        if str(asset_result.status_code) != "200":
            logger.warning("Alpaca API error for %s: %s", ticker, asset_result.reason)
            return False
        return _asset_passes(asset_result.json())
    except requests.RequestException as exc:
        logger.warning("Asset check failed for %s: %s", ticker, exc)
        return False


def find_tickers(session, config):
    """Fetch valid NASDAQ-100 tickers with parallel asset checks and caching."""
    url = SLICKCHARTS_URL
    try:
        result = requests.get(url, headers=SLICKCHARTS_HEADERS, timeout=30)
    except requests.RequestException as exc:
        logger.error("SlickCharts request failed: %s", exc)
        return None

    if str(result.status_code) != "200":
        logger.error(
            "SlickCharts scrape failed: HTTP %s %s",
            result.status_code,
            result.reason,
        )
        return None

    scraped = _parse_slickcharts_html(result.content)
    if not scraped:
        logger.error("SlickCharts page had no recognizable NASDAQ-100 table")
        return None

    # Check cache first — skip API calls if composition hasn't changed
    cache = _load_ticker_cache()
    now = time.time()
    cached_valid = {t for t, ts in cache.items() if (now - ts) < _TICKER_CACHE_TTL}

    if cached_valid and set(scraped) == cached_valid:
        logger.debug("Ticker list unchanged, using cache (%d tickers)", len(cached_valid))
        return sorted(cached_valid)

    valid = _validate_via_batch(session, config, scraped)
    if valid:
        logger.info("Validated %d tickers via batch assets API", len(valid))
    else:
        logger.info(
            "Batch validation unavailable; validating %d tickers in parallel",
            len(scraped),
        )
        valid = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {
                executor.submit(_check_single_asset, session, config, t): t
                for t in scraped
            }
            for future in as_completed(futures):
                ticker = futures[future]
                if future.result():
                    valid.append(ticker)
                    logger.debug("%s accepted", ticker)
                else:
                    logger.info("Asset profile for %s not favorable", ticker)

    # Update cache
    new_cache = {t: now for t in valid}
    _save_ticker_cache(new_cache)

    if not valid:
        logger.error("No valid tickers after Alpaca validation")
        return None

    logger.info("Ticker list updated: %d valid tickers", len(valid))
    return sorted(valid)
