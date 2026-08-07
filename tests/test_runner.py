import time
from unittest.mock import MagicMock, patch

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


@patch("runner.append_trade")
@patch("runner.get_balances")
def test_runner_write_off_quarantines(mock_balances, mock_append):
    config = MagicMock()
    config.paper = True
    account = Status()
    account.tickers = [{"ticker": "AAPL", "volume": 1}]
    account.market = "open"
    mock_balances.return_value = [
        {"symbol": "EA", "qty": "5", "market_value": "900"}
    ]
    runner = BotRunner(config, account)

    with patch.object(account, "save_state"):
        ok, msg = runner.write_off("EA")

    assert ok
    assert account.is_quarantined("EA")
    assert "Wrote off EA" in msg
    mock_append.assert_called_once()
    record = mock_append.call_args[0][0]
    assert record["intent"] == "write_off"
    assert record["symbol"] == "EA"


@patch("runner.get_balances")
def test_runner_write_off_rejects_universe_symbol(mock_balances):
    config = MagicMock()
    account = Status()
    account.tickers = [{"ticker": "EA", "volume": 1}]
    runner = BotRunner(config, account)
    ok, msg = runner.write_off("EA")
    assert not ok
    assert "universe" in msg
    mock_balances.assert_not_called()
