# Aletheia Trader

Signal first, execute later. Every decision signed.

Aletheia Trader is a local-first trading assistant for forex and options signal generation with policy-aware audit logging. It is designed for paper/manual workflows, not autonomous live execution.

## Core Principles

- Generate signals for forex and options.
- Show daily paper P&L from local simulated orders.
- Audit every signal and simulated order decision.
- Keep human-in-the-loop: all orders are pending until explicitly approved.
- No autonomous live trading.

## Project Structure

- `agents/`: signal generation logic for forex/options plus indicator engine.
- `brokers/`: paper wrappers and local simulator ledger.
- `audit/`: gateway wrapper for Aletheia audit events.
- `dashboard/`: Streamlit app for signals and P&L.
- `policies/`: trading policy JSON pack.
- `scripts/`: backtest/bootstrap scripts.
- `tests/`: signal engine tests.

## Quick Start

1. Create a virtual environment and install dependencies:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Set environment values:

```bash
cp .env.example .env
```

3. Run a single forex signal pass:

```bash
python agents/forex_agent.py
```

4. Start the dashboard:

```bash
streamlit run dashboard/app.py
```

## Scripts

- Start dashboard quickly:

```bash
./start.sh
```

- Run signal snapshot plus simulated order writes:

```bash
python scripts/backtest.py
```

- Run tests:

```bash
pytest -q
```

## Docker Compose

```bash
docker compose up --build
```

Dashboard runs on `http://localhost:8501`.

## Notes

- Forex data uses ETF proxies via yfinance (`FXE`, `FXB`, `FXY`) for free local development.
- Options signaling uses yfinance data for `SPY` and `QQQ`.
- Audit wrapper gracefully falls back to mock receipts if the gateway is unavailable.
- Simulator ledger is stored in `data/simulated_orders.json`.
