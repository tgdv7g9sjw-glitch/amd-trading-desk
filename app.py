from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh

from engine import (
    earnings_date,
    get_snapshot,
    grade,
    option_chain,
    portfolio_summary,
    position_actions,
    recommendations,
)

BASE = Path(__file__).resolve().parent
st.set_page_config(
    page_title="AMD Trading Desk V3",
    page_icon="◢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

AUTO_REFRESH_MINUTES = 5
st_autorefresh(
    interval=AUTO_REFRESH_MINUTES * 60 * 1000,
    limit=None,
    key="amd_auto_refresh",
)

st.markdown("""
<style>
.stApp,[data-testid="stAppViewContainer"]{background:#080B12;color:#F7F8FC}
.block-container{padding-top:1.05rem;max-width:1500px}
h1,h2,h3,h4,p,span,label,[data-testid="stMarkdownContainer"]{color:#F7F8FC}
.hero,.decision{padding:22px 25px;border:1px solid #2B3550;border-radius:20px;background:linear-gradient(135deg,#171F32,#0D121D);margin-bottom:16px}
.hero *,.decision *{color:#FFF!important}
.hero-label{color:#CBD3E5!important;font-size:13px;letter-spacing:.06em}
.big{font-size:48px;font-weight:800}
.decision-text{font-size:20px;font-weight:750;line-height:1.5}
[data-testid="stMetric"]{border:1px solid #2B3550;padding:14px 15px;border-radius:15px;background:#141B2B;min-height:115px}
[data-testid="stMetric"] *{color:#FFF!important}
[data-testid="stMetricLabel"] p{color:#CBD3E5!important;font-weight:650}
[data-baseweb="tab"] p{color:#DCE2F0!important;font-weight:650}
[data-testid="stAlert"] p{color:#FFF!important}
@media(max-width:800px){.big{font-size:34px}.decision-text{font-size:18px}}
</style>
""", unsafe_allow_html=True)

with open(BASE / "config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

@st.cache_data(ttl=120, show_spinner=False)
def load_market(config):
    snap = get_snapshot(config)
    result = grade(snap, earnings_date(config), config)
    option_error = None
    try:
        chain = option_chain(config, snap["spot"])
        recs = recommendations(chain, snap, result, config)
    except Exception as exc:
        chain, recs = pd.DataFrame(), pd.DataFrame()
        option_error = str(exc)
    return snap, result, chain, recs, option_error, datetime.now()

c1, c2, c3 = st.columns([1.35, 1, 3])
with c1:
    refresh = st.button("🔄 立即更新全部資料", type="primary", use_container_width=True)
with c2:
    st.caption(f"自動更新：每 {AUTO_REFRESH_MINUTES} 分鐘")
with c3:
    st.caption("頁面開住先會自動更新；按鈕會重抓價格、指標及Option Chain。")

if refresh:
    st.cache_data.clear()
    st.rerun()

try:
    with st.spinner("更新AMD、QQQ、SMH、VIX及Option Chain…"):
        snap, result, chain, recs, option_error, fetched_at = load_market(cfg)
except Exception as exc:
    st.error(f"資料抓取失敗：{exc}")
    st.stop()

positions_path = BASE / "data" / "positions.csv"
positions = pd.read_csv(positions_path)
managed = position_actions(positions, snap["spot"], cfg)
summary = portfolio_summary(positions, cfg, result)

icon = {"GREEN":"🟢","YELLOW":"🟡","RED":"🔴"}[result["label"]]
st.markdown(f"""
<div class="hero">
<div class="hero-label">AMD TRADING DESK V3 · {snap['session']} · FETCHED {fetched_at.strftime('%Y-%m-%d %H:%M:%S')}</div>
<div style="display:flex;justify-content:space-between;align-items:end;gap:20px;flex-wrap:wrap;margin-top:8px">
<div><div class="hero-label">TODAY'S DECISION</div><div class="big">{icon} {result['label']}</div></div>
<div style="text-align:right"><div class="hero-label">CC SCORE</div><div class="big">{result['score']}<span style="font-size:18px"> /100</span></div></div>
</div>
<div style="font-size:18px;margin-top:12px">{result['action']}</div>
</div>
""", unsafe_allow_html=True)

p1,p2,p3,p4,p5,p6 = st.columns(6)
p1.metric("LEAPS", f"{cfg['portfolio']['leaps_contracts']} 張")
p2.metric("已開CC", f"{summary['open_cc']} 張")
p3.metric("剩餘容量", f"{summary['remaining_capacity']} 張")
p4.metric("今日可再開", f"{summary['allowed_today']} 張")
p5.metric("已收Premium", f"${summary['total_credit']:,.0f}")
p6.metric("現有CC浮盈", f"${summary['floating_pnl']:,.0f}")

m1,m2,m3,m4,m5,m6 = st.columns(6)
m1.metric("AMD即時/盤前", f"${snap['spot']:.2f}", f"{snap['day_pct']:+.2f}% vs 收市")
m2.metric("上次收市", f"${snap['regular_close']:.2f}")
m3.metric("RSI 14", f"{snap['rsi']:.1f}")
m4.metric("VIX", f"{snap['vix']:.1f}", f"{snap['vix_day_pct']:+.1f}%")
m5.metric("距60日高", f"{snap['dist_high_pct']:.1f}%")
m6.metric("報價Age", f"{snap['quote_age_minutes']:.0f} 分鐘")

if snap["is_stale"]:
    st.warning("即時報價可能過舊，落單前請在Futu／IB核對。")

tab1, tab2, tab3, tab4 = st.tabs(
    ["決策中心", "Portfolio Manager", "交易日誌", "設定與說明"]
)

with tab1:
    if summary["allowed_today"] == 0:
        direct_advice = "今日唔應該再開新CC。"
    elif recs.empty:
        direct_advice = "今日雖有容量，但冇合約同時符合Delta、Strike及流動性規則。"
    else:
        chosen = recs.head(summary["allowed_today"])
        direct_advice = "；".join(
            f"{r['到期日']} ${r['Strike']:.0f}C｜Delta {r['Delta估算']:.2f}｜Premium約 ${r['每張Premium']:.0f}"
            for _, r in chosen.iterrows()
        )

    st.markdown(f"""
    <div class="decision">
    <div class="hero-label">今日最直接建議</div>
    <div class="decision-text">{direct_advice}</div>
    </div>
    """, unsafe_allow_html=True)

    left, right = st.columns([1.55,1])
    with left:
        h = snap["history"].tail(150)
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=h.index, open=h.Open, high=h.High, low=h.Low, close=h.Close, name="AMD"
        ))
        fig.add_trace(go.Scatter(x=h.index, y=h.EMA20, name="EMA20"))
        fig.add_trace(go.Scatter(x=h.index, y=h.EMA50, name="EMA50"))
        fig.update_layout(
            height=430,
            xaxis_rangeslider_visible=False,
            margin=dict(l=5,r=5,t=25,b=5),
            paper_bgcolor="#111725",
            plot_bgcolor="#111725",
            font=dict(color="#FFF"),
            xaxis=dict(gridcolor="#2A3347"),
            yaxis=dict(gridcolor="#2A3347"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("評分解釋")
        for x in result["blockers"]:
            st.error(x)
        for x in result["positive"]:
            st.success(x)
        for x in result["caution"]:
            st.warning(x)
        st.write("財報：", result["earnings"] or "未能確認")
        st.write("QQQ：", "✅" if snap["qqq_trend"] else "❌")
        st.write("SMH：", "✅" if snap["smh_trend"] else "❌")

    st.subheader("今日新開CC候選")
    if option_error:
        st.warning(f"Option Chain暫時抓取失敗：{option_error}")
    elif result["label"] == "RED":
        st.info("Red日不顯示Strike。")
    elif recs.empty:
        st.warning("沒有合約同時符合Delta、Strike及流動性規則。")
    else:
        view = recs.copy()
        for col in ["OTM %","Delta估算","Bid","Ask","Mid","每張Premium","IV %","Spread %"]:
            view[col] = view[col].round(2)
        st.dataframe(view, hide_index=True, use_container_width=True)

with tab2:
    st.subheader("現有Covered Calls")
    edited = st.data_editor(
        positions,
        num_rows="fixed",
        use_container_width=True,
        key="positions_editor",
    )

    if st.button("儲存CC倉位", type="primary"):
        edited.to_csv(positions_path, index=False)
        st.success("已儲存。")
        st.rerun()

    st.subheader("系統管理建議")
    st.dataframe(
        position_actions(edited, snap["spot"], cfg),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("""
**輸入方式**
- status：`OPEN` 或 `EMPTY`
- expiry：例如 `2026-08-21`
- strike：例如 `700`
- credit_received：開倉每股收到Premium，例如 `2.50`
- current_mark：目前每股期權價格，例如 `1.10`
""")

with tab3:
    journal_path = BASE / "data" / "journal.csv"
    journal = pd.read_csv(journal_path)
    new = st.data_editor(journal, num_rows="dynamic", use_container_width=True)

    if st.button("儲存交易日誌"):
        new.to_csv(journal_path, index=False)
        st.success("已儲存。")

    if not new.empty and "realized_pnl" in new.columns:
        pnl = pd.to_numeric(new["realized_pnl"], errors="coerce")
        j1,j2,j3 = st.columns(3)
        j1.metric("已實現CC收入", f"${pnl.sum():,.0f}")
        j2.metric("交易數", f"{pnl.notna().sum()}")
        j3.metric("平均每宗", f"${pnl.mean():,.0f}" if pnl.notna().any() else "—")

with tab4:
    st.markdown("""
### V3規則
- 5張LEAPS，最多4張CC，至少1張LEAPS完全不覆蓋。
- 系統先扣除已開CC，再根據今日Grade決定仲可開幾張。
- Green最多2張新CC；Yellow最多1張；Red零張。
- 普通CC最少20% OTM。
- 最後兩張長期CC必須900+。
- 40–50%利潤開始考慮BTC；60%優先BTC。
- 10日內且距Strike少於7%會出Roll Alert。
- 頁面開住時每5分鐘更新；可手動Refresh。
- Streamlit免費雲端重新啟動後，CSV有機會重置。正式長期使用應接Google Sheet或Supabase。
""")
