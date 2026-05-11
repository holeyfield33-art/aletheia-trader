from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyPreset:
    id: str
    name: str
    description: str
    best_market_conditions: str
    risk_level: str
    default_parameters: dict[str, float | str | bool]
    expected_behavior: str


_PRESETS: dict[str, StrategyPreset] = {
    "safe_trend_follower": StrategyPreset(
        id="safe_trend_follower",
        name="Safe Trend Follower",
        description="Rides clear trends with strict filters and conservative entries.",
        best_market_conditions="Strong Uptrend or Strong Downtrend with healthy volume",
        risk_level="Low",
        default_parameters={
            "min_confidence": 65.0,
            "max_position_size": 0.02,
            "mtf_required": True,
            "favor_regime": "trending",
        },
        expected_behavior="Fewer but higher-quality trades; aims to avoid noisy markets.",
    ),
    "volatility_crusher": StrategyPreset(
        id="volatility_crusher",
        name="Volatility Crusher",
        description="Targets rapid volatility expansion while capping position size.",
        best_market_conditions="High Volatility or breakout sessions",
        risk_level="High",
        default_parameters={
            "min_confidence": 60.0,
            "max_position_size": 0.015,
            "mtf_required": True,
            "favor_regime": "high-vol",
        },
        expected_behavior="More reactive entries around sharp moves; can be choppier.",
    ),
    "mean_reversion": StrategyPreset(
        id="mean_reversion",
        name="Mean Reversion",
        description="Looks for stretched prices snapping back toward average levels.",
        best_market_conditions="Choppy Market or range-bound sessions",
        risk_level="Medium",
        default_parameters={
            "min_confidence": 58.0,
            "max_position_size": 0.018,
            "mtf_required": False,
            "favor_regime": "mean-reversion",
        },
        expected_behavior="Frequent entries in ranges; avoids chasing trends.",
    ),
    "momentum_breakout": StrategyPreset(
        id="momentum_breakout",
        name="Momentum Breakout",
        description="Acts on strong directional breaks confirmed by momentum.",
        best_market_conditions="Breakout conditions after consolidation",
        risk_level="High",
        default_parameters={
            "min_confidence": 62.0,
            "max_position_size": 0.02,
            "mtf_required": True,
            "favor_regime": "breakout",
        },
        expected_behavior="Captures early breakouts; may produce false starts in noisy tape.",
    ),
    "rsi_macd_confluence": StrategyPreset(
        id="rsi_macd_confluence",
        name="RSI + MACD Confluence",
        description="Waits for RSI and MACD agreement before signaling.",
        best_market_conditions="Moderate trends with orderly pullbacks",
        risk_level="Medium",
        default_parameters={
            "min_confidence": 63.0,
            "max_position_size": 0.0175,
            "mtf_required": True,
            "favor_regime": "trending",
        },
        expected_behavior="Balanced pace with emphasis on confirmation quality.",
    ),
    "news_sentiment_boost": StrategyPreset(
        id="news_sentiment_boost",
        name="News Sentiment Boost",
        description="Placeholder preset that boosts conviction when sentiment aligns.",
        best_market_conditions="Headline-driven sessions and macro events",
        risk_level="Medium",
        default_parameters={
            "min_confidence": 57.0,
            "max_position_size": 0.015,
            "mtf_required": False,
            "favor_regime": "breakout",
            "sentiment_boost_enabled": True,
        },
        expected_behavior="Uses sentiment as an accelerator; should be combined with risk caps.",
    ),
}


def list_presets() -> list[StrategyPreset]:
    return list(_PRESETS.values())


def get_preset(preset_id: str) -> StrategyPreset:
    key = preset_id.strip().lower()
    if key not in _PRESETS:
        return _PRESETS["safe_trend_follower"]
    return _PRESETS[key]
