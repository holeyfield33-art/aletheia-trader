from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import OrderRequest


@dataclass
class AlpacaConfig:
    api_key: str
    secret_key: str
    endpoint: str
    paper: bool
    dry_run: bool


class AlpacaBroker:
    """Alpaca live/paper broker adapter with optional dry-run mode."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        endpoint: str | None = None,
        paper: bool | None = None,
        dry_run: bool | None = None,
        client: TradingClient | None = None,
    ) -> None:
        resolved_endpoint = str(
            endpoint or os.getenv("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets")
        )
        endpoint_lower = str(resolved_endpoint).lower()
        resolved_paper = (
            bool(paper)
            if paper is not None
            else ("paper" in endpoint_lower or "data" not in endpoint_lower)
        )
        if dry_run is None:
            dry_run = os.getenv("ALPACA_DRY_RUN", "true").lower() != "false"

        resolved_api_key = str(api_key or os.getenv("ALPACA_API_KEY", ""))
        resolved_secret_key = str(secret_key or os.getenv("ALPACA_SECRET_KEY", ""))

        self.config = AlpacaConfig(
            api_key=resolved_api_key,
            secret_key=resolved_secret_key,
            endpoint=resolved_endpoint,
            paper=resolved_paper,
            dry_run=bool(dry_run),
        )
        if client is not None:
            self._client: TradingClient | None = client
        elif self.config.dry_run and (not self.config.api_key or not self.config.secret_key):
            # Allow dry-run workflows without forcing API credentials.
            self._client = None
        else:
            self._client = TradingClient(
                api_key=self.config.api_key,
                secret_key=self.config.secret_key,
                paper=self.config.paper,
                url_override=self.config.endpoint,
            )

    @property
    def dry_run(self) -> bool:
        return self.config.dry_run

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        payload = self._from_internal_order(order)
        if self.config.dry_run:
            return {
                "status": "dry_run",
                "endpoint": f"{self.config.endpoint}/v2/orders",
                "payload": payload,
                "config": asdict(self.config),
            }

        request = self._build_order_request(payload)
        client = self._require_client()
        response = client.submit_order(order_data=request)
        return self._serialize(response)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        if self.config.dry_run:
            return {
                "status": "dry_run",
                "action": "cancel_order",
                "order_id": order_id,
            }
        client = self._require_client()
        client.cancel_order_by_id(order_id)
        return {"status": "cancelled", "order_id": order_id}

    def get_positions(self) -> list[dict[str, Any]]:
        client = self._require_client()
        positions = client.get_all_positions()
        return [self._serialize(position) for position in positions]

    def get_account(self) -> dict[str, Any]:
        client = self._require_client()
        account = client.get_account()
        return self._serialize(account)

    def _require_client(self) -> TradingClient:
        if self._client is None:
            raise RuntimeError(
                "Alpaca client unavailable. Configure ALPACA_API_KEY/ALPACA_SECRET_KEY or inject client."
            )
        return self._client

    def _from_internal_order(self, order: dict[str, Any]) -> dict[str, Any]:
        side_token = str(order.get("side", "buy")).upper()
        order_type = str(order.get("order_type", "market")).lower()
        tif = str(order.get("time_in_force", "gtc")).lower()

        mapped_side = "buy"
        if side_token in {"SELL", "PUT_BUY", "SHORT"}:
            mapped_side = "sell"

        payload: dict[str, Any] = {
            "symbol": str(order.get("instrument") or order.get("symbol") or "").upper(),
            "qty": float(order.get("filled_qty", order.get("qty", 0.0)) or 0.0),
            "side": mapped_side,
            "type": order_type,
            "time_in_force": tif,
            "client_order_id": order.get("request_id") or order.get("client_order_id"),
        }

        if order_type in {"limit", "stop_limit"}:
            payload["limit_price"] = float(
                order.get("limit_price", order.get("entry_price", 0.0)) or 0.0
            )
        if order_type in {"stop", "stop_limit"}:
            payload["stop_price"] = float(order.get("stop_price", 0.0) or 0.0)
        if order_type == "trailing_stop":
            trail_price = order.get("trail_price")
            trail_percent = order.get("trail_percent")
            if trail_price is not None:
                payload["trail_price"] = float(trail_price)
            if trail_percent is not None:
                payload["trail_percent"] = float(trail_percent)
        return payload

    @staticmethod
    def _build_order_request(payload: dict[str, Any]) -> OrderRequest:
        order_type = str(payload.get("type", "market")).lower()
        tif = str(payload.get("time_in_force", "gtc")).lower()

        request_payload: dict[str, Any] = {
            "symbol": str(payload["symbol"]),
            "qty": float(payload["qty"]),
            "side": OrderSide.BUY if payload["side"] == "buy" else OrderSide.SELL,
            "type": {
                "market": OrderType.MARKET,
                "limit": OrderType.LIMIT,
                "stop": OrderType.STOP,
                "stop_limit": OrderType.STOP_LIMIT,
                "trailing_stop": OrderType.TRAILING_STOP,
            }.get(order_type, OrderType.MARKET),
            "time_in_force": {
                "day": TimeInForce.DAY,
                "gtc": TimeInForce.GTC,
                "ioc": TimeInForce.IOC,
                "fok": TimeInForce.FOK,
                "opg": TimeInForce.OPG,
                "cls": TimeInForce.CLS,
            }.get(tif, TimeInForce.GTC),
            "client_order_id": payload.get("client_order_id"),
        }

        for key in ["limit_price", "stop_price", "trail_price", "trail_percent"]:
            if key in payload and payload[key] not in {None, 0, 0.0}:
                request_payload[key] = payload[key]

        return OrderRequest(**request_payload)

    @staticmethod
    def _serialize(value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return dumped
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return {"value": str(value)}
