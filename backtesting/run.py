from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from backtesting.engine import BacktestConfig, BacktestEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aletheia Trader vectorized backtesting runner")
    parser.add_argument("--symbol", default="EURUSD", help="Single symbol or comma-separated list")
    parser.add_argument("--strategy", default="macd_rsi", help="Strategy name")
    parser.add_argument("--timeframe", default="1h", help="YFinance interval")
    parser.add_argument("--start", default="2022-01-01", help="Backtest start date")
    parser.add_argument("--end", default="2025-01-01", help="Backtest end date")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--commission-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument("--spread-bps", type=float, default=1.5)
    parser.add_argument("--risk-per-trade", type=float, default=0.01)
    parser.add_argument("--run-optimization", action="store_true")
    parser.add_argument("--run-walkforward", action="store_true")
    parser.add_argument("--run-monte-carlo", action="store_true")
    parser.add_argument("--output-dir", default="backtesting/output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]

    cfg = BacktestConfig(
        symbols=symbols,
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
        strategy=args.strategy,
        strategy_params={"risk_per_trade": args.risk_per_trade},
        initial_cash=args.initial_cash,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        spread_bps=args.spread_bps,
        risk_per_trade=args.risk_per_trade,
    )

    engine = BacktestEngine()
    report = engine.run(cfg)

    optimization = None
    walkforward = None
    if args.run_optimization:
        optimization = engine.optimize(
            cfg,
            symbol=symbols[0],
            param_grid={
                "rsi_buy": [30, 35, 40],
                "rsi_sell": [60, 65, 70],
                "trend_threshold": [0.002, 0.003, 0.004],
            },
        )
    if args.run_walkforward:
        walkforward = engine.walk_forward(
            cfg,
            symbol=symbols[0],
            param_grid={
                "rsi_buy": [30, 35],
                "rsi_sell": [65, 70],
            },
        )

    if args.run_monte_carlo:
        # Monte Carlo is already included per symbol in report results.
        pass

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "config": cfg.__dict__,
        "portfolio_metrics": report.portfolio_metrics,
        "symbols": {
            sym: {
                "metrics": res.metrics,
                "monte_carlo": res.monte_carlo,
                "trade_count": int(len(res.trades)),
            }
            for sym, res in report.results.items()
        },
    }
    if optimization is not None:
        summary["optimization_top5"] = optimization.head(5).to_dict(orient="records")
    if walkforward is not None:
        summary["walk_forward"] = walkforward

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    report.portfolio_equity.to_frame("equity").to_csv(out_dir / "portfolio_equity.csv")
    report.portfolio_drawdown.to_frame("drawdown").to_csv(out_dir / "portfolio_drawdown.csv")

    for sym, res in report.results.items():
        safe = sym.replace("/", "_")
        res.equity_curve.to_frame("equity").to_csv(out_dir / f"{safe}_equity.csv")
        res.drawdown.to_frame("drawdown").to_csv(out_dir / f"{safe}_drawdown.csv")
        res.monthly_returns_heatmap.to_csv(out_dir / f"{safe}_monthly_heatmap.csv")
        res.trades.to_csv(out_dir / f"{safe}_trades.csv", index=False)

        eq_fig = engine.build_equity_curve_figure(res)
        dd_fig = engine.build_drawdown_figure(res)
        eq_fig.write_html(out_dir / f"{safe}_equity_curve.html")
        dd_fig.write_html(out_dir / f"{safe}_drawdown.html")

    print(json.dumps(summary, indent=2, default=str))
    print(f"Artifacts saved to: {out_dir}")


if __name__ == "__main__":
    main()
