from unittest.mock import MagicMock, patch

from market import (
    ClockSnapshot,
    MarketTracker,
    check_time,
    compute_tick_sleep_seconds,
    parse_alpaca_timestamp,
    parse_clock_response,
)


def test_parse_alpaca_timestamp_offset():
    dt = parse_alpaca_timestamp("2024-01-15T10:00:00-05:00")
    assert dt.hour == 10
    assert dt.utcoffset().total_seconds() == -5 * 3600


def test_parse_alpaca_timestamp_zulu():
    dt = parse_alpaca_timestamp("2024-01-15T15:00:00Z")
    assert dt.tzinfo is not None


def test_parse_alpaca_timestamp_fractional():
    dt = parse_alpaca_timestamp("2022-04-28T14:07:45.485843765-04:00")
    assert dt.year == 2022


def test_parse_clock_response():
    snap = parse_clock_response(
        {
            "timestamp": "2024-06-03T10:00:00-04:00",
            "is_open": True,
            "next_open": "2024-06-04T09:30:00-04:00",
            "next_close": "2024-06-03T16:00:00-04:00",
        }
    )
    assert snap.is_open is True
    assert snap.next_open_epoch is not None
    assert snap.next_close_epoch is not None


def test_compute_tick_sleep_open():
    snap = ClockSnapshot(server_epoch=0, is_open=True, next_open_epoch=None, next_close_epoch=None)
    assert compute_tick_sleep_seconds(snap, "open", True) == 60


def test_compute_tick_sleep_clock_fail():
    assert compute_tick_sleep_seconds(None, "closed", False) == 300


def test_compute_tick_sleep_closed_until_open():
    future = int(__import__("time").time()) + 600
    snap = ClockSnapshot(server_epoch=0, is_open=False, next_open_epoch=future, next_close_epoch=None)
    assert compute_tick_sleep_seconds(snap, "closed", True) == 600


def test_empty_calendar_stays_closed_no_sleep():
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
        "next_open": "2024-01-16T09:30:00-05:00",
        "next_close": "2024-01-15T16:00:00-05:00",
    }

    cal_resp = MagicMock()
    cal_resp.status_code = 200
    cal_resp.json.return_value = []

    session = MagicMock()
    session.get.side_effect = [clock_resp, cal_resp]

    with patch("market.time.sleep") as mock_sleep:
        ok, snapshot = check_time(session, account, config, tracker)

    assert ok is True
    assert snapshot is not None
    assert account.market == "closed"
    mock_sleep.assert_not_called()


def test_clock_failure_clears_server_time():
    account = MagicMock()
    account.serverTime = 999
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.title = "test"

    session = MagicMock()
    session.get.return_value = MagicMock(status_code=500, reason="err", text="fail")

    ok, snapshot = check_time(session, account, config, MarketTracker())
    assert ok is False
    assert snapshot is None
    assert account.serverTime == 0
