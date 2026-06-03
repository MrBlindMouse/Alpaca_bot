from backtest.clock import filter_rth_timestamps, is_rth_timestamp, ts_to_epoch


def test_rth_timestamp_weekday_session():
    assert is_rth_timestamp("2025-01-02T15:00:00Z")  # Thu 10:00 ET


def test_rth_rejects_weekend():
    assert not is_rth_timestamp("2025-01-04T15:00:00Z")  # Sat


def test_filter_rth_timestamps():
    ts = [
        "2025-01-02T14:35:00Z",
        "2025-01-04T14:35:00Z",
        "2025-01-02T21:00:00Z",
    ]
    filtered = filter_rth_timestamps(ts)
    assert "2025-01-02T14:35:00Z" in filtered
    assert "2025-01-04T14:35:00Z" not in filtered
    assert "2025-01-02T21:00:00Z" not in filtered


def test_ts_to_epoch():
    assert ts_to_epoch("2025-01-02T14:35:00Z") > 0
