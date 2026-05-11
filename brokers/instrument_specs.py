from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class InstrumentSpec:
    asset_class: str
    pip_value: float
    contract_multiplier: float
    tick_size: float
    notional_per_unit: float
    currency: str

    def to_dict(self) -> dict[str, float | str]:
        return asdict(self)


def infer_asset_class(instrument: str, side: str = "") -> str:
    token = instrument.strip().upper()
    if "/" in token or token.endswith("=X") or (len(token) == 6 and token.isalpha()):
        return "forex"
    if side.upper() in {"CALL_BUY", "PUT_BUY", "CALL_SELL", "PUT_SELL"}:
        return "options"
    return "equity"


def resolve_instrument_spec(instrument: str, side: str = "") -> InstrumentSpec:
    asset_class = infer_asset_class(instrument, side)
    if asset_class == "forex":
        return InstrumentSpec(
            asset_class="forex",
            pip_value=10.0,
            contract_multiplier=100000.0,
            tick_size=0.0001,
            notional_per_unit=100000.0,
            currency="USD",
        )
    if asset_class == "options":
        return InstrumentSpec(
            asset_class="options",
            pip_value=0.0,
            contract_multiplier=100.0,
            tick_size=0.01,
            notional_per_unit=100.0,
            currency="USD",
        )
    return InstrumentSpec(
        asset_class="equity",
        pip_value=0.0,
        contract_multiplier=1.0,
        tick_size=0.01,
        notional_per_unit=1.0,
        currency="USD",
    )
