from __future__ import annotations

from dataclasses import asdict
from typing import Any

from brokers.instrument_specs import InstrumentSpec, infer_asset_class, resolve_instrument_spec


class ProfitCalculator:
    @staticmethod
    def forex_pnl(
        signal: str,
        instrument: str,
        entry: float,
        exit: float,
        quantity: float,
        spec: InstrumentSpec,
        commission: float = 0.0,
    ) -> float:
        side = signal.strip().upper()
        sign = 1.0 if side in {"BUY", "LONG"} else -1.0
        symbol = instrument.strip().upper().replace("=X", "")

        if "/" in symbol:
            base, quote = symbol.split("/", 1)
        elif len(symbol) == 6 and symbol.isalpha():
            base, quote = symbol[:3], symbol[3:]
        else:
            base, quote = "EUR", "USD"

        pip_size = max(float(spec.tick_size), 1e-9)
        pips = sign * ((float(exit) - float(entry)) / pip_size)

        if quote == "USD":
            pip_value = float(spec.pip_value)
        elif base == "USD":
            denom = max(float(exit), 1e-9)
            pip_value = (pip_size / denom) * float(spec.contract_multiplier)
        else:
            denom = max(float(exit), 1e-9)
            pip_value = float(spec.pip_value) / denom

        pnl = pips * pip_value * float(quantity)
        return float(pnl - float(commission))

    @staticmethod
    def equity_pnl(
        signal: str,
        entry: float,
        exit: float,
        quantity: float,
        spec: InstrumentSpec,
        commission: float = 0.0,
    ) -> float:
        side = signal.strip().upper()
        sign = 1.0 if side in {"BUY", "LONG"} else -1.0
        gross = (
            sign * (float(exit) - float(entry)) * float(quantity) * float(spec.contract_multiplier)
        )
        return float(gross - float(commission))

    @staticmethod
    def options_pnl(
        signal: str,
        entry: float,
        exit: float,
        quantity: float,
        spec: InstrumentSpec,
        commission: float = 0.0,
        greeks: dict[str, float] | None = None,
        days_held: float = 0.0,
        underlying_entry: float | None = None,
        underlying_exit: float | None = None,
    ) -> float:
        side = signal.strip().upper()
        sign = 1.0 if side in {"CALL_BUY", "PUT_BUY", "BUY", "LONG"} else -1.0
        multiplier = float(spec.contract_multiplier)

        premium_component = sign * (float(exit) - float(entry)) * float(quantity) * multiplier
        greek_delta_component = 0.0
        greek_theta_component = 0.0

        if greeks:
            delta = float(greeks.get("delta", 0.0))
            theta = float(greeks.get("theta", 0.0))
            if underlying_entry is not None and underlying_exit is not None:
                greek_delta_component = (
                    delta
                    * (float(underlying_exit) - float(underlying_entry))
                    * float(quantity)
                    * multiplier
                )
            greek_theta_component = theta * float(days_held) * float(quantity) * multiplier

        pnl = premium_component + greek_delta_component + greek_theta_component
        return float(pnl - float(commission))

    @staticmethod
    def order_pnl(order: dict[str, Any], exit_price: float | None = None) -> float:
        side = str(order.get("side", ""))
        instrument = str(order.get("instrument", ""))
        entry = float(order.get("filled_price", order.get("entry_price", 0.0)) or 0.0)
        exit_val = (
            float(exit_price)
            if exit_price is not None
            else float(order.get("exit_price", 0.0) or 0.0)
        )
        qty = float(order.get("filled_qty", order.get("qty", 0.0)) or 0.0)
        commission = float(order.get("commission", 0.0) or 0.0)

        raw_spec = order.get("instrument_spec")
        if isinstance(raw_spec, dict):
            spec = InstrumentSpec(
                asset_class=str(raw_spec.get("asset_class", infer_asset_class(instrument, side))),
                pip_value=float(raw_spec.get("pip_value", 0.0)),
                contract_multiplier=float(raw_spec.get("contract_multiplier", 1.0)),
                tick_size=float(raw_spec.get("tick_size", 0.01)),
                notional_per_unit=float(raw_spec.get("notional_per_unit", 1.0)),
                currency=str(raw_spec.get("currency", "USD")),
            )
        else:
            spec = resolve_instrument_spec(instrument, side)

        asset_class = spec.asset_class
        if asset_class == "forex":
            return ProfitCalculator.forex_pnl(
                signal=side,
                instrument=instrument,
                entry=entry,
                exit=exit_val,
                quantity=qty,
                spec=spec,
                commission=commission,
            )
        if asset_class == "options":
            greeks = order.get("greeks") if isinstance(order.get("greeks"), dict) else None
            days_held = float(order.get("days_held", 0.0) or 0.0)
            under_entry = order.get("underlying_entry")
            under_exit = order.get("underlying_exit")
            return ProfitCalculator.options_pnl(
                signal=side,
                entry=entry,
                exit=exit_val,
                quantity=qty,
                spec=spec,
                commission=commission,
                greeks=greeks,
                days_held=days_held,
                underlying_entry=float(under_entry) if under_entry is not None else None,
                underlying_exit=float(under_exit) if under_exit is not None else None,
            )
        return ProfitCalculator.equity_pnl(
            signal=side,
            entry=entry,
            exit=exit_val,
            quantity=qty,
            spec=spec,
            commission=commission,
        )

    @staticmethod
    def order_notional(order: dict[str, Any]) -> float:
        raw_spec = order.get("instrument_spec")
        if isinstance(raw_spec, dict):
            spec = InstrumentSpec(
                asset_class=str(raw_spec.get("asset_class", "equity")),
                pip_value=float(raw_spec.get("pip_value", 0.0)),
                contract_multiplier=float(raw_spec.get("contract_multiplier", 1.0)),
                tick_size=float(raw_spec.get("tick_size", 0.01)),
                notional_per_unit=float(raw_spec.get("notional_per_unit", 1.0)),
                currency=str(raw_spec.get("currency", "USD")),
            )
        else:
            spec = resolve_instrument_spec(
                str(order.get("instrument", "")), str(order.get("side", ""))
            )

        qty = float(order.get("filled_qty", order.get("qty", 0.0)) or 0.0)
        price = float(order.get("filled_price", order.get("entry_price", 0.0)) or 0.0)
        if spec.asset_class == "forex":
            return abs(qty) * float(spec.notional_per_unit)
        return abs(qty) * price * float(spec.contract_multiplier)

    @staticmethod
    def spec_dict(instrument: str, side: str = "") -> dict[str, float | str]:
        return asdict(resolve_instrument_spec(instrument, side))
