"""Real-time risk breach detection and alerting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass
class RiskBreach:
    """Single risk limit breach event."""

    breach_type: Literal["daily_loss", "total_loss", "drawdown", "max_notional"]
    current_value: float
    limit: float
    message: str
    detected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    acknowledged: bool = False
    severity: Literal["warning", "critical"] = "warning"


@dataclass
class BreachAlert:
    """Batch of active breaches for monitoring."""

    active_breaches: list[RiskBreach] = field(default_factory=list)
    circuit_breaker_active: bool = False
    last_update: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    new_trades_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_breaches": [
                {
                    "type": b.breach_type,
                    "current_value": b.current_value,
                    "limit": b.limit,
                    "message": b.message,
                    "detected_at": b.detected_at,
                    "acknowledged": b.acknowledged,
                    "severity": b.severity,
                }
                for b in self.active_breaches
            ],
            "circuit_breaker_active": self.circuit_breaker_active,
            "new_trades_allowed": self.new_trades_allowed,
            "last_update": self.last_update,
        }


class BreachTracker:
    """Monitor portfolio for real-time risk breaches."""

    def __init__(self) -> None:
        self._alerts = BreachAlert()
        self._history: list[RiskBreach] = []

    def check_and_update(
        self,
        daily_loss_pct: float,
        total_loss_pct: float,
        drawdown_pct: float,
        open_notional_pct: float,
        config: dict[str, float],
    ) -> BreachAlert:
        """Check all limits and return updated alert state."""
        new_breaches: list[RiskBreach] = []

        # Check daily loss
        if daily_loss_pct >= config.get("max_daily_loss_pct", 0.03):
            new_breaches.append(
                RiskBreach(
                    breach_type="daily_loss",
                    current_value=daily_loss_pct,
                    limit=config.get("max_daily_loss_pct", 0.03),
                    message=f"Daily loss {daily_loss_pct:.2%} exceeds limit {config.get('max_daily_loss_pct', 0.03):.2%}",
                    severity=(
                        "critical"
                        if daily_loss_pct >= config.get("max_daily_loss_pct", 0.03) * 1.2
                        else "warning"
                    ),
                )
            )

        # Check total loss
        if total_loss_pct >= config.get("max_total_loss_pct", 0.12):
            new_breaches.append(
                RiskBreach(
                    breach_type="total_loss",
                    current_value=total_loss_pct,
                    limit=config.get("max_total_loss_pct", 0.12),
                    message=f"Total loss {total_loss_pct:.2%} exceeds limit {config.get('max_total_loss_pct', 0.12):.2%}",
                    severity="critical",
                )
            )

        # Check drawdown (circuit breaker)
        if drawdown_pct >= config.get("max_drawdown_pct", 0.15):
            new_breaches.append(
                RiskBreach(
                    breach_type="drawdown",
                    current_value=drawdown_pct,
                    limit=config.get("max_drawdown_pct", 0.15),
                    message=f"Drawdown {drawdown_pct:.2%} exceeds limit {config.get('max_drawdown_pct', 0.15):.2%}",
                    severity="critical",
                )
            )

        # Check max notional
        if open_notional_pct >= config.get("max_notional_pct", 0.35):
            new_breaches.append(
                RiskBreach(
                    breach_type="max_notional",
                    current_value=open_notional_pct,
                    limit=config.get("max_notional_pct", 0.35),
                    message=f"Open notional {open_notional_pct:.2%} exceeds limit {config.get('max_notional_pct', 0.35):.2%}",
                    severity="warning",
                )
            )

        # Update breach state
        self._alerts.active_breaches = new_breaches
        self._alerts.circuit_breaker_active = any(b.breach_type == "drawdown" for b in new_breaches)
        self._alerts.new_trades_allowed = len(new_breaches) == 0
        self._alerts.last_update = datetime.now(UTC).isoformat()

        # Track history
        for breach in new_breaches:
            self._history.append(breach)

        return self._alerts

    def get_alerts(self) -> BreachAlert:
        """Return current alert state."""
        return self._alerts

    def acknowledge_breach(self, breach_index: int) -> bool:
        """Mark a breach as acknowledged."""
        if 0 <= breach_index < len(self._alerts.active_breaches):
            self._alerts.active_breaches[breach_index].acknowledged = True
            return True
        return False

    def reset_alerts(self) -> None:
        """Clear all breaches (e.g., on new trading day)."""
        self._alerts.active_breaches = []
        self._alerts.circuit_breaker_active = False
        self._alerts.new_trades_allowed = True

    def get_history(self) -> list[RiskBreach]:
        """Return full breach history."""
        return self._history
