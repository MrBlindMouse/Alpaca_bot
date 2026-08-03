import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from state import Status


def test_bootstrap_creates_state_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "trading_state.json")
        account = Status.bootstrap(0.05, path=path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["tickers"] == []
        assert data["equity"] == 0
        assert data["margin"] == 0.05
        assert data["market"] == "closed"
        assert account.margin == 0.05


def test_check_balances_liquidates_only_orphans():
    account = Status()
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 1.0,
            "difference": 0,
            "price": 100,
            "limitTrade": {"open": False, "id": "", "ts": 0, "side": "", "intent": "", "notional": None},
        }
    ]
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "key"
    config.apiSecret = "secret"
    config.paper = True
    config.dry_run = False

    delete_response = MagicMock()
    delete_response.status_code = 200
    delete_response.json.return_value = {"status": "filled"}

    session = MagicMock()
    session.delete.return_value = delete_response

    positions = [
        {"symbol": "AAPL", "qty": "1"},
        {"symbol": "ORPHAN", "qty": "2"},
    ]

    with patch("state.append_trade"):
        account.check_balances(session, positions, config)

    assert session.delete.call_count == 1
    call_url = session.delete.call_args[0][0]
    assert "ORPHAN" in call_url


def test_check_balances_dry_run_skips_liquidate():
    account = Status()
    account.tickers = []
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "key"
    config.apiSecret = "secret"
    config.paper = True
    config.dry_run = True

    session = MagicMock()
    with patch("state.append_trade") as mock_log:
        account.check_balances(
            session, [{"symbol": "ORPHAN", "qty": "2"}], config
        )

    session.delete.assert_not_called()
    mock_log.assert_called_once()


def test_check_balances_zeros_flat_universe_symbol():
    account = Status()
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 5.0,
            "difference": 0,
            "price": 100,
            "limitTrade": {"open": False, "id": "", "ts": 0, "side": "", "intent": "", "notional": None},
        },
        {
            "ticker": "MSFT",
            "volume": 2.0,
            "difference": 0,
            "price": 200,
            "limitTrade": {"open": False, "id": "", "ts": 0, "side": "", "intent": "", "notional": None},
        },
    ]
    config = MagicMock()
    config.dry_run = False
    config.paper = True

    with patch("state.append_trade"):
        account.check_balances(
            session=MagicMock(),
            positions=[{"symbol": "MSFT", "qty": "2"}],
            config=config,
        )

    by_sym = {t["ticker"]: t for t in account.tickers}
    assert by_sym["AAPL"]["volume"] == 0.0
    assert by_sym["MSFT"]["volume"] == 2.0


@patch("state.find_tickers")
def test_check_ticker_preserves_existing_fields(mock_find):
    account = Status()
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 5.0,
            "difference": 0.02,
            "price": 150.0,
            "limitTrade": {
                "open": True,
                "id": "ord-1",
                "ts": 100,
                "side": "buy",
                "intent": "rebalance_buy",
                "notional": 100.0,
            },
        }
    ]
    mock_find.return_value = ["AAPL", "MSFT"]
    config = MagicMock()
    config.title = "test"

    with patch.object(account, "save_state"):
        account.check_ticker(MagicMock(), config)

    by_sym = {t["ticker"]: t for t in account.tickers}
    assert by_sym["AAPL"]["volume"] == 5.0
    assert by_sym["AAPL"]["price"] == 150.0
    assert by_sym["AAPL"]["difference"] == 0.02
    assert by_sym["AAPL"]["limitTrade"]["id"] == "ord-1"
    assert by_sym["MSFT"]["volume"] == 0
