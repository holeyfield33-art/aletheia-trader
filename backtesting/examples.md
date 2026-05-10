# Backtesting Examples

## Quick start

python -m backtesting.run --symbol EURUSD --strategy macd_rsi

## Multi-asset batch

python -m backtesting.run --symbol EURUSD,BTC-USD,SPY --strategy macd_rsi --timeframe 1h

## Include optimization and walk-forward

python -m backtesting.run \
  --symbol EURUSD \
  --strategy macd_rsi \
  --run-optimization \
  --run-walkforward

## Custom cost model

python -m backtesting.run \
  --symbol SPY \
  --strategy macd_rsi \
  --commission-bps 1.5 \
  --slippage-bps 1.0 \
  --spread-bps 0.5

## Artifacts

Each run writes to backtesting/output/<timestamp>/:
- summary.json
- portfolio_equity.csv
- portfolio_drawdown.csv
- per-symbol equity/drawdown/trades/monthly heatmap CSVs
- per-symbol equity and drawdown HTML plots
