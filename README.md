# Aletheia Trader

Signal first, execute later. Every decision signed.

🎯 **Fully operational trading system** with signal generation, manual approval workflow, and real-time P&L tracking. Features REST API backend, interactive Streamlit dashboard, and complete audit trail for all decisions.

## Core Principles

✅ **Signal-First Design**: Generate forex and options signals independently, approve manually
✅ **Human-in-the-Loop**: All signals pending 120 minutes; explicit approval required for execution  
✅ **Audit Everything**: Every signal and order decision logged and assigned receipt ID  
✅ **Paper Trading**: Simulated order execution with daily/total P&L calculation  
✅ **No Autonomous Trading**: Manual approval gates prevent unintended execution  

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Streamlit Dashboard (8501)                 │
│  - Signal Generation | Order Approval | P&L Analytics      │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTP
┌─────────────────▼───────────────────────────────────────────┐
│              FastAPI Backend (8000)                         │
│  - /v1/signals/generate   [POST]                           │
│  - /v1/signals/pending    [GET]                            │
│  - /v1/signals/approve    [POST]                           │
│  - /v1/signals/reject     [POST]                           │
│  - /v1/orders             [GET]                            │
│  - /v1/orders/close       [POST]                           │
│  - /v1/analytics/pnl      [GET]                            │
└──────────┬──────────────┬──────────────┬────────────────────┘
           │              │              │
      ┌────▼──┐      ┌────▼───┐    ┌────▼──────┐
      │ Forex │      │Options │    │   Audit  │
      │ Agent │      │ Agent  │    │ Wrapper  │
      └────┬──┘      └────┬───┘    └────┬──────┘
           │              │             │
      ┌────▼──────────────▼─────────────▼────────┐
      │  Signal & Order Ledger (JSON storage)     │
      │  - pending_signals.json                   │
      │  - approved_orders.json                   │
      └──────────────────────────────────────────┘
```

## Project Structure

```
aletheia-trader/
├── agents/                       # Signal generation
│   ├── signal_engine.py         # Tech indicators: RSI, MACD, Bollinger Bands
│   ├── forex_agent.py           # EUR/USD, GBP/USD, USD/JPY (yfinance)
│   └── options_agent.py         # SPY, QQQ chains with 0DTE/weekly categorization
├── brokers/                      # Order management
│   ├── signal_and_order_ledger.py # Unified signal→order→execution ledger
│   └── simulator.py             # Paper trading engine
├── audit/                        # Compliance & audit trail
│   └── aletheia_wrapper.py       # Audit event logging, mock fallback
├── api/                          # REST backend
│   └── server.py                # FastAPI endpoints (10 routes)
├── dashboard/                    # User interfaces
│   ├── app_enhanced.py          # Full-featured Streamlit UI
│   └── app.py                   # Original dashboard (legacy)
├── data/                         # Persistent data
│   ├── pending_signals.json
│   └── approved_orders.json
├── tests/                        # Unit tests
│   └── test_signals.py
├── run_system.sh                # One-command startup script
└── requirements.txt             # Python dependencies
```

## Quick Start - Fully Operational System

### 1. Setup Environment

```bash
# Clone/enter repository
cd aletheia-trader

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Full System (One Command)

```bash
./run_system.sh
```

This starts:
- **FastAPI Backend**: `http://127.0.0.1:8000` (API docs at `/docs`)
- **Streamlit Dashboard**: `http://127.0.0.1:8501`

### 3. Use the Dashboard

1. **Generate Signals**: 
   - Go to "Signal Generator" tab
   - Select agent type (forex/options) and instrument
   - Click "Generate Signal" → creates pending signal with 120-min TTL

2. **Approve/Reject**:
   - Return to "Dashboard" tab
   - See pending signals in approval panel
   - Set entry price, then Approve (creates order) or Reject

3. **Manage Orders**:
   - View open positions in Dashboard
   - Set exit price and click "Close Position"
   - Watch P&L calculation

4. **Track Performance**:
   - Go to "Analytics" tab
   - View daily/total P&L, win rate, closed trades
   - See individual trade outcomes

## Signal Workflow

```
┌──────────────────┐
│ Generate Signal  │  POST /v1/signals/generate
│ (Forex/Options)  │  → stores in pending_signals.json (120-min TTL)
└────────┬─────────┘
         │
         ├─ 120 minutes elapse → signal expires ❌
         │
         └─► ┌──────────────────────┐
             │ Pending (Dashboard)  │  GET /v1/signals/pending
             │ Awaiting Approval    │  Shows all non-expired signals
             └────────┬─────────────┘
                      │
             ┌────────┴────────┐
             │                 │
    ┌────────▼──────┐  ┌───────▼───────┐
    │ APPROVE       │  │ REJECT        │
    │ → Create Order│  │ → Discard     │
    │ → OPEN status │  │ PENDING→null  │
    └────────┬──────┘  └───────┬───────┘
             │                 │
    ┌────────▼──────────────────▼──────┐
    │ Order Lifecycle: OPEN → CLOSED   │  POST /v1/orders/close
    │ Entry price: user input          │  Exit price: user input
    │ P&L = sign(side) × (exit-entry)  │  = confirmed amount
    └─────────────────────────────────┘
```

