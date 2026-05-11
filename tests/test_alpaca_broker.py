from __future__ import annotations

from typing import Any

from brokers.alpaca_broker import AlpacaBroker
from brokers.broker_factory import BrokerFactory, PaperBrokerAdapter


class _FakeModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return dict(self._payload)


class _FakeTradingClient:
    def __init__(self) -> None:
        self.last_order_data = None

    def submit_order(self, order_data):
        self.last_order_data = order_data
        return _FakeModel({"id": "alp-1", "status": "accepted"})

    def cancel_order_by_id(self, order_id: str):
        return _FakeModel({"id": order_id, "status": "cancelled"})

    def get_all_positions(self):
        return [_FakeModel({"symbol": "SPY", "qty": "1"})]

    def get_account(self):
        return _FakeModel({"status": "ACTIVE", "buying_power": "10000"})


def test_alpaca_broker_dry_run_submit_order() -> None:
    broker = AlpacaBroker(
        api_key="key",
        secret_key="secret",
        endpoint="https://paper-api.alpaca.markets",
        paper=True,
        dry_run=True,
        client=_FakeTradingClient(),
    )

    result = broker.submit_order(
        {
            "instrument": "SPY",
            "side": "BUY",
            "qty": 2,
            "entry_price": 500.0,
            "order_type": "market",
            "time_in_force": "gtc",
        }
    )

    assert result["status"] == "dry_run"
    assert str(result["endpoint"]).endswith("/v2/orders")
    payload = result["payload"]
    assert payload["symbol"] == "SPY"
    assert payload["side"] == "buy"


def test_alpaca_broker_live_submit_order_uses_sdk_request() -> None:
    fake_client = _FakeTradingClient()
    broker = AlpacaBroker(
        api_key="key",
        secret_key="secret",
        endpoint="https://paper-api.alpaca.markets",
        paper=True,
        dry_run=False,
        client=fake_client,
    )

    result = broker.submit_order(
        {
            "instrument": "SPY",
            "side": "SELL",
            "qty": 1,
            "entry_price": 500.0,
            "order_type": "limit",
            "limit_price": 499.0,
            "time_in_force": "gtc",
            "request_id": "req-1",
        }
    )

    assert result["status"] == "accepted"
    assert fake_client.last_order_data is not None
    dumped = fake_client.last_order_data.model_dump()
    assert dumped["symbol"] == "SPY"
    assert dumped["qty"] == 1.0
    assert dumped["client_order_id"] == "req-1"


def test_broker_factory_modes(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_DRY_RUN", "true")

    paper = BrokerFactory.create("paper")
    assert isinstance(paper, PaperBrokerAdapter)

    alpaca_paper = BrokerFactory.create("alpaca_paper")
    assert isinstance(alpaca_paper, AlpacaBroker)
    assert alpaca_paper.config.paper is True

    alpaca_live = BrokerFactory.create("alpaca_live")
    assert isinstance(alpaca_live, AlpacaBroker)
    assert alpaca_live.config.paper is False
