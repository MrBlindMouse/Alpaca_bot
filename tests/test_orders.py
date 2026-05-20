from orders import OrderResult


def test_order_result_helpers():
    filled = OrderResult(status="filled", order_id="1")
    assert filled.is_filled
    assert not filled.is_failed
    assert not filled.is_limit_placed

    limit = OrderResult(status="limit_placed", order_id="2")
    assert limit.is_limit_placed

    failed = OrderResult(status="failed", error="timeout")
    assert failed.is_failed
