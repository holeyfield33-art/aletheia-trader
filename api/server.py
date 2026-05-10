from __future__ import annotations

import math
import os
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from agents.crypto_agent import CryptoAgent
from agents.forex_agent import ForexAgent
from agents.market_watcher import MarketWatcher, MarketWatcherConfig
from agents.options_agent import OptionsAgent
from agents.signal_engine import NO_SIGNAL
from brokers.signal_and_order_ledger import SignalAndOrderLedger

load_dotenv()

app = FastAPI(title="Aletheia Trader API", version="1.0.1")
ledger = SignalAndOrderLedger()
forex_agent = ForexAgent()
options_agent = OptionsAgent()
market_watcher = MarketWatcher(ledger=ledger)


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"


def _validate_instrument(value: str) -> str:
    cleaned = value.strip().upper()
    if not cleaned:
        raise HTTPException(status_code=422, detail="pair_or_symbol must not be empty")

    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/_")
    if any(ch not in allowed_chars for ch in cleaned):
        raise HTTPException(status_code=422, detail="pair_or_symbol contains invalid characters")
    return cleaned


def _sanitize_indicators(indicators: dict[str, Any] | None) -> dict[str, float]:
    if not indicators:
        return {}

    sanitized: dict[str, float] = {}
    for key, value in indicators.items():
        try:
            numeric = float(value)
            sanitized[key] = numeric if math.isfinite(numeric) else 0.0
        except (TypeError, ValueError):
            sanitized[key] = 0.0
    return sanitized


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    return value


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Allow open access by default, enforce X-API-Key only when API_AUTH_KEY is configured."""
    configured_key = os.getenv("API_AUTH_KEY", "")
    if configured_key and x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key or ""


class GenerateSignalRequest(BaseModel):
    agent_type: Literal["forex", "options"]
    pair_or_symbol: str = Field(min_length=1, max_length=20)


class GenerateSignalResponse(BaseModel):
    signal_id: str
    agent_type: str
    instrument: str
    signal: str
    indicators: dict[str, float]
    receipt: str
    expires_in_minutes: int
    filtered: bool
    filter_reason: str
    confidence_score: float
    regime: str
    recommended_size: float


class ApproveSignalRequest(BaseModel):
    signal_id: str = Field(min_length=3, max_length=64)
    entry_price: float = Field(gt=0)
    qty: float = Field(default=1.0, gt=0)


class RejectSignalRequest(BaseModel):
    signal_id: str = Field(min_length=3, max_length=64)


class CloseOrderRequest(BaseModel):
    order_id: str = Field(min_length=3, max_length=64)
    exit_price: float = Field(gt=0)


class MarketWatcherStartRequest(BaseModel):
    symbols: list[str] | None = None
    timeframe: str = Field(default="1h", min_length=1, max_length=8)
    lookback_period: str = Field(default="30d", min_length=2, max_length=10)
    poll_interval_seconds: float = Field(default=60.0, gt=0)


@app.get("/health")
async def health():
    """Health check endpoint for container and service monitoring."""
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@app.post("/v1/signals/generate", response_model=GenerateSignalResponse)
async def generate_signal(req: GenerateSignalRequest):
    """Generate a new trading signal."""
    signal_id = f"sig-{uuid.uuid4().hex[:8]}"
    instrument = _validate_instrument(req.pair_or_symbol)

    if req.agent_type == "forex":
        result = forex_agent.run(instrument)
        agent_type = "forex"
        resolved_instrument = str(result.get("pair") or instrument)
    elif req.agent_type == "options":
        result = options_agent.run(instrument)
        agent_type = "options"
        resolved_instrument = str(result.get("symbol") or instrument)
    else:
        raise HTTPException(status_code=400, detail="agent_type must be 'forex' or 'options'")

    if result.get("signal") == "ERROR":
        raise HTTPException(
            status_code=500, detail=f"Signal generation failed: {result.get('error')}"
        )

    signal_value: str = str(result.get("signal") or NO_SIGNAL)
    filter_reason: str = str(result.get("filter_reason") or "")
    is_filtered = signal_value == NO_SIGNAL

    raw_meta = result.get("meta")
    indicators = _sanitize_indicators(raw_meta if isinstance(raw_meta, dict) else {})
    raw_chain_data = result.get("chain_data") if agent_type == "options" else None
    chain_data = raw_chain_data if isinstance(raw_chain_data, dict) else None
    receipt = str(result.get("receipt") or "")

    # Only persist valid, actionable signals — filtered signals are discarded
    if not is_filtered:
        ledger.add_signal(
            signal_id=signal_id,
            agent_type=agent_type,
            instrument=resolved_instrument,
            signal=signal_value,
            indicators=indicators,
            chain_data=chain_data,
            receipt=receipt,
            ttl_minutes=120,
        )

    return GenerateSignalResponse(
        signal_id=signal_id,
        agent_type=agent_type,
        instrument=resolved_instrument,
        signal=signal_value,
        indicators=indicators,
        receipt=receipt,
        expires_in_minutes=0 if is_filtered else 120,
        filtered=is_filtered,
        filter_reason=filter_reason,
        confidence_score=float(indicators.get("confidence", 0.0)),
        regime=str(indicators.get("regime", "unknown")),
        recommended_size=float(indicators.get("recommended_size", 0.0)),
    )


@app.get("/v1/signals/pending")
async def get_pending_signals():
    """Get all pending signals awaiting approval."""
    signals = ledger.get_pending_signals()
    safe_signals = _json_safe(signals)
    return {"count": len(signals), "signals": safe_signals}


@app.api_route("/v1/signals/crypto", methods=["GET", "POST"])
async def generate_crypto_signal(
    symbol: str = "BTC-USD",
    gateway_url: str | None = None,
    api_key: str | None = None,
    auth: str = Depends(verify_api_key),
):
    """Generate a crypto signal and return audit receipt metadata."""
    del auth  # dependency side effect only
    symbol = _validate_instrument(symbol)
    agent = CryptoAgent(gateway_url=gateway_url, api_key=api_key)
    return agent.generate_signal(symbol)


@app.post("/v1/signals/approve")
async def approve_signal(req: ApproveSignalRequest):
    """Approve a signal and create an order."""
    signal = ledger.approve_signal(req.signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found or already approved")

    try:
        order = ledger.create_order_from_signal(signal, entry_price=req.entry_price, qty=req.qty)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "order_id": order.get("order_id"),
        "signal_id": req.signal_id,
        "instrument": order.get("instrument"),
        "side": order.get("side"),
        "qty": order.get("qty"),
        "entry_price": order.get("entry_price"),
        "status": "OPEN",
        "executed_at": order.get("executed_at"),
    }


@app.post("/v1/signals/reject")
async def reject_signal(req: RejectSignalRequest):
    """Reject and discard a pending signal."""
    success = ledger.reject_signal(req.signal_id)
    if not success:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {"signal_id": req.signal_id, "status": "rejected"}


@app.get("/v1/orders")
async def get_orders(status: OrderStatus | None = None):
    """Get orders, optionally filtered by status (OPEN, CLOSED, PENDING)."""
    status_value: str | None = status.value if status else None
    orders = ledger.get_orders(status=status_value)
    return {"count": len(orders), "orders": _json_safe(orders)}


@app.post("/v1/orders/close")
async def close_order(req: CloseOrderRequest):
    """Close an open order at a given exit price."""
    try:
        order = ledger.close_order(req.order_id, req.exit_price)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not open")

    sign = 1 if order.get("side") in {"BUY", "CALL_BUY"} else -1
    entry_price = _as_float(order.get("entry_price"))
    qty = _as_float(order.get("qty"))
    pnl = sign * (float(req.exit_price) - entry_price) * qty

    return {
        "order_id": req.order_id,
        "status": "CLOSED",
        "entry_price": order.get("entry_price"),
        "exit_price": req.exit_price,
        "qty": order.get("qty"),
        "pnl": round(pnl, 2),
        "closed_at": order.get("closed_at"),
    }


@app.get("/v1/analytics/pnl")
async def get_pnl():
    """Get daily and total P&L."""
    daily: dict[str, Any] = ledger.get_daily_pnl()
    total: float = ledger.get_total_pnl()
    return _json_safe(
        {
            "daily": daily,
            "total_pnl": total,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )


@app.get("/v1/market-watcher/status")
async def get_market_watcher_status():
    """Get MarketWatcher lifecycle and diagnostic status."""
    return _json_safe(market_watcher.status())


@app.get("/v1/market-watcher/history")
async def get_market_watcher_history(limit: int = Query(default=30, ge=1, le=500)):
    """Get historical MarketWatcher cycle snapshots."""
    history = market_watcher.history()
    return _json_safe({"count": min(limit, len(history)), "history": history[-limit:]})


@app.post("/v1/market-watcher/start")
async def start_market_watcher(req: MarketWatcherStartRequest):
    """Configure and start the MarketWatcher background loop."""
    symbols = req.symbols or market_watcher.config.symbols
    market_watcher.reconfigure(
        symbols=[_validate_instrument(symbol) for symbol in symbols],
        timeframe=req.timeframe,
        poll_interval_seconds=req.poll_interval_seconds,
        lookback_period=req.lookback_period,
    )
    status = market_watcher.start()
    return _json_safe(status)


@app.post("/v1/market-watcher/stop")
async def stop_market_watcher():
    """Stop the MarketWatcher background loop."""
    return _json_safe(market_watcher.stop())


@app.post("/v1/market-watcher/run-once")
async def run_market_watcher_once(req: MarketWatcherStartRequest):
    """Run a single MarketWatcher cycle without leaving the background loop enabled."""
    symbols = req.symbols or market_watcher.config.symbols
    market_watcher.reconfigure(
        symbols=[_validate_instrument(symbol) for symbol in symbols],
        timeframe=req.timeframe,
        poll_interval_seconds=req.poll_interval_seconds,
        lookback_period=req.lookback_period,
    )
    return _json_safe(market_watcher.run_cycle())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
