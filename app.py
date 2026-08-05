from datetime import datetime
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh
from engine import earnings_date,get_snapshot,grade,option_chain,position_actions,recommendations,top_recommendation

BASE = Path(__file__).resolve().parent
st.set_page_config(page_title="AMD Trading Desk",page_icon="◢",layout="wide",initial_sidebar_state="collapsed")
AUTO_REFRESH_MINUTES = 5
st_autorefresh(interval=AUTO_REFRESH_MINUTES*60*1000,limit=None,key="amd_auto_refresh")

st.markdown("""
<style>
.stApp,[data-testid="stAppViewContainer"]{background:#080B12;color:#F7F8FC}
.block-container{padding-top:1.1rem;max-width:1500px}
h1,h2,h3,h4,p,span,label,[data-testid="stMarkdownContainer"]{color:#F7F8FC}
.hero,.decision{padding:22px 25px;border:1px solid #2B3550;border-radius:20px;background:linear-gradient(135deg,#171F32,#0D121D);margin-bottom:16px}
.hero *,.decision *{color:#FFF!important}.hero-label{color:#CBD3E5!important;font-size:13px;letter-spacing:.06em}
.big{font-size:48px;font-weight:800}.decision-text{font-size:22px;font-weight:750;line-height:1.5}
[data-testid="stMetric"]{border:1px solid #2B3550;padding:14px 15px;border-radius:15px;background:#141B2B;min-height:120px}
[data-testid="stMetric"] *{color:#FFF!important}
[data-testid="stMetricLabel"] p{color:#CBD3E5!important;font-weight:650}
[data-baseweb="tab"] p{color:#DCE2F0!important;font-weight:650}
[data-testid="stAlert"] p{color:#FFF!important}
@media(max-width:800px){.big{font-size:34px}.decision-text{font-size:18px}}
</style>
""",unsafe_allow_html=True)

