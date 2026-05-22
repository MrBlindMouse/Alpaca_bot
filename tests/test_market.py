import threading
from unittest.mock import MagicMock, patch

from market import MarketTracker, check_time


@patch("market.remote.post_log")
@patch("reporting.check_in")
def test_holiday_sleep_interrupted_by_stop_event(mock_check_in, mock_post):
    account = MagicMock()
    account.market = "closed"
    account.equity = 1000
    account.serverTime = 0
    account.save_state = MagicMock()

    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "k"
    config.apiSecret = "s"
    config.title = "test"

    tracker = MarketTracker()
    tracker.server = "closed"

    clock_resp = MagicMock()
    clock_resp.status_code = 200
    clock_resp.json.return_value = {
        "timestamp": "2024-01-15T10:00:00-05:00",
        "is_open": False,
    }

    cal_resp = MagicMock()
    cal_resp.status_code = 200
    cal_resp.json.return_value = []

    session = MagicMock()
    session.get.side_effect = [clock_resp, cal_resp]

    stop = threading.Event()

    def interrupt_sleep(_):
        stop.set()

    with patch("market.time.sleep", side_effect=interrupt_sleep):
        with patch("market.HOLIDAY_SLEEP_SECONDS", 100):
            check_time(session, account, config, tracker, stop_event=stop)

    assert stop.is_set()
    assert account.market == "holiday"
