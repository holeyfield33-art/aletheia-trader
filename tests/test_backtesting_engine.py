from __future__ import annotations

import numpy as np
import pandas as pd

from backtesting.engine import BacktestConfig, BacktestEngine


def _synthetic_ohlcv(rows: int = 420, start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=rows, freq="h", tz="UTC")
    base = np.linspace(100.0, 130.0, rows)
    wave = np.sin(np.linspace(0, 20, rows)) * 2.5
    close = base + wave
    data = pd.DataFrame(index=idx)
    data["close"] = close
    data["open"] = data["close"].shift(1).fillna(data["close"])
    data["high"] = data[["open", "close"]].max(axis=1) * 1.001
    data["low"] = data[["open", "close"]].min(axis=1) * 0.999
    data["volume"] = 10_000
    return data


def test_backtest_engine_metrics_and_curves():
    engine = BacktestEngine(cache_dir=".cache/backtesting-test")
    synthetic = _synthetic_ohlcv()

    def fake_fetch(*args, **kwargs):
        return synthetic

    engine.fetch_ohlcv = fake_fetch  # type: ignore[method-assign]

    cfg = BacktestConfig(
        symbols=["EURUSD=X", "SPY"],
        timeframes=["1h"],
        start="2024-01-01",
        end="2024-03-01",
        strategy_params={"confidence_threshold": 55, "rsi_buy": 35, "rsi_sell": 65},
        initial_cash=50_000.0,
    )

    result = engine.run_backtest(cfg)

    for k in [
        "total_return",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "win_rate",
        "profit_factor",
        "expectancy",
    ]:
        assert k in result.metrics

    assert not result.equity_curve.empty
    assert "equity" in result.equity_curve.columns
    assert not result.underwater_curve.empty
    assert "underwater" in result.underwater_curve.columns
    assert result.monte_carlo is not None
    assert result.robustness is not None


def test_walk_forward_optimization_returns_windows():
    engine = BacktestEngine(cache_dir=".cache/backtesting-test")
    synthetic = _synthetic_ohlcv(rows=500)

    def fake_fetch(*args, **kwargs):
        return synthetic

    engine.fetch_ohlcv = fake_fetch  # type: ignore[method-assign]

    cfg = BacktestConfig(
        symbols=["BTC-USD"],
        timeframes=["1h"],
        start="2024-01-01",
        end="2024-04-01",
        strategy_params={"confidence_threshold": 55},
    )

    wf = engine.walk_forward_optimize(
        cfg,
        parameter_grid={"rsi_buy": [30, 35], "rsi_sell": [65, 70]},
        train_bars=180,
        test_bars=60,
    )

    assert "windows" in wf
    assert "summary" in wf
    assert isinstance(wf["windows"], list)
    if wf["windows"]:
        assert "best_params" in wf["windows"][0]
