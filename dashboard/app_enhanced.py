"""Premium Aletheia Trader Dashboard - Professional Command Center"""

from __future__ import annotations

import sys
from contextlib import suppress
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


def render_correlation_heatmap(corr_payload: dict[str, Any]) -> None:
    if not corr_payload:
        st.info("Correlation matrix is not available yet.")
        return

    corr_df = pd.DataFrame(corr_payload)
    if corr_df.empty:
        st.info("Correlation matrix is not available yet.")
        return

    fig = go.Figure(
        data=go.Heatmap(
            z=corr_df.values,
            x=list(corr_df.columns),
            y=list(corr_df.index),
            zmin=-1,
            zmax=1,
            colorscale="RdBu",
            colorbar={"title": "Corr"},
        )
    )
    fig.update_layout(
        title="Cross-Asset Correlation Heatmap",
        template="plotly_dark",
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)


def _status_data_feed_interrupted(watcher_status: dict[str, Any]) -> bool:
    snapshot = watcher_status.get("latest_snapshot")
    if not isinstance(snapshot, dict):
        return False
    if bool(snapshot.get("data_feed_interrupted", False)):
        return True
    failures = snapshot.get("fetch_failures")
    return isinstance(failures, dict) and bool(failures)


def fetch_strategy_presets() -> list[dict[str, Any]]:
    fallback = [
        {
            "id": "safe_trend_follower",
            "name": "Safe Trend Follower",
            "description": "Rides clear trends with conservative entries.",
            "risk_level": "Low",
            "best_market_conditions": "Strong Uptrend or Strong Downtrend",
            "default_parameters": {"min_confidence": 65.0},
            "expected_behavior": "Fewer, cleaner trades.",
        },
        {
            "id": "volatility_crusher",
            "name": "Volatility Crusher",
            "description": "Targets expansion moves with strict caps.",
            "risk_level": "High",
            "best_market_conditions": "High Volatility",
            "default_parameters": {"min_confidence": 60.0},
            "expected_behavior": "Fast entries during sharp moves.",
        },
        {
            "id": "rsi_macd_confluence",
            "name": "RSI + MACD Confluence",
            "description": "Waits for momentum indicators to align.",
            "risk_level": "Medium",
            "best_market_conditions": "Orderly trends",
            "default_parameters": {"min_confidence": 63.0},
            "expected_behavior": "Balanced pace and confirmation.",
        },
        {
            "id": "momentum_breakout",
            "name": "Momentum Breakout",
            "description": "Acts on directional breaks from consolidation.",
            "risk_level": "High",
            "best_market_conditions": "Breakout sessions",
            "default_parameters": {"min_confidence": 62.0},
            "expected_behavior": "Captures early breakout pressure.",
        },
        {
            "id": "mean_reversion",
            "name": "Mean Reversion",
            "description": "Looks for stretched prices snapping back.",
            "risk_level": "Medium",
            "best_market_conditions": "Choppy Market",
            "default_parameters": {"min_confidence": 58.0},
            "expected_behavior": "Frequent range-trading opportunities.",
        },
    ]
    try:
        payload = requests.get(
            f"{API_BASE}/v1/market-watcher/strategies", timeout=REQUEST_TIMEOUT_SECONDS
        ).json()
        strategies = payload.get("strategies")
        if isinstance(strategies, list) and strategies:
            return [item for item in strategies if isinstance(item, dict)]
    except Exception:
        pass
    return fallback


def symbols_for_asset(asset_class: str) -> list[str]:
    if asset_class == "Forex":
        return ["EUR/USD", "GBP/USD", "USD/JPY"]
    if asset_class == "Nasdaq / Stocks":
        return ["SPY", "QQQ", "AAPL", "NVDA"]
    return ["BTC-USD", "ETH-USD", "SOL-USD"]


def scan_seconds_from_label(label: str) -> int:
    mapping = {
        "15 seconds": 15,
        "30 seconds": 30,
        "1 minute": 60,
        "5 minutes": 300,
    }
    return mapping.get(label, 60)


def _agent_type_for_asset(asset_class: str) -> str:
    return "forex" if asset_class == "Forex" else "options"


