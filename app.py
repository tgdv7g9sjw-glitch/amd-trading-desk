from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh

from engine import (
    chain,
    earnings,
    fmt_date,
    manage_pro,
    parse_ddmmyy,
    simple_cc_decision,
    snapshot,
)

BASE = Path(__file__).resolve().parent
st.set_page_config(
    page_title="CC Decision System",
    page_icon="◢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
st_autorefresh(
    interval=int(cfg["system"]["auto_refresh_minutes"]) * 60000,
    limit=None,
    key="auto_refresh",
)

st.markdown(
    """
<style>
:root{
  --bg:#070B12;--card:#111A2A;--border:#33435F;
  --text:#FFFFFF;--muted:#C7D2E3;
  --green:#22C55E;--yellow:#F59E0B;--red:#EF4444;--blue:#2563EB;
}
.stApp,[data-testid="stAppViewContainer"]{background:var(--bg)!important;color:var(--text)!important}
.block-container{max-width:1380px;padding-top:1rem}
h1,h2,h3,p,span,label,[data-testid="stMarkdownContainer"]{color:#FFF!important}
.header,.decision-card,.holding-card{
  border:1px solid var(--border);border-radius:18px;background:var(--card);
  padding:20px 24px;margin-bottom:16px
}
.header-title{font-size:30px;font-weight:800}
.muted{color:var(--muted)!important}
.light{font-size:44px;font-weight:900;line-height:1.15}
.action{font-size:23px;font-weight:800;margin-top:6px}
.check-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}
.check{border:1px solid var(--border);border-radius:14px;padding:15px;background:#162238;min-height:120px}
.check-title{font-size:14px;font-weight:800;color:#DCE6F5!important}
.check-detail{font-size:15px;margin-top:9px;color:#FFF!important}
.holding-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.holding-title{font-size:21px;font-weight:850}
.holding-action{font-size:25px;font-weight:900;margin:8px 0}
.data-line{color:#D7E0EF!important;margin:4px 0}
[data-testid="stMetric"]{border:1px solid var(--border);padding:13px;border-radius:13px;background:#162238}
[data-testid="stMetric"] *{color:#FFF!important}
.stButton button{background:var(--blue)!important;color:#FFF!important;border:1px solid #60A5FA!important}
.stButton button *{color:#FFF!important}
[data-testid="stAlert"] p{color:#FFF!important}
input,textarea{color:#111827!important}
@media(max-width:900px){
 .check-grid,.holding-grid{grid-template-columns:1fr}
 .light{font-size:34px}
}
</style>
""",
    unsafe_allow_html=True,
)

positions_path = BASE / "data" / "positions.csv"
positions = pd.read_csv(positions_path)

@st.cache_data(ttl=120, show_spinner=False)
def load_stock(ticker, config):
    snap = snapshot(ticker, config)
    earn = earnings(ticker, config)
    try:
        options = chain(ticker, config, snap["spot"])
        error = None
    except Exception as exc:
        options = pd.DataFrame()
        error = str(exc)
    decision = simple_cc_decision(ticker, snap, earn, config)
    return snap, earn, options, decision, error, datetime.now()

top_a, top_b, top_c = st.columns([1.2, 1.2, 3])
with top_a:
    ticker = st.selectbox("Stock", list(cfg["stocks"].keys()))
with top_b:
    refresh = st.button("🔄 Refresh Data", type="primary", use_container_width=True)
with top_c:
    st.caption("The page refreshes automatically every 5 minutes while open.")

if refresh:
    st.cache_data.clear()
    st.rerun()

with st.spinner(f"Updating {ticker} price and option data..."):
    snap, earn, options, decision, option_error, fetched = load_stock(ticker, cfg)

colour = {
    "GREEN": "#22C55E",
    "YELLOW": "#F59E0B",
    "RED": "#EF4444",
}[decision["light"]]
symbol = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[decision["light"]]

st.markdown(
    f"""
<div class="header">
  <div class="muted">{ticker} · {snap['session']} · Updated {fetched:%d%m%y %H:%M}</div>
  <div class="light" style="color:{colour}!important">{symbol} {decision['light']}</div>
  <div class="action">{decision['action']}</div>
  <div class="muted" style="margin-top:9px">{decision['conclusion']}</div>
</div>
""",
    unsafe_allow_html=True,
)

checks_html = '<div class="check-grid">'
for item in decision["checks"]:
    icon = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "❌"}[item["status"]]
    checks_html += (
        '<div class="check">'
        f'<div class="check-title">{icon} {item["label"]}</div>'
        f'<div class="check-detail">{item["detail"]}</div>'
        "</div>"
    )
checks_html += "</div>"
st.markdown(checks_html, unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Live / Extended Price", f"${snap['spot']:.2f}", f"{snap['day_pct']:+.2f}%")
m2.metric("Previous / Reference Close", f"${snap['regular_close']:.2f}")
m3.metric("RSI", f"{snap['rsi']:.1f}")
m4.metric("VIX", f"{snap['vix']:.1f}")

st.divider()
st.header("Existing Covered Calls")

managed = manage_pro(positions, ticker, options, snap["spot"], cfg)
open_positions = managed[managed["status"].astype(str).str.upper() == "OPEN"].copy()

if open_positions.empty:
    st.info("No open covered calls have been entered for this stock.")
else:
    cards = '<div class="holding-grid">'
    for _, row in open_positions.iterrows():
        action = str(row.get("System Action", "WATCH"))
        action_colour = (
            "#EF4444"
            if ("BTC" in action or "ROLL" in action or "CLOSE" in action)
            else "#F59E0B"
            if "WATCH" in action or "CHECK" in action or "CONSIDER" in action
            else "#22C55E"
        )
        live_mark = row.get("Live Mark")
        delta = row.get("Current Delta")
        dte = row.get("Days Remaining")
        strike = row.get("strike")
        expiry = row.get("Expiry (DDMMYY)")
        purpose = row.get("purpose", "Income")
        reason = row.get("Action Reason", "")
        mark_text = "Unavailable" if pd.isna(live_mark) else f"${float(live_mark):.2f}"
        delta_text = "Unavailable" if pd.isna(delta) else f"{float(delta):.2f}"
        dte_text = "—" if pd.isna(dte) else str(int(dte))

        cards += f"""
<div class="holding-card">
  <div class="holding-title">{expiry} · ${float(strike):.0f}C</div>
  <div class="muted">{purpose} CC</div>
  <div class="holding-action" style="color:{action_colour}!important">{action}</div>
  <div class="data-line"><b>Current option price:</b> {mark_text}</div>
  <div class="data-line"><b>Delta:</b> {delta_text} &nbsp; <b>DTE:</b> {dte_text}</div>
  <div class="data-line"><b>Why:</b> {reason}</div>
</div>
"""
    cards += "</div>"
    st.markdown(cards, unsafe_allow_html=True)

if option_error:
    st.warning(
        "The live option chain is temporarily unavailable. Existing positions will use the saved fallback mark."
    )

with st.expander("Edit Holdings"):
    st.caption("This section is only for entering or correcting your existing positions.")
    stock_positions = positions[positions["ticker"] == ticker].copy()
    edited = st.data_editor(
        stock_positions,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=f"edit_{ticker}",
    )
    if st.button("Save Holdings", type="primary"):
        positions.loc[positions["ticker"] == ticker, edited.columns] = edited.values
        positions.to_csv(positions_path, index=False)
        st.cache_data.clear()
        st.success("Holdings saved.")
        st.rerun()

st.caption(
    "Yahoo option quotes may be delayed. Verify the option price and Delta with Futu or IB before trading."
)
