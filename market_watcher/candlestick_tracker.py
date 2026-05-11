from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CandleSnapshot:
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: str
    patterns: list[str]


class CandlestickTracker:
    """Tracks latest candles and basic candlestick pattern signals."""

    def __init__(self) -> None:
        self._last_seen_ts: dict[tuple[str, str], str] = {}

    def update_from_frame(
        self, *, symbol: str, timeframe: str, frame: pd.DataFrame
    ) -> CandleSnapshot | None:
        if frame.empty:
            return None

        required = {"open", "high", "low", "close"}
        if not required.issubset(set(frame.columns)):
            return None

        last = frame.iloc[-1]
        timestamp_obj = frame.index[-1]
        timestamp = (
            timestamp_obj.isoformat() if hasattr(timestamp_obj, "isoformat") else str(timestamp_obj)
        )

        key = (symbol, timeframe)
        self._last_seen_ts[key] = timestamp

        patterns = self._detect_patterns(frame.tail(3))
        volume = float(last.get("volume", 0.0)) if "volume" in frame.columns else 0.0
        return CandleSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            open=float(last["open"]),
            high=float(last["high"]),
            low=float(last["low"]),
            close=float(last["close"]),
            volume=volume,
            timestamp=timestamp,
            patterns=patterns,
        )

    def _detect_patterns(self, frame: pd.DataFrame) -> list[str]:
        if frame.empty:
            return []

        patterns: list[str] = []
        latest = frame.iloc[-1]

        o = float(latest["open"])
        h = float(latest["high"])
        low_price = float(latest["low"])
        c = float(latest["close"])

        body = abs(c - o)
        candle_range = max(h - low_price, 1e-12)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - low_price

        if body / candle_range <= 0.1:
            patterns.append("doji")

        if lower_wick >= body * 2.0 and upper_wick <= body:
            patterns.append("hammer")

        if len(frame) >= 2:
            prev = frame.iloc[-2]
            po = float(prev["open"])
            pc = float(prev["close"])

            bullish_engulfing = (pc < po) and (c > o) and (o <= pc) and (c >= po)
            bearish_engulfing = (pc > po) and (c < o) and (o >= pc) and (c <= po)
            if bullish_engulfing:
                patterns.append("bullish_engulfing")
            if bearish_engulfing:
                patterns.append("bearish_engulfing")

        return patterns
