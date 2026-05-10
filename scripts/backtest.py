from __future__ import annotations

import json

from backtesting.engine import BacktestConfig, BacktestEngine


def main() -> None:
    engine = BacktestEngine()
    cfg = BacktestConfig(
        symbols=["EURUSD", "BTC-USD", "SPY"],
        timeframe="1h",
        start="2023-01-01",
        end="2025-01-01",
        strategy="macd_rsi",
        strategy_params={
            "rsi_buy": 35,
            "rsi_sell": 65,
            "trend_threshold": 0.003,
        },
        initial_cash=100_000.0,
        commission_bps=2.0,
        slippage_bps=1.0,
        spread_bps=1.5,
        risk_per_trade=0.01,
    )

    report = engine.run(cfg)
    optimization = engine.optimize(
        cfg,
        symbol="EURUSD",
        param_grid={
            "rsi_buy": [30, 35, 40],
            "rsi_sell": [60, 65, 70],
            "trend_threshold": [0.002, 0.003, 0.004],
        },
    )
    walk_forward = engine.walk_forward_optimize(
        cfg,
        parameter_grid={
            "rsi_buy": [30, 35],
            "rsi_sell": [65, 70],
        },
    )

    payload = {
        "summary": json.loads(engine.to_summary_json(report)),
        "optimization_top5": optimization.head(5).to_dict(orient="records"),
        "walk_forward": walk_forward,
        "portfolio_equity_tail": report.portfolio_equity.tail(5).reset_index().to_dict(orient="records"),
        "portfolio_drawdown_tail": report.portfolio_drawdown.tail(5).reset_index().to_dict(orient="records"),
    }
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
