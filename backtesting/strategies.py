from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import vectorbt as vbt


@dataclass
class StrategySignalPack:
    entries: pd.Series
    exits: pd.Series
    short_entries: pd.Series
    short_exits: pd.Series
    size_pct: pd.Series
    indicators: dict[str, pd.Series]


class BaseStrategy:
    name: str = "base"

    def generate(self, data: pd.DataFrame, params: dict[str, Any]) -> StrategySignalPack:
        raise NotImplementedError


class MACDRSIStrategy(BaseStrategy):
    name = "macd_rsi"

    def generate(self, data: pd.DataFrame, params: dict[str, Any]) -> StrategySignalPack:
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        rsi_period = int(params.get("rsi_period", 14))
        rsi_buy = float(params.get("rsi_buy", 40.0))
        rsi_sell = float(params.get("rsi_sell", 60.0))
        rsi_exit_long = float(params.get("rsi_exit_long", 58.0))
        rsi_exit_short = float(params.get("rsi_exit_short", 42.0))

        macd_fast = int(params.get("macd_fast", 12))
        macd_slow = int(params.get("macd_slow", 26))
        macd_signal = int(params.get("macd_signal", 9))

        trend_fast = int(params.get("trend_fast", 20))
        trend_slow = int(params.get("trend_slow", 50))
        trend_threshold = float(params.get("trend_threshold", 0.0))

        atr_period = int(params.get("atr_period", 14))
        atr_stop_mult = float(params.get("atr_stop_mult", 2.0))
        risk_per_trade = float(params.get("risk_per_trade", 0.01))
        max_position_pct = float(params.get("max_position_pct", 0.35))

        rsi = vbt.RSI.run(close, window=rsi_period).rsi
        macd_obj = vbt.MACD.run(
            close,
            fast_window=macd_fast,
            slow_window=macd_slow,
            signal_window=macd_signal,
        )
        macd_line = macd_obj.macd
        macd_sig = macd_obj.signal

        ema_fast = close.ewm(span=trend_fast, adjust=False).mean()
        ema_slow = close.ewm(span=trend_slow, adjust=False).mean()
        trend_strength = (ema_fast - ema_slow).abs() / ema_slow.replace(0, pd.NA)
        trending = trend_strength.fillna(0.0) > trend_threshold

        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(atr_period, min_periods=1).mean().fillna(0.0)

        bull_cross = (macd_line > macd_sig) & (macd_line.shift(1) <= macd_sig.shift(1))
        bear_cross = (macd_line < macd_sig) & (macd_line.shift(1) >= macd_sig.shift(1))

        bullish_momentum = bull_cross | ((macd_line > macd_sig) & (macd_line.diff() > 0))
        bearish_momentum = bear_cross | ((macd_line < macd_sig) & (macd_line.diff() < 0))

        entries = ((bullish_momentum & (rsi < rsi_buy)) & trending).fillna(False)
        exits = (bear_cross | (rsi > rsi_exit_long)).fillna(False)
        short_entries = ((bearish_momentum & (rsi > rsi_sell)) & trending).fillna(False)
        short_exits = (bull_cross | (rsi < rsi_exit_short)).fillna(False)

        stop_dist = (atr * atr_stop_mult).replace(0, pd.NA)
        size_pct = (risk_per_trade * close / stop_dist).clip(lower=0.0, upper=max_position_pct)
        size_pct = size_pct.fillna(0.0)

        indicators = {
            "rsi": rsi,
            "macd": macd_line,
            "macd_signal": macd_sig,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "atr": atr,
        }

        return StrategySignalPack(
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=short_exits,
            size_pct=size_pct,
            indicators=indicators,
        )


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    MACDRSIStrategy.name: MACDRSIStrategy,
}
