from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock


class HeartbeatMonitor:
    """Tracks watcher liveness and loop health for operations visibility."""

    def __init__(self) -> None:
        self._last_tick: str | None = None
        self._last_error: str | None = None
        self._cycle_count = 0
        self._lock = RLock()

    def tick(self) -> None:
        with self._lock:
            self._cycle_count += 1
            self._last_tick = datetime.now(UTC).isoformat()
            self._last_error = None

    def fail(self, message: str) -> None:
        with self._lock:
            self._last_tick = datetime.now(UTC).isoformat()
            self._last_error = message

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            last = self._last_tick
            age = None
            if last:
                try:
                    age = round(
                        (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds(), 2
                    )
                except ValueError:
                    age = None
            return {
                "last_heartbeat": last,
                "seconds_since_heartbeat": age,
                "cycle_count": self._cycle_count,
                "last_error": self._last_error,
            }
