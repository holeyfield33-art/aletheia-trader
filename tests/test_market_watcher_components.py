from __future__ import annotations

import pandas as pd

from market_watcher.candlestick_tracker import CandlestickTracker
from market_watcher.orchestrator import MarketWatcher
from market_watcher.strategies import get_preset, list_presets
from market_watcher.ticker import LiveTicker


def _sample_frame(rows: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="min", tz="UTC")
    close = pd.Series([100 + (i * 0.2) + ((i % 3) * 0.05) for i in range(rows)], index=idx)
    frame = pd.DataFrame(index=idx)
    frame["open"] = close.shift(1).fillna(close)
    frame["high"] = close * 1.003
    frame["low"] = close * 0.997
    frame["close"] = close
    frame["volume"] = 500 + (pd.Series(range(rows), index=idx) * 4)
    return frame


def test_live_ticker_builds_core_metrics() -> None:
    ticker = LiveTicker()
    frame = _sample_frame()

    snapshot = ticker.build(symbol="SPY", frame=frame)

    assert snapshot.symbol == "SPY"
    assert snapshot.last_price > 0
    assert snapshot.session_high >= snapshot.last_price
    assert snapshot.session_low <= snapshot.last_price
    assert isinstance(snapshot.percent_change, float)


def test_candlestick_tracker_detects_patterns() -> None:
    tracker = CandlestickTracker()
    idx = pd.date_range("2025-01-01", periods=3, freq="min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 98.0, 96.0],
            "high": [101.0, 99.0, 103.0],
            "low": [97.5, 95.0, 95.2],
            "close": [98.0, 96.0, 102.5],
            "volume": [1000, 1200, 1400],
        },
        index=idx,
    )

    candle = tracker.update_from_frame(symbol="BTC-USD", timeframe="1m", frame=frame)

    assert candle is not None
    assert candle.symbol == "BTC-USD"
    assert candle.timeframe == "1m"
    assert "bullish_engulfing" in candle.patterns


def test_strategy_presets_have_required_metadata() -> None:
    presets = list_presets()

    assert len(presets) >= 6
    names = {p.name for p in presets}
    assert "Safe Trend Follower" in names
    assert "Volatility Crusher" in names

    selected = get_preset("rsi_macd_confluence")
    assert selected.risk_level in {"Low", "Medium", "High"}
    assert "min_confidence" in selected.default_parameters


def test_market_watcher_lists_strategy_presets() -> None:
    watcher = MarketWatcher()
    presets = watcher.list_strategy_presets()

    assert presets
    assert any(item["id"] == "safe_trend_follower" for item in presets)
    assert all("description" in item for item in presets)
