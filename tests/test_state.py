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
        assert data["cash"] == 0
        assert data["margin"] == 0.05
        assert data["market"] == "closed"
        assert data.get("quarantined") == []
        assert account.margin == 0.05


def test_save_load_round_trip_cash(tmp_path, monkeypatch):
    path = tmp_path / "trading_state.json"
    monkeypatch.setattr(Status, "STATE_FILE", str(path))
    account = Status()
    account.equity = 12_345.0
    account.cash = 678.9
    account.margin = 0.05
    account.save_state()
    loaded = Status()
    loaded.load_state()
    assert loaded.equity == 12_345.0
    assert loaded.cash == 678.9


def test_tradable_equity_subtracts_quarantined_mv():
    account = Status()
    account.quarantine("EA", reason="test", market_value=1000.0)
    assert account.tradable_equity(50_000.0) == 49_000.0
    assert account.tradable_equity(500.0) == 0.0


def test_check_balances_liquidates_only_orphans():
    account = Status()
    account.tickers = [
        {
            "ticker": "AAPL",
            "volume": 1.0,
            "difference": 0,
            "price": 100,
            "limitTrade": {
                "open": False,
                "id": "",
                "ts": 0,
                "side": "",
                "intent": "",
                "notional": None,
            },
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

    with (
        patch("state.append_trade"),
        patch("state.get_cached_valid_tickers", return_value=[]),
        patch.object(account, "save_state"),
    ):
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
    with (
        patch("state.append_trade") as mock_log,
        patch("state.get_cached_valid_tickers", return_value=[]),
        patch.object(account, "save_state"),
    ):
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
            "limitTrade": {
                "open": False,
                "id": "",
                "ts": 0,
                "side": "",
                "intent": "",
                "notional": None,
            },
        },
        {
            "ticker": "MSFT",
            "volume": 2.0,
            "difference": 0,
            "price": 200,
            "limitTrade": {
                "open": False,
                "id": "",
                "ts": 0,
                "side": "",
                "intent": "",
                "notional": None,
            },
        },
    ]
    config = MagicMock()
    config.dry_run = False
    config.paper = True

    with (
        patch("state.append_trade"),
        patch("state.get_cached_valid_tickers", return_value=[]),
        patch.object(account, "save_state"),
    ):
        account.check_balances(
            session=MagicMock(),
            positions=[{"symbol": "MSFT", "qty": "2"}],
            config=config,
        )

    by_sym = {t["ticker"]: t for t in account.tickers}
    assert by_sym["AAPL"]["volume"] == 0.0
    assert by_sym["MSFT"]["volume"] == 2.0


def test_check_balances_quarantines_untradable_orphan():
    account = Status()
    account.tickers = []
    config = MagicMock()
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "key"
    config.apiSecret = "secret"
    config.paper = True
    config.dry_run = False

    delete_response = MagicMock()
    delete_response.status_code = 422
    delete_response.reason = "Unprocessable Entity"

    session = MagicMock()
    session.delete.return_value = delete_response

    positions = [{"symbol": "EA", "qty": "5", "market_value": "1100"}]

    with (
        patch("state.append_trade"),
        patch("state.get_cached_valid_tickers", return_value=[]),
        patch("state.is_permanently_untradable", return_value=True),
        patch.object(account, "save_state"),
    ):
        account.check_balances(session, positions, config)
        account.check_balances(session, positions, config)

    assert session.delete.call_count == 1
    assert account.is_quarantined("EA")
    assert account.quarantined[0]["market_value"] == 1100.0


def test_check_balances_clears_quarantine_when_flat():
    account = Status()
    account.tickers = []
    account.quarantine("EA", reason="prior", market_value=100.0)
    config = MagicMock()
    config.dry_run = False
    config.paper = True

    with (
        patch("state.append_trade"),
        patch("state.get_cached_valid_tickers", return_value=[]),
        patch.object(account, "save_state"),
    ):
        account.check_balances(session=MagicMock(), positions=[], config=config)

    assert not account.is_quarantined("EA")


def test_check_balances_refreshes_stale_universe():
    account = Status()
    account.tickers = [
        {
            "ticker": "EA",
            "volume": 1.0,
            "difference": 0,
            "price": 100,
            "limitTrade": {
                "open": False,
                "id": "",
                "ts": 0,
                "side": "",
                "intent": "",
                "notional": None,
            },
        }
    ]
    config = MagicMock()
    config.dry_run = False
    config.paper = True
    config.urlBase = "https://paper-api.alpaca."
    config.apiKey = "key"
    config.apiSecret = "secret"

    delete_response = MagicMock()
    delete_response.status_code = 200

    session = MagicMock()
    session.delete.return_value = delete_response

    with (
        patch("state.append_trade"),
        patch("state.get_cached_valid_tickers", return_value=["AAPL"]),
        patch.object(account, "check_ticker") as mock_ct,
        patch.object(account, "save_state"),
    ):
        # Simulate check_ticker dropping EA from universe.
        def _drop_ea(_session, _config):
            account.tickers = [
                {
                    "ticker": "AAPL",
                    "volume": 0,
                    "difference": 0,
                    "price": 0,
                    "limitTrade": {
                        "open": False,
                        "id": "",
                        "ts": 0,
                        "side": "",
                        "intent": "",
                        "notional": None,
                    },
                }
            ]

        mock_ct.side_effect = _drop_ea
        account.check_balances(
            session,
            [{"symbol": "EA", "qty": "1", "market_value": "200"}],
            config,
        )

    mock_ct.assert_called_once()
    assert session.delete.call_count == 1


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


def test_load_state_defaults_quarantined():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "trading_state.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tickers": [],
                    "equity": 1,
                    "market": "closed",
                    "serverTime": 0,
                    "margin": 0.03,
                },
                f,
            )
        account = Status()
        account.STATE_FILE = path
        account.load_state()
        assert account.quarantined == []
