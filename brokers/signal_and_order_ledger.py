from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import json


@dataclass
class PendingSignal:
    signal_id: str
    agent_type: str  # "forex" or "options"
    instrument: str
    signal: str
    indicators: Dict[str, float]
    chain_data: Optional[Dict[str, object]]
    receipt: str
    created_at: str
    expires_at: str


@dataclass
class ApprovedOrder:
    order_id: str
    signal_id: str
    instrument: str
    side: str
    qty: float
    entry_price: float
    status: str  # PENDING, OPEN, CLOSED
    approved_at: str
    executed_at: Optional[str]
    exit_price: Optional[float]
    closed_at: Optional[str]


class SignalAndOrderLedger:
    """Unified ledger for signals and orders."""

    def __init__(self, signals_path: str = "data/pending_signals.json", orders_path: str = "data/approved_orders.json") -> None:
        self.signals_path = Path(signals_path)
        self.orders_path = Path(orders_path)
        
        for path in [self.signals_path, self.orders_path]:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps([], indent=2), encoding="utf-8")

    def add_signal(
        self,
        signal_id: str,
        agent_type: str,
        instrument: str,
        signal: str,
        indicators: Dict[str, float],
        chain_data: Optional[Dict[str, object]],
        receipt: str,
        ttl_minutes: int = 120,
    ) -> Dict[str, object]:
        """Add a pending signal to the ledger."""
        signals = json.loads(self.signals_path.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        pending = {
            "signal_id": signal_id,
            "agent_type": agent_type,
            "instrument": instrument,
            "signal": signal,
            "indicators": indicators,
            "chain_data": chain_data,
            "receipt": receipt,
            "created_at": now.isoformat(),
            "expires_at": (now.timestamp() + ttl_minutes * 60).__format__(".0f"),
            "status": "PENDING",
        }
        signals.append(pending)
        self.signals_path.write_text(json.dumps(signals, indent=2), encoding="utf-8")
        return pending

    def get_pending_signals(self) -> List[Dict[str, object]]:
        """Get all non-expired pending signals."""
        signals = json.loads(self.signals_path.read_text(encoding="utf-8"))
        now_ts = datetime.now(timezone.utc).timestamp()
        active = [s for s in signals if s.get("status") == "PENDING" and float(s.get("expires_at", 0)) > now_ts]
        return active

    def approve_signal(self, signal_id: str) -> Optional[Dict[str, object]]:
        """Approve a signal, convert to order, remove from pending."""
        signals = json.loads(self.signals_path.read_text(encoding="utf-8"))
        
        signal = None
        for i, s in enumerate(signals):
            if s.get("signal_id") == signal_id:
                signal = signals.pop(i)
                break
        
        if not signal:
            return None
        
        signal["status"] = "APPROVED"
        self.signals_path.write_text(json.dumps(signals, indent=2), encoding="utf-8")
        return signal

    def reject_signal(self, signal_id: str) -> bool:
        """Reject and remove a signal."""
        signals = json.loads(self.signals_path.read_text(encoding="utf-8"))
        for i, s in enumerate(signals):
            if s.get("signal_id") == signal_id:
                signals.pop(i)
                self.signals_path.write_text(json.dumps(signals, indent=2), encoding="utf-8")
                return True
        return False

    def create_order_from_signal(
        self,
        signal: Dict[str, object],
        entry_price: float,
        qty: float = 1.0,
    ) -> Dict[str, object]:
        """Create an approved order from a signal."""
        orders = json.loads(self.orders_path.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        order = {
            "order_id": f"ord-{len(orders) + 1}",
            "signal_id": signal.get("signal_id"),
            "instrument": signal.get("instrument"),
            "side": signal.get("signal"),
            "qty": qty,
            "entry_price": entry_price,
            "status": "OPEN",
            "approved_at": now.isoformat(),
            "executed_at": now.isoformat(),
            "exit_price": None,
            "closed_at": None,
        }
        orders.append(order)
        self.orders_path.write_text(json.dumps(orders, indent=2), encoding="utf-8")
        return order

    def get_orders(self, status: Optional[str] = None) -> List[Dict[str, object]]:
        """Get orders, optionally filtered by status."""
        orders = json.loads(self.orders_path.read_text(encoding="utf-8"))
        if status:
            return [o for o in orders if o.get("status") == status]
        return orders

    def close_order(self, order_id: str, exit_price: float) -> Optional[Dict[str, object]]:
        """Close an open order."""
        orders = json.loads(self.orders_path.read_text(encoding="utf-8"))
        for order in orders:
            if order.get("order_id") == order_id and order.get("status") == "OPEN":
                order["status"] = "CLOSED"
                order["exit_price"] = exit_price
                order["closed_at"] = datetime.now(timezone.utc).isoformat()
                self.orders_path.write_text(json.dumps(orders, indent=2), encoding="utf-8")
                return order
        return None

    def get_daily_pnl(self) -> Dict[str, object]:
        """Calculate daily P&L from closed orders."""
        orders = json.loads(self.orders_path.read_text(encoding="utf-8"))
        today = datetime.now(timezone.utc).date()
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
                pnl += sign * (float(order["exit_price"]) - float(order["entry_price"])) * float(order["qty"])
                closed += 1

        return {"date": str(today), "daily_pnl": round(pnl, 2), "closed_orders": closed, "open_orders": open_count}

    def get_total_pnl(self) -> float:
        """Calculate total P&L across all closed orders."""
        orders = json.loads(self.orders_path.read_text(encoding="utf-8"))
        pnl = 0.0

        for order in orders:
            if order.get("status") == "CLOSED" and order.get("exit_price"):
                sign = 1 if order.get("side") in {"BUY", "CALL_BUY"} else -1
                pnl += sign * (float(order["exit_price"]) - float(order["entry_price"])) * float(order["qty"])

        return round(pnl, 2)
