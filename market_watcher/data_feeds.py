from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

import pandas as pd
import requests

from backtesting.data import DataManager


@dataclass
class FeedSnapshot:
    symbol: str
    frame: pd.DataFrame
    source_backend: str
    last_price: float
    last_volume: float
    realized_volatility: float
    order_flow_imbalance: float


class MarketDataFeeds:
    """Flexible data feed layer with yfinance default and Polygon/FMP/AV-ready support."""

    def __init__(
        self,
        data_manager: DataManager | None = None,
        sentiment_cache_ttl_seconds: float = 300.0,
        sentiment_failure_threshold: int = 3,
        sentiment_cooldown_seconds: float = 300.0,
    ) -> None:
        self.data_manager = data_manager or DataManager()
        self.alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.sentiment_cache_ttl_seconds = sentiment_cache_ttl_seconds
        self.sentiment_failure_threshold = sentiment_failure_threshold
        self.sentiment_cooldown_seconds = sentiment_cooldown_seconds
        self._sentiment_cache: dict[str, tuple[float, str, float]] = {}
        self._provider_failures: dict[str, int] = {
            "alt_me_fear_greed": 0,
            "alpha_vantage_news": 0,
        }
        self._provider_blocked_until: dict[str, float] = {
            "alt_me_fear_greed": 0.0,
            "alpha_vantage_news": 0.0,
        }
        self._provider_last_error: dict[str, str] = {
            "alt_me_fear_greed": "",
            "alpha_vantage_news": "",
        }
        self._lock = RLock()

    def fetch_many(
        self,
        *,
        symbols: list[str],
        timeframe: str,
        lookback_period: str,
        end: datetime | None = None,
    ) -> tuple[dict[str, FeedSnapshot], dict[str, str]]:
        ts_end = end or datetime.now(UTC)
        start, _ = self.data_manager.period_to_date_range(lookback_period, end=ts_end)
        snapshots: dict[str, FeedSnapshot] = {}
        failures: dict[str, str] = {}

        for symbol in symbols:
            try:
                frame = self.data_manager.download(
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=ts_end.date().isoformat(),
                )
            except Exception as exc:
                failures[symbol] = str(exc)
                continue
            if frame.empty:
                failures[symbol] = "empty dataset"
                continue

            close = frame["close"].astype(float)
            returns = close.pct_change().dropna()
            realized_vol = (
                float(returns.tail(40).std() * (252 * 24) ** 0.5) if not returns.empty else 0.0
            )

            volume = frame["volume"].astype(float).fillna(0.0)
            flow = self._order_flow_imbalance(close, volume)
            snapshots[symbol] = FeedSnapshot(
                symbol=symbol,
                frame=frame,
                source_backend=str(frame.attrs.get("source_backend", "unknown")),
                last_price=float(close.iloc[-1]),
                last_volume=float(volume.iloc[-1] if len(volume) else 0.0),
                realized_volatility=realized_vol,
                order_flow_imbalance=flow,
            )
        return snapshots, failures

    def fetch_multi_timeframe(
        self,
        *,
        symbol: str,
        timeframes: list[str],
        lookback_period: str,
        end: datetime | None = None,
    ) -> dict[str, pd.DataFrame]:
        ts_end = end or datetime.now(UTC)
        start, _ = self.data_manager.period_to_date_range(lookback_period, end=ts_end)
        out: dict[str, pd.DataFrame] = {}
        for timeframe in timeframes:
            try:
                frame = self.data_manager.download(
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=ts_end.date().isoformat(),
                )
            except Exception:
                continue
            if not frame.empty:
                out[timeframe] = frame
        return out

    def sentiment(self, symbol: str, close: pd.Series) -> tuple[float, str]:
        external = self._external_sentiment(symbol)
        if external is not None:
            return round(external[0], 4), external[1]

        if len(close) < 6:
            return 0.0, "price_proxy"
        short_return = float(close.iloc[-1] / close.iloc[-6] - 1.0)
        trend = (
            close.ewm(span=8, adjust=False).mean().iloc[-1]
            - close.ewm(span=21, adjust=False).mean().iloc[-1]
        )
        baseline = abs(float(close.iloc[-1])) or 1.0
        score = (short_return * 10.0) + (float(trend) / baseline * 20.0)
        return float(max(-1.0, min(1.0, score))), "price_proxy"

    def _external_sentiment(self, symbol: str) -> tuple[float, str] | None:
        cache_key = symbol.strip().upper()
        now_ts = time.time()
        cached = self._sentiment_cache.get(cache_key)
        if cached and now_ts - cached[2] <= self.sentiment_cache_ttl_seconds:
            return cached[0], cached[1]

        providers = self._provider_order(cache_key)
        for provider in providers:
            if not self._provider_available(provider):
                continue

            value = self._fetch_provider_sentiment(provider, cache_key)
            if value is None:
                continue

            self._provider_success(provider)
            self._sentiment_cache[cache_key] = (value[0], value[1], now_ts)
            return value
        return None

    def sentiment_provider_health(self) -> dict[str, dict[str, object]]:
        now_ts = time.time()
        with self._lock:
            return {
                provider: {
                    "failures": failures,
                    "blocked": self._provider_blocked_until.get(provider, 0.0) > now_ts,
                    "blocked_seconds_left": max(
                        self._provider_blocked_until.get(provider, 0.0) - now_ts,
                        0.0,
                    ),
                    "last_error": self._provider_last_error.get(provider, ""),
                }
                for provider, failures in self._provider_failures.items()
            }

    def _provider_order(self, cache_key: str) -> list[str]:
        if cache_key in {"BTC-USD", "ETH-USD", "BTCUSD", "ETHUSD"}:
            return ["alt_me_fear_greed", "alpha_vantage_news"]
        return ["alpha_vantage_news"]

    def _provider_available(self, provider: str) -> bool:
        if provider == "alpha_vantage_news" and not self.alpha_vantage_api_key:
            return False
        with self._lock:
            blocked_until = self._provider_blocked_until.get(provider, 0.0)
        return time.time() >= blocked_until

    def _fetch_provider_sentiment(self, provider: str, symbol: str) -> tuple[float, str] | None:
        if provider == "alt_me_fear_greed":
            value = self._crypto_fear_greed_sentiment()
            if value is None:
                self._provider_failure(provider, "provider returned empty")
            return value
        if provider == "alpha_vantage_news":
            value = self._alpha_vantage_news_sentiment(symbol)
            if value is None:
                self._provider_failure(provider, "provider returned empty")
            return value
        return None

    def _provider_success(self, provider: str) -> None:
        with self._lock:
            self._provider_failures[provider] = 0
            self._provider_last_error[provider] = ""
            self._provider_blocked_until[provider] = 0.0

    def _provider_failure(self, provider: str, reason: str) -> None:
        with self._lock:
            failures = self._provider_failures.get(provider, 0) + 1
            self._provider_failures[provider] = failures
            self._provider_last_error[provider] = reason
            if failures >= self.sentiment_failure_threshold:
                self._provider_blocked_until[provider] = (
                    time.time() + self.sentiment_cooldown_seconds
                )

    def _alpha_vantage_news_sentiment(self, symbol: str) -> tuple[float, str] | None:
        ticker = symbol.replace("/", "").replace("=X", "")
        if ticker == "JPY":
            ticker = "USDJPY"
        try:
            params: dict[str, str | int | float | None] = {
                "function": "NEWS_SENTIMENT",
                "tickers": ticker,
                "limit": 50,
                "apikey": self.alpha_vantage_api_key,
            }
            response = requests.get("https://www.alphavantage.co/query", params=params, timeout=8)
            response.raise_for_status()
            payload = response.json()
            feed = payload.get("feed", [])
            if not isinstance(feed, list):
                return None

            scores: list[float] = []
            for item in feed:
                if not isinstance(item, dict):
                    continue
                raw = item.get("overall_sentiment_score")
                if isinstance(raw, int | float | str):
                    try:
                        scores.append(float(raw))
                    except ValueError:
                        continue
            if not scores:
                return None
            avg = float(sum(scores) / len(scores))
            return max(-1.0, min(1.0, avg)), "alpha_vantage_news"
        except Exception as exc:
            self._provider_failure("alpha_vantage_news", str(exc))
            return None

    @staticmethod
    def _crypto_fear_greed_sentiment() -> tuple[float, str] | None:
        try:
            response = requests.get(
                "https://api.alternative.me/fng/", params={"limit": 1}, timeout=6
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            if not isinstance(data, list) or not data:
                return None
            first = data[0]
            if not isinstance(first, dict):
                return None
            raw = first.get("value")
            value = float(raw) if isinstance(raw, int | float | str) else 50.0
            normalized = max(-1.0, min(1.0, (value - 50.0) / 50.0))
            return normalized, "alt_me_fear_greed"
        except Exception:
            return None

    @staticmethod
    def _order_flow_imbalance(close: pd.Series, volume: pd.Series) -> float:
        if len(close) < 2 or len(volume) < 2:
            return 0.0
        direction = close.diff().fillna(0.0).apply(lambda x: 1.0 if x >= 0 else -1.0)
        weighted = (direction * volume).tail(30)
        denom = float(volume.tail(30).sum()) or 1.0
        return round(float(weighted.sum() / denom), 4)
