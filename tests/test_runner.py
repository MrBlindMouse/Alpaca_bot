import time
from unittest.mock import patch

from config import Config
from market import ClockSnapshot
from runner import BotRunner
from state import Status


@patch("runner.bot_loop")
@patch("config.dotenv_values")
def test_runner_start_stop(mock_env, mock_bot_loop):
    mock_env.return_value = {
        "VERSION": "PAPER",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
        "MARGIN": "0.05",
    }
    config = Config()
    config.update()
    account = Status()
    mock_bot_loop.return_value = (
        True,
        ClockSnapshot(server_epoch=0, is_open=False, next_open_epoch=None, next_close_epoch=None),
    )

    with patch.object(account, "load_state"):
        runner = BotRunner(config, account)
        runner.start()
        assert runner.running
        time.sleep(0.3)
        runner.stop()
        assert not runner.running
