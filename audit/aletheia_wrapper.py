from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

import requests
from dotenv import load_dotenv


load_dotenv()


def _normalize_gateway_base_url(gateway_url: str) -> str:
    """Normalize URL to a base host URL without /v1/audit suffix."""
    base_url = gateway_url.rstrip("/")
    if base_url.endswith("/v1/audit"):
        base_url = base_url[: -len("/v1/audit")]
    return base_url


def audit_signal(signal_data: Dict[str, Any], gateway_url: str | None = None, api_key: str | None = None) -> Dict[str, Any]:
    """Audit signal payload and return a gateway or mock receipt."""
    resolved_gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
    resolved_api_key = api_key or os.getenv("GATEWAY_API_KEY", "")

    if not resolved_gateway_url:
        return {
            "status": "mock",
            "receipt": f"mock-{int(datetime.now().timestamp())}",
            "event": signal_data,
        }

    audit_endpoint = f"{_normalize_gateway_base_url(resolved_gateway_url)}/v1/audit"

    try:
        response = requests.post(
            audit_endpoint,
            json=signal_data,
            headers={"X-API-Key": resolved_api_key},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        if "receipt" not in data:
            data["receipt"] = f"gateway-{int(datetime.now().timestamp())}"
        return data
    except requests.RequestException:
        return {
            "status": "mock_fallback",
            "receipt": f"fallback-{int(datetime.now().timestamp())}",
            "event": signal_data,
        }


class AletheiaWrapper:
    def __init__(self, gateway_url: str | None = None, api_key: str | None = None) -> None:
        self.gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
        self.api_key = api_key or os.getenv("GATEWAY_API_KEY", "")

    def audit(self, action: str, payload: Dict[str, Any], policy_pack: str = "trading_signal") -> Dict[str, Any]:
        """Audit every signal/order decision; fallback to local mock receipt if unavailable."""
        event = {
            "agent_id": "aletheia_trader",
            "action": action,
            "payload": payload,
            "policy_pack": policy_pack,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision_mode": "signal_only_manual_approval",
        }
        return audit_signal(event, gateway_url=self.gateway_url, api_key=self.api_key)
