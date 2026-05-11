from __future__ import annotations

from agents.forex_agent import ForexAgent
from agents.options_agent import OptionsAgent
from backtesting.data import DataManager, DataUnavailableException


def _raise_unavailable(*args, **kwargs):
    del args, kwargs
    raise DataUnavailableException(
        symbol="EURUSD=X",
        timeframe="15m",
        backend_order=["yfinance"],
        failures={"yfinance": "simulated outage"},
    )


def test_forex_agent_returns_data_stale_no_signal_on_outage(tmp_path):
    manager = DataManager(cache_dir=tmp_path / "cache", strict_data_mode=True)
    manager.download = _raise_unavailable  # type: ignore[method-assign]

    agent = ForexAgent(data_manager=manager)
    result = agent.run("EUR/USD")

    assert result["signal"] == "NO_SIGNAL"
    assert result["data_stale"] is True
    assert "Data feed interrupted" in str(result["filter_reason"])


def test_options_agent_returns_data_stale_no_signal_on_outage(tmp_path):
    manager = DataManager(cache_dir=tmp_path / "cache", strict_data_mode=True)
    manager.download = _raise_unavailable  # type: ignore[method-assign]

    agent = OptionsAgent(data_manager=manager)
    result = agent.run("SPY")

    assert result["signal"] == "NO_SIGNAL"
    assert result["data_stale"] is True
    assert "Data feed interrupted" in str(result["filter_reason"])
