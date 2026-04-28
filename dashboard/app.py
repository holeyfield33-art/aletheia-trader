from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from agents.forex_agent import ForexAgent
from agents.options_agent import OptionsAgent
from brokers.simulator import PaperSimulator


st.set_page_config(page_title="Aletheia Trader", layout="wide")
st.title("Aletheia Trader")
st.caption("Signal first, execute later. Every decision signed.")

forex_agent = ForexAgent()
options_agent = OptionsAgent()
simulator = PaperSimulator()

forex_pairs = ["EUR/USD", "GBP/USD", "USD/JPY"]
option_symbols = ["SPY", "QQQ"]

st.subheader("Forex Signals")
forex_results = []
for pair in forex_pairs:
    with st.spinner(f"Analyzing {pair}..."):
        forex_results.append(forex_agent.run(pair))

st.dataframe(pd.DataFrame(forex_results), use_container_width=True)

st.subheader("Options Signals")
options_results = []
for symbol in option_symbols:
    with st.spinner(f"Analyzing {symbol}..."):
        options_results.append(options_agent.run(symbol))

st.dataframe(pd.DataFrame(options_results), use_container_width=True)

st.subheader("Daily Paper P&L")
pnl = simulator.get_daily_pnl()
st.metric("Daily P&L", f"${pnl['daily_pnl']:.2f}")
st.write({"closed_orders": pnl["closed_orders"], "open_orders": pnl["open_orders"], "date": pnl["date"]})

st.subheader("Open and Pending Orders")
orders_df = pd.DataFrame(simulator.list_orders())
if orders_df.empty:
    st.info("No simulated orders yet.")
else:
    st.dataframe(orders_df, use_container_width=True)
