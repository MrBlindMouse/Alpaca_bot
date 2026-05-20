import logging

from requests.adapters import HTTPAdapter
from requests_ratelimiter import LimiterSession
from urllib3.util.retry import Retry

logger = logging.getLogger("alpaca_bot.alpaca")


def create_session() -> LimiterSession:
    session = LimiterSession(per_minute=200, burst=10)
    retry_strategy = Retry(total=3, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session


def get_account(session, config):
    url = f"{config.urlBase}markets/v2/account"
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret,
    }
    return session.get(url, headers=headers).json()


def get_balances(session, config, symbol=None):
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": config.apiKey,
        "APCA-API-SECRET-KEY": config.apiSecret,
    }
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
