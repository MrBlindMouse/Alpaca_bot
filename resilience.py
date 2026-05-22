import logging
import time

logger = logging.getLogger("alpaca_bot.resilience")


class CircuitBreaker:
    """Pause rebalance after consecutive Alpaca failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        backoff_seconds: int = 300,
    ):
        self.failure_threshold = failure_threshold
        self.backoff_seconds = backoff_seconds
        self._consecutive_failures = 0
        self._paused_until = 0.0

    def is_paused(self) -> bool:
        if self._paused_until and time.time() < self._paused_until:
            return True
        if self._paused_until and time.time() >= self._paused_until:
            self._paused_until = 0.0
            self._consecutive_failures = 0
            logger.info("Circuit breaker closed; resuming rebalance")
        return False

    def record_success(self):
        if self._consecutive_failures or self._paused_until:
            self._consecutive_failures = 0
            self._paused_until = 0.0

    def record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._paused_until = time.time() + self.backoff_seconds
            logger.warning(
                "Circuit breaker open after %d failures; pausing rebalance for %ds",
                self._consecutive_failures,
                self.backoff_seconds,
            )
