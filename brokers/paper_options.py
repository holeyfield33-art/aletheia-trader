from __future__ import annotations

from brokers.simulator import PaperSimulator


class PaperOptionsBroker:
    """Paper options broker wrapper backed by local simulator."""

    def __init__(self, simulator: PaperSimulator | None = None) -> None:
        self.simulator = simulator or PaperSimulator()

    def place_signal_order(
        self, symbol: str, signal: str, reference_price: float, qty: float = 1.0
    ) -> dict[str, object]:
        return self.simulator.submit_order(
            instrument=symbol,
            side=signal,
            qty=qty,
            price=reference_price,
            approved=False,
        )
