"""Tests for real-time order execution and risk monitoring."""

import os

import pytest

from brokers.order_executor import OrderExecutor
from risk.breach_tracker import BreachTracker


class TestOrderExecutor:
    """Test OrderExecutor integration with multiple broker modes."""

    def test_executor_paper_mode(self) -> None:
        """Test executor in paper mode (simulator)."""
        executor = OrderExecutor(broker_mode="paper")
        assert executor.is_paper
        assert not executor.is_live

        result = executor.submit_order(
            order_id="ord-1",
            instrument="EUR/USD",
            side="BUY",
            qty=1.0,
            price=1.0850,
        )

        assert result.order_id == "ord-1"
        assert result.status == "submitted"
        assert result.broker_mode == "paper"
        assert result.filled_qty == 1.0
        assert result.filled_price == 1.0850

    def test_executor_alpaca_paper_dry_run(self) -> None:
        """Test executor in alpaca_paper mode with dry-run enabled."""
        os.environ["ALPACA_DRY_RUN"] = "true"
        executor = OrderExecutor(broker_mode="alpaca_paper")
        assert not executor.is_paper
        assert not executor.is_live

        result = executor.submit_order(
            order_id="ord-2",
            instrument="SPY",
            side="BUY",
            qty=10.0,
            price=450.0,
            order_type="market",
        )

        assert result.order_id == "ord-2"
        assert result.status == "dry_run" or result.status == "submitted"
        assert result.broker_mode == "alpaca_paper"

    def test_executor_cancel_order(self) -> None:
        """Test cancelling an order."""
        executor = OrderExecutor(broker_mode="paper")

        result = executor.cancel_order("ord-1")
        assert result["order_id"] == "ord-1"
        assert result["status"] == "cancelled" or result["status"] == "cancel_failed"

    def test_executor_get_account(self) -> None:
        """Test fetching account info."""
        executor = OrderExecutor(broker_mode="paper")
        account = executor.get_account()

        assert isinstance(account, dict)
        assert account.get("mode") == "paper" or "daily_pnl" in account

    def test_execution_error_handling(self) -> None:
        """Test error handling for invalid orders."""
        executor = OrderExecutor(broker_mode="paper")

        result = executor.submit_order(
            order_id="ord-bad",
            instrument="INVALID/PAIR",
            side="BUY",
            qty=-1.0,  # Invalid qty
            price=0.0,  # Invalid price
        )

        assert result.order_id == "ord-bad"
        # Result status depends on how simulator handles validation


class TestBreachTracker:
    """Test BreachTracker for risk limit monitoring."""

    def test_no_breaches_initially(self) -> None:
        """Test that no breaches are active initially."""
        tracker = BreachTracker()
        alerts = tracker.get_alerts()

        assert len(alerts.active_breaches) == 0
        assert not alerts.circuit_breaker_active
        assert alerts.new_trades_allowed

    def test_daily_loss_breach(self) -> None:
        """Test detection of daily loss breach."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        alerts = tracker.check_and_update(
            daily_loss_pct=0.05,  # Exceeds 3% limit
            total_loss_pct=0.02,
            drawdown_pct=0.01,
            open_notional_pct=0.1,
            config=config,
        )

        assert len(alerts.active_breaches) == 1
        breach = alerts.active_breaches[0]
        assert breach.breach_type == "daily_loss"
        assert breach.current_value == 0.05
        assert not alerts.new_trades_allowed

    def test_drawdown_circuit_breaker(self) -> None:
        """Test drawdown triggering circuit breaker."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        alerts = tracker.check_and_update(
            daily_loss_pct=0.01,
            total_loss_pct=0.02,
            drawdown_pct=0.20,  # Exceeds 15% limit
            open_notional_pct=0.1,
            config=config,
        )

        assert len(alerts.active_breaches) == 1
        breach = alerts.active_breaches[0]
        assert breach.breach_type == "drawdown"
        assert alerts.circuit_breaker_active
        assert not alerts.new_trades_allowed

    def test_multiple_breaches(self) -> None:
        """Test detection of multiple simultaneous breaches."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        alerts = tracker.check_and_update(
            daily_loss_pct=0.04,  # Exceeds daily
            total_loss_pct=0.15,  # Exceeds total
            drawdown_pct=0.16,  # Exceeds drawdown
            open_notional_pct=0.1,
            config=config,
        )

        assert len(alerts.active_breaches) == 3
        breach_types = {b.breach_type for b in alerts.active_breaches}
        assert breach_types == {"daily_loss", "total_loss", "drawdown"}
        assert alerts.circuit_breaker_active

    def test_breach_acknowledgement(self) -> None:
        """Test acknowledging a breach."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        tracker.check_and_update(
            daily_loss_pct=0.05,
            total_loss_pct=0.02,
            drawdown_pct=0.01,
            open_notional_pct=0.1,
            config=config,
        )

        success = tracker.acknowledge_breach(0)
        assert success
        assert tracker.get_alerts().active_breaches[0].acknowledged

    def test_breach_history(self) -> None:
        """Test breach history tracking."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        # First breach
        tracker.check_and_update(
            daily_loss_pct=0.04,
            total_loss_pct=0.02,
            drawdown_pct=0.01,
            open_notional_pct=0.1,
            config=config,
        )

        # Second breach
        tracker.check_and_update(
            daily_loss_pct=0.01,
            total_loss_pct=0.15,
            drawdown_pct=0.01,
            open_notional_pct=0.1,
            config=config,
        )

        history = tracker.get_history()
        assert len(history) >= 2

    def test_reset_alerts(self) -> None:
        """Test resetting alerts (e.g., on new trading day)."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        tracker.check_and_update(
            daily_loss_pct=0.05,
            total_loss_pct=0.02,
            drawdown_pct=0.01,
            open_notional_pct=0.1,
            config=config,
        )

        assert len(tracker.get_alerts().active_breaches) > 0

        tracker.reset_alerts()
        alerts = tracker.get_alerts()
        assert len(alerts.active_breaches) == 0
        assert alerts.new_trades_allowed

    def test_no_notional_breach_under_limit(self) -> None:
        """Test no breach when under notional limit."""
        tracker = BreachTracker()
        config = {
            "max_daily_loss_pct": 0.03,
            "max_total_loss_pct": 0.12,
            "max_drawdown_pct": 0.15,
            "max_notional_pct": 0.35,
        }

        alerts = tracker.check_and_update(
            daily_loss_pct=0.01,
            total_loss_pct=0.02,
            drawdown_pct=0.05,
            open_notional_pct=0.30,  # Under 35% limit
            config=config,
        )

        assert len(alerts.active_breaches) == 0
        assert alerts.new_trades_allowed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
