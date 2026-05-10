from __future__ import annotations

from typing import Any

import pandas as pd

from agents.signal_engine import NO_SIGNAL, SignalEngine


class WatcherSignalGenerator:
    """Market watcher signal generation with multi-timeframe confirmation."""

    def __init__(self, signal_engine: SignalEngine | None = None) -> None:
        self.signal_engine = signal_engine or SignalEngine()

    def generate(
        self,
        *,
        frame: pd.DataFrame,
        regime: str,
        correlation_penalty: float,
        multi_tf_frames: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        signal, meta, filter_reason = self.signal_engine.generate_forex_signal(
            frame,
            correlation_penalty=correlation_penalty,
        )

        mtf_confirmed = self._multi_timeframe_confirmation(
            signal=signal, multi_tf_frames=multi_tf_frames
        )
        confidence = float(meta.get("confidence", 0.0))
        if mtf_confirmed:
            confidence = min(100.0, confidence + 10.0)
        elif signal not in {NO_SIGNAL, "HOLD"}:
            confidence = max(0.0, confidence - 10.0)

        if signal not in {NO_SIGNAL, "HOLD"} and confidence < 60.0:
            signal = NO_SIGNAL
            filter_reason = f"Confidence too low after MTF confirmation ({confidence:.1f}/100)"

        return {
            "signal": signal,
            "indicators": {
                **meta,
                "confidence": confidence,
                "regime": regime,
                "mtf_confirmed": mtf_confirmed,
            },
            "filter_reason": filter_reason,
        }

    def _multi_timeframe_confirmation(
        self,
        *,
        signal: str,
        multi_tf_frames: dict[str, pd.DataFrame] | None,
    ) -> bool:
        if signal in {NO_SIGNAL, "HOLD"}:
            return False
        if not multi_tf_frames:
            return False

        bullish = signal == "BUY"
        confirmations = 0
        evaluated = 0
        for frame in multi_tf_frames.values():
            if frame.empty or "close" not in frame.columns:
                continue
            evaluated += 1
            close = frame["close"].astype(float)
            if len(close) < 15:
                continue
            fast = close.ewm(span=8, adjust=False).mean().iloc[-1]
            slow = close.ewm(span=21, adjust=False).mean().iloc[-1]
            if bullish and fast >= slow:
                confirmations += 1
            if (not bullish) and fast <= slow:
                confirmations += 1
        return evaluated > 0 and confirmations >= max(1, evaluated // 2)
