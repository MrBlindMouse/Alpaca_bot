from datetime import date
from unittest.mock import MagicMock, patch

from runner import BotRunner, DAY_END_HOUR_NY
from market import TICK_SLEEP_CLOSED_MAX_SECONDS, TICK_SLEEP_OPEN_SECONDS


def test_should_run_day_end_after_22_ny():
    runner = BotRunner.__new__(BotRunner)
    ny_late = MagicMock()
    ny_late.hour = DAY_END_HOUR_NY
    ny_late.date.return_value = date(2024, 6, 3)
    with patch("runner.datetime") as mock_dt:
        mock_dt.now.return_value = ny_late
        assert runner._should_run_day_end(None) is True
        assert runner._should_run_day_end(date(2024, 6, 3)) is False


def test_should_not_run_day_end_before_22_ny():
    runner = BotRunner.__new__(BotRunner)
    ny_early = MagicMock()
    ny_early.hour = DAY_END_HOUR_NY - 1
    with patch("runner.datetime") as mock_dt:
        mock_dt.now.return_value = ny_early
        assert runner._should_run_day_end(None) is False


@patch("runner.bot_loop")
@patch("config.dotenv_values")
def test_runner_adaptive_sleep_closed(mock_env, mock_bot_loop):
    mock_env.return_value = {
        "VERSION": "PAPER",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
        "MARGIN": "0.05",
    }
    from config import Config
    from market import ClockSnapshot

    config = Config()
    config.update()
    account = MagicMock()
    account.market = "closed"

    runner = BotRunner(config, account)
    snapshot = ClockSnapshot(
        server_epoch=0,
        is_open=False,
        next_open_epoch=None,
        next_close_epoch=None,
    )
    mock_bot_loop.return_value = (True, snapshot)

    sleeps = []

    def capture_wait(timeout):
        sleeps.append(timeout)
        runner._stop.set()
        return True

    with patch.object(account, "load_state"):
        with patch.object(runner, "_safe_check_balances"):
            with patch.object(runner, "_safe_day_end"):
                with patch.object(runner._stop, "wait", side_effect=capture_wait):
                    runner._scheduler_loop()

    assert sleeps[0] == TICK_SLEEP_CLOSED_MAX_SECONDS


@patch("runner.bot_loop")
@patch("config.dotenv_values")
def test_runner_adaptive_sleep_open(mock_env, mock_bot_loop):
    mock_env.return_value = {
        "VERSION": "PAPER",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
        "MARGIN": "0.05",
    }
    from config import Config
    from market import ClockSnapshot

    config = Config()
    config.update()
    account = MagicMock()
    account.market = "open"

    runner = BotRunner(config, account)
    snapshot = ClockSnapshot(server_epoch=0, is_open=True, next_open_epoch=None, next_close_epoch=None)
    mock_bot_loop.return_value = (True, snapshot)

    sleeps = []

    def capture_wait(timeout):
        sleeps.append(timeout)
        runner._stop.set()
        return True

    with patch.object(account, "load_state"):
        with patch.object(runner, "_safe_check_balances"):
            with patch.object(runner, "_safe_day_end"):
                with patch.object(runner._stop, "wait", side_effect=capture_wait):
                    runner._scheduler_loop()

    assert sleeps[0] == TICK_SLEEP_OPEN_SECONDS
