from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd
import yfinance as yf

from audit.aletheia_wrapper import AletheiaWrapper


@dataclass
class BacktestConfig:
    symbols: list[str]
    timeframes: list[str]
    start: str
    end: str
    strategy_params: dict[str, float | int] = field(default_factory=dict)
    initial_cash: float = 100_000.0
    commission_bps: float = 2.0
    slippage_bps: float = 1.0
    spread_bps: float = 1.5
    risk_per_trade: float = 0.01


@dataclass
class BacktestResult:
    config: BacktestConfig
    metrics: dict[str, float]
    equity_curve: pd.DataFrame
    underwater_curve: pd.DataFrame
    trade_log: pd.DataFrame
    by_instrument: dict[str, dict[str, Any]]
    monte_carlo: dict[str, float] | None = None
    robustness: dict[str, Any] | None = None


class AletheiaStrategy(bt.Strategy):
    params = dict(
        rsi_period=14,
        rsi_buy=35,
        rsi_sell=65,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        bb_window=20,
        bb_std=2.0,
        atr_period=14,
        atr_stop_mult=2.0,
        confidence_threshold=60,
        risk_per_trade=0.01,
        initial_cash=100000.0,
        correlation_penalty=0.0,
        mtf_confirmation=True,
        auditor=None,
    )

    def __init__(self) -> None:
        self.rsi = bt.ind.RSI_Safe(self.data.close, period=int(self.p.rsi_period), safediv=True)
        self.macd = bt.ind.MACD(
            self.data.close,
            period_me1=int(self.p.macd_fast),
            period_me2=int(self.p.macd_slow),
            period_signal=int(self.p.macd_signal),
        )
        self.bb = bt.ind.BollingerBands(
            self.data.close,
            period=int(self.p.bb_window),
            devfactor=float(self.p.bb_std),
        )
        self.atr = bt.ind.ATR(self.data, period=int(self.p.atr_period))
        self.adx = bt.ind.ADX(self.data, period=14)
        self.trade_log: list[dict[str, Any]] = []
        self.latest_confidence = 0.0

    def _regime(self) -> str:
        adx_value = float(self.adx[0]) if math.isfinite(float(self.adx[0])) else 0.0
        return "trending" if adx_value >= 25 else "ranging"

    def _mtf_confirmed(self) -> bool:
        if not bool(self.p.mtf_confirmation):
            return True
        if len(self) < 30:
            return False
        close = np.array([float(self.data.close[-i]) for i in range(1, 21)][::-1], dtype=float)
        slow = pd.Series(close).ewm(span=20, adjust=False).mean().iloc[-1]
        fast = pd.Series(close).ewm(span=8, adjust=False).mean().iloc[-1]
        macd_hist = float(self.macd.macd[0] - self.macd.signal[0])
        return (macd_hist >= 0 and fast >= slow) or (macd_hist < 0 and fast < slow)

    def _confidence(self) -> float:
        rsi = float(self.rsi[0])
        macd_hist = float(self.macd.macd[0] - self.macd.signal[0])
        prev_hist = float(self.macd.macd[-1] - self.macd.signal[-1]) if len(self) > 1 else 0.0
        price = float(self.data.close[0])
        bb_upper = float(self.bb.top[0])
        bb_lower = float(self.bb.bot[0])
        bb_mid = float(self.bb.mid[0])

        if min(bb_upper, bb_mid, bb_lower) <= 0:
            return 0.0

        bandwidth = (bb_upper - bb_lower) / bb_mid if bb_mid else 0.0
        rsi_extreme = (rsi < self.p.rsi_buy) or (rsi > self.p.rsi_sell)
        macd_cross = (prev_hist <= 0 < macd_hist) or (prev_hist >= 0 > macd_hist)
        bb_touch = (price <= bb_lower and rsi < 45) or (price >= bb_upper and rsi > 55)

        score = 45.0
        if rsi_extreme:
            score += 20.0
        if macd_cross:
            score += 15.0
        if bb_touch:
            score += 15.0
        if self._mtf_confirmed():
            score += 10.0
        if self._regime() == "trending":
            score += 10.0
        if bandwidth < 0.02:
            score -= 20.0
        score -= min(max(float(self.p.correlation_penalty), 0.0), 1.0) * 20.0
        return float(max(0.0, min(100.0, score)))

    def _size_from_risk(self) -> float:
        atr = float(self.atr[0]) if math.isfinite(float(self.atr[0])) else 0.0
        if atr <= 0:
            return 0.0
        per_unit_risk = atr * float(self.p.atr_stop_mult)
        risk_budget = float(self.p.initial_cash) * float(self.p.risk_per_trade)
        return max(risk_budget / per_unit_risk, 0.0)

    def next(self) -> None:
        if len(self) < max(int(self.p.bb_window), int(self.p.rsi_period)) + 5:
            return

        conf = self._confidence()
        self.latest_confidence = conf
        if conf < float(self.p.confidence_threshold):
            return

        rsi = float(self.rsi[0])
        macd_hist = float(self.macd.macd[0] - self.macd.signal[0])
        prev_hist = float(self.macd.macd[-1] - self.macd.signal[-1]) if len(self) > 1 else 0.0
        size = self._size_from_risk()
        if size <= 0:
            return

        long_setup = rsi < self.p.rsi_buy and macd_hist > 0 and prev_hist <= 0
        short_setup = rsi > self.p.rsi_sell and macd_hist < 0 and prev_hist >= 0

        if not self.position:
            if long_setup:
                self.buy(size=size)
            elif short_setup:
                self.sell(size=size)
            return

        # Exit if momentum flips or setup invalidates.
        if self.position.size > 0 and (macd_hist < 0 or rsi > 60):
            self.close()
        elif self.position.size < 0 and (macd_hist > 0 or rsi < 40):
            self.close()

    def notify_trade(self, trade: bt.Trade) -> None:
        if not trade.isclosed:
            return

        dt = self.data.datetime.datetime(0)
        entry_price = float(trade.price)
        pnl = float(trade.pnlcomm)
        qty = float(abs(trade.size))
        if qty == 0 and getattr(trade, "history", None):
            qty = float(abs(trade.history[-1].status.size))
        side = "LONG" if bool(getattr(trade, "long", True)) else "SHORT"

        entry = {
            "datetime": dt.isoformat(),
            "side": side,
            "qty": qty,
            "entry_price": entry_price,
            "pnl": pnl,
            "confidence": float(self.latest_confidence),
            "regime": self._regime(),
        }

        auditor: AletheiaWrapper | None = self.p.auditor
        if auditor is not None:
            receipt = auditor.audit(action="backtest_trade", payload=entry)
            entry["receipt"] = receipt.get("receipt", "mock-receipt")

        self.trade_log.append(entry)


