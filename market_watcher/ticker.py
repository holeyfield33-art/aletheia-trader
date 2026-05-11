from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd


@dataclass
class TickerSnapshot:
    symbol: str
    timestamp: str
    last_price: float
    percent_change: float
    volume: float
    session_high: float
    session_low: float


class LiveTicker:
    """Builds user-facing ticker snapshots from OHLCV data."""

    def build(self, *, symbol: str, frame: pd.DataFrame) -> TickerSnapshot:
        if frame.empty or "close" not in frame.columns:
            now = datetime.now(UTC).isoformat()
            return TickerSnapshot(
                symbol=symbol,
                timestamp=now,
                last_price=0.0,
                percent_change=0.0,
                volume=0.0,
                session_high=0.0,
                session_low=0.0,
            )

        close = frame["close"].astype(float)
        high = frame["high"].astype(float) if "high" in frame.columns else close
        low = frame["low"].astype(float) if "low" in frame.columns else close
        volume = (
            frame["volume"].astype(float).fillna(0.0)
            if "volume" in frame.columns
            else pd.Series(0.0, index=frame.index)
        )

        last = float(close.iloc[-1])
        base = float(close.iloc[0]) if len(close) > 0 else last
        pct_change = 0.0 if abs(base) <= 1e-12 else ((last / base) - 1.0) * 100.0

        latest_ts = frame.index[-1]
        timestamp = (
            latest_ts.isoformat()
            if hasattr(latest_ts, "isoformat")
            else datetime.now(UTC).isoformat()
        )

        return TickerSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            last_price=round(last, 6),
            percent_change=round(pct_change, 4),
            volume=float(volume.iloc[-1] if len(volume) else 0.0),
            session_high=round(float(high.max()), 6),
            session_low=round(float(low.min()), 6),
        )
