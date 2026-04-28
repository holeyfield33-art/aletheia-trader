from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from brokers.signal_and_order_ledger import SignalAndOrderLedger
from agents.forex_agent import ForexAgent
from agents.options_agent import OptionsAgent

load_dotenv()

app = FastAPI(title="Aletheia Trader API", version="1.0.0")
ledger = SignalAndOrderLedger()
forex_agent = ForexAgent()
options_agent = OptionsAgent()


class GenerateSignalRequest(BaseModel):
    agent_type: str  # "forex" or "options"
    pair_or_symbol: str


class GenerateSignalResponse(BaseModel):
    signal_id: str
    agent_type: str
    instrument: str
    signal: str
    indicators: Dict[str, float]
    receipt: str
    expires_in_minutes: int


class ApproveSignalRequest(BaseModel):
    signal_id: str
    entry_price: float
    qty: float = 1.0


class RejectSignalRequest(BaseModel):
    signal_id: str


class CloseOrderRequest(BaseModel):
    order_id: str
    exit_price: float


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/v1/signals/generate", response_model=GenerateSignalResponse)
async def generate_signal(req: GenerateSignalRequest):
    """Generate a new trading signal."""
    signal_id = f"sig-{uuid.uuid4().hex[:8]}"
    
    if req.agent_type == "forex":
        result = forex_agent.run(req.pair_or_symbol)
        agent_type = "forex"
        instrument = result.get("pair", req.pair_or_symbol)
    elif req.agent_type == "options":
        result = options_agent.run(req.pair_or_symbol)
        agent_type = "options"
        instrument = result.get("symbol", req.pair_or_symbol)
    else:
        raise HTTPException(status_code=400, detail="agent_type must be 'forex' or 'options'")
    
    if result.get("signal") == "ERROR":
        raise HTTPException(status_code=500, detail=f"Signal generation failed: {result.get('error')}")
    
    chain_data = result.get("chain_data") if agent_type == "options" else None
    ledger.add_signal(
        signal_id=signal_id,
        agent_type=agent_type,
        instrument=instrument,
        signal=result.get("signal"),
        indicators=result.get("meta", {}),
        chain_data=chain_data,
        receipt=result.get("receipt", ""),
        ttl_minutes=120,
    )
    
    return GenerateSignalResponse(
        signal_id=signal_id,
        agent_type=agent_type,
        instrument=instrument,
        signal=result.get("signal"),
        indicators=result.get("meta", {}),
        receipt=result.get("receipt", ""),
        expires_in_minutes=120,
    )


@app.get("/v1/signals/pending")
async def get_pending_signals():
    """Get all pending signals awaiting approval."""
    signals = ledger.get_pending_signals()
    return {"count": len(signals), "signals": signals}


@app.post("/v1/signals/approve")
async def approve_signal(req: ApproveSignalRequest):
    """Approve a signal and create an order."""
    signal = ledger.approve_signal(req.signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found or already approved")
    
    order = ledger.create_order_from_signal(signal, entry_price=req.entry_price, qty=req.qty)
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
async def get_orders(status: str = None):
    """Get orders, optionally filtered by status (OPEN, CLOSED, PENDING)."""
    orders = ledger.get_orders(status=status)
    return {"count": len(orders), "orders": orders}


@app.post("/v1/orders/close")
async def close_order(req: CloseOrderRequest):
    """Close an open order at a given exit price."""
    order = ledger.close_order(req.order_id, req.exit_price)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not open")
    
    sign = 1 if order.get("side") in {"BUY", "CALL_BUY"} else -1
    pnl = sign * (float(req.exit_price) - float(order.get("entry_price"))) * float(order.get("qty"))
    
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
    daily = ledger.get_daily_pnl()
    total = ledger.get_total_pnl()
    return {
        "daily": daily,
        "total_pnl": total,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
