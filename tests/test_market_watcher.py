from __future__ import annotations

import time

import pandas as pd

from agents.market_watcher import MarketWatcher, MarketWatcherConfig
from agents.signal_engine import NO_SIGNAL
from backtesting.data import DataManager
from brokers.signal_and_order_ledger import SignalAndOrderLedger


def _sample_market_frame(rows: int = 48) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series([100 + (i * 0.4) + ((i % 5) * 0.2) for i in range(rows)], index=idx)
    frame = pd.DataFrame(index=idx)
    frame["open"] = close.shift(1).fillna(close)
    frame["high"] = close * 1.002
    frame["low"] = close * 0.998
    frame["close"] = close
    frame["volume"] = 1000
    return frame


def test_market_watcher_run_cycle_collects_metrics_and_publishes_signal(tmp_path):
    ledger = SignalAndOrderLedger(
        signals_path=str(tmp_path / "pending.json"),
        orders_path=str(tmp_path / "orders.json"),
    )
    manager = DataManager(cache_dir=tmp_path / "cache")
    watcher = MarketWatcher(
        config=MarketWatcherConfig(symbols=["EUR/USD", "SPY"], poll_interval_seconds=0.01),
        data_manager=manager,
        ledger=ledger,
    )

    sample = _sample_market_frame()

    def fake_download(
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        use_cache: bool = True,
        backend_order=None,
    ):
        del symbol, timeframe, start, end, use_cache, backend_order
        frame = sample.copy()
        frame.attrs["source_backend"] = "test"
        return frame

    watcher.data_manager.download = fake_download  # type: ignore[method-assign]
    watcher.signal_engine.generate_forex_signal = lambda df, correlation_penalty=0.0: (  # type: ignore[method-assign]
        "BUY",
        {
            "confidence": 82.0,
            "recommended_size": 12.5,
            "regime": "trending",
        },
        "",
    )
    watcher.auditor.audit = lambda action, payload, policy_pack="trading_signal": {  # type: ignore[method-assign]
        "receipt": f"test-{action}",
        "payload": payload,
        "policy_pack": policy_pack,
    }

    snapshot = watcher.run_cycle()

    assert snapshot["symbols"]
    assert snapshot["symbols"][0]["volatility_regime"] in {"low", "medium", "high"}
    assert snapshot["symbols"][0]["source_backend"] == "test"
    assert watcher.status()["cycle_count"] == 1
    assert ledger.get_pending_signals()


def test_market_watcher_background_loop_updates_heartbeat(tmp_path):
    ledger = SignalAndOrderLedger(
        signals_path=str(tmp_path / "pending.json"),
        orders_path=str(tmp_path / "orders.json"),
    )
    watcher = MarketWatcher(
        config=MarketWatcherConfig(symbols=["BTC-USD"], poll_interval_seconds=0.02),
        ledger=ledger,
        data_manager=DataManager(cache_dir=tmp_path / "cache"),
    )

    sample = _sample_market_frame()

    def fake_download(
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        use_cache: bool = True,
        backend_order=None,
    ):
        del symbol, timeframe, start, end, use_cache, backend_order
        frame = sample.copy()
        frame.attrs["source_backend"] = "test"
        return frame

    watcher.data_manager.download = fake_download  # type: ignore[method-assign]
    watcher.signal_engine.generate_forex_signal = lambda df, correlation_penalty=0.0: (  # type: ignore[method-assign]
        NO_SIGNAL,
        {
            "confidence": 45.0,
            "recommended_size": 0.0,
            "regime": "ranging",
        },
        "filtered",
    )
    watcher.auditor.audit = lambda action, payload, policy_pack="trading_signal": {  # type: ignore[method-assign]
        "receipt": f"test-{action}",
        "payload": payload,
        "policy_pack": policy_pack,
    }

    watcher.start()
    time.sleep(0.06)
    status = watcher.stop()

    assert status["running"] is False
    assert status["cycle_count"] >= 1
    assert status["last_heartbeat"] is not None


def test_market_watcher_uses_external_sentiment_feed_when_available(tmp_path):
    ledger = SignalAndOrderLedger(
        signals_path=str(tmp_path / "pending.json"),
        orders_path=str(tmp_path / "orders.json"),
    )
    watcher = MarketWatcher(
        config=MarketWatcherConfig(symbols=["SPY"], poll_interval_seconds=0.02),
        ledger=ledger,
        data_manager=DataManager(cache_dir=tmp_path / "cache"),
    )

    sample = _sample_market_frame()

    def fake_download(
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        use_cache: bool = True,
        backend_order=None,
    ):
        del symbol, timeframe, start, end, use_cache, backend_order
        frame = sample.copy()
        frame.attrs["source_backend"] = "test"
        return frame

    watcher.data_manager.download = fake_download  # type: ignore[method-assign]
    watcher._external_sentiment = lambda symbol: (0.71, "alpha_vantage_news")  # type: ignore[method-assign]
    watcher.signal_engine.generate_forex_signal = lambda df, correlation_penalty=0.0: (  # type: ignore[method-assign]
        "HOLD",
        {
            "confidence": 60.0,
            "recommended_size": 5.0,
            "regime": "trending",
        },
        "",
    )
    watcher.auditor.audit = lambda action, payload, policy_pack="trading_signal": {  # type: ignore[method-assign]
        "receipt": f"test-{action}",
        "payload": payload,
        "policy_pack": policy_pack,
    }

    snapshot = watcher.run_cycle()
    assert snapshot["symbols"]
    assert snapshot["symbols"][0]["sentiment_source"] == "alpha_vantage_news"
    assert float(snapshot["symbols"][0]["sentiment_score"]) == 0.71
