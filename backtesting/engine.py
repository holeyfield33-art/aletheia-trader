from __future__ import annotations

import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from audit.aletheia_wrapper import AletheiaWrapper
from backtesting.data import DataManager
from backtesting.strategies import STRATEGY_REGISTRY, BaseStrategy
from risk.manager import PortfolioRiskState, RiskManager


@dataclass
class BacktestConfig:
    symbols: list[str]
    timeframe: str
    start: str
    end: str
    strategy: str = "macd_rsi"
    strategy_params: dict[str, float | int] = field(default_factory=dict)
    initial_cash: float = 100_000.0
    commission_bps: float = 2.0
    slippage_bps: float = 1.0
    spread_bps: float = 1.5
    risk_per_trade: float = 0.01
    allow_short: bool = True
    use_cache: bool = True


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    metrics: dict[str, float]
    equity_curve: pd.Series
    drawdown: pd.Series
    monthly_returns_heatmap: pd.DataFrame
    trades: pd.DataFrame
    indicators: pd.DataFrame
    parameters: dict[str, float | int]
    monte_carlo: dict[str, float]


@dataclass
class BacktestRunReport:
    config: BacktestConfig
    results: dict[str, BacktestResult]
    portfolio_equity: pd.Series
    portfolio_drawdown: pd.Series
    portfolio_metrics: dict[str, float]
    risk_snapshot: dict[str, object]


