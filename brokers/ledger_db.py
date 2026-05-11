"""Database-backed ledger for signals and orders."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_

from brokers.db import DatabaseManager, Order, Signal
from brokers.profit_calculator import ProfitCalculator


class DatabaseLedger:
    """Database-backed signal and order ledger using SQLAlchemy."""

    def __init__(self, db_url: str | None = None) -> None:
        resolved_db_url = (
            db_url if db_url is not None else os.getenv("DATABASE_URL", "sqlite:///./trading.db")
        )
        self.db = DatabaseManager(resolved_db_url)
        self.db.init_db()

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
    ) -> dict[str, Any]:
        """Add a pending signal to the database."""
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be > 0")

        now = datetime.now(UTC)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_minutes * 60, tz=UTC)
        session = self.db.get_session()
        try:
            signal_obj = Signal(
                signal_id=signal_id,
                agent_type=agent_type,
                instrument=instrument,
                signal=signal,
                indicators=indicators,
                chain_data=chain_data,
                receipt=receipt,
                created_at=now,
                expires_at=expires_at,
                status="PENDING",
            )
            session.add(signal_obj)
            session.commit()
            session.refresh(signal_obj)
            payload = signal_obj.to_dict()
            payload["expires_at"] = f"{expires_at.timestamp():.0f}"
            return payload
        finally:
            session.close()

    def get_pending_signals(self) -> list[dict[str, Any]]:
        """Get all non-expired pending signals."""
        now = datetime.now(UTC)
        session = self.db.get_session()
        try:
            signals = (
                session.query(Signal)
                .filter(
                    and_(
                        Signal.status == "PENDING",
                        Signal.expires_at > now,
                    )
                )
                .order_by(Signal.id.asc())
                .all()
            )
            payload: list[dict[str, Any]] = []
            for signal_obj in signals:
                item = signal_obj.to_dict()
                if signal_obj.expires_at is not None:
                    item["expires_at"] = f"{signal_obj.expires_at.timestamp():.0f}"
                payload.append(item)
            return payload
        finally:
            session.close()

    def approve_signal(self, signal_id: str) -> dict[str, Any] | None:
        """Approve a signal."""
        session = self.db.get_session()
        try:
            signal_obj = session.query(Signal).filter(Signal.signal_id == signal_id).first()
            if not signal_obj:
                return None

            db_signal = cast(Any, signal_obj)
            db_signal.status = "APPROVED"
            db_signal.approved_at = datetime.now(UTC)
            session.commit()
            session.refresh(signal_obj)
            payload = signal_obj.to_dict()
            if signal_obj.expires_at is not None:
                payload["expires_at"] = f"{signal_obj.expires_at.timestamp():.0f}"
            return payload
        finally:
            session.close()

    def reject_signal(self, signal_id: str) -> bool:
        """Reject and remove a signal."""
        session = self.db.get_session()
        try:
            signal_obj = session.query(Signal).filter(Signal.signal_id == signal_id).first()
            if not signal_obj:
                return False

            session.delete(signal_obj)
            session.commit()
            return True
        finally:
            session.close()

    def create_order_from_signal(
        self,
        signal: dict[str, object],
        entry_price: float,
        qty: float = 1.0,
        commission: float = 0.0,
    ) -> dict[str, Any]:
        """Create an approved order from a signal."""
        if entry_price <= 0:
            raise ValueError("entry_price must be > 0")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        now = datetime.now(UTC)
        session = self.db.get_session()
        try:
            # Generate order_id from current count
            count = session.query(Order).count()
            order_id = f"ord-{count + 1}"

            order_obj = Order(
                order_id=order_id,
                signal_id=str(signal.get("signal_id", "")),
                instrument=str(signal.get("instrument", "")),
                side=str(signal.get("signal", "")),
                qty=float(qty),
                entry_price=float(entry_price),
                filled_qty=float(qty),
                filled_price=float(entry_price),
                commission=float(commission),
                instrument_spec=ProfitCalculator.spec_dict(
                    str(signal.get("instrument", "")), str(signal.get("signal", ""))
                ),
                status="OPEN",
                approved_at=now,
                executed_at=now,
            )
            session.add(order_obj)
            session.commit()
            session.refresh(order_obj)
            return order_obj.to_dict()
        finally:
            session.close()

    def get_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get orders, optionally filtered by status."""
        session = self.db.get_session()
        try:
            query = session.query(Order)
            if status:
                query = query.filter(Order.status == status)
            orders = query.order_by(Order.id.asc()).all()
            return [o.to_dict() for o in orders]
        finally:
            session.close()

    def close_order(self, order_id: str, exit_price: float) -> dict[str, Any] | None:
        """Close an open order."""
        if exit_price <= 0:
            raise ValueError("exit_price must be > 0")

        session = self.db.get_session()
        try:
            order_obj = (
                session.query(Order)
                .filter(and_(Order.order_id == order_id, Order.status == "OPEN"))
                .first()
            )

            if not order_obj:
                return None

            db_order = cast(Any, order_obj)
            db_order.status = "CLOSED"
            db_order.exit_price = float(exit_price)
            db_order.realized_pnl = round(
                ProfitCalculator.order_pnl(order_obj.to_dict(), exit_price), 2
            )
            db_order.closed_at = datetime.now(UTC)
            session.commit()
            session.refresh(order_obj)
            return order_obj.to_dict()
        finally:
            session.close()

    def get_daily_pnl(self) -> dict[str, Any]:
        """Calculate daily P&L from closed orders."""
        today = datetime.now(UTC).date()
        session = self.db.get_session()
        try:
            orders = (
                session.query(Order)
                .filter(
                    and_(
                        Order.status == "CLOSED",
                        Order.closed_at.isnot(None),
                    )
                )
                .all()
            )

            pnl = 0.0
            closed = 0
            open_count = session.query(Order).filter(Order.status == "OPEN").count()

            for order in orders:
                if (
                    order.closed_at
                    and order.closed_at.date() == today
                    and order.realized_pnl is not None
                ):
                    pnl += float(order.realized_pnl)
                    closed += 1

            return {
                "date": str(today),
                "daily_pnl": round(pnl, 2),
                "closed_orders": closed,
                "open_orders": open_count,
            }
        finally:
            session.close()

    def get_total_pnl(self) -> float:
        """Calculate total P&L across all closed orders."""
        session = self.db.get_session()
        try:
            orders = session.query(Order).filter(Order.status == "CLOSED").all()

            pnl = 0.0
            for order in orders:
                if order.realized_pnl is not None:
                    pnl += float(order.realized_pnl)

            return round(pnl, 2)
        finally:
            session.close()
