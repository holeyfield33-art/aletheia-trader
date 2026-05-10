from __future__ import annotations

import os
from datetime import UTC, datetime

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

from audit.aletheia_wrapper import audit_signal

load_dotenv()


class CryptoAgent:
    """Generate simple crypto signals and audit each decision."""

    def __init__(self, gateway_url: str | None = None, api_key: str | None = None) -> None:
        self.gateway_url = gateway_url or os.getenv("ALETHEIA_GATEWAY", "")
        self.api_key = api_key or os.getenv("GATEWAY_API_KEY", "")
        self.coinbase_api_key = os.getenv("COINBASE_API_KEY", "")
        self.base_url = "https://api.exchange.coinbase.com"

    def get_historical_prices(
        self, symbol: str = "BTC-USD", days: int = 5, granularity_seconds: int = 3600
    ) -> pd.DataFrame:
        """Fetch hourly candles from Coinbase; fallback to yfinance if needed."""
        end = datetime.now(UTC)
        start = end - pd.Timedelta(days=days)

        try:
            headers = {"Accept": "application/json"}
            if self.coinbase_api_key:
                headers["CB-ACCESS-KEY"] = self.coinbase_api_key

            response = requests.get(
                f"{self.base_url}/products/{symbol}/candles",
                params={
                    "granularity": granularity_seconds,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
                headers=headers,
                timeout=8,
            )
            response.raise_for_status()
            candles = response.json()

            if candles:
                # Coinbase candle format: [time, low, high, open, close, volume]
                df = pd.DataFrame(
                    candles, columns=["time", "low", "high", "open", "close", "volume"]
                )
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                df = df.sort_values("time").set_index("time")
                return df
        except requests.RequestException:
            pass

        data = yf.download(
            symbol, period=f"{days}d", interval="1h", auto_adjust=True, progress=False
        )
        if data.empty:
            return data

        if "Close" in data.columns:
            data = data.rename(columns={"Close": "close"})
        elif "close" not in data.columns:
            data["close"] = data.iloc[:, 0]
        return data

    def compute_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    def generate_signal(self, symbol: str = "BTC-USD") -> dict[str, object]:
        """Generate BUY/SELL/HOLD signal from RSI and audit it."""
        data = self.get_historical_prices(symbol)
        if data.empty or "close" not in data.columns:
            signal: dict[str, object] = {
                "agent_type": "crypto",
                "symbol": symbol,
                "action": "HOLD",
                "reason": "no data",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            receipt = audit_signal(signal, self.gateway_url, self.api_key)
            signal["receipt"] = receipt.get("receipt", "mock-receipt")
            return signal

        rsi_series = self.compute_rsi(data["close"])
        current_rsi = float(rsi_series.iloc[-1])
        current_price = float(data["close"].iloc[-1])

        if current_rsi < 35:
            action = "BUY"
            reason = f"RSI oversold ({current_rsi:.1f})"
        elif current_rsi > 70:
            action = "SELL"
            reason = f"RSI overbought ({current_rsi:.1f})"
        else:
            action = "HOLD"
            reason = f"RSI neutral ({current_rsi:.1f})"

        result: dict[str, object] = {
            "agent_type": "crypto",
            "symbol": symbol,
            "action": action,
            "current_price": current_price,
            "rsi": current_rsi,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        receipt = audit_signal(result, self.gateway_url, self.api_key)
        result["receipt"] = receipt.get("receipt", "mock-receipt")
        return result
