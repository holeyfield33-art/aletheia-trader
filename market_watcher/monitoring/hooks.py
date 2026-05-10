from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import Any

MarketHook = Callable[[dict[str, Any]], None]


class HookRegistry:
    """Observer hook registry for streaming watcher events to other components."""

    def __init__(self) -> None:
        self._hooks: dict[str, dict[str, MarketHook]] = defaultdict(dict)
        self._lock = RLock()

    def register(self, event_name: str, hook: MarketHook) -> str:
        hook_id = uuid.uuid4().hex
        with self._lock:
            self._hooks[event_name][hook_id] = hook
        return hook_id

    def unregister(self, event_name: str, hook_id: str) -> bool:
        with self._lock:
            handlers = self._hooks.get(event_name)
            if not handlers or hook_id not in handlers:
                return False
            del handlers[hook_id]
            if not handlers:
                del self._hooks[event_name]
            return True

    def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        with self._lock:
            hooks = list(self._hooks.get(event_name, {}).values())
        for hook in hooks:
            try:
                hook(payload)
            except Exception:
                continue