api_ok, status = check_api()
strategy_presets = fetch_strategy_presets()
preset_by_name = {
    str(item.get("name", "")): item for item in strategy_presets if item.get("name")
}

# Sidebar - Global Controls
with st.sidebar:
    st.title("🛡️ Aletheia Trader")
    st.caption("Protected by Aletheia Core")

    asset_class = st.selectbox(
        "Market Mode",
        options=["Forex", "Nasdaq / Stocks", "Crypto (Coinbase)"],
        help="Choose which market class the dashboard should focus on.",
    )

    strategy_names = list(preset_by_name.keys())
    strategy_preset = st.selectbox(
        "Trading Strategy",
        options=strategy_names,
        help="One-click strategy presets with beginner-friendly defaults.",
    )
    selected_preset = preset_by_name.get(strategy_preset, strategy_presets[0])
    selected_preset_id = str(selected_preset.get("id", "safe_trend_follower"))

    st.divider()
    risk_per_trade = st.slider(
        "Risk per Trade (%)",
        min_value=0.5,
        max_value=5.0,
        value=1.0,
        step=0.1,
        help="Maximum account risk per position.",
    )
    max_daily_loss = st.slider(
        "Max Daily Loss (%)",
        min_value=1.0,
        max_value=10.0,
        value=3.0,
        step=0.5,
        help="Trading pauses once this drawdown limit is reached.",
    )

    st.divider()
    aletheia_enabled = st.toggle(
        "Enable Aletheia Protection",
        value=True,
        help="When enabled, watcher decisions stay under Aletheia policy control.",
    )
    eli5_mode = st.toggle(
        "Explain Like I'm 5",
        value=True,
        help="Adds plain-English signal explanations for beginners.",
    )
    scan_interval = st.select_slider(
        "Scan Frequency",
        options=["15 seconds", "30 seconds", "1 minute", "5 minutes"],
        value="1 minute",
        help="How often the live watcher panel refreshes and polls status.",
    )

    st.divider()
    if api_ok:
        st.success(f"✅ API {status}")
    else:
        st.error(f"❌ API {status}")
    st.caption(f"Current Mode: **{asset_class}** • **{strategy_preset}**")

if api_ok and st.session_state.get("mw_selected_preset") != selected_preset_id:
    with suppress(Exception):
        requests.post(
            f"{API_BASE}/v1/market-watcher/strategies/select",
            params={"preset_id": selected_preset_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    st.session_state["mw_selected_preset"] = selected_preset_id

scan_seconds = scan_seconds_from_label(scan_interval)
asset_symbols = symbols_for_asset(asset_class)

render_header()
if aletheia_enabled:
    render_protection_banner()
else:
    st.warning("Aletheia protection is disabled in UI controls. Decisions may be less protected.")

if not api_ok:
    st.warning(
        "API is offline. Live watcher, signal generation, and approvals are unavailable until API recovers."
    )
    st.code("uvicorn api.server:app --host 0.0.0.0 --port 8000", language="bash")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📡 Live Market Watcher",
        "⚡ Signals",
        "✅ Approvals",
        "📊 Backtest",
        "⚙️ Settings",
    ]
)

