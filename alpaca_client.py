import logging
from typing import Any, Dict, Iterator, List, Optional

from requests.adapters import HTTPAdapter
from requests_ratelimiter import LimiterSession
from urllib3.util.retry import Retry

logger = logging.getLogger("alpaca_bot.alpaca")


class AlpacaAPIError(Exception):
    """Alpaca trading API returned a non-success response."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def alpaca_headers(config, *, json_content: bool = False) -> dict:
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret,
    }
    if json_content:
        headers["content-type"] = "application/json"
    return headers


def create_session() -> LimiterSession:
    session = LimiterSession(per_minute=200, burst=10)
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session


def create_data_session(per_minute: int = 150, burst: int = 5) -> LimiterSession:
    """Rate-limited session for data.alpaca.markets (backtest bar fetch)."""
    session = LimiterSession(per_minute=per_minute, burst=burst)
    retry_strategy = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session


def fetch_stock_bars_pages(
    session,
    config,
    symbol: str,
    *,
    start: str,
    end: str,
    timeframe: str = "5Min",
    feed: str = "iex",
    adjustment: str = "all",
    limit: int = 10000,
) -> Iterator[List[Dict[str, Any]]]:
    """
    Yield pages of raw bar dicts from Alpaca historical bars API.
    Each page is the 'bars' array from one response.
    """
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params: Dict[str, Any] = {
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "limit": limit,
        "adjustment": adjustment,
        "feed": feed,
        "sort": "asc",
    }
    page_token: Optional[str] = None
    while True:
        req_params = dict(params)
        if page_token:
            req_params["page_token"] = page_token
        response = session.get(url, headers=alpaca_headers(config), params=req_params)
        if response.status_code != 200:
            raise RuntimeError(
                f"Alpaca bars {symbol}: {response.status_code} {response.text[:300]}"
            )
        payload = response.json()
        bars = payload.get("bars") or []
        if bars:
            yield bars
        page_token = payload.get("next_page_token")
        if not page_token:
            break


def get_account(session, config):
    url = f"{config.urlBase}markets/v2/account"
    response = session.get(url, headers=alpaca_headers(config))
    if response.status_code != 200:
        raise AlpacaAPIError(
            f"account request failed: {response.status_code} {response.reason}",
            status_code=response.status_code,
        )
    return response.json()


def get_snapshot_vwap(session, config, symbol: str):
    """Latest minute VWAP from Alpaca data API, or None if unavailable."""
    url = (
        "https://data.alpaca.markets/v2/stocks/snapshots"
        f"?symbols={symbol}&feed=iex"
    )
    response = session.get(url, headers=alpaca_headers(config))
    if response.status_code != 200:
        return None
    data = response.json()
    bar = data.get(symbol, {}).get("minuteBar")
    if not bar:
        return None
    vw = bar.get("vw")
    return float(vw) if vw is not None else None


def get_balances(session, config, symbol=None):
    headers = alpaca_headers(config)
    url = f"{config.urlBase}markets/v2/positions{f'/{symbol}' if symbol else ''}"
    response = session.get(url, headers=headers)
    if response.status_code == 200:
        json_response = response.json()
        return float(json_response["qty"]) if symbol else json_response
    if symbol and response.status_code == 404:
        return 0.0
    logger.error(
        "Error finding %s: %s",
        "balance" if symbol else "balances",
        f"{response.status_code} {response.reason}",
    )
    return None
