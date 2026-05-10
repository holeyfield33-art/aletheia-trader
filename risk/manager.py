from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class RiskConfig:
    max_risk_per_trade: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_total_loss_pct: float = 0.12
    max_drawdown_pct: float = 0.15
    var_confidence: float = 0.95
    cvar_confidence: float = 0.95
    max_position_notional_pct: float = 0.35


@dataclass
class PortfolioRiskState:
    equity_curve: pd.Series
    starting_capital: float
    current_capital: float
    open_notional: float
    day_start_capital: float


class RiskManager:
    """Production-grade risk controls for strategy and portfolio layers."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def dynamic_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_price: float,
        signal_confidence: float,
        correlation_penalty: float = 0.0,
    ) -> dict[str, float]:
        """Calculate risk-aware position size using stop distance and confidence scaling."""
        capital = max(float(capital), 0.0)
        entry_price = max(float(entry_price), 0.0)
        stop_price = float(stop_price)

        stop_distance = abs(entry_price - stop_price)
        if capital <= 0 or entry_price <= 0 or stop_distance <= 0:
            return {
                "units": 0.0,
                "notional": 0.0,
                "risk_budget": 0.0,
                "size_pct_capital": 0.0,
            }

        confidence_scale = np.clip(float(signal_confidence) / 100.0, 0.0, 1.0)
        corr_scale = 1.0 - np.clip(float(correlation_penalty), 0.0, 0.9)
        risk_budget = capital * self.config.max_risk_per_trade * confidence_scale * corr_scale
        units = max(risk_budget / stop_distance, 0.0)
        notional = units * entry_price

        max_notional = capital * self.config.max_position_notional_pct
        if notional > max_notional and entry_price > 0:
            units = max_notional / entry_price
            notional = max_notional

        return {
            "units": float(units),
            "notional": float(notional),
            "risk_budget": float(risk_budget),
            "size_pct_capital": float(notional / capital) if capital > 0 else 0.0,
        }

    def var_cvar(
        self,
        returns: pd.Series,
        confidence: float | None = None,
    ) -> dict[str, float]:
        """Historical VaR/CVaR in return space (negative values imply loss)."""
        if returns.empty:
            return {
                "var": 0.0,
                "cvar": 0.0,
                "confidence": float(confidence or self.config.var_confidence),
            }

        conf = float(confidence or self.config.var_confidence)
        conf = float(np.clip(conf, 0.5, 0.999))

        clean = returns.dropna().astype(float)
        if clean.empty:
            return {"var": 0.0, "cvar": 0.0, "confidence": conf}

        q = float(np.quantile(clean, 1.0 - conf))
        tail = clean[clean <= q]
        cvar = float(tail.mean()) if not tail.empty else q

        return {"var": q, "cvar": cvar, "confidence": conf}

    def correlation_matrix(self, returns_by_asset: dict[str, pd.Series]) -> pd.DataFrame:
        """Compute cross-asset return correlations with aligned timestamps."""
        if not returns_by_asset:
            return pd.DataFrame()

        frame = pd.DataFrame({k: v for k, v in returns_by_asset.items()}).dropna(how="all")
        if frame.empty:
            return pd.DataFrame()
        return frame.corr().fillna(0.0)

    def check_limits(
        self,
        state: PortfolioRiskState,
    ) -> dict[str, object]:
        """Evaluate drawdown and loss circuit-breaker state for execution gating."""
        if state.equity_curve.empty:
            return {
                "allow_new_risk": True,
                "reasons": [],
                "daily_loss_pct": 0.0,
                "total_loss_pct": 0.0,
                "drawdown_pct": 0.0,
                "circuit_breaker": False,
            }

        equity = state.equity_curve.astype(float)
        peak = float(equity.cummax().iloc[-1]) if len(equity) else float(state.starting_capital)

        day_start = max(float(state.day_start_capital), 1e-9)
        start_cap = max(float(state.starting_capital), 1e-9)
        current = float(state.current_capital)

        daily_loss_pct = max((day_start - current) / day_start, 0.0)
        total_loss_pct = max((start_cap - current) / start_cap, 0.0)
        drawdown_pct = max((peak - current) / peak, 0.0) if peak > 0 else 0.0

        reasons: list[str] = []
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            reasons.append("daily_loss_limit")
        if total_loss_pct >= self.config.max_total_loss_pct:
            reasons.append("total_loss_limit")
        if drawdown_pct >= self.config.max_drawdown_pct:
            reasons.append("drawdown_circuit_breaker")

        return {
            "allow_new_risk": len(reasons) == 0,
            "reasons": reasons,
            "daily_loss_pct": float(daily_loss_pct),
            "total_loss_pct": float(total_loss_pct),
            "drawdown_pct": float(drawdown_pct),
            "circuit_breaker": "drawdown_circuit_breaker" in reasons,
        }

    def portfolio_risk_snapshot(
        self,
        state: PortfolioRiskState,
        returns_by_asset: dict[str, pd.Series],
    ) -> dict[str, object]:
        corr = self.correlation_matrix(returns_by_asset)
        if returns_by_asset:
            portfolio_returns = pd.concat(list(returns_by_asset.values()), axis=1).mean(axis=1)
        else:
            portfolio_returns = pd.Series(dtype=float)
        tail = self.var_cvar(portfolio_returns, confidence=self.config.var_confidence)
        limits = self.check_limits(state)

        return {
            "limits": limits,
            "var": float(tail["var"]),
            "cvar": float(tail["cvar"]),
            "correlation_matrix": corr.round(6).to_dict(),
            "open_notional_pct": (
                float(state.open_notional / state.current_capital)
                if state.current_capital > 0
                else 0.0
            ),
        }


def side_from_signal(signal: str) -> Literal["long", "short", "flat"]:
    s = signal.upper().strip()
    if s in {"BUY", "CALL_BUY", "LONG"}:
        return "long"
    if s in {"SELL", "PUT_BUY", "SHORT"}:
        return "short"
    return "flat"
