from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:

    def st_autorefresh(*args, **kwargs):
        return None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

API_BASE = "http://localhost:8000"
REQUEST_TIMEOUT_SECONDS = 5

st.set_page_config(page_title="Aletheia Trader", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Aletheia Trader")
st.caption("Signal first, execute later. Every decision signed.")


def render_receipt_preview(receipt: str) -> None:
    """Render short receipt text plus expandable full-value viewer."""
    if not receipt:
        st.caption("Receipt: none")
        return
    preview = f"{receipt[:16]}..." if len(receipt) > 16 else receipt
    st.caption(f"Receipt: {preview}")
    with st.expander("View full receipt", expanded=False):
        st.code(receipt)


def check_api_health() -> tuple[bool, str]:
    """Return API reachability and a short status message for UI gating."""
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            return True, "online"
        return False, f"unhealthy (HTTP {resp.status_code})"
    except requests.RequestException as exc:
        return False, f"offline ({exc})"


# Sidebar navigation
with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Select View:", ["Dashboard", "Signal Generator", "Orders", "Analytics", "Settings"]
    )
    api_ok, api_status = check_api_health()
    st.caption(f"API Status: {api_status}")

if not api_ok and page != "Settings":
    st.error("Backend API is not reachable, so dashboard actions are temporarily unavailable.")
    st.info("Start the API service, then refresh this page.")
    st.code("uvicorn api.server:app --host 0.0.0.0 --port 8000")
    st.stop()

