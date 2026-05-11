from __future__ import annotations

from brokers.instrument_specs import resolve_instrument_spec
from brokers.profit_calculator import ProfitCalculator


def test_forex_pnl_known_scenario() -> None:
    spec = resolve_instrument_spec("EUR/USD", "BUY")
    pnl = ProfitCalculator.forex_pnl(
        signal="BUY",
        instrument="EUR/USD",
        entry=1.1000,
        exit=1.1020,
        quantity=1.0,
        spec=spec,
    )
    assert round(pnl, 2) == 200.0


def test_equity_pnl_known_scenario() -> None:
    spec = resolve_instrument_spec("SPY", "BUY")
    pnl = ProfitCalculator.equity_pnl(
        signal="BUY",
        entry=100.0,
        exit=105.0,
        quantity=10.0,
        spec=spec,
    )
    assert round(pnl, 2) == 50.0


def test_options_pnl_known_scenario_with_greeks() -> None:
    spec = resolve_instrument_spec("SPY", "CALL_BUY")
    pnl = ProfitCalculator.options_pnl(
        signal="CALL_BUY",
        entry=2.0,
        exit=3.0,
        quantity=2.0,
        spec=spec,
        greeks={"delta": 0.5, "theta": -0.02},
        days_held=5.0,
        underlying_entry=100.0,
        underlying_exit=101.0,
    )
    assert round(pnl, 2) == 280.0
