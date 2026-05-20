"""In-process bot scheduler with start/stop for CLI and TUI."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import schedule

from alpaca_client import create_session
from config import Config, log_remote_disabled_once
from market import MarketTracker
from reporting import day_end
from scheduler import bot_loop, check_balances
from state import Status

logger = logging.getLogger("alpaca_bot.runner")

JOIN_TIMEOUT_SECONDS = 10


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
        self._jobs_registered = False

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
        self.config.update()

    def _register_jobs(self):
        schedule.clear()
        schedule.every(1).minute.do(
            self._safe_bot_loop,
        )
        schedule.every(1).hour.do(
            self._safe_check_balances,
        )
        schedule.every().day.at("22:00").do(
            self._safe_day_end,
        )
        self._jobs_registered = True

    def _safe_bot_loop(self):
        try:
            bot_loop(
                self.session,
                self.account,
                self.config,
                self.tracker,
            )
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("bot_loop failed")
        finally:
            self._last_loop_at = time.time()

    def _safe_check_balances(self):
        try:
            check_balances(self.session, self.account, self.config)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("check_balances failed")

    def _safe_day_end(self):
        try:
            day_end(self.session, self.account, self.config)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("day_end failed")

    def _scheduler_loop(self):
        log_remote_disabled_once(self.config, logger)
        while not self._stop.is_set():
            schedule.run_pending()
            time.sleep(1)

    def start(self) -> None:
        if self.running:
            return
        self.account.load_state()
        self._stop.clear()
        if not self._jobs_registered:
            self._register_jobs()
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
        schedule.clear()
        self._jobs_registered = False
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
