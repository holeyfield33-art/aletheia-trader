from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from audit.aletheia_wrapper import AletheiaWrapper


class AletheiaCoreGuard:
    """Thin guardrail wrapper to ensure all decisions pass through Aletheia audit."""

    def __init__(self, gateway_url: str | None = None, api_key: str | None = None) -> None:
        self.wrapper = AletheiaWrapper(gateway_url=gateway_url, api_key=api_key)

    def audit_decision(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        audit_payload = {
            **payload,
            "guard_timestamp": datetime.now(UTC).isoformat(),
            "guard": "aletheia_core",
        }
        return self.wrapper.audit(
            action=action, payload=audit_payload, policy_pack="trading_signal"
        )

    def audit_market_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.wrapper.audit(
            action="market_data_request",
            payload=payload,
            policy_pack="market_data",
        )
