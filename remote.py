import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("alpaca_bot.remote")

TIMEOUT_SECONDS = 10


def _post(config, path: str, payload: dict, headers: Optional[dict] = None) -> bool:
    if not config.remote_logging_enabled:
        return False
    url = f"{config.remote_base_url}{path}"
    try:
        result = requests.post(
            url, json=payload, headers=headers or {"accept": "application/json"}, timeout=TIMEOUT_SECONDS
        )
        if result.status_code != 200:
            logger.warning(
                "Remote POST %s failed: status=%s body=%s",
                path,
                result.status_code,
                result.text[:500],
            )
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("Remote POST %s failed: %s", path, exc)
        return False


def post_log(config, snippet: str, app_title: str, code: str = "2") -> bool:
    return _post(config, "/log", {"code": code, "app": app_title, "snippet": snippet})


def post_record(config, payload: Dict[str, Any]) -> bool:
    return _post(config, "/record", payload)


def post_checkin(config, payload: Dict[str, Any]) -> bool:
    return _post(config, "/bot", payload)


def post_dashboard(config, payload: Dict[str, Any]) -> bool:
    return _post(config, "/general", payload)
