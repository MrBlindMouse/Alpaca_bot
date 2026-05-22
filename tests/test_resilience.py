import time

from resilience import CircuitBreaker


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, backoff_seconds=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.is_paused()


def test_circuit_resets_on_success():
    cb = CircuitBreaker(failure_threshold=2, backoff_seconds=60)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert not cb.is_paused()


def test_circuit_closes_after_backoff():
    cb = CircuitBreaker(failure_threshold=1, backoff_seconds=1)
    cb.record_failure()
    assert cb.is_paused()
    cb._paused_until = time.time() - 1
    assert not cb.is_paused()
