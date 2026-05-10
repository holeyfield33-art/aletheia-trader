from __future__ import annotations

import os
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from agents.signal_engine import SignalEngine
from audit.aletheia_wrapper import AletheiaWrapper
from backtesting.data import DataManager

load_dotenv()


def _categorize_expiration(exp_str: str) -> str:
    """Categorize expiration as 0DTE, weekly, or monthly."""
    exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
    today = datetime.now(UTC).date()
    dte = (exp - today).days

    if dte <= 1:
        return "0DTE"
    elif dte <= 7:
        return "weekly"
    else:
        return "monthly"


class OptionsAgent:
    """Generate directional options signals with strike selection and chain analysis."""

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

    def get_price_data(self, symbol: str, period: str = "1mo", interval: str = "30m"):
        start, end = self.data_manager.period_to_date_range(period)
        data = self.data_manager.download(
            symbol=symbol,
            timeframe=interval,
            start=start,
            end=end,
        )
        if data.empty:
            return data
        return data

    def get_option_chain_metadata(
        self, symbol: str, limit_expirations: int = 3
    ) -> dict[str, object]:
        """Fetch option chain data and find best strikes for signals."""
        try:
            ticker = yf.Ticker(symbol)
            expirations = list(ticker.options)[:limit_expirations]

            chains = {}
            for exp in expirations:
                cat = _categorize_expiration(exp)
                opts = ticker.option_chain(exp)

                calls = opts.calls
                puts = opts.puts

                chains[exp] = {
                    "category": cat,
                    "num_calls": len(calls),
                    "num_puts": len(puts),
                    "call_volume": int(calls["volume"].sum()) if "volume" in calls.columns else 0,
                    "put_volume": int(puts["volume"].sum()) if "volume" in puts.columns else 0,
                    "atm_call_strike": (
                        float(calls.loc[calls["strike"].abs().idxmin()]["strike"])
                        if not calls.empty
                        else 0.0
                    ),
                    "atm_put_strike": (
                        float(puts.loc[puts["strike"].abs().idxmin()]["strike"])
                        if not puts.empty
                        else 0.0
                    ),
                }

            return {"expirations": list(expirations), "chains": chains}
        except Exception as e:
            return {"error": str(e), "expirations": []}

    def get_nearest_expiration(self, symbol: str) -> str | None:
        try:
            ticker = yf.Ticker(symbol)
            expirations = list(ticker.options)
            return expirations[0] if expirations else None
        except Exception:
            return None

    def _fallback_signal(self, symbol: str) -> dict[str, object]:
        # Synthetic close series (25 rows so BB window of 20 can compute).
        # Includes a deep dip to trigger oversold RSI and a MACD crossover.
        synthetic = pd.DataFrame(
            {
                "close": [
                    410.0,
                    410.5,
                    411.2,
                    410.7,
                    410.1,
                    409.6,
                    408.9,
                    408.2,
                    407.5,
                    406.8,
                    406.1,
                    405.5,
                    405.0,
                    405.4,
                    406.0,
                    406.7,
                    407.4,
                    408.1,
                    408.8,
                    409.5,
                    410.0,
                    410.3,
                    410.6,
                    410.2,
                    409.8,
                ]
            }
        )
        synthetic["high"] = synthetic["close"] * 1.001
        synthetic["low"] = synthetic["close"] * 0.999
        signal, indicators, filter_reason = self.engine.generate_options_signal(synthetic)
        payload = {
            "instrument_type": "options",
            "symbol": symbol,
            "signal": signal,
            "current_price": float(synthetic["close"].iloc[-1].item()),
            "expiration_hint": None,
            "chain_metadata": {"expirations": [], "chains": {}, "fallback_mode": True},
            "indicators": indicators,
            "approval_required": True,
            "fallback_mode": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)
        return {
            "symbol": symbol,
            "signal": signal,
            "current_price": float(synthetic["close"].iloc[-1].item()),
            "expiration": None,
            "chain_data": {"expirations": [], "chains": {}, "fallback_mode": True},
            "meta": indicators,
            "filter_reason": filter_reason,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }

    def run(self, symbol: str = "SPY") -> dict[str, object]:
        data = self.get_price_data(symbol)
        if data.empty:
            return self._fallback_signal(symbol)

        signal, indicators, filter_reason = self.engine.generate_options_signal(data)
        expiration = self.get_nearest_expiration(symbol)
        chain_meta = self.get_option_chain_metadata(symbol)

        current_price = float(data["close"].iloc[-1].item()) if len(data) > 0 else 0.0

        payload = {
            "instrument_type": "options",
            "symbol": symbol,
            "signal": signal,
            "current_price": current_price,
            "expiration_hint": expiration,
            "chain_metadata": chain_meta,
            "indicators": indicators,
            "approval_required": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)

        return {
            "symbol": symbol,
            "signal": signal,
            "current_price": current_price,
            "expiration": expiration,
            "chain_data": chain_meta,
            "meta": indicators,
            "filter_reason": filter_reason,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }
