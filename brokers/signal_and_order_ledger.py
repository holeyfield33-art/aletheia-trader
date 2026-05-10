from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


class SignalAndOrderLedger:
    """Unified ledger for signals and orders."""

    def __init__(
        self,
        signals_path: str = "data/pending_signals.json",
        orders_path: str = "data/approved_orders.json",
    ) -> None:
        self.signals_path = Path(signals_path)
        self.orders_path = Path(orders_path)
        self._lock = RLock()

        for path in [self.signals_path, self.orders_path]:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                self._atomic_write(path, [])

    def _atomic_write(self, path: Path, payload: list[dict[str, Any]]) -> None:
        serialized = json.dumps(payload, indent=2)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temp_file:
            temp_file.write(serialized)
            temp_name = temp_file.name
        Path(temp_name).replace(path)

    def _read_json_list(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []

        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                return payload
        except json.JSONDecodeError:
            return []
        return []

    def add_signal(
        self,
        signal_id: str,
        agent_type: str,
        instrument: str,
        signal: str,
        indicators: dict[str, float],
        chain_data: dict[str, object] | None,
        receipt: str,
        ttl_minutes: int = 120,
    ) -> dict[str, object]:
        """Add a pending signal to the ledger."""
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be > 0")

        now = datetime.now(UTC)
        pending: dict[str, object] = {
            "signal_id": signal_id,
            "agent_type": agent_type,
            "instrument": instrument,
            "signal": signal,
            "indicators": indicators,
            "chain_data": chain_data,
            "receipt": receipt,
            "created_at": now.isoformat(),
            "expires_at": f"{now.timestamp() + ttl_minutes * 60:.0f}",
            "status": "PENDING",
        }

        with self._lock:
            signals = self._read_json_list(self.signals_path)
            signals.append(pending)
            self._atomic_write(self.signals_path, signals)
        return pending

    def get_pending_signals(self) -> list[dict[str, object]]:
        """Get all non-expired pending signals."""
        with self._lock:
            signals = self._read_json_list(self.signals_path)
        now_ts = datetime.now(UTC).timestamp()
        active = [
            s
            for s in signals
            if s.get("status") == "PENDING" and float(s.get("expires_at", 0)) > now_ts
        ]
        return active

    def approve_signal(self, signal_id: str) -> dict[str, object] | None:
        """Approve a signal, convert to order, remove from pending."""
        with self._lock:
            signals = self._read_json_list(self.signals_path)

            signal = None
            for i, item in enumerate(signals):
                if item.get("signal_id") == signal_id:
                    signal = signals.pop(i)
                    break

            if not signal:
                return None

            signal["status"] = "APPROVED"
            self._atomic_write(self.signals_path, signals)
            return signal

    def reject_signal(self, signal_id: str) -> bool:
        """Reject and remove a signal."""
        with self._lock:
            signals = self._read_json_list(self.signals_path)
            for i, item in enumerate(signals):
                if item.get("signal_id") == signal_id:
                    signals.pop(i)
                    self._atomic_write(self.signals_path, signals)
                    return True
        return False

    def create_order_from_signal(
        self,
        signal: dict[str, object],
        entry_price: float,
        qty: float = 1.0,
    ) -> dict[str, object]:
        """Create an approved order from a signal."""
        if entry_price <= 0:
            raise ValueError("entry_price must be > 0")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        now = datetime.now(UTC)
        with self._lock:
            orders = self._read_json_list(self.orders_path)
            order = {
                "order_id": f"ord-{len(orders) + 1}",
                "signal_id": signal.get("signal_id"),
                "instrument": signal.get("instrument"),
                "side": signal.get("signal"),
                "qty": float(qty),
                "entry_price": float(entry_price),
                "status": "OPEN",
                "approved_at": now.isoformat(),
                "executed_at": now.isoformat(),
                "exit_price": None,
                "closed_at": None,
            }
            orders.append(order)
            self._atomic_write(self.orders_path, orders)
            return order

    def get_orders(self, status: str | None = None) -> list[dict[str, object]]:
        """Get orders, optionally filtered by status."""
        with self._lock:
            orders = self._read_json_list(self.orders_path)
        if status:
            return [o for o in orders if o.get("status") == status]
        return orders

    def close_order(self, order_id: str, exit_price: float) -> dict[str, object] | None:
        """Close an open order."""
        if exit_price <= 0:
            raise ValueError("exit_price must be > 0")

        with self._lock:
            orders = self._read_json_list(self.orders_path)
            for order in orders:
                if order.get("order_id") == order_id and order.get("status") == "OPEN":
                    order["status"] = "CLOSED"
                    order["exit_price"] = float(exit_price)
                    order["closed_at"] = datetime.now(UTC).isoformat()
                    self._atomic_write(self.orders_path, orders)
                    return order
        return None

    def get_daily_pnl(self) -> dict[str, object]:
        """Calculate daily P&L from closed orders."""
        with self._lock:
            orders = self._read_json_list(self.orders_path)
        today = datetime.now(UTC).date()
        pnl = 0.0
        closed = 0
        open_count = 0

        for order in orders:
            closed_ts = order.get("closed_at")
            if not closed_ts:
                if order.get("status") == "OPEN":
                    open_count += 1
                continue

            closed_date = datetime.fromisoformat(closed_ts).date()
            if closed_date != today:
                continue

            if order.get("status") == "CLOSED" and order.get("exit_price"):
                sign = 1 if order.get("side") in {"BUY", "CALL_BUY"} else -1
                pnl += (
                    sign
                    * (float(order["exit_price"]) - float(order["entry_price"]))
                    * float(order["qty"])
                )
                closed += 1

        return {
            "date": str(today),
            "daily_pnl": round(pnl, 2),
            "closed_orders": closed,
            "open_orders": open_count,
        }

    def get_total_pnl(self) -> float:
        """Calculate total P&L across all closed orders."""
        with self._lock:
            orders = self._read_json_list(self.orders_path)
        pnl = 0.0

        for order in orders:
            if order.get("status") == "CLOSED" and order.get("exit_price"):
                sign = 1 if order.get("side") in {"BUY", "CALL_BUY"} else -1
                pnl += (
                    sign
                    * (float(order["exit_price"]) - float(order["entry_price"]))
                    * float(order["qty"])
                )

        return round(pnl, 2)