with open(BASE/"config.yaml","r",encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

@st.cache_data(ttl=120,show_spinner=False)
def load_all(config):
    snap = get_snapshot(config)
    result = grade(snap,earnings_date(config),config)
    option_error = None
    try:
        chain = option_chain(config,snap["spot"])
        recs = recommendations(chain,snap,result,config)
    except Exception as exc:
        chain,recs = pd.DataFrame(),pd.DataFrame()
        option_error = str(exc)
    return snap,result,chain,recs,option_error,datetime.now()

c1,c2,c3 = st.columns([1.3,1,3])
with c1:
    refresh = st.button("🔄 立即更新市場資料",type="primary",use_container_width=True)
with c2:
    st.caption(f"自動更新：每 {AUTO_REFRESH_MINUTES} 分鐘")
with c3:
    st.caption("頁面開住先會自動更新；按鈕可隨時強制重新抓取。")
if refresh:
    st.cache_data.clear()
    st.rerun()

try:
    with st.spinner("正在更新AMD、QQQ、SMH、VIX及Option Chain…"):
        snap,result,chain,recs,option_error,fetched_at = load_all(cfg)
except Exception as exc:
    st.error(f"暫時未能抓取資料：{exc}")
    st.stop()

icon={"GREEN":"🟢","YELLOW":"🟡","RED":"🔴"}[result["label"]]
st.markdown(f"""
<div class="hero">
<div class="hero-label">AMD TRADING DESK · {snap['session']} · FETCHED {fetched_at.strftime('%Y-%m-%d %H:%M:%S')}</div>
<div style="display:flex;justify-content:space-between;align-items:end;gap:20px;flex-wrap:wrap;margin-top:8px">
<div><div class="hero-label">TODAY'S DECISION</div><div class="big">{icon} {result['label']}</div></div>
<div style="text-align:right"><div class="hero-label">CC SCORE</div><div class="big">{result['score']}<span style="font-size:18px"> /100</span></div></div>
</div>
<div style="font-size:18px;margin-top:12px">{result['action']}</div>
</div>
""",unsafe_allow_html=True)

advice = top_recommendation(recs,result)
st.markdown(f"""
<div class="decision">
<div class="hero-label">今日最直接建議</div>
<div class="decision-text">{advice}</div>
</div>
""",unsafe_allow_html=True)

a,b,c,d,e,f = st.columns(6)
a.metric("AMD即時/盤前",f"${snap['spot']:.2f}",f"{snap['day_pct']:+.2f}% vs 上次收市")
b.metric("上次收市",f"${snap['regular_close']:.2f}")
c.metric("RSI 14",f"{snap['rsi']:.1f}")
d.metric("VIX",f"{snap['vix']:.1f}",f"{snap['vix_day_pct']:+.1f}%")
e.metric("距60日高",f"{snap['dist_high_pct']:.1f}%")
f.metric("今日最多新開",f"{result['max_new']} 張")

if snap["is_stale"]:
    st.warning(f"即時報價可能過舊：{snap['quote_age_minutes']:.0f}分鐘前。")
st.caption(f"報價來源：{snap['quote_source']}｜紐約時間：{snap['quote_time_ny'].strftime('%Y-%m-%d %H:%M:%S')}")

tab1,tab2,tab3,tab4 = st.tabs(["今日決策","現有CC","交易日誌","設定與說明"])
with tab1:
    left,right = st.columns([1.55,1])
    with left:
        h=snap["history"].tail(150)
        fig=go.Figure()
        fig.add_trace(go.Candlestick(x=h.index,open=h.Open,high=h.High,low=h.Low,close=h.Close,name="AMD"))
        fig.add_trace(go.Scatter(x=h.index,y=h.EMA20,name="EMA20"))
        fig.add_trace(go.Scatter(x=h.index,y=h.EMA50,name="EMA50"))
        fig.update_layout(height=430,xaxis_rangeslider_visible=False,margin=dict(l=5,r=5,t=25,b=5),
                          paper_bgcolor="#111725",plot_bgcolor="#111725",font=dict(color="#FFF"),
                          xaxis=dict(gridcolor="#2A3347"),yaxis=dict(gridcolor="#2A3347"))
        st.plotly_chart(fig,use_container_width=True)
    with right:
        st.subheader("評分解釋")
        for x in result["blockers"]: st.error(x)
        for x in result["positive"]: st.success(x)
        for x in result["caution"]: st.warning(x)
        st.write("財報：",result["earnings"] or "未能確認")
        st.write("市場趨勢：",f"QQQ {'✅' if snap['qqq_trend'] else '❌'} ｜ SMH {'✅' if snap['smh_trend'] else '❌'}")

    st.subheader("建議CC明細")
    if option_error:
        st.warning(f"Option Chain暫時抓取失敗：{option_error}")
    elif result["label"]=="RED":
        st.info("Red日不顯示Strike。")
    elif recs.empty:
        st.warning("沒有合約同時符合Delta、Strike及流動性規則。")
    else:
        view=recs.copy()
        for col in ["OTM %","Delta估算","Bid","Ask","Mid","每張Premium","IV %","Spread %"]:
            view[col]=view[col].round(2)
        st.dataframe(view,hide_index=True,use_container_width=True)

with tab2:
    path=BASE/"data/positions.csv"
    positions=pd.read_csv(path)
    edited=st.data_editor(positions,num_rows="fixed",use_container_width=True)
    if st.button("儲存倉位",type="primary"):
        edited.to_csv(path,index=False);st.success("已儲存。")
    st.dataframe(position_actions(edited,snap["spot"],cfg),hide_index=True,use_container_width=True)

with tab3:
    path=BASE/"data/journal.csv"
    journal=pd.read_csv(path)
    new=st.data_editor(journal,num_rows="dynamic",use_container_width=True)
    if st.button("儲存交易日誌"):
        new.to_csv(path,index=False);st.success("已儲存。")

with tab4:
    st.markdown("""
### 更新及盤前邏輯
- 打開網頁時抓一次。
- 頁面開住時每5分鐘自動更新。
- 按「立即更新市場資料」可強制更新。
- 盤前／盤後價用1分鐘extended-hours bar嘗試抓取。
- RSI、EMA、趨勢仍使用正常交易時段日線，避免薄成交扭曲。
- 盤前Grade屬暫定，開市後要再Refresh。
- Yahoo資料可能延遲，落單前要在Futu／IB核對。
""")
