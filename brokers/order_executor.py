"""Live order execution router with broker selection and status tracking."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from brokers.alpaca_broker import AlpacaBroker
from brokers.broker_factory import BrokerFactory
from brokers.profit_calculator import ProfitCalculator


@dataclass
class OrderExecutionResult:
    """Result of order submission."""

    order_id: str
    status: str  # submitted, filled, rejected, pending, cancelled
    broker_mode: str
    filled_qty: float = 0.0
    filled_price: float = 0.0
    commission: float = 0.0
    broker_order_id: str | None = None
    broker_response: dict[str, Any] = field(default_factory=dict)
    submitted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    filled_at: str | None = None
    error: str | None = None


@dataclass
class OrderStatus:
    """Current status of an order from the broker."""

    order_id: str
    broker_order_id: str | None
    status: str  # pending, filled, partial, rejected, cancelled
    filled_qty: float
    filled_price: float
    commission: float
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class OrderExecutor:
    """Route and execute orders through the appropriate broker."""

    def __init__(self, broker_mode: str | None = None) -> None:
        self.broker_mode: str = broker_mode or os.getenv("BROKER_MODE") or "paper"
        self._broker = BrokerFactory.create(self.broker_mode)
        self._order_to_broker_id: dict[str, str] = {}
        self._broker_id_to_order: dict[str, str] = {}

    @property
    def is_live(self) -> bool:
        """Check if executing against live broker."""
        return self.broker_mode == "alpaca_live"

    @property
    def is_paper(self) -> bool:
        """Check if executing in paper mode."""
        return self.broker_mode == "paper"

    def submit_order(
        self,
        order_id: str,
        instrument: str,
        side: str,
        qty: float,
        price: float | None = None,
        order_type: str = "market",
        time_in_force: str = "gtc",
        commission: float = 0.0,
    ) -> OrderExecutionResult:
        """Submit order to broker and return execution result."""
        try:
            payload = {
                "request_id": order_id,
                "instrument": instrument,
                "symbol": instrument,
                "side": side,
                "qty": qty,
                "filled_qty": qty,
                "filled_price": price or 0.0,
                "entry_price": price or 0.0,
                "order_type": order_type,
                "time_in_force": time_in_force,
                "commission": commission,
                "instrument_spec": ProfitCalculator.spec_dict(instrument, side),
            }

            broker_response = self._broker.submit_order(payload)

            if isinstance(self._broker, AlpacaBroker):
                # Live/paper Alpaca execution
                status = self._map_alpaca_status(broker_response)
                broker_order_id = broker_response.get("id") or broker_response.get("order_id")
                if broker_order_id:
                    self._order_to_broker_id[order_id] = str(broker_order_id)
                    self._broker_id_to_order[str(broker_order_id)] = order_id

                result = OrderExecutionResult(
                    order_id=order_id,
                    status=status,
                    broker_mode=self.broker_mode,
                    filled_qty=float(broker_response.get("filled_qty", qty)) or qty,
                    filled_price=float(broker_response.get("filled_price", price or 0.0))
                    or price
                    or 0.0,
                    commission=float(broker_response.get("commission", commission)) or commission,
                    broker_order_id=broker_order_id,
                    broker_response=broker_response,
                    filled_at=(datetime.now(UTC).isoformat() if status == "filled" else None),
                )
            else:
                # Paper (simulator) execution
                result = OrderExecutionResult(
                    order_id=order_id,
                    status="submitted",
                    broker_mode="paper",
                    filled_qty=qty,
                    filled_price=price or 0.0,
                    commission=commission,
                    broker_response=broker_response,
                    filled_at=datetime.now(UTC).isoformat(),
                )

            return result
        except Exception as exc:
            return OrderExecutionResult(
                order_id=order_id,
                status="rejected",
                broker_mode=self.broker_mode,
                broker_response={},
                error=str(exc),
            )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order."""
        broker_order_id = self._order_to_broker_id.get(order_id)

        try:
            result = self._broker.cancel_order(broker_order_id or order_id)
            return {
                "order_id": order_id,
                "broker_order_id": broker_order_id,
                "status": "cancelled",
                "result": result,
            }
        except Exception as exc:
            return {
                "order_id": order_id,
                "status": "cancel_failed",
                "error": str(exc),
            }

    def get_order_status(self, order_id: str) -> OrderStatus | None:
        """Poll broker for current order status."""
        broker_order_id = self._order_to_broker_id.get(order_id)
        if not broker_order_id and isinstance(self._broker, AlpacaBroker):
            return None

        try:
            if isinstance(self._broker, AlpacaBroker) and broker_order_id:
                # Poll Alpaca for live status
                orders = self._broker.get_positions()  # Note: get_positions returns open orders
                for order_info in orders:
                    if (
                        order_info.get("id") == broker_order_id
                        or order_info.get("order_id") == broker_order_id
                    ):
                        return OrderStatus(
                            order_id=order_id,
                            broker_order_id=broker_order_id,
                            status=self._map_alpaca_status(order_info),
                            filled_qty=float(order_info.get("filled_qty", 0)) or 0.0,
                            filled_price=float(order_info.get("filled_price", 0)) or 0.0,
                            commission=float(order_info.get("commission", 0)) or 0.0,
                        )
                return None
            else:
                # Paper: status is implicit FILLED
                return OrderStatus(
                    order_id=order_id,
                    broker_order_id=None,
                    status="filled",
                    filled_qty=0.0,
                    filled_price=0.0,
                    commission=0.0,
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch order status for {order_id}: {exc}") from exc

    def get_positions(self) -> list[dict[str, Any]]:
        """Get all open positions from broker."""
        return self._broker.get_positions()

    def get_account(self) -> dict[str, Any]:
        """Get account info from broker."""
        return self._broker.get_account()

    @staticmethod
    def _map_alpaca_status(response: dict[str, Any]) -> str:
        """Map Alpaca order status to internal status."""
        status = response.get("status", "").lower()
        if "filled" in status or "accepted" in status:
            return "filled"
        if "partial" in status:
            return "partial"
        if "rejected" in status or "cancelled" in status:
            return "rejected"
        if "pending" in status or "new" in status:
            return "pending"
        return status or "unknown"
