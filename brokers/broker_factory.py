from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from brokers.alpaca_broker import AlpacaBroker
from brokers.profit_calculator import ProfitCalculator
from brokers.simulator import PaperSimulator


class PaperBrokerAdapter:
    """Generic paper broker adapter with Alpaca-like methods."""

    def __init__(self, simulator: PaperSimulator | None = None) -> None:
        self.simulator = simulator or PaperSimulator()

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        instrument = str(order.get("instrument") or order.get("symbol") or "")
        side = str(order.get("side") or "BUY")
        qty = float(order.get("filled_qty", order.get("qty", 0.0)) or 0.0)
        price = float(order.get("filled_price", order.get("entry_price", 0.0)) or 0.0)
        commission = float(order.get("commission", 0.0) or 0.0)

        out = self.simulator.submit_order(
            instrument=instrument,
            side=side,
            qty=qty,
            price=price,
            approved=True,
            commission=commission,
            instrument_spec=ProfitCalculator.spec_dict(instrument, side),
        )
        out["mode"] = "paper"
        return out

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return {"status": "paper_noop", "order_id": order_id}

    def get_positions(self) -> list[dict[str, Any]]:
        orders = self.simulator.list_orders()
        return [order for order in orders if str(order.get("status")) == "OPEN"]

    def get_account(self) -> dict[str, Any]:
        pnl = self.simulator.get_daily_pnl()
        return {
            "mode": "paper",
            "daily_pnl": pnl.get("daily_pnl", 0.0),
            "open_orders": pnl.get("open_orders", 0),
            "closed_orders": pnl.get("closed_orders", 0),
        }


class BrokerFactory:
    @staticmethod
    def create(mode: str | None = None) -> PaperBrokerAdapter | AlpacaBroker:
        mode_token = mode if mode is not None else os.getenv("BROKER_MODE") or "paper"
        broker_mode = str(mode_token).strip().lower()
        dry_run = os.getenv("ALPACA_DRY_RUN", "true").lower() != "false"

        if broker_mode == "paper":
            return PaperBrokerAdapter()
        if broker_mode == "alpaca_paper":
            return AlpacaBroker(paper=True, dry_run=dry_run)
        if broker_mode == "alpaca_live":
            return AlpacaBroker(paper=False, dry_run=dry_run)

        raise ValueError(
            f"Unsupported BROKER_MODE '{broker_mode}'. Use paper|alpaca_paper|alpaca_live"
        )

    @staticmethod
    def describe(mode: str | None = None) -> dict[str, Any]:
        broker = BrokerFactory.create(mode)
        if isinstance(broker, AlpacaBroker):
            return {"type": "alpaca", **asdict(broker.config)}
        return {"type": "paper"}