if page == "Dashboard":
    st_autorefresh(interval=60000, key="dashboard_refresh")
    st.subheader("📊 Dashboard")

    col1, col2, col3 = st.columns(3)

    try:
        pnl_resp = requests.get(f"{API_BASE}/v1/analytics/pnl").json()
        daily_pnl = pnl_resp["daily"]["daily_pnl"]
        total_pnl = pnl_resp["total_pnl"]

        with col1:
            st.metric("Daily P&L", f"${daily_pnl:,.2f}", delta=None)

        with col2:
            st.metric("Total P&L", f"${total_pnl:,.2f}", delta=None)

        with col3:
            orders_resp = requests.get(f"{API_BASE}/v1/orders").json()
            st.metric("Total Orders", orders_resp["count"], delta=None)
    except Exception as e:
        st.error(f"Could not fetch analytics: {e}")

    st.divider()

    st.subheader("⏳ Pending Signals (Awaiting Approval)")
    try:
        signals_resp = requests.get(f"{API_BASE}/v1/signals/pending").json()
        signals = signals_resp.get("signals", [])

        if signals:
            for sig in signals:
                with st.container(border=True):
                    col_left, col_right = st.columns([3, 1])

                    with col_left:
                        st.write(
                            f"**{sig['agent_type'].upper()}** | {sig['instrument']} → `{sig['signal']}`"
                        )

                        # Show indicators
                        indicators = sig.get("indicators", {})
                        ind_cols = st.columns(4)
                        if indicators:
                            ind_items = list(indicators.items())
                            for i, (key, val) in enumerate(ind_items[:4]):
                                with ind_cols[i]:
                                    st.caption(f"{key}: {val:.2f}")

                        render_receipt_preview(str(sig.get("receipt", "")))

                    with col_right:
                        st.write("**Entry Price:**")
                        entry_price = st.number_input(
                            "$", value=100.0, key=f"entry_{sig['signal_id']}"
                        )

                        col_a, col_r = st.columns(2)
                        with col_a:
                            if st.button(
                                "✅ Approve",
                                key=f"approve_{sig['signal_id']}",
                                use_container_width=True,
                            ):
                                try:
                                    resp = requests.post(
                                        f"{API_BASE}/v1/signals/approve",
                                        json={
                                            "signal_id": sig["signal_id"],
                                            "entry_price": entry_price,
                                            "qty": 1.0,
                                        },
                                    )
                                    if resp.status_code == 200:
                                        st.success(f"Approved! Order: {resp.json()['order_id']}")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")

                        with col_r:
                            if st.button(
                                "❌ Reject",
                                key=f"reject_{sig['signal_id']}",
                                use_container_width=True,
                            ):
                                try:
                                    requests.post(
                                        f"{API_BASE}/v1/signals/reject",
                                        json={"signal_id": sig["signal_id"]},
                                    )
                                    st.info("Rejected.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
        else:
            st.info("No pending signals.")
    except Exception as e:
        st.error(f"Error fetching signals: {e}")

    st.divider()

    st.subheader("📈 Open Positions")
    try:
        orders_resp = requests.get(f"{API_BASE}/v1/orders?status=OPEN").json()
        orders = orders_resp.get("orders", [])

        if orders:
            for order in orders:
                with st.container(border=True):
                    col_left, col_right = st.columns([3, 1])

                    with col_left:
                        st.write(
                            f"**{order['order_id']}** | {order['instrument']} {order['side']} x{order['qty']}"
                        )
                        st.caption(
                            f"Entry: ${order['entry_price']:.2f} | Opened: {order['executed_at'][:10]}"
                        )

                    with col_right:
                        st.write("**Exit Price:**")
                        exit_price = st.number_input(
                            "$", value=order["entry_price"], key=f"exit_{order['order_id']}"
                        )

                        if st.button(
                            "🔒 Close Position",
                            key=f"close_{order['order_id']}",
                            use_container_width=True,
                        ):
                            try:
                                resp = requests.post(
                                    f"{API_BASE}/v1/orders/close",
                                    json={"order_id": order["order_id"], "exit_price": exit_price},
                                )
                                if resp.status_code == 200:
                                    data = resp.json()
                                    st.success(f"Closed! P&L: ${data['pnl']:.2f}")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
        else:
            st.info("No open positions.")
    except Exception as e:
        st.error(f"Error fetching orders: {e}")


elif page == "Signal Generator":
    st.subheader("🚀 Generate Signals")

    col_type, col_instr = st.columns(2)

    with col_type:
        agent_type = st.selectbox("Agent Type", ["forex", "options"])

    with col_instr:
        if agent_type == "forex":
            pair = st.selectbox("Pair", ["EUR/USD", "GBP/USD", "USD/JPY"])
            instrument = pair
        else:
            symbol = st.selectbox("Symbol", ["SPY", "QQQ", "DIA"])
            instrument = symbol

    if st.button("Generate Signal", use_container_width=True, type="primary"):
        try:
            with st.spinner("Generating signal..."):
                resp = requests.post(
                    f"{API_BASE}/v1/signals/generate",
                    json={"agent_type": agent_type, "pair_or_symbol": instrument},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.success(f"✅ Signal generated: {data['signal_id']}")

                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Signal:** `{data['signal']}`")
                        st.write(f"**Instrument:** {data['instrument']}")
                    with col2:
                        render_receipt_preview(str(data.get("receipt", "")))

                    st.write("**Indicators:**")
                    st.json(data["indicators"])

                    st.info(
                        f"Signal expires in {data['expires_in_minutes']} minutes. Go to Dashboard to approve/reject."
                    )
                else:
                    st.error(f"Error: {resp.text}")
        except Exception as e:
            st.error(f"Error: {e}")

    st.divider()
    with st.expander("Crypto Signals (Coinbase)"):
        crypto_symbol = st.selectbox("Symbol", ["BTC-USD", "ETH-USD", "SOL-USD"], key="crypto_sym")
        crypto_gateway = st.text_input("Aletheia Gateway URL (optional)", key="crypto_gw")
        crypto_key = st.text_input("API Key (optional)", type="password", key="crypto_key")

        if st.button("Generate Crypto Signal", use_container_width=True):
            try:
                with st.spinner(f"Analyzing {crypto_symbol}..."):
                    params = {"symbol": crypto_symbol}
                    if crypto_gateway:
                        params["gateway_url"] = crypto_gateway
                    if crypto_key:
                        params["api_key"] = crypto_key

                    response = requests.post(
                        f"{API_BASE}/v1/signals/crypto",
                        params=params,
                        headers={"X-API-Key": st.session_state.get("api_key", "")},
                    )

                    if response.status_code == 200:
                        signal = response.json()
                        st.json(signal)
                        st.success(
                            f"Signal: {signal.get('action', 'N/A')} - {signal.get('reason', 'no reason')}"
                        )
                        render_receipt_preview(str(signal.get("receipt", "")))
                    else:
                        st.error(f"Error: {response.text}")
            except Exception as e:
                st.error(f"Error: {e}")


elif page == "Orders":
    st.subheader("📋 Order History")

    status_filter = st.selectbox("Filter by Status", ["All", "OPEN", "CLOSED"])

    try:
        if status_filter == "All":
            resp = requests.get(f"{API_BASE}/v1/orders").json()
        else:
            resp = requests.get(f"{API_BASE}/v1/orders?status={status_filter}").json()

        orders = resp.get("orders", [])

        if orders:
            df = pd.DataFrame(orders)

            # Calculate P&L for closed orders
            def calc_pnl(row):
                if row["status"] != "CLOSED" or not row["exit_price"]:
                    return None
                sign = 1 if row["side"] in {"BUY", "CALL_BUY"} else -1
                return sign * (row["exit_price"] - row["entry_price"]) * row["qty"]

            df["pnl"] = df.apply(calc_pnl, axis=1)

            # Display orders
            display_cols = [
                "order_id",
                "instrument",
                "side",
                "qty",
                "entry_price",
                "exit_price",
                "status",
                "pnl",
            ]
            st.dataframe(df[display_cols], use_container_width=True)
        else:
            st.info(f"No {status_filter.lower()} orders found.")
    except Exception as e:
        st.error(f"Error: {e}")


elif page == "Analytics":
    st.subheader("📊 Performance Analytics")

    try:
        pnl_resp = requests.get(f"{API_BASE}/v1/analytics/pnl").json()
        orders_resp = requests.get(f"{API_BASE}/v1/orders").json()

        daily = pnl_resp["daily"]
        total = pnl_resp["total_pnl"]
        all_orders = orders_resp.get("orders", [])

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Daily P&L", f"${daily['daily_pnl']:.2f}")
        with col2:
            st.metric("Total P&L", f"${total:.2f}")
        with col3:
            closed = len([o for o in all_orders if o["status"] == "CLOSED"])
            st.metric("Closed Orders", closed)

        st.divider()

        # P&L breakdown
        closed_orders = [o for o in all_orders if o["status"] == "CLOSED" and o.get("exit_price")]
        if closed_orders:
            pnl_data = []
            for o in closed_orders:
                sign = 1 if o["side"] in {"BUY", "CALL_BUY"} else -1
                pnl = sign * (o["exit_price"] - o["entry_price"]) * o["qty"]
                pnl_data.append(
                    {
                        "Order": o["order_id"],
                        "Instrument": o["instrument"],
                        "Side": o["side"],
                        "P&L": round(pnl, 2),
                    }
                )

            df = pd.DataFrame(pnl_data)
            st.write("**Closed Trades P&L**")
            st.dataframe(df, use_container_width=True)

            # Stats
            total_trades = len(df)
            winning = len(df[df["P&L"] > 0])
            losing = len(df[df["P&L"] < 0])
            win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Trades", total_trades)
            with col2:
                st.metric("Win Rate", f"{win_rate:.1f}%")
            with col3:
                st.metric("Winning", winning)
            with col4:
                st.metric("Losing", losing)
        else:
            st.info("No closed trades yet.")
    except Exception as e:
        st.error(f"Error: {e}")


elif page == "Settings":
    st.subheader("⚙️ Settings")

    st.info("API Configuration")
    st.write(f"**API Endpoint:** {API_BASE}")

    st.write("**Environment**")
    col1, col2 = st.columns(2)
    with col1:
        env = st.text_input("ALETHEIA_GATEWAY (leave empty for mock)", value="")
    with col2:
        key = st.text_input("GATEWAY_API_KEY (optional)", value="", type="password")

    if st.button("Test API Connection"):
        try:
            resp = requests.get(f"{API_BASE}/health")
            if resp.status_code == 200:
                st.success(f"✅ API healthy: {resp.json()}")
            else:
                st.error(f"API returned {resp.status_code}")
        except Exception as e:
            st.error(f"❌ Cannot connect to API: {e}")
            st.info("Make sure the API server is running: `python api/server.py`")
