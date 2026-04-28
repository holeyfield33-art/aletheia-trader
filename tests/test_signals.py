import pandas as pd

from agents.signal_engine import SignalEngine


def _sample_df() -> pd.DataFrame:
    closes = [
        100,
        101,
        102,
        101,
        100,
        99,
        98,
        99,
        100,
        102,
        104,
        103,
        102,
        101,
        100,
        99,
        98,
        97,
        98,
        99,
        100,
        101,
        102,
        103,
        104,
    ]
    return pd.DataFrame({"close": closes})


def test_generate_forex_signal_returns_valid_action():
    engine = SignalEngine()
    action, meta = engine.generate_forex_signal(_sample_df())
    assert action in {"BUY", "SELL", "HOLD"}
    assert "rsi" in meta
    assert "macd_hist" in meta


def test_generate_options_signal_returns_valid_action():
    engine = SignalEngine()
    action, meta = engine.generate_options_signal(_sample_df())
    assert action in {"CALL_BUY", "PUT_BUY", "HOLD"}
    assert "rsi" in meta
    assert "bb_mid" in meta
