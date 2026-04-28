from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd


@dataclass
class IndicatorSnapshot:
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_mid: float
    bb_lower: float


class SignalEngine:
    def __init__(
        self,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_window: int = 20,
        bb_std: float = 2.0,
    ) -> None:
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_window = bb_window
        self.bb_std = bb_std

    def compute_rsi(self, prices: pd.Series) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def compute_macd(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = prices.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = prices.ewm(span=self.macd_slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.macd_signal, adjust=False).mean()
        histogram = macd - signal
        return macd, signal, histogram

    def compute_bollinger_bands(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = prices.rolling(window=self.bb_window).mean()
        std = prices.rolling(window=self.bb_window).std()
        upper = mid + (self.bb_std * std)
        lower = mid - (self.bb_std * std)
        return upper, mid, lower

    def _snapshot(self, close: pd.Series) -> IndicatorSnapshot:
        rsi = self.compute_rsi(close)
        macd, signal, hist = self.compute_macd(close)
        bb_upper, bb_mid, bb_lower = self.compute_bollinger_bands(close)
        
        rsi_val = float(rsi.iloc[-1].item()) if rsi.iloc[-1] is not pd.NA else 50.0
        macd_val = float(macd.iloc[-1].item()) if macd.iloc[-1] is not pd.NA else 0.0
        signal_val = float(signal.iloc[-1].item()) if signal.iloc[-1] is not pd.NA else 0.0
        hist_val = float(hist.iloc[-1].item()) if hist.iloc[-1] is not pd.NA else 0.0
        bb_u_val = float(bb_upper.iloc[-1].item()) if bb_upper.iloc[-1] is not pd.NA else 0.0
        bb_m_val = float(bb_mid.iloc[-1].item()) if bb_mid.iloc[-1] is not pd.NA else 0.0
        bb_l_val = float(bb_lower.iloc[-1].item()) if bb_lower.iloc[-1] is not pd.NA else 0.0
        
        return IndicatorSnapshot(
            rsi=rsi_val,
            macd=macd_val,
            macd_signal=signal_val,
            macd_hist=hist_val,
            bb_upper=bb_u_val,
            bb_mid=bb_m_val,
            bb_lower=bb_l_val,
        )

    def generate_forex_signal(self, df: pd.DataFrame) -> Tuple[str, Dict[str, float]]:
        """df must include a `close` column; returns BUY, SELL, or HOLD."""
        close = df["close"]
        snap = self._snapshot(close)
        prev_hist = float(self.compute_macd(close)[2].iloc[-2].item()) if len(close) > 1 else 0.0

        if snap.rsi < 30 and snap.macd_hist > 0 and prev_hist <= 0:
            action = "BUY"
        elif snap.rsi > 70 and snap.macd_hist < 0 and prev_hist >= 0:
            action = "SELL"
        else:
            action = "HOLD"

        return action, snap.__dict__

    def generate_options_signal(self, df: pd.DataFrame) -> Tuple[str, Dict[str, float]]:
        """Simple directional options signal: CALL_BUY, PUT_BUY, or HOLD."""
        close = df["close"]
        snap = self._snapshot(close)

        if snap.rsi < 40 and snap.macd_hist > 0:
            action = "CALL_BUY"
        elif snap.rsi > 60 and snap.macd_hist < 0:
            action = "PUT_BUY"
        else:
            action = "HOLD"

        return action, snap.__dict__
