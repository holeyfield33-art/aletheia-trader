from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
from typing import Dict, Optional, List

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


def _categorize_expiration(exp_str: str) -> str:
    """Categorize expiration as 0DTE, weekly, or monthly."""
    exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
    today = datetime.now(timezone.utc).date()
    dte = (exp - today).days
    
    if dte <= 1:
        return "0DTE"
    elif dte <= 7:
        return "weekly"
    else:
        return "monthly"


class OptionsAgent:
    """Generate directional options signals with strike selection and chain analysis."""

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

    def get_option_chain_metadata(self, symbol: str, limit_expirations: int = 3) -> Dict[str, object]:
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
                    "atm_call_strike": float(calls.loc[calls["strike"].abs().idxmin()]["strike"]) if not calls.empty else 0.0,
                    "atm_put_strike": float(puts.loc[puts["strike"].abs().idxmin()]["strike"]) if not puts.empty else 0.0,
                }
            
            return {"expirations": list(expirations), "chains": chains}
        except Exception as e:
            return {"error": str(e), "expirations": []}

    def get_nearest_expiration(self, symbol: str) -> Optional[str]:
        try:
            ticker = yf.Ticker(symbol)
            expirations = list(ticker.options)
            return expirations[0] if expirations else None
        except Exception:
            return None

    def run(self, symbol: str = "SPY") -> Dict[str, object]:
        data = self.get_price_data(symbol)
        if data.empty:
            return {"symbol": symbol, "signal": "ERROR", "error": "no data"}

        signal, indicators = self.engine.generate_options_signal(data)
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        receipt = self.auditor.audit(action="generate_signal", payload=payload)

        return {
            "symbol": symbol,
            "signal": signal,
            "current_price": current_price,
            "expiration": expiration,
            "chain_data": chain_meta,
            "meta": indicators,
            "receipt": receipt.get("receipt", "mock-receipt"),
            "approved": False,
        }


if __name__ == "__main__":
    agent = OptionsAgent()
    print(agent.run("SPY"))