## Key Features

### 🎯 Signal Engine
- **RSI (14)**: Relative Strength Index for momentum
- **MACD (12/26/9)**: Divergence crossover signals
- **Bollinger Bands (20, 2σ)**: Volatility and reversion trades

### 💱 Forex Agent
- EUR/USD, GBP/USD, USD/JPY via yfinance ETF proxies
- Historical data automatically fetched
- Audit receipt generated per signal

### 📊 Options Agent
- SPY, QQQ chain analysis
- Categorizes expirations: 0DTE, weekly, monthly
- Extracts ATM strikes, implied volatility, volumes
- Current price included in signal context

### 🔐 Audit Trail
- All signals assigned unique receipt ID
- All approvals/rejections logged with timestamp
- Graceful fallback to mock receipts if gateway unavailable
- Order execution recorded with entry/exit prices

### 📈 P&L Calculation
- Daily breakdown by date
- Total cumulative P&L
- Per-trade attribution (win/loss)
- Open vs. closed position tracking

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/v1/signals/generate` | Create signal (forex/options) |
| GET | `/v1/signals/pending` | List non-expired pending signals |
| POST | `/v1/signals/approve` | Approve signal, create order |
| POST | `/v1/signals/reject` | Reject and discard signal |
| GET | `/v1/orders` | List all orders (filter by status) |
| POST | `/v1/orders/close` | Close order, calculate P&L |
| GET | `/v1/analytics/pnl` | Daily + total P&L breakdown |
| GET | `/health` | API liveness check |

## Manual Testing

```bash
# Start API in separate terminal
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000

# Generate a signal
curl -X POST http://127.0.0.1:8000/v1/signals/generate \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "forex", "pair_or_symbol": "EUR/USD"}'

# Get pending signals
curl http://127.0.0.1:8000/v1/signals/pending

# Approve a signal (replace signal_id)
curl -X POST http://127.0.0.1:8000/v1/signals/approve \
  -H "Content-Type: application/json" \
  -d '{"signal_id": "sig-xxx", "entry_price": 1.0850, "qty": 1.0}'

# Get open orders
curl http://127.0.0.1:8000/v1/orders?status=OPEN

# Close an order
curl -X POST http://127.0.0.1:8000/v1/orders/close \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ord-1", "exit_price": 1.0900}'

# Get P&L analytics
curl http://127.0.0.1:8000/v1/analytics/pnl
```

## Running Tests

```bash
# Run all tests
pytest -q

# Expected output:
# .. [100%] 2 passed
```

## Environment Variables

```bash
# Optional: Connect to real Aletheia gateway (defaults to mock)
export ALETHEIA_GATEWAY="https://gateway.aletheia.io/v1/audit"
export GATEWAY_API_KEY="your-secret-key"

# If not set, audit wrapper uses mock receipts
```

## Data Storage

All data persisted locally in `data/` directory:

- `pending_signals.json`: Signals awaiting approval (auto-expires at TTL)
- `approved_orders.json`: Executed orders with entry/exit/P&L

Both files are JSON arrays with full history for audit trail.

## Docker Deployment

```bash
docker compose up --build
```

Services:
- **FastAPI**: http://localhost:8000 (swagger: `/docs`)
- **Streamlit**: http://localhost:8501

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot connect to API" | Ensure `python -m uvicorn api.server:app` is running on port 8000 |
| "No data for EUR/USD" | yfinance proxy `FXE` may be temporarily unavailable; try again in 60s |
| "Signal expired" | Pending signals are 120 min TTL; generate fresh signal |
| "Order not found" | Check order ID format (e.g., `ord-1`) in `/v1/orders` |

## Architecture Notes

- **Stateless API**: All state in JSON files (easily switchable to DB)
- **Timezone-Aware**: UTC for all timestamps (no DST issues)
- **Graceful Degradation**: Audit wrapper works with or without gateway
- **No External Brokers**: Paper-trading only; human approval required for any live execution
- **Observable**: Full audit trail, every decision logged, all P&L attributed

---

**Status**: ✅ Fully Operational  
**Last Updated**: 2026-04-28  
**Test Coverage**: 2/2 passing
