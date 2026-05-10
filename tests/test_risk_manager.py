from __future__ import annotations

import numpy as np
import pandas as pd

from risk.manager import PortfolioRiskState, RiskConfig, RiskManager, side_from_signal


def _equity_curve() -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=10, freq="D", tz="UTC")
    vals = [100000, 101000, 102000, 101500, 100800, 99500, 99000, 98500, 98000, 97500]
    return pd.Series(vals, index=idx)


def test_dynamic_position_sizing_scales_with_confidence_and_correlation():
    manager = RiskManager(RiskConfig(max_risk_per_trade=0.01, max_position_notional_pct=0.5))

    hi_conf = manager.dynamic_position_size(
        capital=100000,
        entry_price=100,
        stop_price=98,
        signal_confidence=90,
        correlation_penalty=0.0,
    )
    lo_conf = manager.dynamic_position_size(
        capital=100000,
        entry_price=100,
        stop_price=98,
        signal_confidence=40,
        correlation_penalty=0.5,
    )

    assert hi_conf["units"] > lo_conf["units"]
    assert 0.0 < hi_conf["size_pct_capital"] <= 0.5


def test_var_cvar_and_correlation_matrix():
    manager = RiskManager()
    rng = np.random.default_rng(7)
    idx = pd.date_range("2025-01-01", periods=300, freq="h", tz="UTC")

    r1 = pd.Series(rng.normal(0.0002, 0.01, size=len(idx)), index=idx)
    r2 = pd.Series(rng.normal(0.0001, 0.012, size=len(idx)), index=idx)

    tail = manager.var_cvar(r1, confidence=0.95)
    assert tail["var"] <= 0.0
    assert tail["cvar"] <= tail["var"]

    corr = manager.correlation_matrix({"A": r1, "B": r2})
    assert list(corr.columns) == ["A", "B"]
    assert float(corr.loc["A", "A"]) == 1.0


def test_limits_and_circuit_breaker():
    manager = RiskManager(
        RiskConfig(max_daily_loss_pct=0.01, max_total_loss_pct=0.02, max_drawdown_pct=0.02)
    )
    state = PortfolioRiskState(
        equity_curve=_equity_curve(),
        starting_capital=100000,
        current_capital=97500,
        open_notional=10000,
        day_start_capital=99500,
    )
    limits = manager.check_limits(state)
    assert limits["allow_new_risk"] is False
    assert limits["circuit_breaker"] is True


def test_portfolio_snapshot_contains_core_metrics():
    manager = RiskManager()
    idx = pd.date_range("2025-01-01", periods=120, freq="h", tz="UTC")
    a = pd.Series(np.sin(np.linspace(0, 10, len(idx))) * 0.005, index=idx)
    b = pd.Series(np.cos(np.linspace(0, 10, len(idx))) * 0.004, index=idx)
    state = PortfolioRiskState(
        equity_curve=_equity_curve(),
        starting_capital=100000,
        current_capital=99000,
        open_notional=12000,
        day_start_capital=100200,
    )

    snap = manager.portfolio_risk_snapshot(state, {"EURUSD": a, "SPY": b})
    assert "limits" in snap
    assert "var" in snap and "cvar" in snap
    assert "correlation_matrix" in snap


def test_side_from_signal_mapping():
    assert side_from_signal("BUY") == "long"
    assert side_from_signal("PUT_BUY") == "short"
    assert side_from_signal("HOLD") == "flat"