with tab1:
    st.subheader(f"Live {asset_class} Market Watcher")
    st.info(f"Using **{strategy_preset}** strategy | Scanning every {scan_interval}")
    st_autorefresh(interval=scan_seconds * 1000, key="live-watcher-refresh")

    symbols_text = st.text_input(
        "Symbols",
        value=",".join(asset_symbols),
        help="Comma-separated list of symbols for the active market mode.",
    )
    c1, c2, c3 = st.columns(3)
    timeframe_choice = c1.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"], index=3)
    lookback = c2.text_input("Lookback", value="30d", help="Historical range used for analysis")
    poll_seconds = c3.number_input("Poll seconds", min_value=5.0, value=float(scan_seconds), step=5.0)

    start_payload = {
        "symbols": [s.strip().upper() for s in symbols_text.split(",") if s.strip()],
        "timeframe": timeframe_choice,
        "poll_interval_seconds": float(poll_seconds),
        "lookback_period": lookback,
        "strategy_preset_id": selected_preset_id,
        "eli5_mode": eli5_mode,
        "risk_per_trade_percent": float(risk_per_trade),
        "max_daily_loss_percent": float(max_daily_loss),
    }

    action_col1, action_col2, action_col3 = st.columns(3)
    if action_col1.button("▶ Start Watcher", type="primary", use_container_width=True, disabled=not api_ok):
        try:
            requests.post(
                f"{API_BASE}/v1/market-watcher/start",
                json=start_payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            st.success("Market watcher started with selected preset and risk profile.")
        except Exception as e:
            st.error(f"Failed to start watcher: {str(e)[:80]}")

    if action_col2.button("⏹ Stop Watcher", use_container_width=True, disabled=not api_ok):
        try:
            requests.post(f"{API_BASE}/v1/market-watcher/stop", timeout=REQUEST_TIMEOUT_SECONDS)
            st.success("Market watcher stopped")
        except Exception as e:
            st.error(f"Failed to stop watcher: {str(e)[:80]}")

    if action_col3.button("⚡ Run One Cycle", use_container_width=True, disabled=not api_ok):
        try:
            requests.post(
                f"{API_BASE}/v1/market-watcher/run-once",
                json=start_payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            st.success("Single cycle completed")
        except Exception as e:
            st.error(f"Run-once failed: {str(e)[:80]}")

    if api_ok:
        try:
            status_payload = requests.get(
                f"{API_BASE}/v1/market-watcher/status", timeout=REQUEST_TIMEOUT_SECONDS
            ).json()
            watcher_status = status_payload if isinstance(status_payload, dict) else {}
            snapshot = watcher_status.get("latest_snapshot") or {}
            snapshot_data = snapshot if isinstance(snapshot, dict) else {}
            watched_rows = (
                snapshot_data.get("symbols")
                if isinstance(snapshot_data.get("symbols"), list)
                else []
            )

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("State", "RUNNING" if watcher_status.get("running") else "STOPPED")
            k2.metric("Cycles", str(watcher_status.get("cycle_count", 0)))
            k3.metric(
                "Heartbeat Lag (s)",
                f"{_as_float(watcher_status.get('seconds_since_heartbeat')):.1f}",
            )
            k4.metric("Last Error", str(watcher_status.get("last_error") or "none")[:18])

            if _status_data_feed_interrupted(watcher_status):
                st.error(
                    "🚨 Data feed interrupted. Signal generation is paused until market data recovers."
                )

            st.markdown("### Ticker + Regime Diagnostics")
            if watched_rows:
                symbol_df = pd.DataFrame(watched_rows)
                display_cols = [
                    "symbol",
                    "last_price",
                    "percent_change",
                    "session_high",
                    "session_low",
                    "signal",
                    "confidence",
                    "regime_label",
                    "sentiment_label",
                    "source_backend",
                ]
                visible_cols = [c for c in display_cols if c in symbol_df.columns]
                st.dataframe(symbol_df[visible_cols], use_container_width=True, hide_index=True)

                eli5_rows = [
                    {
                        "symbol": row.get("symbol"),
                        "explanation": row.get("eli5", "No explanation available."),
                    }
                    for row in watched_rows
                    if isinstance(row, dict)
                ]
                if eli5_mode and eli5_rows:
                    with st.expander("🧠 Plain English Explanations", expanded=False):
                        st.dataframe(pd.DataFrame(eli5_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No snapshots yet. Start the watcher or run one cycle.")

            st.markdown("### Live Candlestick Tracker")
            history_payload = requests.get(
                f"{API_BASE}/v1/market-watcher/history?limit=180", timeout=REQUEST_TIMEOUT_SECONDS
            ).json()
            history = history_payload.get("history", []) if isinstance(history_payload, dict) else []

            candle_rows: list[dict[str, Any]] = []
            for cycle in history:
                if not isinstance(cycle, dict):
                    continue
                cycle_ts = cycle.get("timestamp")
                symbols = cycle.get("symbols", [])
                if not isinstance(symbols, list):
                    continue
                for symbol_row in symbols:
                    if not isinstance(symbol_row, dict):
                        continue
                    candle = symbol_row.get("candlestick")
                    if not isinstance(candle, dict):
                        continue
                    candle_rows.append(
                        {
                            "symbol": symbol_row.get("symbol"),
                            "timestamp": candle.get("timestamp") or cycle_ts,
                            "open": _as_float(candle.get("open")),
                            "high": _as_float(candle.get("high")),
                            "low": _as_float(candle.get("low")),
                            "close": _as_float(candle.get("close")),
                            "patterns": ", ".join(candle.get("patterns", [])),
                        }
                    )

            if candle_rows:
                candle_df = pd.DataFrame(candle_rows)
                candle_symbols = sorted(candle_df["symbol"].dropna().unique().tolist())
                chosen_symbol = st.selectbox("Chart Symbol", options=candle_symbols)
                symbol_candles = candle_df[candle_df["symbol"] == chosen_symbol].copy()
                symbol_candles["timestamp"] = pd.to_datetime(symbol_candles["timestamp"], errors="coerce")
                symbol_candles = symbol_candles.dropna().sort_values("timestamp").tail(120)

                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=symbol_candles["timestamp"],
                            open=symbol_candles["open"],
                            high=symbol_candles["high"],
                            low=symbol_candles["low"],
                            close=symbol_candles["close"],
                            name=chosen_symbol,
                        )
                    ]
                )
                fig.update_layout(
                    title=f"{chosen_symbol} Candlestick Stream",
                    template="plotly_dark",
                    height=420,
                    xaxis_rangeslider_visible=False,
                )
                st.plotly_chart(fig, use_container_width=True)

                latest_patterns = symbol_candles["patterns"].iloc[-1] if not symbol_candles.empty else ""
                if latest_patterns:
                    st.caption(f"Latest pattern cues: {latest_patterns}")
            else:
                st.info("Candlestick history will appear after watcher cycles complete.")

            st.markdown("### Correlation Map")
            corr = snapshot_data.get("correlation_matrix")
            render_correlation_heatmap(corr if isinstance(corr, dict) else {})
        except Exception as e:
            st.error(f"Live watcher panel error: {str(e)[:90]}")

with tab2:
    st.subheader("Latest Signals")
    st.caption("Signals are generated based on your selected market mode and strategy preset.")
    signal_symbol = st.selectbox(
        "Signal Symbol",
        options=asset_symbols,
        help="Pick one symbol and generate a fresh signal using current sidebar settings.",
    )

    if st.button("Generate Signal", type="primary", disabled=not api_ok):
        with st.spinner("Generating signal..."):
            try:
                if asset_class == "Crypto (Coinbase)":
                    resp = requests.get(
                        f"{API_BASE}/v1/signals/crypto",
                        params={"symbol": signal_symbol},
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.success(f"Signal generated for {signal_symbol}")
                        st.json(data)
                    else:
                        st.error(f"API error {resp.status_code}: {resp.text[:120]}")
                else:
                    resp = requests.post(
                        f"{API_BASE}/v1/signals/generate",
                        json={
                            "agent_type": _agent_type_for_asset(asset_class),
                            "pair_or_symbol": signal_symbol,
                        },
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("filtered"):
                            if data.get("data_feed_interrupted") or (
                                "Data feed interrupted" in str(data.get("filter_reason", ""))
                            ):
                                st.error(
                                    "🚨 Data feed interrupted. No signal generated while feeds are stale."
                                )
                            render_filtered_signal(data)
                            render_signal_quality(data)
                        else:
                            st.success(f"✅ Signal: {data.get('signal', 'N/A')} for {signal_symbol}")
                            render_signal_quality(data)
                            render_receipt(str(data.get("receipt", "")))
                            st.json(data.get("indicators", {}))
                    else:
                        st.error(f"API error {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                st.error(f"Signal generation error: {str(e)[:80]}")

    st.markdown("### Pending Signal Queue")
    if api_ok:
        try:
            pending_payload = requests.get(
                f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS
            ).json()
            pending = pending_payload.get("signals", []) if isinstance(pending_payload, dict) else []
            if pending:
                pending_df = pd.DataFrame(pending)
                if "instrument" in pending_df.columns:
                    pending_df = pending_df[pending_df["instrument"].isin(asset_symbols)]
                st.dataframe(pending_df, use_container_width=True, hide_index=True)
            else:
                st.info("No pending signals right now.")
        except Exception as e:
            st.error(f"Pending signal panel error: {str(e)[:80]}")

with tab3:
    st.subheader("Approvals")
    st.caption("Human review step before execution. Aletheia receipts remain visible for traceability.")
    if api_ok:
        try:
            signals = (
                requests.get(f"{API_BASE}/v1/signals/pending", timeout=REQUEST_TIMEOUT_SECONDS)
                .json()
                .get("signals", [])
            )
            signals = [s for s in signals if str(s.get("instrument", "")) in asset_symbols]
            if signals:
                for i, sig in enumerate(signals):
                    with st.container(border=True):
                        st.markdown(
                            f"**#{i + 1}: {sig.get('agent_type', 'N/A').upper()} • {sig.get('instrument', 'N/A')}**"
                        )
                        c1, c2, c3 = st.columns([1, 1, 1])
                        entry_price = c1.number_input(
                            "Entry Price",
                            min_value=0.0001,
                            value=100.0,
                            key=f"appr_entry_{sig.get('signal_id', i)}",
                        )
                        qty = c2.number_input(
                            "Quantity",
                            min_value=0.01,
                            value=1.0,
                            step=0.01,
                            key=f"appr_qty_{sig.get('signal_id', i)}",
                        )
                        approve_clicked = c3.button(
                            "Approve",
                            key=f"approve_{sig.get('signal_id', i)}",
                            type="primary",
                            use_container_width=True,
                        )
                        reject_clicked = c3.button(
                            "Reject",
                            key=f"reject_{sig.get('signal_id', i)}",
                            use_container_width=True,
                        )

                        if approve_clicked:
                            resp = requests.post(
                                f"{API_BASE}/v1/signals/approve",
                                json={
                                    "signal_id": sig.get("signal_id"),
                                    "entry_price": entry_price,
                                    "qty": qty,
                                },
                                timeout=REQUEST_TIMEOUT_SECONDS,
                            )
                            if resp.status_code == 200:
                                st.success("Signal approved and converted to order.")
                                st.rerun()
                            else:
                                st.error(f"Approve failed: {resp.text[:120]}")

                        if reject_clicked:
                            resp = requests.post(
                                f"{API_BASE}/v1/signals/reject",
                                json={"signal_id": sig.get("signal_id")},
                                timeout=REQUEST_TIMEOUT_SECONDS,
                            )
                            if resp.status_code == 200:
                                st.warning("Signal rejected.")
                                st.rerun()
                            else:
                                st.error(f"Reject failed: {resp.text[:120]}")

                        render_receipt(str(sig.get("receipt", "")))
            else:
                st.success("No pending approvals in this market mode.")
        except Exception as e:
            st.error(f"Approvals panel error: {str(e)[:90]}")

with tab4:
    st.subheader("Backtest")
    st.caption("One-click backtesting aligned to your selected strategy preset and risk profile.")

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            symbol_text = st.text_input("Symbols", value=",".join(asset_symbols))
            strategy_name = st.selectbox("Engine Strategy", ["macd_rsi"], help="Execution engine")
            timeframe = st.selectbox("Timeframe", ["15m", "1h", "4h", "1d"], index=1)
        with c2:
            raw_start = st.date_input("Start", value=datetime(2023, 1, 1), key="bt_start")
            raw_end = st.date_input("End", value=datetime(2025, 1, 1), key="bt_end")
            start_date = normalize_date_input(raw_start)
            end_date = normalize_date_input(raw_end)
            initial_cash = st.number_input(
                "Initial Cash", min_value=1000.0, value=100000.0, step=1000.0
            )
        with c3:
            commission_bps = st.number_input("Commission (bps)", min_value=0.0, value=2.0, step=0.1)
            slippage_bps = st.number_input("Slippage (bps)", min_value=0.0, value=1.0, step=0.1)
            spread_bps = st.number_input("Spread (bps)", min_value=0.0, value=1.5, step=0.1)
            risk_per_trade_decimal = float(risk_per_trade) / 100.0

    if st.button("▶ Run Backtest", type="primary", use_container_width=True):
        symbols = [s.strip() for s in symbol_text.split(",") if s.strip()]
        cfg = BacktestConfig(
            symbols=symbols,
            timeframe=timeframe,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            strategy=strategy_name,
            strategy_params={"risk_per_trade": risk_per_trade_decimal},
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            spread_bps=spread_bps,
            risk_per_trade=risk_per_trade_decimal,
        )

        with st.spinner("Running backtest..."):
            engine = BacktestEngine()
            report = engine.run(cfg)
            st.session_state["bt_payload"] = {"engine": engine, "report": report, "config": cfg}

    bt_payload = cast(dict[str, Any] | None, st.session_state.get("bt_payload"))
    if isinstance(bt_payload, dict):
        page_engine = cast(BacktestEngine, bt_payload["engine"])
        report = cast(Any, bt_payload["report"])
        p = report.portfolio_metrics

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sharpe", f"{p.get('sharpe', 0.0):.2f}")
        m2.metric("Sortino", f"{p.get('sortino', 0.0):.2f}")
        m3.metric("Calmar", f"{p.get('calmar', 0.0):.2f}")
        m4.metric("Max DD", f"{p.get('max_drawdown', 0.0) * 100:.2f}%")

        symbols_available = list(report.results.keys())
        if symbols_available:
            selected = st.selectbox("Inspect Symbol", symbols_available)
            result = report.results[selected]
            lcol, rcol = st.columns(2)
            lcol.plotly_chart(page_engine.build_equity_curve_figure(result), use_container_width=True)
            rcol.plotly_chart(page_engine.build_drawdown_figure(result), use_container_width=True)
            render_monthly_heatmap(result.monthly_returns_heatmap, selected)
        else:
            st.info("No backtest result rows yet.")

with tab5:
    st.subheader("Settings / Options")
    st.caption("Advanced controls, strategy details, and integrations.")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Strategy Parameters**")
        st.write(f"Preset: **{selected_preset.get('name', 'Unknown')}**")
        st.write(
            f"Best Conditions: {selected_preset.get('best_market_conditions', 'Market dependent')}"
        )
        st.write(f"Risk Level: {selected_preset.get('risk_level', 'Unknown')}")
        st.caption(str(selected_preset.get("description", "")))
        defaults = selected_preset.get("default_parameters", {})
        if isinstance(defaults, dict) and defaults:
            st.json(defaults)
        st.info(str(selected_preset.get("expected_behavior", "No behavior notes.")))

    with col2:
        st.markdown("**Connections**")
        st.caption("Quick checks for data and venue connectivity.")
        if st.button("Test Coinbase Connection", type="primary", disabled=not api_ok):
            try:
                resp = requests.get(
                    f"{API_BASE}/v1/signals/crypto",
                    params={"symbol": "BTC-USD"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    st.success("Coinbase-style crypto signal route is reachable.")
                else:
                    st.error(f"Connection test failed ({resp.status_code})")
            except Exception as e:
                st.error(f"Connection test error: {str(e)[:80]}")

        if st.button("Test API Health"):
            ok, state = check_api()
            if ok:
                st.success(f"API healthy: {state}")
            else:
                st.error(f"API unhealthy: {state}")

        st.divider()
        st.markdown(
            "**Operational Profile**\n"
            f"- Aletheia Protection: {'Enabled' if aletheia_enabled else 'Disabled'}\n"
            f"- ELI5 Mode: {'Enabled' if eli5_mode else 'Disabled'}\n"
            f"- Scan Frequency: {scan_interval}\n"
            f"- Risk Per Trade: {risk_per_trade:.1f}%\n"
            f"- Max Daily Loss: {max_daily_loss:.1f}%"
        )
