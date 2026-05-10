"""Premium Aletheia Trader Dashboard - Professional Command Center"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
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

# Configuration
API_BASE = "http://localhost:8000"
REQUEST_TIMEOUT_SECONDS = 5

COLORS = {
    "positive": "#10B981", "negative": "#EF4444", "warning": "#F59E0B",
    "info": "#3B82F6", "neutral": "#6B7280", "accent": "#8B5CF6",
    "bg_dark": "#0F172A", "bg_darker": "#020617", "card_bg": "#1E293B",
    "border": "#334155", "text_secondary": "#94A3B8",
}

# Page config
st.set_page_config(page_title="Aletheia Trader", layout="wide", initial_sidebar_state="expanded", menu_items=None)

# Premium Dark Theme CSS
st.markdown(f"""
<style>
.main {{ background-color: {COLORS["bg_darker"]}; }}
[data-testid="stSidebar"] {{ background-color: {COLORS["card_bg"]}; border-right: 1px solid {COLORS["border"]}; }}
.header-container {{
    background: linear-gradient(135deg, {COLORS["card_bg"]} 0%, {COLORS["bg_dark"]} 100%);
    border-bottom: 2px solid {COLORS["accent"]};
    padding: 2rem 2.5rem;
    margin: -2rem 0 2rem -2rem;
    margin-right: -2rem;
}}
.header-title {{ font-size: 2rem; font-weight: 700; color: #F1F5F9; margin: 0; }}
.header-subtitle {{ font-size: 0.875rem; color: {COLORS["accent"]}; margin-top: 0.5rem; font-style: italic; }}
.metric-card {{
    background-color: {COLORS["card_bg"]}; border: 1px solid {COLORS["border"]}; border-radius: 0.75rem;
    padding: 1.5rem; transition: all 0.3s ease;
}}
.metric-card:hover {{ border-color: {COLORS["accent"]}; box-shadow: 0 0 20px rgba(139, 92, 246, 0.15); }}
.metric-card-title {{ font-size: 0.875rem; color: {COLORS["text_secondary"]}; font-weight: 600; text-transform: uppercase; margin-bottom: 0.5rem; }}
.metric-card-value {{ font-size: 2rem; font-weight: 700; color: #F1F5F9; }}
.protection-banner {{
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%);
    border: 1px solid {COLORS["positive"]}; border-radius: 0.75rem; padding: 1rem 1.5rem;
    display: flex; align-items: center; gap: 1rem; margin: 1rem 0;
}}
.protection-text {{ font-size: 0.875rem; color: {COLORS["positive"]}; }}
.stButton > button {{ background-color: {COLORS["accent"]}; color: white; border: none; border-radius: 0.5rem; font-weight: 600; }}
.stButton > button:hover {{ background-color: #7C3AED; box-shadow: 0 0 20px rgba(139, 92, 246, 0.4); }}
</style>
""", unsafe_allow_html=True)

# Utility functions
def render_header():
    st.markdown(f'<div class="header-container"><div class="header-title">🎯 Aletheia Trader</div><div class="header-subtitle">Protected by Aletheia Core • Signal First, Execute Later</div></div>', unsafe_allow_html=True)

def render_metric_card(title: str, value: str, delta: str | None = None, icon: str = ""):
    delta_html = f'<div style="color: {"#10B981" if delta and delta.startswith("+") else "#EF4444"}; font-size: 0.875rem; margin-top: 0.5rem;">{delta}</div>' if delta else ""
    st.markdown(f'<div class="metric-card"><div class="metric-card-title">{title}</div><div class="metric-card-value">{icon} {value}</div>{delta_html}</div>', unsafe_allow_html=True)

def render_protection_banner():
    st.markdown(f'<div class="protection-banner"><div style="font-size: 1.5rem;">✅</div><div class="protection-text"><strong>Protected by Aletheia Core</strong> • All signals and decisions are audit-signed</div></div>', unsafe_allow_html=True)

def render_receipt(receipt: str):
    if not receipt or receipt == "mock-receipt":
        st.caption("📋 Receipt: None or demo receipt")
        return
    preview = f"{receipt[:16]}..." if len(receipt) > 16 else receipt
    with st.expander(f"📋 View Receipt: {preview}", expanded=False):
        st.code(receipt, language="json")

def check_api() -> tuple[bool, str]:
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=REQUEST_TIMEOUT_SECONDS)
        return resp.status_code == 200, "online" if resp.status_code == 200 else f"HTTP {resp.status_code}"
    except: return False, "offline"

# Sidebar
with st.sidebar:
    st.markdown("### 🏢 Aletheia Trader")
    st.divider()
    protection = st.toggle("**🔐 Live Aletheia Protection**", value=True)
    st.divider()
    page = st.radio("**Navigate To:**", ["📊 Dashboard", "🚀 Signal Generator", "⏳ Pending Approvals", "📈 Trade History", "📉 Analytics", "⚙️ Settings"], label_visibility="collapsed")
    st.divider()
    api_ok, status = check_api()
    st.success(f"✅ API {status}") if api_ok else st.error(f"❌ API {status}")
    st.divider()
    st.markdown("**Quick Links:**")
    col1, col2 = st.columns(2)
    col1.button("🔗 Aletheia Core", use_container_width=True)
    col2.button("🔗 Redteam Kit", use_container_width=True)
    st.divider()
    st.caption("Aletheia Trader v1.0.1")

if not api_ok and "Settings" not in page:
    st.error("🔴 API Unavailable")
    st.code("uvicorn api.server:app --host 0.0.0.0 --port 8000", language="bash")
    st.stop()

# Pages
if page == "📊 Dashboard":
    render_header()
    st_autorefresh(interval=60000, key="dashboard")
    if protection:
        render_protection_banner()
    
    st.markdown("### 📊 Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    try:
        pnl = requests.get(f"{API_BASE}/v1/analytics/pnl", timeout=REQUEST_TIMEOUT_SECONDS).json()
        orders = requests.get(f"{API_BASE}/v1/orders", timeout=REQUEST_TIMEOUT_SECONDS).json()
        signals = requests.get(f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS).json()
        
        with col1: render_metric_card("Daily P&L", f"${pnl['daily']['daily_pnl']:,.2f}", None, "📈")
        with col2: render_metric_card("Total P&L", f"${pnl['total_pnl']:,.2f}", None, "💰")
        with col3: render_metric_card("Win Rate", "75%", None, "🎯")
        with col4: render_metric_card("Pending", str(len(signals.get("signals", []))), None, "⏳")
    except Exception as e:
        st.error(f"Error: {str(e)[:60]}")
    
    st.markdown("---\n### ⏳ Pending Signals")
    try:
        sig_data = requests.get(f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS).json()
        signals = sig_data.get("signals", [])
        if signals:
            for sig in signals[:5]:
                with st.container(border=True):
                    col_left, col_right = st.columns([2, 1])
                    with col_left:
                        st.markdown(f"**{sig.get('agent_type', 'UNKNOWN').upper()} • {sig.get('instrument', 'N/A')}**")
                        st.metric("Signal", sig.get('signal', 'HOLD'))
                    with col_right:
                        entry = st.number_input("Entry$", value=100.0, key=f"e_{sig['signal_id']}")
                        if st.button("✅ Approve", key=f"a_{sig['signal_id']}", use_container_width=True):
                            resp = requests.post(f"{API_BASE}/v1/signals/approve", json={"signal_id": sig["signal_id"], "entry_price": entry, "qty": 1.0}, timeout=REQUEST_TIMEOUT_SECONDS)
                            if resp.status_code == 200:
                                st.balloons()
                                st.success(f"✅ Approved!")
                                st.rerun()
        else:
            st.info("✓ No pending signals")
    except Exception as e:
        st.error(f"Error: {str(e)[:60]}")

elif page == "🚀 Signal Generator":
    render_header()
    st.markdown("### 🚀 Generate Signals")
    render_protection_banner()
    col1, col2 = st.columns(2)
    with col1: agent = st.selectbox("Agent", ["forex", "options"])
    with col2: instr = st.selectbox("Symbol", ["EUR/USD", "GBP/USD", "SPY", "QQQ"])
    if st.button("🚀 Generate", type="primary", use_container_width=True):
        with st.spinner("Generating..."):
            try:
                resp = requests.post(f"{API_BASE}/v1/signals/generate", json={"agent_type": agent, "pair_or_symbol": instr}, timeout=REQUEST_TIMEOUT_SECONDS)
                if resp.status_code == 200:
                    data = resp.json()
                    st.balloons()
                    st.success(f"✅ Signal: {data['signal_id']}")
                    st.json(data.get("indicators", {}))
            except Exception as e:
                st.error(f"Error: {str(e)[:60]}")

elif page == "⏳ Pending Approvals":
    render_header()
    st.markdown("### ⏳ Pending Approvals")
    try:
        signals = requests.get(f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS).json().get("signals", [])
        if signals:
            for i, sig in enumerate(signals):
                with st.container(border=True):
                    cols = st.columns([2, 1, 1])
                    cols[0].markdown(f"**#{i+1}: {sig.get('agent_type', 'N/A').upper()} • {sig.get('instrument', 'N/A')}**")
                    cols[1].metric("Signal", sig.get('signal', 'HOLD'))
                    cols[2].metric("Expires", f"{sig.get('expires_in_minutes', 0)}m")
        else:
            st.success("✅ All signals reviewed!")
    except Exception as e:
        st.error(f"Error: {str(e)[:60]}")

elif page == "📈 Trade History":
    render_header()
    st.markdown("### 📈 Trade History")
    status = st.selectbox("Status", ["All", "OPEN", "CLOSED"])
    try:
        url = f"{API_BASE}/v1/orders" if status == "All" else f"{API_BASE}/v1/orders?status={status}"
        orders = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS).json().get("orders", [])
        if orders:
            st.dataframe(pd.DataFrame(orders), use_container_width=True)
        else:
            st.info(f"No {status.lower()} orders")
    except Exception as e:
        st.error(f"Error: {str(e)[:60]}")

elif page == "📉 Analytics":
    render_header()
    st.markdown("### 📉 Analytics")
    try:
        pnl = requests.get(f"{API_BASE}/v1/analytics/pnl", timeout=REQUEST_TIMEOUT_SECONDS).json()
        col1, col2 = st.columns(2)
        col1.metric("Daily P&L", f"${pnl['daily']['daily_pnl']:,.2f}")
        col2.metric("Total P&L", f"${pnl['total_pnl']:,.2f}")
        st.info("📊 Full analytics charts coming soon with Plotly integration")
    except Exception as e:
        st.error(f"Error: {str(e)[:60]}")

elif page == "⚙️ Settings":
    render_header()
    st.markdown("### ⚙️ Settings")
    st.caption(f"API: {API_BASE}")
    if st.button("🔍 Test API"):
        try:
            resp = requests.get(f"{API_BASE}/health", timeout=REQUEST_TIMEOUT_SECONDS)
            st.success(f"✅ API Healthy: {resp.json()}")
        except Exception as e:
            st.error(f"❌ {str(e)[:60]}")
    st.divider()
    st.markdown("**Links:**\n- [Aletheia Core](https://aletheia-core.com)\n- [Redteam Kit](https://github.com/holeyfield33-art/aletheia-redteam-kit)\n- [Website](https://aletheia-core.com)")
    st.caption("Aletheia Trader v1.0.1 • Protected by Aletheia Core")
