"""Tests for database-backed ledger."""

import os
import tempfile
from datetime import UTC, datetime

import pytest

from brokers.ledger_db import DatabaseLedger
from brokers.ledger_migration import export_db_to_json, migrate_json_to_db


class TestDatabaseLedger:
    """Test DatabaseLedger functionality."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db_url = f"sqlite:///{db_path}"
            ledger = DatabaseLedger(db_url)
            yield ledger

    def test_add_signal(self, temp_db):
        """Test adding a signal to the database."""
        result = temp_db.add_signal(
            signal_id="sig-1",
            agent_type="forex",
            instrument="EUR/USD",
            signal="BUY",
            indicators={"rsi": 70.0, "macd": 0.5},
            chain_data=None,
            receipt="mock-123",
            ttl_minutes=120,
        )

        assert result["signal_id"] == "sig-1"
        assert result["status"] == "PENDING"
        assert result["instrument"] == "EUR/USD"

    def test_get_pending_signals(self, temp_db):
        """Test retrieving pending signals."""
        temp_db.add_signal(
            signal_id="sig-1",
            agent_type="forex",
            instrument="EUR/USD",
            signal="BUY",
            indicators={},
            chain_data=None,
            receipt="mock-123",
            ttl_minutes=120,
        )
        temp_db.add_signal(
            signal_id="sig-2",
            agent_type="options",
            instrument="SPY",
            signal="SELL",
            indicators={},
            chain_data=None,
            receipt="mock-124",
            ttl_minutes=120,
        )

        signals = temp_db.get_pending_signals()
        assert len(signals) == 2
        assert signals[0]["signal_id"] == "sig-1"
        assert signals[1]["signal_id"] == "sig-2"

    def test_approve_signal(self, temp_db):
        """Test approving a signal."""
        temp_db.add_signal(
            signal_id="sig-1",
            agent_type="forex",
            instrument="EUR/USD",
            signal="BUY",
            indicators={},
            chain_data=None,
            receipt="mock-123",
            ttl_minutes=120,
        )

        result = temp_db.approve_signal("sig-1")
        assert result["status"] == "APPROVED"
        assert result["approved_at"] is not None

    def test_reject_signal(self, temp_db):
        """Test rejecting a signal."""
        temp_db.add_signal(
            signal_id="sig-1",
            agent_type="forex",
            instrument="EUR/USD",
            signal="BUY",
            indicators={},
            chain_data=None,
            receipt="mock-123",
            ttl_minutes=120,
        )

        success = temp_db.reject_signal("sig-1")
        assert success

        signals = temp_db.get_pending_signals()
        assert len(signals) == 0

    def test_create_order_from_signal(self, temp_db):
        """Test creating an order from a signal."""
        signal_dict = {
            "signal_id": "sig-1",
            "instrument": "EUR/USD",
            "signal": "BUY",
        }

        order = temp_db.create_order_from_signal(
            signal_dict, entry_price=1.0850, qty=1.0, commission=0.0
        )

        assert order["order_id"] == "ord-1"
        assert order["status"] == "OPEN"
        assert order["entry_price"] == 1.0850
        assert order["qty"] == 1.0

    def test_get_orders(self, temp_db):
        """Test retrieving orders."""
        signal_dict = {
            "signal_id": "sig-1",
            "instrument": "EUR/USD",
            "signal": "BUY",
        }

        temp_db.create_order_from_signal(signal_dict, entry_price=1.0850, qty=1.0)
        temp_db.create_order_from_signal(signal_dict, entry_price=1.0900, qty=2.0)

        orders = temp_db.get_orders()
        assert len(orders) == 2
        assert orders[0]["status"] == "OPEN"

    def test_close_order(self, temp_db):
        """Test closing an order."""
        signal_dict = {
            "signal_id": "sig-1",
            "instrument": "EUR/USD",
            "signal": "BUY",
        }

        temp_db.create_order_from_signal(signal_dict, entry_price=1.0850, qty=1.0)

        closed = temp_db.close_order("ord-1", exit_price=1.0900)
        assert closed["status"] == "CLOSED"
        assert closed["exit_price"] == 1.0900
        assert closed["realized_pnl"] is not None

    def test_get_daily_pnl(self, temp_db):
        """Test daily P&L calculation."""
        signal_dict = {
            "signal_id": "sig-1",
            "instrument": "EUR/USD",
            "signal": "BUY",
        }

        temp_db.create_order_from_signal(signal_dict, entry_price=1.0850, qty=1.0)
        temp_db.close_order("ord-1", exit_price=1.0900)

        daily_pnl = temp_db.get_daily_pnl()
        assert daily_pnl["daily_pnl"] != 0.0
        assert daily_pnl["closed_orders"] == 1

    def test_get_total_pnl(self, temp_db):
        """Test total P&L calculation."""
        signal_dict = {
            "signal_id": "sig-1",
            "instrument": "EUR/USD",
            "signal": "BUY",
        }

        temp_db.create_order_from_signal(signal_dict, entry_price=1.0850, qty=1.0)
        temp_db.close_order("ord-1", exit_price=1.0900)

        total_pnl = temp_db.get_total_pnl()
        assert isinstance(total_pnl, float)
        assert total_pnl != 0.0


class TestDatabaseMigration:
    """Test migration utilities."""

    def test_json_to_db_migration(self):
        """Test migrating JSON to database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create temporary JSON files
            import json

            json_dir = os.path.join(tmpdir, "data")
            os.makedirs(json_dir)

            signals_file = os.path.join(json_dir, "signals.json")
            orders_file = os.path.join(json_dir, "orders.json")

            signals_data = [
                {
                    "signal_id": "sig-1",
                    "agent_type": "forex",
                    "instrument": "EUR/USD",
                    "signal": "BUY",
                    "indicators": {},
                    "chain_data": None,
                    "receipt": "mock-123",
                    "status": "PENDING",
                    "created_at": datetime.now(UTC).isoformat(),
                    "expires_at": str(datetime.now(UTC).timestamp() + 120 * 60),
                    "approved_at": None,
                }
            ]
            orders_data = [
                {
                    "order_id": "ord-1",
                    "signal_id": "sig-1",
                    "instrument": "EUR/USD",
                    "side": "BUY",
                    "qty": 1.0,
                    "entry_price": 1.0850,
                    "filled_qty": 1.0,
                    "filled_price": 1.0850,
                    "commission": 0.0,
                    "instrument_spec": {"asset_class": "forex"},
                    "status": "OPEN",
                    "exit_price": None,
                    "realized_pnl": None,
                    "approved_at": datetime.now(UTC).isoformat(),
                    "executed_at": datetime.now(UTC).isoformat(),
                    "closed_at": None,
                }
            ]

            with open(signals_file, "w") as f:
                json.dump(signals_data, f)
            with open(orders_file, "w") as f:
                json.dump(orders_data, f)

            # Run migration
            db_url = f"sqlite:///{os.path.join(tmpdir, 'test.db')}"
            result = migrate_json_to_db(signals_file, orders_file, db_url)

            assert result["signals_migrated"] == 1
            assert result["orders_migrated"] == 1

    def test_db_to_json_export(self):
        """Test exporting database to JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_url = f"sqlite:///{os.path.join(tmpdir, 'test.db')}"
            ledger = DatabaseLedger(db_url)

            # Add some data
            ledger.add_signal(
                signal_id="sig-1",
                agent_type="forex",
                instrument="EUR/USD",
                signal="BUY",
                indicators={},
                chain_data=None,
                receipt="mock-123",
                ttl_minutes=120,
            )

            # Export
            export_dir = os.path.join(tmpdir, "export")
            result = export_db_to_json(
                db_url,
                os.path.join(export_dir, "signals_backup.json"),
                os.path.join(export_dir, "orders_backup.json"),
            )

            assert result["signals_exported"] == 1
            assert result["orders_exported"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
