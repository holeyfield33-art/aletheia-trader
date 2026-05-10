from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

MarketHook = Callable[[dict[str, Any]], None]


class HookRegistry:
    """Observer hook registry for streaming watcher events to other components."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[MarketHook]] = defaultdict(list)

    def register(self, event_name: str, hook: MarketHook) -> None:
        self._hooks[event_name].append(hook)

    def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        for hook in self._hooks.get(event_name, []):
            try:
                hook(payload)
            except Exception:
                continue
