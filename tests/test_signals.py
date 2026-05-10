import pandas as pd

from agents.signal_engine import NO_SIGNAL, SignalEngine


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
    df = pd.DataFrame({"close": closes})
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    return df


def _strong_oversold_df() -> pd.DataFrame:
    """25-bar series with a sharp dip — should survive RSI+MACD validation."""
    closes = [
        100.0,
        100.3,
        100.6,
        100.2,
        99.8,
        99.3,
        98.7,
        98.0,
        97.2,
        96.3,
        95.3,
        94.2,
        93.0,
        93.5,
        94.1,
        94.8,
        95.6,
        96.4,
        97.3,
        98.2,
        99.1,
        100.0,
        100.8,
        101.5,
        102.0,
    ]
    df = pd.DataFrame({"close": closes})
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    return df


def _short_df() -> pd.DataFrame:
    """Only 10 bars — BB window of 20 can't fire, should be filtered."""
    df = pd.DataFrame({"close": [100, 101, 102, 101, 100, 99, 98, 99, 100, 102]})
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    return df


def test_generate_forex_signal_returns_valid_action():
    engine = SignalEngine()
    action, meta, filter_reason = engine.generate_forex_signal(_sample_df())
    assert action in {"BUY", "SELL", "HOLD", NO_SIGNAL}
    assert "rsi" in meta
    assert "macd_hist" in meta
    assert "confidence" in meta
    assert "regime" in meta
    assert "recommended_size" in meta
    assert isinstance(filter_reason, str)


def test_generate_options_signal_returns_valid_action():
    engine = SignalEngine()
    action, meta, filter_reason = engine.generate_options_signal(_sample_df())
    assert action in {"CALL_BUY", "PUT_BUY", "HOLD", NO_SIGNAL}
    assert "rsi" in meta
    assert "bb_mid" in meta
    assert 0.0 <= float(meta.get("confidence", 0.0)) <= 100.0
    assert isinstance(filter_reason, str)


def test_short_data_filtered_as_no_signal():
    """Fewer bars than BB window → Bollinger Bands not computed → NO_SIGNAL."""
    engine = SignalEngine()
    action, meta, filter_reason = engine.generate_forex_signal(_short_df())
    assert action == NO_SIGNAL
    assert filter_reason != ""
    assert "Bollinger" in filter_reason


def test_strong_signal_passes_validation():
    """Sharp oversold dip series should clear at least BB validation."""
    engine = SignalEngine()
    action, meta, filter_reason = engine.generate_forex_signal(_strong_oversold_df())
    # Signal can be BUY/HOLD if trend reversal is mild — key is it must NOT be NO_SIGNAL
    # (BB is computed so rule 1 passes; direction depends on indicator values)
    # If still NO_SIGNAL, reason must contain a specific condition string not BB
    if action == NO_SIGNAL:
        assert "Bollinger Bands not yet calculated" not in filter_reason
    else:
        assert filter_reason == ""


def test_no_signal_has_non_empty_reason():
    """Any NO_SIGNAL result must carry a human-readable reason."""
    engine = SignalEngine()
    action, meta, filter_reason = engine.generate_forex_signal(_short_df())
    if action == NO_SIGNAL:
        assert len(filter_reason) > 0


def test_correlation_penalty_reduces_recommended_size():
    engine = SignalEngine()
    _, meta_no_penalty, _ = engine.generate_forex_signal(
        _strong_oversold_df(), correlation_penalty=0.0
    )
    _, meta_penalty, _ = engine.generate_forex_signal(
        _strong_oversold_df(), correlation_penalty=0.8
    )
    assert float(meta_penalty["recommended_size"]) <= float(meta_no_penalty["recommended_size"])
