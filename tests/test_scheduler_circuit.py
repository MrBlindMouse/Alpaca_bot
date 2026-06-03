from unittest.mock import MagicMock, patch

from scheduler import bot_loop


@patch("scheduler.bot")
@patch("scheduler.maintain_open_limits")
@patch("scheduler.check_time")
def test_circuit_paused_still_maintains_limits(mock_check_time, mock_maintain, mock_bot):
    mock_check_time.return_value = (True, None)

    session = MagicMock()
    account = MagicMock()
    account.market = "open"
    account.tickers = []
    config = MagicMock()
    config.title = "Alpaca Test"

    circuit = MagicMock()
    circuit.is_paused.return_value = True

    bot_loop(session, account, config, MagicMock(), circuit=circuit)

    mock_maintain.assert_called_once()
    mock_bot.assert_not_called()
