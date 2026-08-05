from pathlib import Path
from datetime import datetime
import yaml, pandas as pd, streamlit as st, plotly.graph_objects as go
from engine import get_snapshot, earnings_date, grade, option_chain, recommendations, position_actions

BASE=Path(__file__).resolve().parent
st.set_page_config(page_title="AMD Trading Desk",page_icon="◢",layout="wide",initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container{padding-top:1.2rem;max-width:1500px}.hero{padding:22px 26px;border:1px solid #252d42;border-radius:20px;background:linear-gradient(135deg,#111725 0%,#0b0f18 100%);margin-bottom:18px}
.big{font-size:52px;font-weight:800;line-height:1}.muted{color:#8f9bb3}.card{padding:18px;border:1px solid #252d42;border-radius:16px;background:#111725;height:100%}
[data-testid="stMetric"]{border:1px solid #252d42;padding:15px;border-radius:15px;background:#111725}
</style>""",unsafe_allow_html=True)
cfg=yaml.safe_load((BASE/"config.yaml").read_text(encoding="utf-8"))

@st.cache_data(ttl=900,show_spinner=False)
def load_all(cfg):
    snap=get_snapshot(cfg); earn=earnings_date(cfg); result=grade(snap,earn,cfg)
    chain=option_chain(cfg,snap["spot"]); recs=recommendations(chain,snap,result,cfg)
    return snap,result,chain,recs

try:
    with st.spinner("更新AMD、QQQ、SMH、VIX及Option Chain…"):
        snap,result,chain,recs=load_all(cfg)
except Exception as e:
    st.error(f"暫時未能抓取資料：{e}"); st.stop()

icon={"GREEN":"🟢","YELLOW":"🟡","RED":"🔴"}[result["label"]]
st.markdown(f"""<div class="hero"><div class="muted">AMD TRADING DESK · UPDATED {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<div style="display:flex;justify-content:space-between;align-items:end;gap:20px;flex-wrap:wrap">
<div><div style="font-size:22px;margin-top:10px">TODAY'S DECISION</div><div class="big">{icon} {result["label"]}</div></div>
<div style="text-align:right"><div class="muted">CC SCORE</div><div class="big">{result["score"]}<span style="font-size:20px"> /100</span></div></div></div>
<div style="font-size:19px;margin-top:14px">{result["action"]}</div></div>""",unsafe_allow_html=True)

a,b,c,d,e,f=st.columns(6)
a.metric("AMD",f"${snap['spot']:.2f}",f"{snap['day_pct']:+.2f}%")
b.metric("5日",f"{snap['week_pct']:+.1f}%")
c.metric("RSI 14",f"{snap['rsi']:.1f}")
d.metric("VIX",f"{snap['vix']:.1f}",f"{snap['vix_day_pct']:+.1f}%")
e.metric("距60日高",f"{snap['dist_high_pct']:.1f}%")
f.metric("今日最多新開",f"{result['max_new']} 張")

tab1,tab2,tab3,tab4=st.tabs(["今日決策","現有CC","交易日誌","設定與說明"])
with tab1:
    l,r=st.columns([1.55,1])
    with l:
        h=snap["history"].tail(150)
        fig=go.Figure()
        fig.add_trace(go.Candlestick(x=h.index,open=h.Open,high=h.High,low=h.Low,close=h.Close,name="AMD"))
        fig.add_trace(go.Scatter(x=h.index,y=h.EMA20,name="EMA20"))
        fig.add_trace(go.Scatter(x=h.index,y=h.EMA50,name="EMA50"))
        fig.update_layout(height=430,xaxis_rangeslider_visible=False,margin=dict(l=5,r=5,t=25,b=5),legend_orientation="h")
        st.plotly_chart(fig,use_container_width=True)
    with r:
        st.subheader("評分解釋")
        for x in result["blockers"]: st.error(x)
        for x in result["positive"]: st.success(x)
        for x in result["caution"]: st.warning(x)
        st.write("財報：", result["earnings"] or "Yahoo未能確認；可手動設定")
        st.write("市場趨勢：",f"QQQ {'✅' if snap['qqq_trend'] else '❌'} ｜ SMH {'✅' if snap['smh_trend'] else '❌'}")
    st.subheader("建議合約")
    if result["label"]=="RED": st.info("Red日不顯示任何Strike，避免被高Premium誘惑。")
    elif recs.empty: st.warning("冇合約同時符合20% OTM、Delta、流動性及Spread規則。今日寧願唔做。")
    else:
        view=recs.copy()
        for x in ["OTM %","Delta估算","Bid","Ask","Mid","每張Premium","IV %","Spread %"]: view[x]=view[x].round(2)
        st.dataframe(view,hide_index=True,use_container_width=True)
        st.caption("Green最多2張；Yellow最多1張。四行係候選用途，唔代表要一次過全部開倉。")

with tab2:
    path=BASE/"data/positions.csv"
    positions=pd.read_csv(path)
    edited=st.data_editor(positions,num_rows="fixed",use_container_width=True)
    c1,c2=st.columns([1,4])
    if c1.button("儲存倉位",type="primary"):
        try: edited.to_csv(path,index=False); st.success("已儲存。")
        except Exception: st.warning("雲端免費版檔案可能在重新啟動後重置；正式版可接Google Sheet。")
    managed=position_actions(edited,snap["spot"],cfg)
    st.dataframe(managed,hide_index=True,use_container_width=True)
    st.caption("credit_received及current_mark均以每股期權價輸入，例如收到$12.50就填12.50。")

with tab3:
    jpath=BASE/"data/journal.csv"; journal=pd.read_csv(jpath)
    new=st.data_editor(journal,num_rows="dynamic",use_container_width=True)
    if st.button("儲存交易日誌"):
        try: new.to_csv(jpath,index=False); st.success("已儲存。")
        except Exception: st.warning("雲端免費版重新啟動可能重置檔案。")
    if not new.empty and "realized_pnl" in new:
        pnl=pd.to_numeric(new.realized_pnl,errors="coerce")
        x1,x2,x3=st.columns(3)
        x1.metric("已實現CC收入",f"${pnl.sum():,.0f}")
        x2.metric("交易數",f"{pnl.notna().sum()}")
        x3.metric("平均每宗",f"${pnl.mean():,.0f}" if pnl.notna().any() else "—")

with tab4:
    st.markdown("""### 核心紀律
- Premium目標唔係硬性KPI；冇好價就零交易。
- 普通CC最少20% OTM。
- 最後兩張長期CC必須900+。
- Red禁止開新倉；Yellow最多1張；Green最多2張。
- 至少保留1張LEAPS完全冇CC。
- 40–50%利潤開始考慮BTC；60%優先BTC。
""")
    st.download_button("下載目前設定",data=(BASE/"config.yaml").read_bytes(),file_name="config.yaml")
    if st.button("立即重新抓取資料"): st.cache_data.clear(); st.rerun()
    st.caption("Yahoo/yfinance屬研究用途資料源。正式落單前必須在Futu或IB核對報價、Greeks及財報日期。")
