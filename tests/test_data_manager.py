from __future__ import annotations

import pandas as pd

from backtesting.data import DataManager


def _sample_ohlcv() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=6, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105],
            "high": [101, 102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
            "volume": [1000, 1100, 1200, 1300, 1400, 1500],
        },
        index=idx,
    )


def test_data_manager_falls_through_backend_order(tmp_path):
    manager = DataManager(cache_dir=tmp_path, backend_order=["polygon", "yfinance"])

    def fake_enabled(backend: str) -> bool:
        return backend in {"polygon", "yfinance"}

    def fake_fetch(
        *, backend: str, symbol: str, timeframe: str, start: str, end: str
    ) -> pd.DataFrame:
        del symbol, timeframe, start, end
        if backend == "polygon":
            return pd.DataFrame()
        return _sample_ohlcv()

    manager._backend_enabled = fake_enabled  # type: ignore[method-assign]
    manager._fetch_from_backend = fake_fetch  # type: ignore[method-assign]

    data = manager.download(
        symbol="EURUSD",
        timeframe="1h",
        start="2025-01-01",
        end="2025-01-02",
        use_cache=False,
    )

    assert not data.empty
    assert data.attrs["source_backend"] == "yfinance"
    assert list(data.columns) == ["open", "high", "low", "close", "volume"]


def test_data_manager_reuses_cache_before_refetch(tmp_path):
    manager = DataManager(cache_dir=tmp_path, backend_order=["yfinance"])
    calls = {"count": 0}

    def fake_fetch(
        *, backend: str, symbol: str, timeframe: str, start: str, end: str
    ) -> pd.DataFrame:
        del backend, symbol, timeframe, start, end
        calls["count"] += 1
        return _sample_ohlcv()

    manager._fetch_from_backend = fake_fetch  # type: ignore[method-assign]

    first = manager.download(
        symbol="SPY",
        timeframe="1h",
        start="2025-01-01",
        end="2025-01-02",
        use_cache=True,
    )
    second = manager.download(
        symbol="SPY",
        timeframe="1h",
        start="2025-01-01",
        end="2025-01-02",
        use_cache=True,
    )

    assert calls["count"] == 1
    assert not first.empty
    assert not second.empty
    assert second.attrs["source_backend"] == "yfinance"
