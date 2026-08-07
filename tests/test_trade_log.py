import json
import tempfile

from trade_log import append_trade, build_trade_record, utc_now_iso


def test_build_trade_record_keys():
    record = build_trade_record(
        symbol="AAPL",
        side="buy",
        intent="rebalance_buy",
        order_type="market",
        market_session="open",
        status="filled",
        paper=True,
        order_id="abc",
        notional=100.0,
    )
    assert record["symbol"] == "AAPL"
    assert record["status"] == "filled"
    assert record["paper"] is True


def test_append_trade_writes_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/trades.jsonl"
        append_trade({"symbol": "MSFT", "status": "filled"}, path=path)
        with open(path, encoding="utf-8") as f:
            line = json.loads(f.readline())
        assert line["symbol"] == "MSFT"
        assert "ts" in line
        assert utc_now_iso().endswith("Z")


def test_append_order_event_writes_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/orders.jsonl"
        from trade_log import append_order_event

        append_order_event({"symbol": "AAPL", "status": "limit_placed"}, path=path)
        with open(path, encoding="utf-8") as f:
            line = json.loads(f.readline())
        assert line["status"] == "limit_placed"
        assert "ts" in line
