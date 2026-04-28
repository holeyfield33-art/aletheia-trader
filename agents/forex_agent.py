from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Dict, Optional

import requests
import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

try:
    from agents.signal_engine import SignalEngine
except ModuleNotFoundError:  # pragma: no cover
    from signal_engine import SignalEngine

try:
    from audit.aletheia_wrapper import AletheiaWrapper
except ModuleNotFoundError:  # pragma: no cover
    from aletheia_wrapper import AletheiaWrapper


load_dotenv()


class ForexAgent:
    """Generate forex signals and send each decision through audit."""

    def __init__(self, gateway_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
        self.api_key = api_key or os.getenv("GATEWAY_API_KEY", "")
        self.engine = SignalEngine()
        self.auditor = AletheiaWrapper(self.gateway_url, self.api_key)

    def get_forex_data(self, pair: str, period: str = "5d", interval: str = "15m"):
        mapping = {"EUR/USD": "FXE", "GBP/USD": "FXB", "USD/JPY": "FXY"}
        ticker = mapping.get(pair, "FXE")
        data = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
        if data.empty:
            return data

        if "Close" in data.columns:
            data = data.rename(columns={"Close": "close"})
        elif "close" not in data.columns:
            data["close"] = data.iloc[:, 0]
        return data

    def run(self, pair: str = "EUR/USD") -> Dict[str, object]:
        data = self.get_forex_data(pair)
        if data.empty:
            return {"pair": pair, "signal": "ERROR", "error": "no data"}

        signal, indicators = self.engine.generate_forex_signal(data)
        payload = {
            "instrument_type": "forex",
            "pair": pair,
            "signal": signal,
            "indicators": indicators,
            "approval_required": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)
        return {
            "pair": pair,
            "signal": signal,
            "meta": indicators,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }


if __name__ == "__main__":
    agent = ForexAgent()
    print(agent.run("EUR/USD"))
