"""Background scheduler for periodic episodi polling.

Runs poll_episodi() on a configurable interval via the POLL_INTERVAL env var.
Supports values like '1h', '6h', '1d', '7d'. Default: '1d'.
"""

import logging
import os
import re
import threading
from datetime import UTC, datetime

from rai import core, poller

log = logging.getLogger(__name__)

# Parse interval from env
_INTERVAL_PATTERN = re.compile(r"^(\d+)\s*(h|d|m)$", re.IGNORECASE)
_DEFAULT_INTERVAL = "1d"


def _parse_interval(value):
    """Parse interval string like '1h', '6h', '1d', '7d', '30m' to seconds."""
    value = (value or "").strip()
    if not value:
        value = _DEFAULT_INTERVAL

    m = _INTERVAL_PATTERN.match(value)
    if not m:
        log.warning("Invalid POLL_INTERVAL '%s', using default '%s'", value, _DEFAULT_INTERVAL)
        value = _DEFAULT_INTERVAL
        m = _INTERVAL_PATTERN.match(value)

    num = int(m.group(1))
    unit = m.group(2).lower()

    if unit == "m":
        return num * 60
    elif unit == "h":
        return num * 3600
    elif unit == "d":
        return num * 86400
    return num * 86400


class Scheduler:
    """Background scheduler that runs poll_episodi() periodically."""

    def __init__(self):
        self._interval = _parse_interval(os.environ.get("POLL_INTERVAL", _DEFAULT_INTERVAL))
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Status tracking
        self._last_run = None
        self._last_result = None
        self._next_run = None
        self._running = False

    @property
    def interval_seconds(self):
        return self._interval

    @property
    def interval_human(self):
        """Human-readable interval string."""
        s = self._interval
        if s >= 86400:
            d = s // 86400
            return f"{d}d"
        elif s >= 3600:
            h = s // 3600
            return f"{h}h"
        else:
            m = s // 60
            return f"{m}m"

    def get_status(self):
        """Get current scheduler status as a dict."""
        with self._lock:
            return {
                "running": self._running,
                "interval": self.interval_human,
                "interval_seconds": self._interval,
                "last_run": self._last_run,
                "last_result": self._last_result,
                "next_run": self._next_run,
            }

    def start(self):
        """Start the scheduler background thread."""
        if self._thread and self._thread.is_alive():
            log.warning("Scheduler already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="poller-scheduler")
        self._thread.start()
        log.info("Scheduler started (interval: %s)", self.interval_human)

    def stop(self):
        """Stop the scheduler."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Scheduler stopped")

    def poll_now(self, progress_callback=None):
        """Run a poll immediately (can be called from any thread).

        Returns the poll result dict.
        """
        return self._do_poll(progress_callback=progress_callback)

    def _loop(self):
        """Main scheduler loop: run immediately, then every interval."""
        # Run immediately on startup
        self._do_poll()

        while not self._stop_event.is_set():
            with self._lock:
                self._next_run = datetime.now(UTC).timestamp() + self._interval

            # Wait for interval or stop signal
            if self._stop_event.wait(timeout=self._interval):
                break  # Stop signal received

            self._do_poll()

    def _do_poll(self, progress_callback=None):
        """Execute a single poll cycle."""
        with self._lock:
            if self._running:
                log.warning("Poll already in progress, skipping")
                return self._last_result
            self._running = True

        try:
            log.info("Starting poll...")
            session = core.make_session()
            result = poller.poll_episodi(session=session, progress_callback=progress_callback)

            with self._lock:
                self._last_run = datetime.now(UTC).isoformat()
                self._last_result = result

            if result.get("success"):
                log.info(
                    "Poll complete: %s — %d new, %d skipped, %d failed",
                    result.get("audiobook", "?"),
                    result.get("episodes_downloaded", 0),
                    result.get("episodes_skipped", 0),
                    result.get("episodes_failed", 0),
                )
            else:
                log.error("Poll failed: %s", result.get("error", "unknown"))

            return result

        except Exception as e:
            log.error("Poll error: %s", e, exc_info=True)
            with self._lock:
                self._last_run = datetime.now(UTC).isoformat()
                self._last_result = {"success": False, "error": str(e)}
            return self._last_result

        finally:
            with self._lock:
                self._running = False


# Module-level singleton
_scheduler = None


def get_scheduler():
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
