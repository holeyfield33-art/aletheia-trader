from __future__ import annotations

import math
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import requests

from agents.signal_engine import NO_SIGNAL, SignalEngine
from audit.aletheia_wrapper import AletheiaWrapper
from backtesting.data import DataManager
from brokers.signal_and_order_ledger import SignalAndOrderLedger


@dataclass
class MarketWatcherConfig:
    symbols: list[str]
    timeframe: str = "1h"
    lookback_period: str = "30d"
    poll_interval_seconds: float = 60.0
    signal_ttl_minutes: int = 90
    history_limit: int = 120
    signal_cooldown_seconds: float = 900.0


class MarketWatcher:
    """Background market orchestrator that monitors diagnostics and emits trader signals."""

    def __init__(
        self,
        config: MarketWatcherConfig | None = None,
        *,
        data_manager: DataManager | None = None,
        signal_engine: SignalEngine | None = None,
        ledger: SignalAndOrderLedger | None = None,
        gateway_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.config = config or MarketWatcherConfig(symbols=["EUR/USD", "SPY", "BTC-USD"])
        self.data_manager = data_manager or DataManager(
            gateway_url=gateway_url,
            api_key=api_key,
        )
        self.signal_engine = signal_engine or SignalEngine()
        self.ledger = ledger or SignalAndOrderLedger()
        self.auditor = AletheiaWrapper(gateway_url=gateway_url, api_key=api_key)
        self.alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.sentiment_cache_ttl_seconds = 300.0

        self._history: deque[dict[str, Any]] = deque(maxlen=self.config.history_limit)
        self._last_published_at: dict[tuple[str, str], float] = {}
        self._sentiment_cache: dict[str, tuple[float, str, float]] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cycle_count = 0
        self._last_heartbeat: str | None = None
        self._last_error: str | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="market-watcher", daemon=True
            )
            self._thread.start()
            return self.status()

    def stop(self, timeout: float = 2.0) -> dict[str, Any]:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            self._thread = None
            return self.status()

    def run_cycle(self) -> dict[str, Any]:
        end = datetime.now(UTC)
        start, _ = self.data_manager.period_to_date_range(self.config.lookback_period, end=end)
        market_frames: dict[str, pd.DataFrame] = {}
        fetch_failures: dict[str, str] = {}

        for symbol in self.config.symbols:
            try:
                frame = self.data_manager.download(
                    symbol=symbol,
                    timeframe=self.config.timeframe,
                    start=start,
                    end=end.date().isoformat(),
                )
            except Exception as exc:
                fetch_failures[symbol] = str(exc)
                continue
            if frame.empty:
                fetch_failures[symbol] = "empty dataset"
                continue
            market_frames[symbol] = frame

        correlation_matrix = self._build_correlation_matrix(market_frames)
        snapshot = {
            "timestamp": end.isoformat(),
            "heartbeat": end.isoformat(),
            "timeframe": self.config.timeframe,
            "symbols": [],
            "correlation_matrix": (
                correlation_matrix.round(4).to_dict() if not correlation_matrix.empty else {}
            ),
            "fetch_failures": fetch_failures,
        }

        for symbol, frame in market_frames.items():
            penalty = self._correlation_penalty(symbol, correlation_matrix)
            signal, meta, filter_reason = self.signal_engine.generate_forex_signal(
                frame,
                correlation_penalty=penalty,
            )
            diagnostics = self._build_symbol_metrics(
                symbol=symbol,
                frame=frame,
                meta=meta,
                signal=signal,
                filter_reason=filter_reason,
                correlation_penalty=penalty,
            )
            snapshot["symbols"].append(diagnostics)
            self._audit_decision(symbol, signal, diagnostics, filter_reason)
            self._publish_signal(symbol, signal, meta, diagnostics)

        with self._lock:
            self._cycle_count += 1
            self._last_heartbeat = end.isoformat()
            self._last_error = None if snapshot["symbols"] else "no active market data collected"
            self._history.append(snapshot)
        return snapshot

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = self._history[-1] if self._history else None
            thread = self._thread
            last_heartbeat = self._last_heartbeat
            return {
                "running": bool(thread and thread.is_alive() and not self._stop_event.is_set()),
                "cycle_count": self._cycle_count,
                "last_heartbeat": last_heartbeat,
                "seconds_since_heartbeat": self._seconds_since(last_heartbeat),
                "last_error": self._last_error,
                "watched_symbols": list(self.config.symbols),
                "timeframe": self.config.timeframe,
                "poll_interval_seconds": self.config.poll_interval_seconds,
                "metrics_history_size": len(self._history),
                "latest_snapshot": latest,
            }

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def reconfigure(
        self,
        *,
        symbols: list[str] | None = None,
        timeframe: str | None = None,
        poll_interval_seconds: float | None = None,
        lookback_period: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if symbols is not None:
                self.config.symbols = symbols
            if timeframe is not None:
                self.config.timeframe = timeframe
            if poll_interval_seconds is not None:
                self.config.poll_interval_seconds = poll_interval_seconds
            if lookback_period is not None:
                self.config.lookback_period = lookback_period
            return self.status()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    self._last_heartbeat = datetime.now(UTC).isoformat()
            if self._stop_event.wait(self.config.poll_interval_seconds):
                break

    def _build_correlation_matrix(self, market_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        returns_by_symbol: dict[str, pd.Series] = {}
        for symbol, frame in market_frames.items():
            returns = frame["close"].astype(float).pct_change().dropna()
            if not returns.empty:
                returns_by_symbol[symbol] = returns
        if len(returns_by_symbol) < 2:
            return pd.DataFrame()
        return pd.DataFrame(returns_by_symbol).corr().fillna(0.0)

    def _correlation_penalty(self, symbol: str, matrix: pd.DataFrame) -> float:
        if matrix.empty or symbol not in matrix.columns:
            return 0.0
        peers = matrix.loc[symbol].drop(labels=[symbol], errors="ignore").abs()
        if peers.empty:
            return 0.0
        return float(min(peers.max(), 1.0))

    def _build_symbol_metrics(
        self,
        *,
        symbol: str,
        frame: pd.DataFrame,
        meta: dict[str, float],
        signal: str,
        filter_reason: str,
        correlation_penalty: float,
    ) -> dict[str, Any]:
        close = frame["close"].astype(float)
        returns = close.pct_change().dropna()
        rolling_vol = returns.rolling(20).std().iloc[-1] if len(returns) >= 20 else returns.std()
        realized_vol = float(0.0 if pd.isna(rolling_vol) else rolling_vol * math.sqrt(252 * 24))
        volatility_regime = self._volatility_regime(realized_vol)
        anomaly_score = self._anomaly_score(returns)
        sentiment_score, sentiment_source = self._sentiment_score(symbol=symbol, close=close)
        return {
            "symbol": symbol,
            "last_price": float(close.iloc[-1]),
            "source_backend": str(frame.attrs.get("source_backend", "unknown")),
            "signal": signal,
            "filter_reason": filter_reason,
            "confidence": float(meta.get("confidence", 0.0)),
            "recommended_size": float(meta.get("recommended_size", 0.0)),
            "regime": str(meta.get("regime", volatility_regime)),
            "volatility_regime": volatility_regime,
            "realized_volatility": realized_vol,
            "correlation_penalty": float(correlation_penalty),
            "anomaly_score": anomaly_score,
            "sentiment_score": sentiment_score,
            "sentiment_source": sentiment_source,
            "sentiment_label": self._sentiment_label(sentiment_score),
        }

    @staticmethod
    def _volatility_regime(realized_volatility: float) -> str:
        if realized_volatility >= 0.40:
            return "high"
        if realized_volatility >= 0.18:
            return "medium"
        return "low"

    @staticmethod
    def _anomaly_score(returns: pd.Series) -> float:
        if len(returns) < 5:
            return 0.0
        sample = returns.tail(30)
        mean = float(sample.mean())
        std = float(sample.std())
        if std <= 1e-9:
            return 0.0
        score = abs(float((sample.iloc[-1] - mean) / std))
        return round(score, 4)

    def _sentiment_score(self, *, symbol: str, close: pd.Series) -> tuple[float, str]:
        external = self._external_sentiment(symbol)
        if external is not None:
            score, source = external
            return round(score, 4), source

        if len(close) < 6:
            return 0.0, "price_proxy"
        short_return = float(close.iloc[-1] / close.iloc[-6] - 1.0)
        trend = (
            close.ewm(span=8, adjust=False).mean().iloc[-1]
            - close.ewm(span=21, adjust=False).mean().iloc[-1]
        )
        baseline = abs(float(close.iloc[-1])) or 1.0
        score = math.tanh((short_return * 10.0) + (float(trend) / baseline * 20.0))
        return round(score, 4), "price_proxy"

    def _external_sentiment(self, symbol: str) -> tuple[float, str] | None:
        cache_key = symbol.strip().upper()
        now_ts = time.time()
        cached = self._sentiment_cache.get(cache_key)
        if cached and (now_ts - cached[2]) <= self.sentiment_cache_ttl_seconds:
            return cached[0], cached[1]

        # Crypto has a robust public sentiment proxy without API keys.
        if cache_key in {"BTC-USD", "ETH-USD", "BTCUSD", "ETHUSD"}:
            crypto = self._crypto_fear_greed_sentiment()
            if crypto is not None:
                self._sentiment_cache[cache_key] = (crypto[0], crypto[1], now_ts)
                return crypto

        if self.alpha_vantage_api_key:
            alpha = self._alpha_vantage_news_sentiment(cache_key)
            if alpha is not None:
                self._sentiment_cache[cache_key] = (alpha[0], alpha[1], now_ts)
                return alpha
        return None

    def _alpha_vantage_news_sentiment(self, symbol: str) -> tuple[float, str] | None:
        ticker = symbol.replace("/", "").replace("=X", "")
        if ticker == "JPY":
            ticker = "USDJPY"
        try:
            response = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker,
                    "limit": 50,
                    "apikey": self.alpha_vantage_api_key,
                },
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            feed = payload.get("feed", [])
            if not isinstance(feed, list) or not feed:
                return None

            scores: list[float] = []
            for item in feed:
                if not isinstance(item, dict):
                    continue
                raw = item.get("overall_sentiment_score")
                try:
                    scores.append(float(raw))
                except (TypeError, ValueError):
                    continue

            if not scores:
                return None
            avg = float(sum(scores) / len(scores))
            clipped = max(-1.0, min(1.0, avg))
            return clipped, "alpha_vantage_news"
        except Exception:
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
            value = float(data[0].get("value", 50.0))
            normalized = max(-1.0, min(1.0, (value - 50.0) / 50.0))
            return normalized, "alt_me_fear_greed"
        except Exception:
            return None

    @staticmethod
    def _sentiment_score_legacy(close: pd.Series) -> float:
        if len(close) < 6:
            return 0.0
        short_return = float(close.iloc[-1] / close.iloc[-6] - 1.0)
        trend = (
            close.ewm(span=8, adjust=False).mean().iloc[-1]
            - close.ewm(span=21, adjust=False).mean().iloc[-1]
        )
        baseline = abs(float(close.iloc[-1])) or 1.0
        score = math.tanh((short_return * 10.0) + (float(trend) / baseline * 20.0))
        return round(score, 4)

    @staticmethod
    def _sentiment_label(sentiment_score: float) -> str:
        if sentiment_score >= 0.3:
            return "bullish"
        if sentiment_score <= -0.3:
            return "bearish"
        return "neutral"

    def _audit_decision(
        self,
        symbol: str,
        signal: str,
        diagnostics: dict[str, Any],
        filter_reason: str,
    ) -> None:
        self.auditor.audit(
            action="market_watcher_decision",
            payload={
                "symbol": symbol,
                "signal": signal,
                "diagnostics": diagnostics,
                "filter_reason": filter_reason,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            policy_pack="trading_signal",
        )

    def _publish_signal(
        self,
        symbol: str,
        signal: str,
        meta: dict[str, float],
        diagnostics: dict[str, Any],
    ) -> None:
        if signal in {NO_SIGNAL, "HOLD"}:
            return

        signal_key = (symbol, signal)
        now_ts = time.time()
        last_published = self._last_published_at.get(signal_key, 0.0)
        if now_ts - last_published < self.config.signal_cooldown_seconds:
            return

        receipt = self.auditor.audit(
            action="market_watcher_publish_signal",
            payload={
                "symbol": symbol,
                "signal": signal,
                "diagnostics": diagnostics,
                "indicators": meta,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            policy_pack="trading_signal",
        )
        indicator_payload = {
            "confidence": float(meta.get("confidence", 0.0)),
            "recommended_size": float(meta.get("recommended_size", 0.0)),
            "anomaly_score": float(diagnostics.get("anomaly_score", 0.0)),
            "correlation_penalty": float(diagnostics.get("correlation_penalty", 0.0)),
            "realized_volatility": float(diagnostics.get("realized_volatility", 0.0)),
        }
        self.ledger.add_signal(
            signal_id=f"mw-{uuid.uuid4().hex[:10]}",
            agent_type="market_watcher",
            instrument=symbol,
            signal=signal,
            indicators=indicator_payload,
            chain_data=diagnostics,
            receipt=str(receipt.get("receipt", "mock-receipt")),
            ttl_minutes=self.config.signal_ttl_minutes,
        )
        self._last_published_at[signal_key] = now_ts

    @staticmethod
    def _seconds_since(timestamp: str | None) -> float | None:
        if not timestamp:
            return None
        try:
            return round((datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds(), 2)
        except ValueError:
            return None
