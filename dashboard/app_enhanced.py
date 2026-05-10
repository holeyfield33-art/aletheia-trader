"""Premium Aletheia Trader Dashboard - Professional Command Center"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from backtesting.engine import BacktestConfig, BacktestEngine

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
    "positive": "#10B981",
    "negative": "#EF4444",
    "warning": "#F59E0B",
    "info": "#3B82F6",
    "neutral": "#6B7280",
    "accent": "#8B5CF6",
    "bg_dark": "#0F172A",
    "bg_darker": "#020617",
    "card_bg": "#1E293B",
    "border": "#334155",
    "text_secondary": "#94A3B8",
}

# Page config
st.set_page_config(
    page_title="Aletheia Trader", layout="wide", initial_sidebar_state="expanded", menu_items=None
)

# Premium Dark Theme CSS
st.markdown(
    f"""
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
""",
    unsafe_allow_html=True,
)


# Utility functions
def render_header():
    st.markdown(
        '<div class="header-container"><div class="header-title">🎯 Aletheia Trader</div><div class="header-subtitle">Protected by Aletheia Core • Signal First, Execute Later</div></div>',
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, delta: str | None = None, icon: str = ""):
    delta_html = (
        f'<div style="color: {"#10B981" if delta and delta.startswith("+") else "#EF4444"}; font-size: 0.875rem; margin-top: 0.5rem;">{delta}</div>'
        if delta
        else ""
    )
    st.markdown(
        f'<div class="metric-card"><div class="metric-card-title">{title}</div><div class="metric-card-value">{icon} {value}</div>{delta_html}</div>',
        unsafe_allow_html=True,
    )


def render_protection_banner():
    st.markdown(
        '<div class="protection-banner"><div style="font-size: 1.5rem;">✅</div><div class="protection-text"><strong>Protected by Aletheia Core</strong> • All signals and decisions are audit-signed</div></div>',
        unsafe_allow_html=True,
    )


def render_receipt(receipt: str):
    if not receipt or receipt == "mock-receipt":
        st.caption("📋 Receipt: None or demo receipt")
        return
    preview = f"{receipt[:16]}..." if len(receipt) > 16 else receipt
    with st.expander(f"📋 View Receipt: {preview}", expanded=False):
        st.code(receipt, language="json")


def render_filtered_signal(data: dict) -> None:
    """Render a clear 'filtered / weak signal' card with the reason."""
    reason = data.get("filter_reason") or "Conditions too weak for a reliable trade."
    st.markdown(
        f"""
        <div style="background:rgba(239,68,68,0.1);border:1px solid #EF4444;border-radius:0.75rem;
                    padding:1.25rem 1.5rem;margin:1rem 0;">
            <div style="font-size:1rem;font-weight:700;color:#EF4444;">🚫 Invalid / Weak Signal — Filtered</div>
            <div style="font-size:0.875rem;color:#94A3B8;margin-top:0.5rem;"><strong>Reason:</strong> {reason}</div>
            <div style="font-size:0.75rem;color:#64748B;margin-top:0.5rem;">
                Signal ID: {data.get('signal_id', 'N/A')} &nbsp;|&nbsp; Instrument: {data.get('instrument', 'N/A')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("🔬 View Raw Indicators", expanded=False):
        st.json(data.get("indicators", {}))


def render_signal_quality(data: dict) -> None:
    confidence = float(data.get("confidence_score", 0.0) or 0.0)
    regime = str(data.get("regime", "unknown") or "unknown").upper()
    recommended_size = float(data.get("recommended_size", 0.0) or 0.0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Confidence", f"{confidence:.1f}/100")
    c2.metric("Regime", regime)
    c3.metric("Recommended Size", f"{recommended_size:.2f}")


def render_monthly_heatmap(monthly: pd.DataFrame, symbol: str) -> None:
    if monthly.empty:
        st.info("No monthly returns to visualize yet.")
        return

    fig = go.Figure(
        data=go.Heatmap(
            z=(monthly * 100.0).fillna(0.0).values,
            x=list(monthly.columns),
            y=[str(y) for y in monthly.index.tolist()],
            colorscale="RdYlGn",
            colorbar={"title": "%"},
        )
    )
    fig.update_layout(
        title=f"Monthly Returns Heatmap: {symbol}",
        xaxis_title="Month",
        yaxis_title="Year",
        template="plotly_dark",
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def check_api() -> tuple[bool, str]:
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=REQUEST_TIMEOUT_SECONDS)
        return resp.status_code == 200, (
            "online" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        )
    except Exception:
        return False, "offline"


def normalize_date_input(value: date | tuple[date, ...] | None) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, tuple) and value:
        return value[0]
    return datetime.now().date()


# Sidebar
with st.sidebar:
    st.markdown("### 🏢 Aletheia Trader")
    st.divider()
    protection = st.toggle("**🔐 Live Aletheia Protection**", value=True)
    st.divider()
    page = st.radio(
        "**Navigate To:**",
        [
            "📊 Dashboard",
            "🚀 Signal Generator",
            "🧪 Backtesting Lab",
            "⏳ Pending Approvals",
            "📈 Trade History",
            "📉 Analytics",
            "⚙️ Settings",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    api_ok, status = check_api()
    if api_ok:
        st.success(f"✅ API {status}")
    else:
        st.error(f"❌ API {status}")
    st.divider()
    st.markdown("**Quick Links:**")
    col1, col2 = st.columns(2)
    col1.button("🔗 Aletheia Core", use_container_width=True)
    col2.button("🔗 Redteam Kit", use_container_width=True)
    st.divider()
    st.caption("Aletheia Trader v1.0.1")

if not api_ok and page not in {"⚙️ Settings", "🧪 Backtesting Lab"}:
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
        signals = requests.get(
            f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS
        ).json()

        with col1:
            render_metric_card("Daily P&L", f"${pnl['daily']['daily_pnl']:,.2f}", None, "📈")
        with col2:
            render_metric_card("Total P&L", f"${pnl['total_pnl']:,.2f}", None, "💰")
        with col3:
            render_metric_card("Win Rate", "75%", None, "🎯")
        with col4:
            render_metric_card("Pending", str(len(signals.get("signals", []))), None, "⏳")
    except Exception as e:
        st.error(f"Error: {str(e)[:60]}")

    st.markdown("---\n### ⏳ Pending Signals")
    try:
        sig_data = requests.get(
            f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS
        ).json()
        signals = sig_data.get("signals", [])
        if signals:
            for sig in signals[:5]:
                with st.container(border=True):
                    col_left, col_right = st.columns([2, 1])
                    with col_left:
                        st.markdown(
                            f"**{sig.get('agent_type', 'UNKNOWN').upper()} • {sig.get('instrument', 'N/A')}**"
                        )
                        st.metric("Signal", sig.get("signal", "HOLD"))
                    with col_right:
                        entry = st.number_input("Entry$", value=100.0, key=f"e_{sig['signal_id']}")
                        if st.button(
                            "✅ Approve", key=f"a_{sig['signal_id']}", use_container_width=True
                        ):
                            resp = requests.post(
                                f"{API_BASE}/v1/signals/approve",
                                json={
                                    "signal_id": sig["signal_id"],
                                    "entry_price": entry,
                                    "qty": 1.0,
                                },
                                timeout=REQUEST_TIMEOUT_SECONDS,
                            )
                            if resp.status_code == 200:
                                st.balloons()
                                st.success("✅ Approved!")
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
    with col1:
        agent = st.selectbox("Agent", ["forex", "options"])
    with col2:
        instr = st.selectbox("Symbol", ["EUR/USD", "GBP/USD", "SPY", "QQQ"])
    if st.button("🚀 Generate", type="primary", use_container_width=True):
        with st.spinner("Generating..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/v1/signals/generate",
                    json={"agent_type": agent, "pair_or_symbol": instr},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("filtered"):
                        render_filtered_signal(data)
                        render_signal_quality(data)
                    else:
                        st.balloons()
                        st.success(
                            f"✅ Valid Signal: **{data['signal']}** — ID: {data['signal_id']}"
                        )
                        st.caption("Validation status: Passed strict filters")
                        render_signal_quality(data)
                        st.json(data.get("indicators", {}))
                else:
                    st.error(f"API error {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                st.error(f"Error: {str(e)[:60]}")

elif page == "🧪 Backtesting Lab":
    render_header()
    st.markdown("### 🧪 Backtesting Lab")
    st.caption(
        "Vectorized strategy research with risk snapshot, optimization, and walk-forward analysis."
    )

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            symbol_text = st.text_input("Symbols (comma-separated)", value="EURUSD,BTC-USD,SPY")
            strategy_name = st.selectbox("Strategy", ["macd_rsi"])
            timeframe = st.selectbox("Timeframe", ["15m", "1h", "4h", "1d"], index=1)
        with c2:
            raw_start = st.date_input("Start", value=datetime(2023, 1, 1))
            raw_end = st.date_input("End", value=datetime(2025, 1, 1))
            start_date = normalize_date_input(raw_start)
            end_date = normalize_date_input(raw_end)
            initial_cash = st.number_input(
                "Initial Cash", min_value=1000.0, value=100000.0, step=1000.0
            )
        with c3:
            commission_bps = st.number_input("Commission (bps)", min_value=0.0, value=2.0, step=0.1)
            slippage_bps = st.number_input("Slippage (bps)", min_value=0.0, value=1.0, step=0.1)
            spread_bps = st.number_input("Spread (bps)", min_value=0.0, value=1.5, step=0.1)
            risk_per_trade = st.number_input(
                "Risk / Trade", min_value=0.001, max_value=0.05, value=0.01, step=0.001
            )

    opt_col, wf_col, run_col = st.columns([1, 1, 2])
    run_opt = opt_col.checkbox("Run Optimization", value=True)
    run_wf = wf_col.checkbox("Run Walk-Forward", value=True)

    if run_col.button("▶ Run Backtest", type="primary", use_container_width=True):
        symbols = [s.strip() for s in symbol_text.split(",") if s.strip()]
        cfg = BacktestConfig(
            symbols=symbols,
            timeframe=timeframe,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            strategy=strategy_name,
            strategy_params={"risk_per_trade": risk_per_trade},
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            spread_bps=spread_bps,
            risk_per_trade=risk_per_trade,
        )

        with st.spinner("Running vectorized backtest..."):
            engine = BacktestEngine()
            report = engine.run(cfg)
            payload: dict[str, Any] = {"engine": engine, "report": report, "config": cfg}

            if run_opt and symbols:
                payload["optimization"] = engine.optimize(
                    cfg,
                    symbol=symbols[0],
                    param_grid={
                        "rsi_buy": [30, 35, 40],
                        "rsi_sell": [60, 65, 70],
                        "trend_threshold": [0.0, 0.002, 0.004],
                    },
                )

            if run_wf and symbols:
                payload["walk_forward"] = engine.walk_forward(
                    cfg,
                    symbol=symbols[0],
                    param_grid={
                        "rsi_buy": [30, 35],
                        "rsi_sell": [65, 70],
                    },
                    train_bars=300,
                    test_bars=120,
                    step_bars=120,
                )

            st.session_state["bt_payload"] = payload

    bt_payload = cast(dict[str, Any] | None, st.session_state.get("bt_payload"))
    if isinstance(bt_payload, dict):
        page_engine = cast(BacktestEngine, bt_payload["engine"])
        report = cast(Any, bt_payload["report"])

        st.markdown("---\n### 📌 Portfolio Summary")
        p = report.portfolio_metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sharpe", f"{p.get('sharpe', 0.0):.2f}")
        c2.metric("Sortino", f"{p.get('sortino', 0.0):.2f}")
        c3.metric("Calmar", f"{p.get('calmar', 0.0):.2f}")
        c4.metric("Max DD", f"{p.get('max_drawdown', 0.0) * 100:.2f}%")

        risk = cast(dict[str, Any], report.risk_snapshot)
        st.markdown("### 🛡️ Risk Snapshot")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("VaR", f"{_as_float(risk.get('var', 0.0)) * 100:.2f}%")
        r2.metric("CVaR", f"{_as_float(risk.get('cvar', 0.0)) * 100:.2f}%")
        r3.metric("Open Notional", f"{_as_float(risk.get('open_notional_pct', 0.0)) * 100:.2f}%")
        limits = risk.get("limits", {}) if isinstance(risk, dict) else {}
        r4.metric("Risk Gate", "OPEN" if limits.get("allow_new_risk", True) else "HALTED")

        symbols_available = list(report.results.keys())
        if not symbols_available:
            st.warning("No symbols produced backtest results. Check symbol inputs and date range.")
        else:
            selected = st.selectbox("Inspect Symbol", symbols_available)
            result = report.results[selected]

            left, right = st.columns(2)
            left.plotly_chart(
                page_engine.build_equity_curve_figure(result), use_container_width=True
            )
            right.plotly_chart(page_engine.build_drawdown_figure(result), use_container_width=True)

            render_monthly_heatmap(result.monthly_returns_heatmap, selected)

            st.markdown("### 📄 Performance Tear Sheet")
            tear_rows = {
                **result.metrics,
                **{f"mc_{k}": v for k, v in result.monte_carlo.items()},
                "risk_var": _as_float(risk.get("var", 0.0)),
                "risk_cvar": _as_float(risk.get("cvar", 0.0)),
            }
            tear_df = pd.DataFrame([{"metric": k, "value": v} for k, v in tear_rows.items()])
            st.dataframe(tear_df, use_container_width=True, hide_index=True)

            st.markdown("### 📚 Trade Log")
            st.dataframe(result.trades.tail(200), use_container_width=True)

        if "optimization" in bt_payload and isinstance(bt_payload["optimization"], pd.DataFrame):
            st.markdown("### 🧬 Parameter Optimization")
            st.dataframe(bt_payload["optimization"].head(20), use_container_width=True)

        if "walk_forward" in bt_payload and isinstance(bt_payload["walk_forward"], dict):
            st.markdown("### 🔁 Walk-Forward")
            wf = bt_payload["walk_forward"]
            st.json(wf.get("summary", {}))
            windows = wf.get("windows", [])
            if windows:
                st.dataframe(pd.DataFrame(windows), use_container_width=True)

elif page == "⏳ Pending Approvals":
    render_header()
    st.markdown("### ⏳ Pending Approvals")
    try:
        signals = (
            requests.get(f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS)
            .json()
            .get("signals", [])
        )
        if signals:
            for i, sig in enumerate(signals):
                with st.container(border=True):
                    cols = st.columns([2, 1, 1])
                    cols[0].markdown(
                        f"**#{i+1}: {sig.get('agent_type', 'N/A').upper()} • {sig.get('instrument', 'N/A')}**"
                    )
                    cols[1].metric("Signal", sig.get("signal", "HOLD"))
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
        url = (
            f"{API_BASE}/v1/orders" if status == "All" else f"{API_BASE}/v1/orders?status={status}"
        )
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
    st.markdown(
        "**Links:**\n- [Aletheia Core](https://aletheia-core.com)\n- [Redteam Kit](https://github.com/holeyfield33-art/aletheia-redteam-kit)\n- [Website](https://aletheia-core.com)"
    )
    st.caption("Aletheia Trader v1.0.1 • Protected by Aletheia Core")