class BacktestEngine:
    def __init__(
        self,
        cache_dir: str | Path = ".cache/backtesting",
        gateway_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.downloader = DataManager(
            cache_dir=cache_dir,
            gateway_url=gateway_url,
            api_key=api_key,
        )
        self.auditor = AletheiaWrapper(gateway_url=gateway_url, api_key=api_key)
        self.risk = RiskManager()

    def run(self, config: BacktestConfig) -> BacktestRunReport:
        results: dict[str, BacktestResult] = {}
        equity_curves: list[pd.Series] = []
        returns_by_asset: dict[str, pd.Series] = {}

        for symbol in config.symbols:
            data = self.downloader.download(
                symbol=symbol,
                timeframe=config.timeframe,
                start=config.start,
                end=config.end,
                use_cache=config.use_cache,
            )
            if data.empty:
                continue

            result = self._run_single(symbol=symbol, data=data, config=config)
            results[symbol] = result
            equity_curves.append(result.equity_curve.rename(symbol))
            returns_by_asset[symbol] = result.equity_curve.pct_change().fillna(0.0)

        if not equity_curves:
            idx = pd.DatetimeIndex([pd.Timestamp.utcnow()])
            portfolio_equity = pd.Series([config.initial_cash], index=idx, name="equity")
            portfolio_drawdown = pd.Series([0.0], index=idx, name="drawdown")
            portfolio_metrics = self._compute_metrics(
                equity=portfolio_equity,
                returns=portfolio_equity.pct_change().fillna(0.0),
                trade_returns=np.array([], dtype=float),
                timeframe=config.timeframe,
            )
            empty_state = PortfolioRiskState(
                equity_curve=portfolio_equity,
                starting_capital=float(config.initial_cash),
                current_capital=float(config.initial_cash),
                open_notional=0.0,
                day_start_capital=float(config.initial_cash),
            )
            risk_snapshot = self.risk.portfolio_risk_snapshot(empty_state, {})
            return BacktestRunReport(
                config=config,
                results=results,
                portfolio_equity=portfolio_equity,
                portfolio_drawdown=portfolio_drawdown,
                portfolio_metrics=portfolio_metrics,
                risk_snapshot=risk_snapshot,
            )

        joined = pd.concat(equity_curves, axis=1).ffill().dropna(how="all")
        portfolio_equity = joined.mean(axis=1).rename("equity")
        portfolio_returns = portfolio_equity.pct_change().fillna(0.0)
        portfolio_drawdown = (portfolio_equity / portfolio_equity.cummax() - 1.0).rename("drawdown")

        all_trade_returns = []
        for result in results.values():
            if not result.trades.empty:
                all_trade_returns.extend(result.trades["trade_return"].astype(float).tolist())

        portfolio_metrics = self._compute_metrics(
            equity=portfolio_equity,
            returns=portfolio_returns,
            trade_returns=np.array(all_trade_returns, dtype=float),
            timeframe=config.timeframe,
        )

        day_start_capital = (
            float(portfolio_equity.iloc[-2])
            if len(portfolio_equity) > 1
            else float(config.initial_cash)
        )
        risk_state = PortfolioRiskState(
            equity_curve=portfolio_equity,
            starting_capital=float(config.initial_cash),
            current_capital=float(portfolio_equity.iloc[-1]),
            open_notional=0.0,
            day_start_capital=day_start_capital,
        )
        risk_snapshot = self.risk.portfolio_risk_snapshot(risk_state, returns_by_asset)

        self.auditor.audit(
            action="backtest_summary",
            payload={
                "symbols": list(results.keys()),
                "timeframe": config.timeframe,
                "start": config.start,
                "end": config.end,
                "strategy": config.strategy,
                "metrics": portfolio_metrics,
                "risk_snapshot": risk_snapshot,
            },
        )

        return BacktestRunReport(
            config=config,
            results=results,
            portfolio_equity=portfolio_equity,
            portfolio_drawdown=portfolio_drawdown,
            portfolio_metrics=portfolio_metrics,
            risk_snapshot=risk_snapshot,
        )

    def run_backtest(self, config: BacktestConfig) -> BacktestResult:
        if not config.symbols:
            raise ValueError("BacktestConfig.symbols must contain at least one symbol")

        symbol = config.symbols[0]
        data = self.downloader.download(
            symbol=symbol,
            timeframe=config.timeframe,
            start=config.start,
            end=config.end,
            use_cache=config.use_cache,
        )
        if data.empty:
            idx = pd.DatetimeIndex([pd.Timestamp.utcnow()])
            empty = pd.Series([config.initial_cash], index=idx)
            return BacktestResult(
                symbol=symbol,
                timeframe=config.timeframe,
                metrics={
                    "total_return": 0.0,
                    "sharpe": 0.0,
                    "sortino": 0.0,
                    "calmar": 0.0,
                    "max_drawdown": 0.0,
                    "max_drawdown_duration_bars": 0.0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                    "expectancy": 0.0,
                },
                equity_curve=empty,
                drawdown=pd.Series([0.0], index=idx),
                monthly_returns_heatmap=pd.DataFrame(),
                trades=pd.DataFrame(),
                indicators=pd.DataFrame(),
                parameters=config.strategy_params,
                monte_carlo={
                    "mc_p5_return": 0.0,
                    "mc_p50_return": 0.0,
                    "mc_p95_return": 0.0,
                    "mc_prob_loss": 0.0,
                },
            )
        return self._run_single(symbol=symbol, data=data, config=config)

    def optimize(
        self,
        config: BacktestConfig,
        symbol: str,
        param_grid: dict[str, list[int | float]],
        objective: str = "sharpe",
    ) -> pd.DataFrame:
        data = self.downloader.download(
            symbol=symbol,
            timeframe=config.timeframe,
            start=config.start,
            end=config.end,
            use_cache=config.use_cache,
        )
        if data.empty:
            return pd.DataFrame()

        keys = list(param_grid.keys())
        rows: list[dict[str, Any]] = []
        for combo in itertools.product(*param_grid.values()):
            params = {**config.strategy_params, **dict(zip(keys, combo, strict=False))}
            res = self._run_from_data(
                symbol=symbol, data=data, config=config, strategy_params=params
            )
            row: dict[str, Any] = {"objective": float(res.metrics.get(objective, 0.0))}
            row.update(params)
            for metric_key in [
                "sharpe",
                "sortino",
                "calmar",
                "max_drawdown",
                "win_rate",
                "profit_factor",
            ]:
                row[metric_key] = float(res.metrics.get(metric_key, 0.0))
            rows.append(row)

        out = pd.DataFrame(rows)
        if out.empty:
            return out
        return out.sort_values(by="objective", ascending=False).reset_index(drop=True)

    def walk_forward(
        self,
        config: BacktestConfig,
        symbol: str,
        param_grid: dict[str, list[int | float]],
        train_bars: int = 252,
        test_bars: int = 126,
        step_bars: int = 126,
    ) -> dict[str, Any]:
        data = self.downloader.download(
            symbol=symbol,
            timeframe=config.timeframe,
            start=config.start,
            end=config.end,
            use_cache=config.use_cache,
        )
        if data.empty or len(data) < train_bars + test_bars:
            return {"windows": [], "summary": {"avg_oos_sharpe": 0.0, "count": 0}}

        windows: list[dict[str, Any]] = []
        i = 0
        while i + train_bars + test_bars <= len(data):
            train_df = data.iloc[i : i + train_bars]
            test_df = data.iloc[i + train_bars : i + train_bars + test_bars]

            opt = self._optimize_on_data(config, symbol, train_df, param_grid)
            if opt.empty:
                break
            best = opt.iloc[0].to_dict()
            best_params = {k: best[k] for k in param_grid if k in best}
            test_res = self._run_from_data(
                symbol=symbol,
                data=test_df,
                config=config,
                strategy_params={**config.strategy_params, **best_params},
            )

            windows.append(
                {
                    "train_start": str(train_df.index[0]),
                    "train_end": str(train_df.index[-1]),
                    "test_start": str(test_df.index[0]),
                    "test_end": str(test_df.index[-1]),
                    "best_params": best_params,
                    "test_sharpe": float(test_res.metrics.get("sharpe", 0.0)),
                    "test_total_return": float(test_res.metrics.get("total_return", 0.0)),
                }
            )

            i += step_bars

        avg_oos_sharpe = float(np.mean([w["test_sharpe"] for w in windows])) if windows else 0.0
        return {
            "windows": windows,
            "summary": {
                "avg_oos_sharpe": avg_oos_sharpe,
                "count": len(windows),
            },
        }

    def walk_forward_optimize(
        self,
        config: BacktestConfig,
        parameter_grid: dict[str, list[int | float]],
        train_bars: int = 252,
        test_bars: int = 126,
    ) -> dict[str, Any]:
        return self.walk_forward(
            config=config,
            symbol=config.symbols[0],
            param_grid=parameter_grid,
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=test_bars,
        )

    def build_equity_curve_figure(self, result: BacktestResult) -> go.Figure:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=result.equity_curve.index,
                y=result.equity_curve.values,
                mode="lines",
                name="Equity",
            )
        )
        fig.update_layout(
            title=f"Equity Curve: {result.symbol} ({result.timeframe})",
            xaxis_title="Time",
            yaxis_title="Equity",
            template="plotly_dark",
            height=450,
        )
        return fig

    def build_drawdown_figure(self, result: BacktestResult) -> go.Figure:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=result.drawdown.index,
                y=result.drawdown.values,
                mode="lines",
                fill="tozeroy",
                name="Drawdown",
            )
        )
        fig.update_layout(
            title=f"Drawdown: {result.symbol} ({result.timeframe})",
            xaxis_title="Time",
            yaxis_title="Drawdown",
            template="plotly_dark",
            height=350,
        )
        return fig

    @staticmethod
    def to_summary_json(report: BacktestRunReport) -> str:
        payload = {
            "config": asdict(report.config),
            "portfolio_metrics": report.portfolio_metrics,
            "risk_snapshot": report.risk_snapshot,
            "symbols": {
                symbol: {
                    "metrics": result.metrics,
                    "trade_count": int(len(result.trades)),
                    "monte_carlo": result.monte_carlo,
                }
                for symbol, result in report.results.items()
            },
        }
        return json.dumps(payload, indent=2, default=str)

    def _run_single(
        self, symbol: str, data: pd.DataFrame, config: BacktestConfig
    ) -> BacktestResult:
        return self._run_from_data(
            symbol=symbol,
            data=data,
            config=config,
            strategy_params=config.strategy_params,
        )

    def _run_from_data(
        self,
        symbol: str,
        data: pd.DataFrame,
        config: BacktestConfig,
        strategy_params: dict[str, float | int],
    ) -> BacktestResult:
        strategy_cls = STRATEGY_REGISTRY.get(config.strategy)
        if strategy_cls is None:
            raise ValueError(
                f"Unknown strategy '{config.strategy}'. Available: {sorted(STRATEGY_REGISTRY)}"
            )

        strategy: BaseStrategy = strategy_cls()
        merged_params = {**strategy_params}
        merged_params.setdefault("risk_per_trade", config.risk_per_trade)

        pack = strategy.generate(data, merged_params)
        position = self._build_position_series(
            entries=pack.entries,
            exits=pack.exits,
            short_entries=pack.short_entries,
            short_exits=pack.short_exits,
            allow_short=config.allow_short,
        )

        close = data["close"].astype(float)
        asset_returns = close.pct_change().fillna(0.0)
        prior_position = position.shift(1).fillna(0.0)

        size_pct = pack.size_pct.reindex(close.index).fillna(0.0).clip(lower=0.0, upper=1.0)
        gross_returns = prior_position * asset_returns * size_pct

        total_cost_rate = (
            float(config.commission_bps) + float(config.spread_bps) + float(config.slippage_bps)
        ) / 10_000.0
        turnover = position.diff().abs().fillna(position.abs()) * size_pct
        costs = turnover * total_cost_rate
        strategy_returns = gross_returns - costs

        equity = (1.0 + strategy_returns).cumprod() * float(config.initial_cash)
        drawdown = (equity / equity.cummax() - 1.0).fillna(0.0)

        trades = self._extract_trade_log(
            close=close,
            position=position,
            size_pct=size_pct,
            returns=strategy_returns,
            initial_cash=float(config.initial_cash),
        )
        trade_returns = (
            trades["trade_return"].astype(float).to_numpy()
            if not trades.empty
            else np.array([], dtype=float)
        )

        metrics = self._compute_metrics(
            equity=equity,
            returns=strategy_returns,
            trade_returns=trade_returns,
            timeframe=config.timeframe,
        )
        monthly_heatmap = self._monthly_returns_heatmap(strategy_returns)
        monte = self.monte_carlo_simulation(trade_returns)

        indicator_frame = pd.DataFrame({k: v for k, v in pack.indicators.items()})

        self.auditor.audit(
            action="backtest_symbol",
            payload={
                "symbol": symbol,
                "strategy": config.strategy,
                "timeframe": config.timeframe,
                "metrics": metrics,
                "trade_count": int(len(trades)),
            },
        )

        return BacktestResult(
            symbol=symbol,
            timeframe=config.timeframe,
            metrics=metrics,
            equity_curve=equity,
            drawdown=drawdown,
            monthly_returns_heatmap=monthly_heatmap,
            trades=trades,
            indicators=indicator_frame,
            parameters=merged_params,
            monte_carlo=monte,
        )

    def _optimize_on_data(
        self,
        config: BacktestConfig,
        symbol: str,
        data: pd.DataFrame,
        param_grid: dict[str, list[int | float]],
    ) -> pd.DataFrame:
        keys = list(param_grid.keys())
        rows: list[dict[str, Any]] = []

        for combo in itertools.product(*param_grid.values()):
            params = {**config.strategy_params, **dict(zip(keys, combo, strict=False))}
            res = self._run_from_data(
                symbol=symbol, data=data, config=config, strategy_params=params
            )
            row: dict[str, Any] = {"objective": float(res.metrics.get("sharpe", 0.0))}
            row.update(params)
            row["total_return"] = float(res.metrics.get("total_return", 0.0))
            row["sharpe"] = float(res.metrics.get("sharpe", 0.0))
            row["max_drawdown"] = float(res.metrics.get("max_drawdown", 0.0))
            rows.append(row)

        out = pd.DataFrame(rows)
        if out.empty:
            return out
        return out.sort_values(by="objective", ascending=False).reset_index(drop=True)

    @staticmethod
    def monte_carlo_simulation(
        trade_returns: np.ndarray,
        n_sims: int = 1000,
    ) -> dict[str, float]:
        if trade_returns.size == 0:
            return {
                "mc_p5_return": 0.0,
                "mc_p50_return": 0.0,
                "mc_p95_return": 0.0,
                "mc_prob_loss": 0.0,
            }

        finals = np.zeros(n_sims, dtype=float)
        for i in range(n_sims):
            shuffled = np.random.permutation(trade_returns)
            finals[i] = float(np.prod(1.0 + shuffled) - 1.0)

        return {
            "mc_p5_return": float(np.percentile(finals, 5)),
            "mc_p50_return": float(np.percentile(finals, 50)),
            "mc_p95_return": float(np.percentile(finals, 95)),
            "mc_prob_loss": float((finals < 0).mean()),
        }

    @staticmethod
    def _build_position_series(
        entries: pd.Series,
        exits: pd.Series,
        short_entries: pd.Series,
        short_exits: pd.Series,
        allow_short: bool,
    ) -> pd.Series:
        idx = entries.index
        pos = np.zeros(len(idx), dtype=float)
        current = 0.0

        e = entries.fillna(False).to_numpy(dtype=bool)
        x = exits.fillna(False).to_numpy(dtype=bool)
        se = short_entries.fillna(False).to_numpy(dtype=bool)
        sx = short_exits.fillna(False).to_numpy(dtype=bool)

        for i in range(len(idx)):
            if current == 0.0:
                if e[i]:
                    current = 1.0
                elif allow_short and se[i]:
                    current = -1.0
            elif current > 0:
                if x[i]:
                    current = 0.0
                elif allow_short and se[i]:
                    current = -1.0
            else:
                if sx[i]:
                    current = 0.0
                elif e[i]:
                    current = 1.0
            pos[i] = current

        return pd.Series(pos, index=idx, name="position")

    @staticmethod
    def _extract_trade_log(
        close: pd.Series,
        position: pd.Series,
        size_pct: pd.Series,
        returns: pd.Series,
        initial_cash: float,
    ) -> pd.DataFrame:
        records: list[dict[str, Any]] = []
        current_side = 0.0
        entry_price = 0.0
        entry_time: pd.Timestamp | None = None
        entry_size = 0.0

        for ts, pos in position.items():
            prev_side = current_side
            if prev_side == 0.0 and pos != 0.0:
                current_side = float(pos)
                entry_price = float(close.loc[ts])
                entry_time = pd.Timestamp(ts)
                entry_size = float(size_pct.loc[ts])
                continue

            if prev_side != 0.0 and pos != prev_side:
                exit_price = float(close.loc[ts])
                if entry_time is None or entry_price <= 0:
                    current_side = float(pos)
                    entry_price = exit_price
                    entry_time = pd.Timestamp(ts)
                    entry_size = float(size_pct.loc[ts])
                    continue

                direction = 1.0 if prev_side > 0 else -1.0
                trade_return = direction * ((exit_price / entry_price) - 1.0) * max(entry_size, 0.0)
                pnl = initial_cash * trade_return
                held_returns = returns.loc[(returns.index >= entry_time) & (returns.index <= ts)]
                bars = int(len(held_returns))

                records.append(
                    {
                        "entry_time": str(entry_time),
                        "exit_time": str(pd.Timestamp(ts)),
                        "side": "LONG" if prev_side > 0 else "SHORT",
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "size_pct": entry_size,
                        "trade_return": float(trade_return),
                        "pnl": float(pnl),
                        "bars": bars,
                    }
                )

                current_side = float(pos)
                if current_side != 0.0:
                    entry_price = exit_price
                    entry_time = pd.Timestamp(ts)
                    entry_size = float(size_pct.loc[ts])
                else:
                    entry_price = 0.0
                    entry_time = None
                    entry_size = 0.0

        return pd.DataFrame(records)

    @staticmethod
    def _compute_metrics(
        equity: pd.Series,
        returns: pd.Series,
        trade_returns: np.ndarray,
        timeframe: str,
    ) -> dict[str, float]:
        periods = BacktestEngine._periods_per_year(timeframe)
        avg = float(returns.mean())
        vol = float(returns.std())
        downside = returns[returns < 0]
        downside_vol = float(downside.std()) if len(downside) else 0.0

        sharpe = avg / vol * math.sqrt(periods) if vol > 0 else 0.0
        sortino = avg / downside_vol * math.sqrt(periods) if downside_vol > 0 else 0.0

        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) else 0.0
        max_dd = float((equity / equity.cummax() - 1.0).min()) if len(equity) else 0.0
        annual_return = (
            (float(equity.iloc[-1] / equity.iloc[0])) ** (periods / max(len(equity), 1)) - 1.0
            if len(equity) > 1 and equity.iloc[0] > 0
            else 0.0
        )
        calmar = annual_return / abs(max_dd) if max_dd < 0 else 0.0
        max_dd_duration = float(
            BacktestEngine._max_drawdown_duration(equity / equity.cummax() - 1.0)
        )

        if trade_returns.size > 0:
            wins = trade_returns[trade_returns > 0]
            losses = trade_returns[trade_returns < 0]
            win_rate = float((trade_returns > 0).mean())
            gross_profit = float(wins.sum())
            gross_loss = abs(float(losses.sum()))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
            expectancy = float(trade_returns.mean())
        else:
            win_rate = 0.0
            profit_factor = 0.0
            expectancy = 0.0

        return {
            "total_return": total_return,
            "sharpe": float(sharpe),
            "sortino": float(sortino),
            "calmar": float(calmar),
            "max_drawdown": float(max_dd),
            "max_drawdown_duration_bars": max_dd_duration,
            "win_rate": win_rate,
            "profit_factor": float(profit_factor),
            "expectancy": expectancy,
        }

    @staticmethod
    def _monthly_returns_heatmap(returns: pd.Series) -> pd.DataFrame:
        if returns.empty:
            return pd.DataFrame()
        monthly = (1.0 + returns).resample("ME").prod() - 1.0
        monthly_df = monthly.to_frame("ret")
        monthly_df["year"] = monthly_df.index.year
        monthly_df["month"] = monthly_df.index.strftime("%b")
        month_order = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        heatmap = monthly_df.pivot(index="year", columns="month", values="ret")
        return heatmap.reindex(columns=month_order)

    @staticmethod
    def _max_drawdown_duration(drawdown: pd.Series) -> int:
        in_dd = drawdown < 0
        max_len = 0
        cur = 0
        for flag in in_dd.tolist():
            if flag:
                cur += 1
                max_len = max(max_len, cur)
            else:
                cur = 0
        return max_len

    @staticmethod
    def _periods_per_year(timeframe: str) -> int:
        tf = timeframe.lower()
        if tf.endswith("m"):
            minutes = int(tf[:-1]) if tf[:-1].isdigit() else 60
            return int((24 * 60 / minutes) * 252)
        if tf.endswith("h"):
            hours = int(tf[:-1]) if tf[:-1].isdigit() else 1
            return int((24 / hours) * 252)
        if tf.endswith("d"):
            return 252
        if tf.endswith("wk") or tf.endswith("w"):
            return 52
        return 252
