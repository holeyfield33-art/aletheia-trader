from __future__ import annotations

import asyncio
import math
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from agents.signal_engine import NO_SIGNAL, SignalEngine
from backtesting.data import DataManager
from brokers.signal_and_order_ledger import SignalAndOrderLedger
from core.aletheia_guard import AletheiaCoreGuard
from market_watcher.alerts import AlertEngine
from market_watcher.data_feeds import MarketDataFeeds
from market_watcher.monitoring import HeartbeatMonitor, HookRegistry, MarketStateStore
from market_watcher.regime_detector import RegimeDetector
from market_watcher.signal_generator import WatcherSignalGenerator


@dataclass
class MarketWatcherConfig:
    symbols: list[str]
    timeframe: str = "1h"
    lookback_period: str = "30d"
    confirmation_timeframes: tuple[str, ...] = ("15m", "1h", "4h")
    poll_interval_seconds: float = 60.0
    signal_ttl_minutes: int = 90
    history_limit: int = 120
    signal_cooldown_seconds: float = 900.0


class MarketWatcher:
    """Professional market watcher orchestrator with heartbeat and secure signal publication."""

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
        self.feeds = MarketDataFeeds(data_manager=data_manager or DataManager())
        self.detector = RegimeDetector()
        self.signal_generator = WatcherSignalGenerator(signal_engine=signal_engine)
        self.alerts = AlertEngine()
        self.state_store = MarketStateStore(max_history=self.config.history_limit)
        self.heartbeat = HeartbeatMonitor()
        self.hooks = HookRegistry()
        self.ledger = ledger or SignalAndOrderLedger()
        self.guard = AletheiaCoreGuard(gateway_url=gateway_url, api_key=api_key)

        self._last_published_at: dict[tuple[str, str], float] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

        # Backward-compatible attributes used by existing API/tests.
        self.data_manager = self.feeds.data_manager
        self.signal_engine = self.signal_generator.signal_engine
        self.auditor = self.guard.wrapper

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
        worker = self._thread
        if worker and worker.is_alive():
            worker.join(timeout=timeout)
        with self._lock:
            self._thread = None
        return self.status()

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

    def run_cycle(self) -> dict[str, Any]:
        cycle_ts = datetime.now(UTC)
        snapshots, fetch_failures = self.feeds.fetch_many(
            symbols=self.config.symbols,
            timeframe=self.config.timeframe,
            lookback_period=self.config.lookback_period,
            end=cycle_ts,
        )

        correlation_matrix = self._build_correlation_matrix(snapshots)
        snapshot: dict[str, Any] = {
            "timestamp": cycle_ts.isoformat(),
            "heartbeat": cycle_ts.isoformat(),
            "timeframe": self.config.timeframe,
            "symbols": [],
            "alerts": [],
            "correlation_matrix": (
                correlation_matrix.round(4).to_dict() if not correlation_matrix.empty else {}
            ),
            "fetch_failures": fetch_failures,
        }

        for symbol, feed in snapshots.items():
            corr_penalty = self._correlation_penalty(symbol, correlation_matrix)
            regime = self.detector.detect(feed.frame["close"].astype(float))
            multi_tf = self.feeds.fetch_multi_timeframe(
                symbol=symbol,
                timeframes=[
                    tf for tf in self.config.confirmation_timeframes if tf != self.config.timeframe
                ],
                lookback_period=self.config.lookback_period,
                end=cycle_ts,
            )

            result = self.signal_generator.generate(
                frame=feed.frame,
                regime=regime,
                correlation_penalty=corr_penalty,
                multi_tf_frames=multi_tf,
            )
            signal = str(result["signal"])
            indicators = result["indicators"]
            filter_reason = str(result.get("filter_reason", ""))

            sentiment_score, sentiment_source = self._sentiment_score(
                symbol=symbol,
                close=feed.frame["close"].astype(float),
            )
            anomaly = self.detector.anomaly_score(feed.frame["close"].astype(float))
            diagnostics = {
                "symbol": symbol,
                "signal": signal,
                "filter_reason": filter_reason,
                "source_backend": feed.source_backend,
                "last_price": feed.last_price,
                "last_volume": feed.last_volume,
                "order_flow_imbalance": feed.order_flow_imbalance,
                "realized_volatility": feed.realized_volatility,
                "volatility_regime": self._volatility_bucket(feed.realized_volatility),
                "regime": str(indicators.get("regime", regime)),
                "confidence": float(indicators.get("confidence", 0.0)),
                "recommended_size": float(indicators.get("recommended_size", 0.0)),
                "correlation_penalty": corr_penalty,
                "anomaly_score": anomaly,
                "sentiment_score": sentiment_score,
                "sentiment_source": sentiment_source,
                "sentiment_label": self._sentiment_label(sentiment_score),
                "mtf_confirmed": bool(indicators.get("mtf_confirmed", False)),
            }

            snapshot["symbols"].append(diagnostics)
            self.hooks.emit("symbol_update", diagnostics)
            alerts = self.alerts.evaluate_symbol(diagnostics)
            snapshot["alerts"].extend(alerts)

            self._audit_decision(symbol=symbol, diagnostics=diagnostics)
            self._publish_signal(symbol=symbol, signal=signal, diagnostics=diagnostics)

        self.state_store.append_snapshot(snapshot)
        self.heartbeat.tick()
        self.hooks.emit("cycle_complete", snapshot)
        return snapshot

    async def run_cycle_async(self) -> dict[str, Any]:
        """Async wrapper so watcher can be integrated into async schedulers."""
        return await asyncio.to_thread(self.run_cycle)

    def history(self) -> list[dict[str, Any]]:
        return self.state_store.history()

    def sentiment_provider_health(self) -> dict[str, dict[str, object]]:
        return self.feeds.sentiment_provider_health()

    def status(self) -> dict[str, Any]:
        latest = self.state_store.latest_snapshot()
        hb = self.heartbeat.snapshot()
        worker = self._thread
        return {
            "running": bool(worker and worker.is_alive() and not self._stop_event.is_set()),
            "cycle_count": hb["cycle_count"],
            "last_heartbeat": hb["last_heartbeat"],
            "seconds_since_heartbeat": hb["seconds_since_heartbeat"],
            "last_error": hb["last_error"],
            "watched_symbols": list(self.config.symbols),
            "timeframe": self.config.timeframe,
            "poll_interval_seconds": self.config.poll_interval_seconds,
            "metrics_history_size": len(self.state_store.history()),
            "latest_snapshot": latest,
        }

    # Backward-compat hook used in tests.
    def _external_sentiment(self, symbol: str) -> tuple[float, str] | None:
        return self.feeds._external_sentiment(symbol)

    def _sentiment_score(self, *, symbol: str, close: pd.Series) -> tuple[float, str]:
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
        score = math.tanh((short_return * 10.0) + (float(trend) / baseline * 20.0))
        return round(score, 4), "price_proxy"

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception as exc:
                self.heartbeat.fail(str(exc))
            if self._stop_event.wait(self.config.poll_interval_seconds):
                break

    def _publish_signal(self, *, symbol: str, signal: str, diagnostics: dict[str, Any]) -> None:
        if signal in {NO_SIGNAL, "HOLD"}:
            return

        key = (symbol, signal)
        now_ts = time.time()
        last = self._last_published_at.get(key, 0.0)
        if now_ts - last < self.config.signal_cooldown_seconds:
            return

        receipt = self.guard.audit_decision(
            action="market_watcher_publish_signal",
            payload={
                "symbol": symbol,
                "signal": signal,
                "diagnostics": diagnostics,
            },
        )

        indicator_payload = {
            "confidence": float(diagnostics.get("confidence", 0.0)),
            "recommended_size": float(diagnostics.get("recommended_size", 0.0)),
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
        self._last_published_at[key] = now_ts

    def _audit_decision(self, *, symbol: str, diagnostics: dict[str, Any]) -> None:
        self.guard.audit_decision(
            action="market_watcher_decision",
            payload={
                "symbol": symbol,
                "signal": diagnostics.get("signal"),
                "diagnostics": diagnostics,
                "filter_reason": diagnostics.get("filter_reason", ""),
            },
        )

    @staticmethod
    def _build_correlation_matrix(snapshots: dict[str, Any]) -> pd.DataFrame:
        returns_by_symbol: dict[str, pd.Series] = {}
        for symbol, feed in snapshots.items():
            if not hasattr(feed, "frame"):
                continue
            frame = feed.frame
            if "close" not in frame.columns:
                continue
            returns = frame["close"].astype(float).pct_change().dropna()
            if not returns.empty:
                returns_by_symbol[symbol] = returns
        if len(returns_by_symbol) < 2:
            return pd.DataFrame()
        return pd.DataFrame(returns_by_symbol).corr().fillna(0.0)

    @staticmethod
    def _correlation_penalty(symbol: str, matrix: pd.DataFrame) -> float:
        if matrix.empty or symbol not in matrix.columns:
            return 0.0
        peers = matrix.loc[symbol].drop(labels=[symbol], errors="ignore").abs()
        if peers.empty:
            return 0.0
        return float(min(peers.max(), 1.0))

    @staticmethod
    def _volatility_bucket(realized_volatility: float) -> str:
        if realized_volatility >= 0.4:
            return "high"
        if realized_volatility >= 0.18:
            return "medium"
        return "low"

    @staticmethod
    def _sentiment_label(sentiment_score: float) -> str:
        if sentiment_score >= 0.3:
            return "bullish"
        if sentiment_score <= -0.3:
            return "bearish"
        return "neutral"
