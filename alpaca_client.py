import logging

from requests.adapters import HTTPAdapter
from requests_ratelimiter import LimiterSession
from urllib3.util.retry import Retry

logger = logging.getLogger("alpaca_bot.alpaca")


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
    retry_strategy = Retry(total=3, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session


def get_account(session, config):
    url = f"{config.urlBase}markets/v2/account"
    return session.get(url, headers=alpaca_headers(config)).json()


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
    logger.error(
        "Error finding %s: %s",
        "balance" if symbol else "balances",
        f"{response.status_code} {response.reason}",
    )
    return None
