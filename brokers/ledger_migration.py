"""Migration utilities for converting JSON ledger to database."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from brokers.db import DatabaseManager, Order, Signal


def migrate_json_to_db(
    json_signals_path: str = "data/pending_signals.json",
    json_orders_path: str = "data/approved_orders.json",
    db_url: str = "sqlite:///./trading.db",
) -> dict[str, int]:
    """Migrate JSON ledger data to database.

    Returns:
        Dictionary with counts: {"signals_migrated": N, "orders_migrated": M}
    """
    db = DatabaseManager(db_url)
    db.init_db()

    migrated = {"signals_migrated": 0, "orders_migrated": 0}

    # Migrate signals
    signals_file = Path(json_signals_path)
    if signals_file.exists():
        session = db.get_session()
        try:
            with open(signals_file, encoding="utf-8") as f:
                raw = f.read().strip()
                if raw:
                    signals_data = json.loads(raw)
                    for sig_dict in signals_data:
                        # Check if already exists
                        sig_id = sig_dict.get("signal_id")
                        if not session.query(Signal).filter(Signal.signal_id == sig_id).first():
                            signal_obj = Signal(
                                signal_id=sig_id,
                                agent_type=sig_dict.get("agent_type", ""),
                                instrument=sig_dict.get("instrument", ""),
                                signal=sig_dict.get("signal", ""),
                                indicators=sig_dict.get("indicators", {}),
                                chain_data=sig_dict.get("chain_data"),
                                receipt=sig_dict.get("receipt", ""),
                                status=sig_dict.get("status", "PENDING"),
                                created_at=datetime.fromisoformat(
                                    sig_dict.get("created_at", datetime.now(UTC).isoformat())
                                ),
                                expires_at=(
                                    datetime.fromtimestamp(
                                        float(sig_dict.get("expires_at", 0))
                                    ).replace(tzinfo=UTC)
                                    if sig_dict.get("expires_at")
                                    else None
                                ),
                                approved_at=(
                                    datetime.fromisoformat(sig_dict.get("approved_at"))
                                    if sig_dict.get("approved_at")
                                    else None
                                ),
                            )
                            session.add(signal_obj)
                            migrated["signals_migrated"] += 1
            session.commit()
        finally:
            session.close()

    # Migrate orders
    orders_file = Path(json_orders_path)
    if orders_file.exists():
        session = db.get_session()
        try:
            with open(orders_file, encoding="utf-8") as f:
                raw = f.read().strip()
                if raw:
                    orders_data = json.loads(raw)
                    for ord_dict in orders_data:
                        # Check if already exists
                        ord_id = ord_dict.get("order_id")
                        if not session.query(Order).filter(Order.order_id == ord_id).first():
                            order_obj = Order(
                                order_id=ord_id,
                                signal_id=ord_dict.get("signal_id"),
                                instrument=ord_dict.get("instrument", ""),
                                side=ord_dict.get("side", ""),
                                qty=float(ord_dict.get("qty", 0.0)),
                                entry_price=float(ord_dict.get("entry_price", 0.0)),
                                filled_qty=float(ord_dict.get("filled_qty", 0.0)),
                                filled_price=float(ord_dict.get("filled_price", 0.0)),
                                commission=float(ord_dict.get("commission", 0.0)),
                                instrument_spec=ord_dict.get("instrument_spec"),
                                status=ord_dict.get("status", "OPEN"),
                                exit_price=(
                                    float(ord_dict.get("exit_price"))
                                    if ord_dict.get("exit_price")
                                    else None
                                ),
                                realized_pnl=(
                                    float(ord_dict.get("realized_pnl"))
                                    if ord_dict.get("realized_pnl")
                                    else None
                                ),
                                approved_at=datetime.fromisoformat(
                                    ord_dict.get("approved_at", datetime.now(UTC).isoformat())
                                ),
                                executed_at=datetime.fromisoformat(
                                    ord_dict.get("executed_at", datetime.now(UTC).isoformat())
                                ),
                                closed_at=(
                                    datetime.fromisoformat(ord_dict.get("closed_at"))
                                    if ord_dict.get("closed_at")
                                    else None
                                ),
                            )
                            session.add(order_obj)
                            migrated["orders_migrated"] += 1
            session.commit()
        finally:
            session.close()

    return migrated


def export_db_to_json(
    db_url: str = "sqlite:///./trading.db",
    output_signals_path: str = "data/signals_backup.json",
    output_orders_path: str = "data/orders_backup.json",
) -> dict[str, int]:
    """Export database data back to JSON for backup/compatibility.

    Returns:
        Dictionary with counts: {"signals_exported": N, "orders_exported": M}
    """
    db = DatabaseManager(db_url)
    exported = {"signals_exported": 0, "orders_exported": 0}

    # Export signals
    session = db.get_session()
    try:
        signals = session.query(Signal).all()
        signals_data = [s.to_dict() for s in signals]
        Path(output_signals_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_signals_path, "w", encoding="utf-8") as f:
            json.dump(signals_data, f, indent=2)
        exported["signals_exported"] = len(signals_data)
    finally:
        session.close()

    # Export orders
    session = db.get_session()
    try:
        orders = session.query(Order).all()
        orders_data = [o.to_dict() for o in orders]
        Path(output_orders_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_orders_path, "w", encoding="utf-8") as f:
            json.dump(orders_data, f, indent=2)
        exported["orders_exported"] = len(orders_data)
    finally:
        session.close()

    return exported
