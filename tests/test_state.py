import json
import os
import tempfile

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
