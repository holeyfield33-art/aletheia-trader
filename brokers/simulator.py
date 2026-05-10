from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass
class SimulatedOrder:
    order_id: str
    instrument: str
    side: str
    qty: float
    entry_price: float
    exit_price: float | None
    status: str
    approved: bool
    created_at: str
    closed_at: str | None


class PaperSimulator:
    """Manual-approval paper simulator with ledger persistence."""

    def __init__(self, ledger_path: str = "data/simulated_orders.json") -> None:
        self.ledger_path = Path(ledger_path)
        self._lock = RLock()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self._write([])

    def _read(self) -> list[dict[str, object]]:
        if not self.ledger_path.exists():
            return []
        raw = self.ledger_path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                return payload
        except json.JSONDecodeError:
            return []
        return []

    def _write(self, payload: list[dict[str, Any]]) -> None:
        serialized = json.dumps(payload, indent=2)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.ledger_path.parent, delete=False
        ) as temp_file:
            temp_file.write(serialized)
            temp_name = temp_file.name
        Path(temp_name).replace(self.ledger_path)

    def submit_order(
        self, instrument: str, side: str, qty: float, price: float, approved: bool = False
    ) -> dict[str, object]:
        if qty <= 0:
            raise ValueError("qty must be > 0")
        if price <= 0:
            raise ValueError("price must be > 0")

        with self._lock:
            orders = self._read()
            now = datetime.now(UTC).isoformat()
            order = SimulatedOrder(
                order_id=f"sim-{len(orders) + 1}",
                instrument=instrument,
                side=side,
                qty=float(qty),
                entry_price=float(price),
                exit_price=None,
                status="OPEN" if approved else "PENDING_APPROVAL",
                approved=approved,
                created_at=now,
                closed_at=None,
            )
            serialized = asdict(order)
            orders.append(serialized)
            self._write(orders)
            return serialized

    def approve_order(self, order_id: str) -> dict[str, object] | None:
        with self._lock:
            orders = self._read()
            for order in orders:
                if order["order_id"] == order_id:
                    order["approved"] = True
                    if order["status"] == "PENDING_APPROVAL":
                        order["status"] = "OPEN"
                    self._write(orders)
                    return order
        return None

    def close_order(self, order_id: str, exit_price: float) -> dict[str, object] | None:
        if exit_price <= 0:
            raise ValueError("exit_price must be > 0")

        with self._lock:
            orders = self._read()
            for order in orders:
                if order["order_id"] == order_id and order["status"] == "OPEN":
                    order["exit_price"] = float(exit_price)
                    order["status"] = "CLOSED"
                    order["closed_at"] = datetime.now(UTC).isoformat()
                    self._write(orders)
                    return order
        return None

    @staticmethod
    def _as_float(value: object, default: float = 0.0) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return default

    def get_daily_pnl(self) -> dict[str, object]:
        with self._lock:
            orders = self._read()
        day = datetime.now(UTC).date()
        pnl = 0.0
        closed = 0
        open_count = 0

        for order in orders:
            created_raw = str(order.get("created_at", ""))
            if not created_raw:
                continue
            created = datetime.fromisoformat(created_raw).date()
            if created != day:
                continue

            status = str(order.get("status", ""))
            if status == "CLOSED" and order.get("exit_price") is not None:
                side = str(order.get("side", ""))
                sign = 1 if side.upper() in {"BUY", "CALL_BUY"} else -1
                exit_price = self._as_float(order.get("exit_price", 0.0))
                entry_price = self._as_float(order.get("entry_price", 0.0))
                qty = self._as_float(order.get("qty", 0.0))
                pnl += sign * (exit_price - entry_price) * qty
                closed += 1
            elif status in {"OPEN", "PENDING_APPROVAL"}:
                open_count += 1

        return {
            "date": str(day),
            "daily_pnl": round(pnl, 2),
            "closed_orders": closed,
            "open_orders": open_count,
        }

    def list_orders(self) -> list[dict[str, object]]:
        with self._lock:
            return self._read()
