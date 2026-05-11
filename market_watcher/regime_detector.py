from __future__ import annotations

import math

import pandas as pd


class RegimeDetector:
    """Detects operational market regimes for signal context and risk controls."""

    def detect(self, close: pd.Series) -> str:
        returns = close.pct_change().dropna()
        if len(close) < 30 or returns.empty:
            return "unknown"

        rolling_vol = returns.tail(40).std()
        realized_vol = float(rolling_vol * math.sqrt(252 * 24)) if not pd.isna(rolling_vol) else 0.0

        upper = close.rolling(window=20).max().iloc[-1]
        lower = close.rolling(window=20).min().iloc[-1]
        last = float(close.iloc[-1])
        ema_fast = float(close.ewm(span=8, adjust=False).mean().iloc[-1])
        ema_slow = float(close.ewm(span=21, adjust=False).mean().iloc[-1])

        if realized_vol >= 0.45:
            return "high-vol"
        if last >= float(upper) * 0.998 or last <= float(lower) * 1.002:
            return "breakout"

        trend_strength = abs((ema_fast - ema_slow) / ema_slow) if ema_slow else 0.0
        if trend_strength >= 0.008:
            return "trending"

        zscore = self.mean_reversion_score(close)
        if abs(zscore) >= 1.2:
            return "mean-reversion"
        return "ranging"

    @staticmethod
    def mean_reversion_score(close: pd.Series) -> float:
        window = close.tail(40)
        if len(window) < 20:
            return 0.0
        mean = float(window.mean())
        std = float(window.std())
        if std <= 1e-12:
            return 0.0
        return float((window.iloc[-1] - mean) / std)

    @staticmethod
    def anomaly_score(close: pd.Series) -> float:
        returns = close.pct_change().dropna().tail(30)
        if len(returns) < 5:
            return 0.0
        mean = float(returns.mean())
        std = float(returns.std())
        if std <= 1e-12:
            return 0.0
        score = abs(float((returns.iloc[-1] - mean) / std))
        return round(score, 4)

    @staticmethod
    def plain_english_label(regime: str) -> str:
        labels = {
            "trending": "Strong Uptrend or Downtrend",
            "ranging": "Choppy Market",
            "high-vol": "High Volatility",
            "breakout": "Breakout In Progress",
            "mean-reversion": "Pullback / Mean Reversion Zone",
            "unknown": "Market State Building",
        }
        return labels.get(regime, "Unclassified Market")