class BacktestEngine:
    def __init__(
        self,
        cache_dir: str | Path = ".cache/backtesting",
        gateway_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.auditor = AletheiaWrapper(gateway_url=gateway_url, api_key=api_key)

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        cache_key = hashlib.sha1(f"{symbol}|{timeframe}|{start}|{end}".encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"{symbol.replace('/', '_')}_{timeframe}_{cache_key}.csv"

        if use_cache and cache_file.exists():
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index, utc=True)
            return cached

        data = yf.download(
            symbol,
            interval=timeframe,
            start=start,
            end=end,
            auto_adjust=False,
            progress=False,
        )
        if data.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        data = data.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in data.columns:
                data[col] = 0.0
        out = data[["open", "high", "low", "close", "volume"]].dropna().copy()
        out.index = pd.to_datetime(out.index, utc=True)
        if use_cache and not out.empty:
            out.to_csv(cache_file)
        return out

    def _run_single(
        self,
        data: pd.DataFrame,
        config: BacktestConfig,
        strategy_params: dict[str, float | int],
        correlation_penalty: float = 0.0,
    ) -> tuple[pd.Series, pd.DataFrame, dict[str, float]]:
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(float(config.initial_cash))

        total_commission_bps = float(config.commission_bps) + float(config.spread_bps)
        commission = total_commission_bps / 10_000.0
        slippage = float(config.slippage_bps) / 10_000.0
        cerebro.broker.setcommission(commission=commission)
        cerebro.broker.set_slippage_perc(perc=slippage)

        bt_data = bt.feeds.PandasData(
            dataname=data.rename(columns=str.capitalize)
            .rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        )
        cerebro.adddata(bt_data)

        params = {
            "risk_per_trade": float(config.risk_per_trade),
            "initial_cash": float(config.initial_cash),
            "correlation_penalty": float(correlation_penalty),
            "auditor": self.auditor,
        }
        params.update(strategy_params)

        cerebro.addstrategy(AletheiaStrategy, **params)
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="returns")
        strat = cerebro.run()[0]

        returns_dict = strat.analyzers.returns.get_analysis()
        if not returns_dict:
            returns = pd.Series([0.0], index=[data.index[-1]])
        else:
            returns = pd.Series(returns_dict)
            returns.index = pd.to_datetime(returns.index, utc=True)
            returns = returns.sort_index()

        equity = float(config.initial_cash) * (1.0 + returns).cumprod()
        equity.name = "equity"
        trades = pd.DataFrame(strat.trade_log)
        if trades.empty:
            trades = pd.DataFrame(columns=["datetime", "side", "qty", "entry_price", "pnl", "confidence", "regime", "receipt"])

        trade_returns = np.array([], dtype=float)
        if not trades.empty:
            trade_returns = trades["pnl"].astype(float).to_numpy() / float(config.initial_cash)

        return equity, trades, self._compute_metrics(equity, trade_returns)

    def run_backtest(self, config: BacktestConfig) -> BacktestResult:
        all_equities: list[pd.Series] = []
        all_trades: list[pd.DataFrame] = []
        by_instrument: dict[str, dict[str, Any]] = {}
        returns_by_leg: list[pd.Series] = []

        for symbol, timeframe in itertools.product(config.symbols, config.timeframes):
            data = self.fetch_ohlcv(symbol, timeframe, config.start, config.end)
            if data.empty:
                by_instrument[f"{symbol}:{timeframe}"] = {"status": "no_data"}
                continue

            corr_penalty = self._portfolio_correlation_penalty(data, returns_by_leg)
            equity, trades, metrics = self._run_single(
                data=data,
                config=config,
                strategy_params=config.strategy_params,
                correlation_penalty=corr_penalty,
            )

            leg_key = f"{symbol}:{timeframe}"
            leg_returns = equity.pct_change().fillna(0.0)
            returns_by_leg.append(leg_returns)
            all_equities.append(equity.rename(leg_key))
            all_trades.append(trades.assign(symbol=symbol, timeframe=timeframe))
            by_instrument[leg_key] = {
                "rows": int(len(data)),
                "metrics": metrics,
                "corr_penalty": float(corr_penalty),
            }

        if not all_equities:
            empty_curve = pd.DataFrame({"equity": [config.initial_cash]})
            empty_underwater = pd.DataFrame({"underwater": [0.0]})
            return BacktestResult(
                config=config,
                metrics={k: 0.0 for k in [
                    "total_return", "sharpe", "sortino", "max_drawdown", "calmar", "win_rate", "profit_factor", "expectancy"
                ]},
                equity_curve=empty_curve,
                underwater_curve=empty_underwater,
                trade_log=pd.DataFrame(),
                by_instrument=by_instrument,
            )

        joined = pd.concat(all_equities, axis=1).sort_index().ffill().dropna(how="all")
        portfolio_equity = joined.mean(axis=1).rename("equity").to_frame()
        underwater = (portfolio_equity["equity"] / portfolio_equity["equity"].cummax() - 1.0).rename("underwater").to_frame()

        trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
        trade_returns = (
            trades_df["pnl"].astype(float).to_numpy() / float(config.initial_cash)
            if not trades_df.empty
            else np.array([], dtype=float)
        )
        metrics = self._compute_metrics(portfolio_equity["equity"], trade_returns)

        monte = self.monte_carlo_simulation(trade_returns)
        robustness = self.parameter_perturbation_test(config)

        return BacktestResult(
            config=config,
            metrics=metrics,
            equity_curve=portfolio_equity,
            underwater_curve=underwater,
            trade_log=trades_df,
            by_instrument=by_instrument,
            monte_carlo=monte,
            robustness=robustness,
        )

    def walk_forward_optimize(
        self,
        config: BacktestConfig,
        parameter_grid: dict[str, list[int | float]],
        train_bars: int = 250,
        test_bars: int = 100,
    ) -> dict[str, Any]:
        if not config.symbols or not config.timeframes:
            return {"windows": [], "summary": {"avg_oos_sharpe": 0.0}}

        symbol = config.symbols[0]
        timeframe = config.timeframes[0]
        data = self.fetch_ohlcv(symbol, timeframe, config.start, config.end)
        if data.empty or len(data) < train_bars + test_bars:
            return {"windows": [], "summary": {"avg_oos_sharpe": 0.0}}

        keys = list(parameter_grid.keys())
        combos = list(itertools.product(*parameter_grid.values()))
        windows: list[dict[str, Any]] = []

        i = 0
        while i + train_bars + test_bars <= len(data):
            train_df = data.iloc[i : i + train_bars]
            test_df = data.iloc[i + train_bars : i + train_bars + test_bars]

            best_score = -1e9
            best_params: dict[str, int | float] = {}
            for combo in combos:
                candidate = dict(zip(keys, combo))
                _, _, train_metrics = self._run_single(train_df, config, {**config.strategy_params, **candidate})
                score = float(train_metrics.get("sharpe", -1e9))
                if score > best_score:
                    best_score = score
                    best_params = candidate

            _, _, test_metrics = self._run_single(test_df, config, {**config.strategy_params, **best_params})
            windows.append(
                {
                    "train_start": str(train_df.index[0]),
                    "train_end": str(train_df.index[-1]),
                    "test_start": str(test_df.index[0]),
                    "test_end": str(test_df.index[-1]),
                    "best_params": best_params,
                    "train_sharpe": float(best_score),
                    "test_sharpe": float(test_metrics.get("sharpe", 0.0)),
                    "test_total_return": float(test_metrics.get("total_return", 0.0)),
                }
            )

            i += test_bars

        avg_oos_sharpe = float(np.mean([w["test_sharpe"] for w in windows])) if windows else 0.0
        return {"windows": windows, "summary": {"avg_oos_sharpe": avg_oos_sharpe, "count": len(windows)}}

    def monte_carlo_simulation(
        self,
        trade_returns: np.ndarray,
        n_sims: int = 1000,
        horizon: int = 200,
    ) -> dict[str, float]:
        if trade_returns.size == 0:
            return {
                "mc_p5_return": 0.0,
                "mc_p50_return": 0.0,
                "mc_p95_return": 0.0,
                "mc_prob_loss": 0.0,
            }

        sims = []
        for _ in range(n_sims):
            path = np.random.choice(trade_returns, size=horizon, replace=True)
            sims.append(float(np.prod(1.0 + path) - 1.0))

        arr = np.array(sims)
        return {
            "mc_p5_return": float(np.percentile(arr, 5)),
            "mc_p50_return": float(np.percentile(arr, 50)),
            "mc_p95_return": float(np.percentile(arr, 95)),
            "mc_prob_loss": float((arr < 0).mean()),
        }

    def parameter_perturbation_test(
        self,
        config: BacktestConfig,
        trials: int = 30,
        perturb_pct: float = 0.20,
    ) -> dict[str, Any]:
        if not config.symbols or not config.timeframes:
            return {"trials": 0, "robust_ratio": 0.0, "avg_sharpe": 0.0}

        symbol = config.symbols[0]
        timeframe = config.timeframes[0]
        data = self.fetch_ohlcv(symbol, timeframe, config.start, config.end)
        if data.empty:
            return {"trials": 0, "robust_ratio": 0.0, "avg_sharpe": 0.0}

        base = config.strategy_params or {"rsi_buy": 35, "rsi_sell": 65}
        sharpes: list[float] = []

        for _ in range(trials):
            perturbed: dict[str, int | float] = {}
            for k, v in base.items():
                if isinstance(v, (int, float)):
                    lo = float(v) * (1.0 - perturb_pct)
                    hi = float(v) * (1.0 + perturb_pct)
                    sample = float(np.random.uniform(lo, hi))
                    perturbed[k] = int(round(sample)) if isinstance(v, int) else sample
                else:
                    perturbed[k] = v

            _, _, metrics = self._run_single(data, config, perturbed)
            sharpes.append(float(metrics.get("sharpe", 0.0)))

        sharpe_arr = np.array(sharpes)
        return {
            "trials": int(trials),
            "robust_ratio": float((sharpe_arr > 0).mean()) if sharpe_arr.size else 0.0,
            "avg_sharpe": float(sharpe_arr.mean()) if sharpe_arr.size else 0.0,
            "min_sharpe": float(sharpe_arr.min()) if sharpe_arr.size else 0.0,
            "max_sharpe": float(sharpe_arr.max()) if sharpe_arr.size else 0.0,
        }

    @staticmethod
    def to_summary_json(result: BacktestResult) -> str:
        payload = {
            "config": asdict(result.config),
            "metrics": result.metrics,
            "by_instrument": result.by_instrument,
            "monte_carlo": result.monte_carlo,
            "robustness": result.robustness,
            "equity_points": int(len(result.equity_curve)),
            "trade_count": int(len(result.trade_log)),
        }
        return json.dumps(payload, indent=2)

    @staticmethod
    def _portfolio_correlation_penalty(
        candidate_data: pd.DataFrame,
        existing_returns: list[pd.Series],
    ) -> float:
        if not existing_returns:
            return 0.0
        cand_ret = candidate_data["close"].pct_change().dropna()
        if cand_ret.empty:
            return 0.0

        corrs = []
        for series in existing_returns:
            aligned = pd.concat([cand_ret, series], axis=1).dropna()
            if len(aligned) < 20:
                continue
            corrs.append(abs(float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))))

        if not corrs:
            return 0.0
        return float(min(1.0, np.mean(corrs)))

    @staticmethod
    def _compute_metrics(equity: pd.Series, trade_returns: np.ndarray) -> dict[str, float]:
        returns = equity.pct_change().dropna()
        if returns.empty:
            return {
                "total_return": 0.0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_drawdown": 0.0,
                "calmar": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
            }

        annualizer = math.sqrt(252)
        mean = float(returns.mean())
        std = float(returns.std())
        downside = returns[returns < 0]
        downside_std = float(downside.std()) if not downside.empty else 0.0

        sharpe = (mean / std * annualizer) if std > 0 else 0.0
        sortino = (mean / downside_std * annualizer) if downside_std > 0 else 0.0

        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
        drawdown = equity / equity.cummax() - 1.0
        max_dd = float(drawdown.min())
        calmar = (total_return / abs(max_dd)) if max_dd < 0 else 0.0

        if trade_returns.size:
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
            "max_drawdown": max_dd,
            "calmar": float(calmar),
            "win_rate": win_rate,
            "profit_factor": float(profit_factor),
            "expectancy": expectancy,
        }
