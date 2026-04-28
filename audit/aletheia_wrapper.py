from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

import requests
from dotenv import load_dotenv


load_dotenv()


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

        if not self.gateway_url:
            return {"status": "mock", "receipt": f"mock-{int(datetime.now().timestamp())}", "event": event}

        try:
            response = requests.post(
                f"{self.gateway_url.rstrip('/')}/v1/audit",
                json=event,
                headers={"X-API-Key": self.api_key},
                timeout=3,
            )
            response.raise_for_status()
            data = response.json()
            if "receipt" not in data:
                data["receipt"] = f"gateway-{int(datetime.now().timestamp())}"
            return data
        except requests.RequestException:
            return {"status": "mock_fallback", "receipt": f"fallback-{int(datetime.now().timestamp())}", "event": event}
