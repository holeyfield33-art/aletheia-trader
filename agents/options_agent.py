from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import sys
from typing import Dict, Optional

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


class OptionsAgent:
    """Generate directional options signals for index ETFs."""

    def __init__(self, gateway_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
        self.api_key = api_key or os.getenv("GATEWAY_API_KEY", "")
        self.engine = SignalEngine()
        self.auditor = AletheiaWrapper(self.gateway_url, self.api_key)

    def get_price_data(self, symbol: str, period: str = "1mo", interval: str = "30m"):
        data = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
        if data.empty:
            return data

        if "Close" in data.columns:
            data = data.rename(columns={"Close": "close"})
        elif "close" not in data.columns:
            data["close"] = data.iloc[:, 0]
        return data

    def get_nearest_expiration(self, symbol: str) -> Optional[str]:
        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options)
        return expirations[0] if expirations else None

    def run(self, symbol: str = "SPY") -> Dict[str, object]:
        data = self.get_price_data(symbol)
        if data.empty:
            return {"symbol": symbol, "signal": "ERROR", "error": "no data"}

        signal, indicators = self.engine.generate_options_signal(data)
        expiration = self.get_nearest_expiration(symbol)
        payload = {
            "instrument_type": "options",
            "symbol": symbol,
            "signal": signal,
            "expiration_hint": expiration,
            "indicators": indicators,
            "approval_required": True,
            "timestamp": datetime.utcnow().isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)

        return {
            "symbol": symbol,
            "signal": signal,
            "expiration": expiration,
            "meta": indicators,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }


if __name__ == "__main__":
    agent = OptionsAgent()
    print(agent.run("SPY"))
