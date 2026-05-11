from __future__ import annotations

import pandas as pd

from backtesting.engine import BacktestConfig, BacktestEngine
from brokers.signal_and_order_ledger import SignalAndOrderLedger
from brokers.simulator import PaperSimulator


def _uptrend(rows: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series([100.0 + (i * 0.1) for i in range(rows)], index=idx)
    frame = pd.DataFrame(index=idx)
    frame["open"] = close.shift(1).fillna(close)
    frame["high"] = close * 1.001
    frame["low"] = close * 0.999
    frame["close"] = close
    frame["volume"] = 1000
    return frame


def _downtrend(rows: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series([120.0 - (i * 0.1) for i in range(rows)], index=idx)
    frame = pd.DataFrame(index=idx)
    frame["open"] = close.shift(1).fillna(close)
    frame["high"] = close * 1.001
    frame["low"] = close * 0.999
    frame["close"] = close
    frame["volume"] = 1000
    return frame


def test_paper_simulator_forex_pnl_matches_calculator(tmp_path) -> None:
    simulator = PaperSimulator(ledger_path=str(tmp_path / "sim_orders.json"))
    order = simulator.submit_order("EUR/USD", "BUY", qty=1.0, price=1.1000, approved=True)
    closed = simulator.close_order(str(order["order_id"]), exit_price=1.1010)

    assert closed is not None
    assert round(float(closed["realized_pnl"]), 2) == 100.0

    daily = simulator.get_daily_pnl()
    assert round(float(daily["daily_pnl"]), 2) == 100.0


def test_ledger_forex_pnl_matches_calculator(tmp_path) -> None:
    ledger = SignalAndOrderLedger(
        signals_path=str(tmp_path / "pending.json"),
        orders_path=str(tmp_path / "orders.json"),
    )
    signal = ledger.add_signal(
        signal_id="sig-1",
        agent_type="forex",
        instrument="EUR/USD",
        signal="BUY",
        indicators={},
        chain_data=None,
        receipt="test",
    )
    approved = ledger.approve_signal(str(signal["signal_id"]))
    assert approved is not None

    order = ledger.create_order_from_signal(approved, entry_price=1.1000, qty=1.0)
    closed = ledger.close_order(str(order["order_id"]), exit_price=1.1010)

    assert closed is not None
    assert round(float(closed["realized_pnl"]), 2) == 100.0
    assert round(float(ledger.get_total_pnl()), 2) == 100.0


def test_backtest_portfolio_equity_respects_weighted_sum() -> None:
    engine = BacktestEngine(cache_dir=".cache/backtesting-test")

    def fake_download(*, symbol: str, **kwargs):
        del kwargs
        if symbol == "EUR/USD":
            return _uptrend()
        return _downtrend()

    engine.downloader.download = fake_download  # type: ignore[method-assign]

    cfg = BacktestConfig(
        symbols=["EUR/USD", "SPY"],
        timeframe="1h",
        start="2025-01-01",
        end="2025-01-10",
        strategy="macd_rsi",
        initial_cash=100000.0,
    )
    report = engine.run(cfg)

    assert not report.portfolio_equity.empty
    assert abs(float(report.portfolio_equity.iloc[0]) - cfg.initial_cash) < 1e-6
