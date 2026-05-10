from __future__ import annotations

import json

from backtesting.engine import BacktestConfig, BacktestEngine


def main() -> None:
    engine = BacktestEngine()
    cfg = BacktestConfig(
        symbols=["EURUSD=X", "BTC-USD", "SPY"],
        timeframes=["1h", "1d"],
        start="2023-01-01",
        end="2025-01-01",
        strategy_params={
            "rsi_buy": 35,
            "rsi_sell": 65,
            "confidence_threshold": 60,
        },
        initial_cash=100_000.0,
        commission_bps=2.0,
        slippage_bps=1.0,
        spread_bps=1.5,
        risk_per_trade=0.01,
    )

    result = engine.run_backtest(cfg)
    walk_forward = engine.walk_forward_optimize(
        cfg,
        parameter_grid={
            "rsi_buy": [30, 35, 40],
            "rsi_sell": [60, 65, 70],
            "confidence_threshold": [55, 60, 65],
        },
    )

    payload = {
        "summary": json.loads(engine.to_summary_json(result)),
        "walk_forward": walk_forward,
        "equity_tail": result.equity_curve.tail(5).reset_index().to_dict(orient="records"),
        "underwater_tail": result.underwater_curve.tail(5).reset_index().to_dict(orient="records"),
    }
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
