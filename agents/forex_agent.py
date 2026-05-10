from __future__ import annotations

import os
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from agents.signal_engine import SignalEngine
from audit.aletheia_wrapper import AletheiaWrapper

load_dotenv()


class ForexAgent:
    """Generate forex signals and send each decision through audit."""

    def __init__(self, gateway_url: str | None = None, api_key: str | None = None) -> None:
        self.gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
        self.api_key = api_key or os.getenv("GATEWAY_API_KEY", "")
        self.engine = SignalEngine()
        self.auditor = AletheiaWrapper(self.gateway_url, self.api_key)

    def get_forex_data(self, pair: str, period: str = "5d", interval: str = "15m"):
        mapping = {"EUR/USD": "FXE", "GBP/USD": "FXB", "USD/JPY": "FXY"}
        ticker = mapping.get(pair, "FXE")
        data = yf.download(
            ticker, period=period, interval=interval, auto_adjust=True, progress=False
        )
        if data.empty:
            return data

        if "Close" in data.columns:
            data = data.rename(columns={"Close": "close"})
        elif "close" not in data.columns:
            data["close"] = data.iloc[:, 0]
        return data

    def _fallback_signal(self, pair: str) -> dict[str, object]:
        # Synthetic close series keeps local dev/test e2e flows functional when market data is unavailable.
        synthetic = pd.DataFrame(
            {"close": [100, 100.4, 100.9, 100.5, 100.1, 99.8, 100.2, 100.6, 100.3, 100.0]}
        )
        signal, indicators = self.engine.generate_forex_signal(synthetic)
        payload = {
            "instrument_type": "forex",
            "pair": pair,
            "signal": signal,
            "indicators": indicators,
            "approval_required": True,
            "fallback_mode": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)
        return {
            "pair": pair,
            "signal": signal,
            "meta": indicators,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }

    def run(self, pair: str = "EUR/USD") -> dict[str, object]:
        data = self.get_forex_data(pair)
        if data.empty:
            return self._fallback_signal(pair)

        signal, indicators = self.engine.generate_forex_signal(data)
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
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }
