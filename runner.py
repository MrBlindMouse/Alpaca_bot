"""In-process bot scheduler with start/stop for CLI and TUI.

ponytail: single-process daemon thread only. Upgrade to a separate worker
process only if tick latency or crash isolation becomes a real problem.
"""

import logging
import threading
import time
from datetime import date, datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from alpaca_client import AlpacaAPIError, alpaca_headers, create_session, get_account
from config import Config, log_remote_disabled_once
from live_broker import LiveBroker
from market import ClockSnapshot, MarketTracker, check_time, compute_tick_sleep_seconds
from rebalance import _fetch_snapshot_prices, force_rebalance_symbol
from reporting import day_end
from resilience import CircuitBreaker
from scheduler import bot_loop, check_balances
from state import Status

logger = logging.getLogger("alpaca_bot.runner")

JOIN_TIMEOUT_SECONDS = 10
NY_TZ = ZoneInfo("America/New_York")
BALANCE_INTERVAL_SECONDS = 3600
DAY_END_HOUR_NY = 22


class BotRunner:
    def __init__(self, config: Config, account: Optional[Status] = None):
        self.config = config
        self.session = create_session()
        self.tracker = MarketTracker()
        self.account = account or Status()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_loop_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self.circuit = CircuitBreaker()
        self._tick_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_loop_at(self) -> Optional[datetime]:
        if self._last_loop_at is None:
            return None
        return datetime.fromtimestamp(self._last_loop_at, tz=timezone.utc)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def reload_config(self):
        paused_until = self.circuit._paused_until
        consecutive_failures = self.circuit._consecutive_failures
        self.config.update()
        self.circuit = CircuitBreaker(
            failure_threshold=self.config.circuit_failure_threshold,
            backoff_seconds=self.config.circuit_backoff_seconds,
        )
        self.circuit._paused_until = paused_until
        self.circuit._consecutive_failures = consecutive_failures

    def _run_bot_loop(self) -> Tuple[bool, Optional[ClockSnapshot]]:
        with self._tick_lock:
            try:
                result = bot_loop(
                    self.session,
                    self.account,
                    self.config,
                    self.tracker,
                    stop_event=self._stop,
                    circuit=self.circuit,
                )
                self._last_error = None
                return result
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("bot_loop failed")
                return False, None
            finally:
                self._last_loop_at = time.time()

    def force_balance(self, symbol: str) -> Tuple[bool, str]:
        """RTH one-shot: force one ticker to equal-$ target (no hysteresis)."""
        sym = (symbol or "").strip().upper()
        if not sym:
            return False, "Symbol required"

        with self._tick_lock:
            try:
                self.config.update()
                self.account.margin = self.config.margin
                clock_ok, _snapshot = check_time(
                    self.session, self.account, self.config, self.tracker
                )
                if not clock_ok:
                    msg = "Market clock unavailable"
                    self._last_error = msg
                    return False, msg
                if self.account.market != "open":
                    msg = (
                        f"Market not open (session={self.account.market}); "
                        "force balance is RTH-only"
                    )
                    return False, msg

                try:
                    account_data = get_account(self.session, self.config)
                except AlpacaAPIError as exc:
                    self._last_error = str(exc)
                    return False, str(exc)
                self.account.equity = float(account_data["equity"])

                headers = alpaca_headers(self.config, json_content=True)
                prices = _fetch_snapshot_prices(
                    self.session, self.config, self.account, headers
                )
                broker = LiveBroker(
                    self.session, self.config, self.account, circuit=self.circuit
                )
                ok, message = force_rebalance_symbol(
                    self.account,
                    self.config,
                    symbol=sym,
                    prices=prices,
                    broker=broker,
                    session="open",
                )
                if ok:
                    self.account.save_state()
                    self._last_error = None
                else:
                    self._last_error = message
                return ok, message
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("force_balance failed")
                return False, str(exc)

    def _safe_check_balances(self):
        try:
            check_balances(
                self.session, self.account, self.config, circuit=self.circuit
            )
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("check_balances failed")

    def _safe_day_end(self):
        try:
            day_end(self.session, self.account, self.config)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("day_end failed")

    def _should_run_day_end(self, last_day_end: Optional[date]) -> bool:
        now_ny = datetime.now(NY_TZ)
        if now_ny.hour < DAY_END_HOUR_NY:
            return False
        today = now_ny.date()
        return last_day_end != today

    def _scheduler_loop(self):
        log_remote_disabled_once(self.config, logger)
        last_balance_at = 0.0
        last_day_end: Optional[date] = None

        while not self._stop.is_set():
            clock_ok, snapshot = self._run_bot_loop()

            now = time.time()
            if now - last_balance_at >= BALANCE_INTERVAL_SECONDS:
                self._safe_check_balances()
                last_balance_at = now

            if self._should_run_day_end(last_day_end):
                self._safe_day_end()
                last_day_end = datetime.now(NY_TZ).date()

            sleep_seconds = compute_tick_sleep_seconds(
                snapshot,
                self.account.market,
                clock_ok,
            )
            logger.debug("Next bot tick in %ds (market=%s)", sleep_seconds, self.account.market)
            if self._stop.wait(sleep_seconds):
                break

    def start(self) -> None:
        if self.running:
            return
        self.config.update()
        self.circuit = CircuitBreaker(
            failure_threshold=self.config.circuit_failure_threshold,
            backoff_seconds=self.config.circuit_backoff_seconds,
        )
        self.account.load_state()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            name="alpaca-bot-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Bot scheduler started")

    def stop(self) -> None:
        if not self.running:
            return
        self._stop.set()
        self._thread.join(timeout=JOIN_TIMEOUT_SECONDS)
        self._thread = None
        logger.info("Bot scheduler stopped")

    def run_forever(self):
        """Blocking loop for headless CLI (Ctrl+C to stop)."""
        self.start()
        try:
            while self.running and not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Shutting down")
        finally:
            self.stop()
