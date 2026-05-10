from __future__ import annotations

import numpy as np
import pandas as pd

from backtesting.engine import BacktestConfig, BacktestEngine


def _synthetic_ohlcv(rows: int = 900, start: str = "2023-01-01") -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=rows, freq="h", tz="UTC")
    trend = np.linspace(100.0, 140.0, rows)
    wave = np.sin(np.linspace(0, 60, rows)) * 4.0
    noise = np.cos(np.linspace(0, 20, rows)) * 0.5
    close = trend + wave + noise

    df = pd.DataFrame(index=idx)
    df["close"] = close
    df["open"] = df["close"].shift(1).fillna(df["close"])
    df["high"] = df[["open", "close"]].max(axis=1) * 1.0015
    df["low"] = df[["open", "close"]].min(axis=1) * 0.9985
    df["volume"] = 10_000
    return df


def test_vectorized_backtest_report_and_metrics():
    engine = BacktestEngine(cache_dir=".cache/backtesting-test")
    synthetic = _synthetic_ohlcv()

    def fake_download(*args, **kwargs):
        return synthetic

    engine.downloader.download = fake_download  # type: ignore[method-assign]

    cfg = BacktestConfig(
        symbols=["EURUSD", "SPY"],
        timeframe="1h",
        start="2023-01-01",
        end="2024-01-01",
        strategy="macd_rsi",
        strategy_params={"rsi_buy": 35, "rsi_sell": 65},
        initial_cash=50_000.0,
    )

    report = engine.run(cfg)

    assert report.results
    assert "limits" in report.risk_snapshot
    assert "var" in report.risk_snapshot
    for k in [
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "max_drawdown_duration_bars",
        "win_rate",
        "profit_factor",
        "expectancy",
    ]:
        assert k in report.portfolio_metrics

    first = next(iter(report.results.values()))
    assert not first.equity_curve.empty
    assert not first.drawdown.empty
    assert first.monthly_returns_heatmap is not None
    assert isinstance(first.monte_carlo, dict)


def test_optimization_and_walk_forward_outputs():
    engine = BacktestEngine(cache_dir=".cache/backtesting-test")
    synthetic = _synthetic_ohlcv(rows=1200)

    def fake_download(*args, **kwargs):
        return synthetic

    engine.downloader.download = fake_download  # type: ignore[method-assign]

    cfg = BacktestConfig(
        symbols=["EURUSD"],
        timeframe="1h",
        start="2023-01-01",
        end="2024-06-01",
        strategy="macd_rsi",
        strategy_params={"rsi_buy": 35, "rsi_sell": 65},
    )

    opt = engine.optimize(
        cfg,
        symbol="EURUSD",
        param_grid={
            "rsi_buy": [30, 35],
            "rsi_sell": [65, 70],
        },
    )
    assert not opt.empty
    assert "objective" in opt.columns

    wf = engine.walk_forward(
        cfg,
        symbol="EURUSD",
        param_grid={
            "rsi_buy": [30, 35],
            "rsi_sell": [65, 70],
        },
        train_bars=300,
        test_bars=120,
        step_bars=120,
    )
    assert "windows" in wf
    assert "summary" in wf
    assert isinstance(wf["windows"], list)
