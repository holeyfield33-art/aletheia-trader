from __future__ import annotations

import os
from datetime import UTC, datetime
from logging import getLogger

from dotenv import load_dotenv

from agents.signal_engine import SignalEngine
from audit.aletheia_wrapper import AletheiaWrapper
from backtesting.data import DataManager, DataUnavailableException

load_dotenv()
logger = getLogger(__name__)


class ForexAgent:
    """Generate forex signals and send each decision through audit."""

    def __init__(
        self,
        gateway_url: str | None = None,
        api_key: str | None = None,
        data_manager: DataManager | None = None,
    ) -> None:
        self.gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
        self.api_key = api_key or os.getenv("GATEWAY_API_KEY", "")
        self.engine = SignalEngine()
        self.auditor = AletheiaWrapper(self.gateway_url, self.api_key)
        self.data_manager = data_manager or DataManager(
            gateway_url=self.gateway_url,
            api_key=self.api_key,
        )

    def get_forex_data(self, pair: str, period: str = "5d", interval: str = "15m"):
        start, end = self.data_manager.period_to_date_range(period)
        data = self.data_manager.download(
            symbol=pair,
            timeframe=interval,
            start=start,
            end=end,
        )
        if data.empty:
            return data
        return data

    def _fallback_signal(self, pair: str) -> None:
        logger.critical(
            "Data feed interrupted for %s. Synthetic fallback is disabled; no signal generated.",
            pair,
        )
        return None

    def run(self, pair: str = "EUR/USD") -> dict[str, object]:
        try:
            data = self.get_forex_data(pair)
        except DataUnavailableException as exc:
            self._fallback_signal(pair)
            return {
                "pair": pair,
                "signal": "NO_SIGNAL",
                "meta": {},
                "filter_reason": f"Data feed interrupted: {exc}",
                "receipt": "mock-receipt",
                "approved": False,
                "data_stale": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        if data.empty:
            self._fallback_signal(pair)
            return {
                "pair": pair,
                "signal": "NO_SIGNAL",
                "meta": {},
                "filter_reason": "Data feed interrupted: empty dataset",
                "receipt": "mock-receipt",
                "approved": False,
                "data_stale": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        signal, indicators, filter_reason = self.engine.generate_forex_signal(data)
        payload = {
            "instrument_type": "forex",
            "pair": pair,
            "signal": signal,
            "indicators": indicators,
            "approval_required": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)
        return {
            "pair": pair,
            "signal": signal,
            "meta": indicators,
            "filter_reason": filter_reason,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }
