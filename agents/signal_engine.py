from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

NO_SIGNAL = "NO_SIGNAL"


@dataclass
class IndicatorSnapshot:
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    atr: float
    confidence: float
    mtf_confirmed: bool
    regime: str
    recommended_size: float


class SignalEngine:
    def __init__(
        self,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_window: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
        risk_per_trade: float = 0.01,
        capital: float = 100_000.0,
    ) -> None:
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.risk_per_trade = risk_per_trade
        self.capital = capital

    def compute_rsi(self, prices: pd.Series) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def compute_macd(self, prices: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = prices.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = prices.ewm(span=self.macd_slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.macd_signal, adjust=False).mean()
        histogram = macd - signal
        return macd, signal, histogram

    def compute_bollinger_bands(self, prices: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        mid = prices.rolling(window=self.bb_window).mean()
        std = prices.rolling(window=self.bb_window).std()
        upper = mid + (self.bb_std * std)
        lower = mid - (self.bb_std * std)
        return upper, mid, lower

    def compute_atr(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
    ) -> pd.Series:
        prev_close = close.shift(1)
        tr_components = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        )
        tr = tr_components.max(axis=1)
        return tr.rolling(window=self.atr_period, min_periods=1).mean().fillna(0.0)

    @staticmethod
    def _estimate_regime(close: pd.Series) -> str:
        if len(close) < 20:
            return "unknown"
        fast = close.ewm(span=8, adjust=False).mean()
        slow = close.ewm(span=20, adjust=False).mean()
        trend_strength = (
            abs(float((fast.iloc[-1] - slow.iloc[-1]) / slow.iloc[-1])) if slow.iloc[-1] else 0.0
        )
        return "trending" if trend_strength > 0.008 else "ranging"

    @staticmethod
    def _mtf_confirmation(close: pd.Series, macd_hist: pd.Series) -> bool:
        if len(close) < 24:
            return False
        higher = close.iloc[-24:].reset_index(drop=True)
        higher_tf = higher.groupby(higher.index // 4).last()
        if len(higher_tf) < 4:
            return False
        fast = higher_tf.ewm(span=4, adjust=False).mean().iloc[-1]
        slow = higher_tf.ewm(span=8, adjust=False).mean().iloc[-1]
        current_hist = float(macd_hist.iloc[-1]) if len(macd_hist) else 0.0
        return (current_hist >= 0 and fast >= slow) or (current_hist < 0 and fast < slow)

    def _confidence_score(
        self,
        snap: IndicatorSnapshot,
        prev_hist: float,
        last_price: float,
        correlation_penalty: float,
    ) -> float:
        if snap.bb_mid <= 0:
            return 0.0

        rsi_extreme = snap.rsi < 35 or snap.rsi > 65
        macd_cross = (prev_hist <= 0 < snap.macd_hist) or (prev_hist >= 0 > snap.macd_hist)
        bb_touch = (last_price <= snap.bb_lower and snap.rsi < 45) or (
            last_price >= snap.bb_upper and snap.rsi > 55
        )
        bb_width = (snap.bb_upper - snap.bb_lower) / snap.bb_mid if snap.bb_mid else 0.0

        score = 45.0
        if rsi_extreme:
            score += 20.0
        if macd_cross:
            score += 15.0
        if bb_touch:
            score += 15.0
        if snap.mtf_confirmed:
            score += 10.0
        if snap.regime == "trending":
            score += 10.0
        if bb_width < 0.02:
            score -= 20.0

        score -= min(max(correlation_penalty, 0.0), 1.0) * 20.0
        return max(0.0, min(100.0, score))

    def _atr_position_size(self, atr: float, correlation_penalty: float) -> float:
        if atr <= 0:
            return 0.0
        base_risk = self.capital * self.risk_per_trade
        adjusted_risk = base_risk * (1.0 - min(max(correlation_penalty, 0.0), 0.9))
        stop_distance = atr * 2.0
        if stop_distance <= 0:
            return 0.0
        return max(adjusted_risk / stop_distance, 0.0)

    def _snapshot(
        self,
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        correlation_penalty: float,
    ) -> IndicatorSnapshot:
        rsi = self.compute_rsi(close)
        macd, signal, hist = self.compute_macd(close)
        bb_upper, bb_mid, bb_lower = self.compute_bollinger_bands(close)
        atr = self.compute_atr(high, low, close)
        regime = self._estimate_regime(close)
        mtf_ok = self._mtf_confirmation(close, hist)

        def _safe(series: pd.Series, fallback: float) -> float:
            val = series.iloc[-1]
            try:
                fval = float(val.item()) if hasattr(val, "item") else float(val)
                return fval if math.isfinite(fval) else fallback
            except (TypeError, ValueError):
                return fallback

        snap = IndicatorSnapshot(
            rsi=_safe(rsi, 50.0),
            macd=_safe(macd, 0.0),
            macd_signal=_safe(signal, 0.0),
            macd_hist=_safe(hist, 0.0),
            bb_upper=_safe(bb_upper, 0.0),
            bb_mid=_safe(bb_mid, 0.0),
            bb_lower=_safe(bb_lower, 0.0),
            atr=_safe(atr, 0.0),
            confidence=0.0,
            mtf_confirmed=mtf_ok,
            regime=regime,
            recommended_size=0.0,
        )
        prev_hist = _safe(hist.shift(1), 0.0)
        last_price = _safe(close, 0.0)
        snap.confidence = self._confidence_score(
            snap=snap,
            prev_hist=prev_hist,
            last_price=last_price,
            correlation_penalty=correlation_penalty,
        )
        snap.recommended_size = self._atr_position_size(snap.atr, correlation_penalty)
        return snap

    def _validate_signal(
        self,
        snap: IndicatorSnapshot,
        prev_hist: float,
        last_price: float,
    ) -> tuple[bool, str]:
        """Validate whether market conditions are strong enough to generate a signal.

        Returns (is_valid, filter_reason). An empty filter_reason means the signal is valid.

        Rules (all must pass):
          1. Bollinger Bands must be properly computed (all bands > 0).
          2. At least ONE of the following conditions must be true:
             a. Strong RSI: rsi < 35 (oversold) OR rsi > 65 (overbought)
             b. Fresh MACD crossover: histogram changes sign between prev and current bar
             c. Price touching a Bollinger Band with RSI confirmation:
                  - price <= bb_lower AND rsi < 45  (lower band + oversold bias)
                  - price >= bb_upper AND rsi > 55  (upper band + overbought bias)
        """
        # Rule 1 — Bollinger Bands must be calculated
        if snap.bb_upper <= 0 or snap.bb_mid <= 0 or snap.bb_lower <= 0:
            return False, "Bollinger Bands not yet calculated (insufficient price history)"

        bb_width = (snap.bb_upper - snap.bb_lower) / snap.bb_mid if snap.bb_mid else 0.0
        if 45 <= snap.rsi <= 55 and bb_width < 0.02:
            return False, "RSI near 50 with flat Bollinger Bands (weak regime)"

        # Rule 2a — Strong RSI
        rsi_strong = snap.rsi < 35 or snap.rsi > 65

        # Rule 2b — Fresh MACD histogram crossover (sign change)
        macd_crossover = (prev_hist > 0 and snap.macd_hist < 0) or (
            prev_hist < 0 and snap.macd_hist > 0
        )

        # Rule 2c — Price touching Bollinger Band with RSI confirmation
        bb_lower_touch = last_price <= snap.bb_lower and snap.rsi < 45
        bb_upper_touch = last_price >= snap.bb_upper and snap.rsi > 55
        bb_touch_rsi = bb_lower_touch or bb_upper_touch

        if rsi_strong or macd_crossover or bb_touch_rsi:
            if snap.confidence < 60:
                return False, f"Confidence too low ({snap.confidence:.1f}/100)"
            return True, ""

        # Build human-readable reason why each condition failed
        reasons: list[str] = []
        if not rsi_strong:
            reasons.append(f"RSI {snap.rsi:.1f} is near neutral (requires <35 or >65)")
        if not macd_crossover:
            reasons.append(
                f"no fresh MACD crossover (hist: {prev_hist:+.4f} → {snap.macd_hist:+.4f})"
            )
        if not bb_touch_rsi:
            reasons.append(
                f"price {last_price:.4f} not touching Bollinger Bands "
                f"[{snap.bb_lower:.4f} – {snap.bb_upper:.4f}] with RSI confirmation"
            )
        return False, "; ".join(reasons)

    def generate_forex_signal(
        self,
        df: pd.DataFrame,
        correlation_penalty: float = 0.0,
    ) -> tuple[str, dict[str, float], str]:
        """Return (signal, indicators, filter_reason).

        signal is one of: BUY | SELL | HOLD | NO_SIGNAL
        filter_reason is non-empty only when signal == NO_SIGNAL.
        """
        close = df["close"].astype(float)
        if "high" in df.columns and "low" in df.columns:
            high = df["high"].astype(float)
            low = df["low"].astype(float)
        else:
            high = close * 1.001
            low = close * 0.999

        snap = self._snapshot(close, high, low, correlation_penalty)
        prev_hist = float(self.compute_macd(close)[2].iloc[-2].item()) if len(close) > 1 else 0.0
        last_price = float(close.iloc[-1].item())

        valid, reason = self._validate_signal(snap, prev_hist, last_price)
        if not valid:
            return NO_SIGNAL, snap.__dict__, reason

        if snap.rsi < 35 and snap.macd_hist > 0 and prev_hist <= 0:
            action = "BUY"
        elif snap.rsi > 65 and snap.macd_hist < 0 and prev_hist >= 0:
            action = "SELL"
        else:
            action = "HOLD"

        return action, snap.__dict__, ""

    def generate_options_signal(
        self,
        df: pd.DataFrame,
        correlation_penalty: float = 0.0,
    ) -> tuple[str, dict[str, float], str]:
        """Return (signal, indicators, filter_reason).

        signal is one of: CALL_BUY | PUT_BUY | HOLD | NO_SIGNAL
        filter_reason is non-empty only when signal == NO_SIGNAL.
        """
        close = df["close"].astype(float)
        if "high" in df.columns and "low" in df.columns:
            high = df["high"].astype(float)
            low = df["low"].astype(float)
        else:
            high = close * 1.001
            low = close * 0.999

        snap = self._snapshot(close, high, low, correlation_penalty)
        prev_hist = float(self.compute_macd(close)[2].iloc[-2].item()) if len(close) > 1 else 0.0
        last_price = float(close.iloc[-1].item())

        valid, reason = self._validate_signal(snap, prev_hist, last_price)
        if not valid:
            return NO_SIGNAL, snap.__dict__, reason

        if snap.rsi < 35 and snap.macd_hist > 0:
            action = "CALL_BUY"
        elif snap.rsi > 65 and snap.macd_hist < 0:
            action = "PUT_BUY"
        else:
            action = "HOLD"

        return action, snap.__dict__, ""
