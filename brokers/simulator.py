from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import json


@dataclass
class SimulatedOrder:
    order_id: str
    instrument: str
    side: str
    qty: float
    entry_price: float
    exit_price: Optional[float]
    status: str
    approved: bool
    created_at: str
    closed_at: Optional[str]


class PaperSimulator:
    """Manual-approval paper simulator with ledger persistence."""

    def __init__(self, ledger_path: str = "data/simulated_orders.json") -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self._write([])

    def _read(self) -> List[Dict[str, object]]:
        return json.loads(self.ledger_path.read_text(encoding="utf-8"))

    def _write(self, payload: List[Dict[str, object]]) -> None:
        self.ledger_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def submit_order(self, instrument: str, side: str, qty: float, price: float, approved: bool = False) -> Dict[str, object]:
        orders = self._read()
        now = datetime.now(timezone.utc).isoformat()
        order = SimulatedOrder(
            order_id=f"sim-{len(orders) + 1}",
            instrument=instrument,
            side=side,
            qty=qty,
            entry_price=price,
            exit_price=None,
            status="OPEN" if approved else "PENDING_APPROVAL",
            approved=approved,
            created_at=now,
            closed_at=None,
        )
        orders.append(asdict(order))
        self._write(orders)
        return asdict(order)

    def approve_order(self, order_id: str) -> Optional[Dict[str, object]]:
        orders = self._read()
        for order in orders:
            if order["order_id"] == order_id:
                order["approved"] = True
                if order["status"] == "PENDING_APPROVAL":
                    order["status"] = "OPEN"
                self._write(orders)
                return order
        return None

    def close_order(self, order_id: str, exit_price: float) -> Optional[Dict[str, object]]:
        orders = self._read()
        for order in orders:
            if order["order_id"] == order_id and order["status"] == "OPEN":
                order["exit_price"] = exit_price
                order["status"] = "CLOSED"
                order["closed_at"] = datetime.now(timezone.utc).isoformat()
                self._write(orders)
                return order
        return None

    def get_daily_pnl(self) -> Dict[str, object]:
        orders = self._read()
        day = datetime.now(timezone.utc).date()
        pnl = 0.0
        closed = 0
        open_count = 0

        for order in orders:
            created = datetime.fromisoformat(order["created_at"]).date()
            if created != day:
                continue

            if order["status"] == "CLOSED" and order["exit_price"] is not None:
                sign = 1 if order["side"].upper() in {"BUY", "CALL_BUY"} else -1
                pnl += sign * (float(order["exit_price"]) - float(order["entry_price"])) * float(order["qty"])
                closed += 1
            elif order["status"] in {"OPEN", "PENDING_APPROVAL"}:
                open_count += 1

        return {"date": str(day), "daily_pnl": round(pnl, 2), "closed_orders": closed, "open_orders": open_count}

    def list_orders(self) -> List[Dict[str, object]]:
        return self._read()
