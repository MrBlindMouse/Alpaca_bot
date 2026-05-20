import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("alpaca_bot.ticker_source")

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


def find_tickers(session, config):
    url = SLICKCHARTS_URL
    try:
        result = requests.get(url, headers=SLICKCHARTS_HEADERS, timeout=30)
    except requests.RequestException as exc:
        logger.error("SlickCharts request failed: %s", exc)
        return None
    tickers = []
    invalid_tickers = set()
    if str(result.status_code) == "200":
        tickers = _parse_slickcharts_html(result.content)
        if not tickers:
            logger.error("SlickCharts page had no recognizable NASDAQ-100 table")
            return None
        for ticker in tickers[:]:
            asset_url = f"{config.urlBase}markets/v2/assets/{ticker}"
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": config.apiKey,
                "APCA-API-SECRET-KEY": config.apiSecret,
            }
            asset_result = session.get(asset_url, headers=headers)
            if str(asset_result.status_code) == "200":
                json_result = asset_result.json()
                if (
                    json_result["tradable"]
                    and json_result["fractionable"]
                    and json_result["status"] == "active"
                    and "ptp_no_exception" not in json_result["attributes"]
                    and "ptp_with_exception" not in json_result["attributes"]
                ):
                    logger.debug("%s accepted", ticker)
                else:
                    invalid_tickers.add(ticker)
                    logger.info("Asset profile for %s not favorable", ticker)
            else:
                invalid_tickers.add(ticker)
                logger.warning("Alpaca API error for %s: %s", ticker, asset_result.reason)
        return [t for t in tickers if t not in invalid_tickers]
    logger.error(
        "SlickCharts scrape failed: HTTP %s %s",
        result.status_code,
        result.reason,
    )
    return None
