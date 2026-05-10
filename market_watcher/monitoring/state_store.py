from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Any


class MarketStateStore:
    """Time-series state store for market snapshots and symbol-level diagnostics."""

    def __init__(self, max_history: int = 240) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=max_history)
        self._symbol_state: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def append_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._history.append(snapshot)
            for row in snapshot.get("symbols", []):
                if isinstance(row, dict):
                    symbol = str(row.get("symbol", "")).upper()
                    if symbol:
                        self._symbol_state[symbol] = row

    def latest_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return self._history[-1] if self._history else None

    def history(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._history)
        if limit is None:
            return rows
        return rows[-max(limit, 0) :]

    def symbol_state(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            return self._symbol_state.get(symbol.upper())
