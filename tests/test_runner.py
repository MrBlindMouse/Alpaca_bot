import time
from unittest.mock import patch

import schedule

from config import Config
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

    with patch.object(account, "load_state"):
        runner = BotRunner(config, account)
        runner.start()
        assert runner.running
        time.sleep(0.3)
        runner.stop()
        assert not runner.running

    schedule.clear()
