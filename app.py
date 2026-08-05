from datetime import datetime
from pathlib import Path
import uuid
import pandas as pd
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh
from engine import snapshot,earnings,grade,chain,recs,manage_pro,income_summary,fmt_date,parse_ddmmyy,decision_checklist,checklist_summary

BASE=Path(__file__).resolve().parent
st.set_page_config(page_title='OIMS v1.0',page_icon='◢',layout='wide')
cfg=yaml.safe_load((BASE/'config.yaml').read_text())
st_autorefresh(interval=int(cfg['system']['auto_refresh_minutes'])*60000,limit=None,key='auto')
st.markdown("""
<style>
:root{
  --bg:#070B12;
  --sidebar:#0C1320;
  --card:#121B2B;
  --card2:#172236;
  --border:#33435F;
  --text:#FFFFFF;
  --muted:#C8D2E3;
  --blue:#3B82F6;
  --green:#36D17C;
}
.stApp,[data-testid="stAppViewContainer"]{
  background:var(--bg)!important;
  color:var(--text)!important;
}
.block-container{max-width:1500px;padding-top:1rem}
h1,h2,h3,h4,p,span,label,[data-testid="stMarkdownContainer"]{
  color:var(--text)!important;
}
.hero,.box{
  padding:20px 23px;
  border:1px solid var(--border);
  border-radius:18px;
  background:var(--card);
  margin-bottom:14px;
}
.hero *,.box *{color:#FFF!important}
.big{font-size:40px;font-weight:800}

/* Sidebar — dark background, pure white text */
section[data-testid="stSidebar"]{
  background:var(--sidebar)!important;
  border-right:1px solid #26344A!important;
}
section[data-testid="stSidebar"] *{
  color:#FFFFFF!important;
  opacity:1!important;
}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{
  color:#FFFFFF!important;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label{
  background:transparent!important;
  border-radius:10px!important;
  padding:8px 10px!important;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover{
  background:#17243A!important;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){
  background:var(--blue)!important;
}
section[data-testid="stSidebar"] button{
  background:#17243A!important;
  color:#FFFFFF!important;
  border:1px solid #40506B!important;
}
section[data-testid="stSidebar"] button *{color:#FFFFFF!important}

/* Metrics */
[data-testid="stMetric"]{
  border:1px solid var(--border);
  padding:14px;
  border-radius:14px;
  background:var(--card2);
  min-height:118px;
}
[data-testid="stMetric"] *{color:#FFFFFF!important}
[data-testid="stMetricLabel"] p{color:var(--muted)!important}
[data-testid="stMetricDelta"] *{opacity:1!important}

/* Tabs and table */
[data-baseweb="tab"] p{color:#DDE6F5!important;font-weight:650}
[data-baseweb="tab"][aria-selected="true"] p{color:#FFFFFF!important}
[data-testid="stDataFrame"]{border:1px solid var(--border);border-radius:12px;overflow:hidden}

/* All buttons, especially Download CSV */
.stButton button,
.stDownloadButton button{
  background:#1F5FBF!important;
  color:#FFFFFF!important;
  border:1px solid #60A5FA!important;
  font-weight:750!important;
}
.stButton button *,
.stDownloadButton button *{
  color:#FFFFFF!important;
  opacity:1!important;
}
.stButton button:hover,
.stDownloadButton button:hover{
  background:#256FD5!important;
}
[data-testid="stAlert"] p{color:#FFFFFF!important}

/* Inputs */
input, textarea{
  color:#111827!important;
}

.checklist-summary{
  padding:18px 20px;
  border:1px solid #3B4E6B;
  border-radius:16px;
  background:#111B2C;
  margin:12px 0 16px 0;
}
.checklist-title{font-size:22px;font-weight:800;color:#FFF!important}
.checklist-sub{font-size:15px;color:#CBD5E1!important;margin-top:6px}
</style>

""",unsafe_allow_html=True)

pos_path=BASE/'data/positions.csv';journal_path=BASE/'data/journal.csv'
pos=pd.read_csv(pos_path);journal=pd.read_csv(journal_path)

@st.cache_data(ttl=120,show_spinner=False)
def load(t,c):
 s=snapshot(t,c);g=grade(s,earnings(t,c),c)
 try:x=chain(t,c,s['spot']);r=recs(t,x,s,g,c);err=None
 except Exception as e:x=pd.DataFrame();r=pd.DataFrame();err=str(e)
 return s,g,x,r,err,datetime.now()

def save_all():
 pos.to_csv(pos_path,index=False);journal.to_csv(journal_path,index=False)

def normalize_recommendation_columns(df):
    """Support both legacy Chinese and current English engine column names."""
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    aliases = {
        '到期日': 'Expiry',
        '用途': 'Use Case',
        '每張Premium': 'Premium / Contract',
        '每Premium': 'Premium / Contract',
        'Premium': 'Premium / Contract',
    }
    for old, new in aliases.items():
        if old in out.columns and new not in out.columns:
            out = out.rename(columns={old: new})
    return out

page=st.sidebar.radio('Navigation',['Overview','Stocks','Journal','Settings'])
if st.sidebar.button('🔄 Refresh All Data',use_container_width=True):st.cache_data.clear();st.rerun()

if page=='Overview':
 inc=income_summary(journal,cfg)
 st.markdown("<div class='hero'><div>OPTIONS INCOME MANAGEMENT SYSTEM</div><div class='big'>Portfolio Overview</div><div>Never sacrifice long-term capital appreciation for short-term premium.</div></div>",unsafe_allow_html=True)
 c1,c2=st.columns(2)
 with c1:
  st.write(f"**Monthly Income: ${inc['monthly']:,.0f} / ${inc['monthly_target']:,.0f}**");st.progress(min(1.0,inc['monthly']/inc['monthly_target']) if inc['monthly_target'] else 0)
 with c2:
  st.write(f"**YTD Income: ${inc['ytd']:,.0f} / ${inc['annual_target']:,.0f}**");st.progress(min(1.0,inc['ytd']/inc['annual_target']) if inc['annual_target'] else 0)
 st.subheader("Today's Decisions")
 cols=st.columns(4)
 for col,t in zip(cols,cfg['stocks'].keys()):
  with col:
   try:
    s,g,x,r,e,ts=load(t,cfg);opened=int(pd.to_numeric(pos.loc[(pos.ticker==t)&(pos.status.astype(str).str.upper()=='OPEN'),'contracts'],errors='coerce').fillna(0).sum());cap=max(0,int(cfg['stocks'][t]['max_cc'])-opened);allowed=min(cap,g['max_new']);icon={'GREEN':'🟢','YELLOW':'🟡','RED':'🔴'}[g['label']]
    st.markdown(f"<div class='box'><h3>{t}</h3><div class='big'>{icon} {g['label']}</div><p>{cfg['stocks'][t]['income_role']}</p><p>Max New Today: <b>{allowed}</b></p><p>${s['spot']:.2f}</p></div>",unsafe_allow_html=True)
   except Exception as ex:st.error(f'{t}: {ex}')
 st.subheader('YTD Income by Stock')
 if inc['by_stock'].empty:st.info('No closed-trade history yet.')
 else:st.bar_chart(inc['by_stock'])

elif page=='Stocks':
 t=st.selectbox('Stock',list(cfg['stocks']))
 s,g,x,r,err,ts=load(t,cfg)
 r=normalize_recommendation_columns(r)
 icon={'GREEN':'🟢','YELLOW':'🟡','RED':'🔴'}[g['label']]
 checklist=decision_checklist(t,s,earnings(t,cfg),cfg)
 checklist_result=checklist_summary(checklist)

 st.markdown(f"<div class='hero'><div>{t} · {s['session']} · {ts:%d%m%y %H:%M}</div><div class='big'>{checklist_result['decision']}</div><div>{checklist_result['explanation']}</div></div>",unsafe_allow_html=True)

 st.subheader('Decision Checklist')
 decision_color={'CC SETUP VALID':'#22C55E','WAIT / CONSERVATIVE ONLY':'#F59E0B','NO NEW CC':'#EF4444','NO TRADE':'#EF4444'}.get(checklist_result['decision'],'#94A3B8')
 st.markdown(f"<div class='checklist-summary' style='border-left:6px solid {decision_color}'><div class='checklist-title'>{checklist_result['decision']}</div><div class='checklist-sub'>{checklist_result['explanation']}</div></div>",unsafe_allow_html=True)

 checklist_view=checklist.copy()
 checklist_view['Status']=checklist_view['Status'].map({'PASS':'✅ PASS','FAIL':'❌ FAIL','CAUTION':'⚠️ CAUTION','BLOCK':'🛑 BLOCK'}).fillna(checklist_view['Status'])
 st.dataframe(checklist_view[['Status','Condition','Actual','Required / Preferred','Importance']],hide_index=True,use_container_width=True)

 if checklist_result['hard_blockers']>0:
  blockers=checklist[checklist['Hard Blocker']==True]
  st.error('Trade blocked because: '+'; '.join(blockers['Condition'].astype(str).tolist()))
 elif checklist_result['decision']=='WAIT / CONSERVATIVE ONLY':
  st.warning('The setup is incomplete. Do not use a closer strike merely to reach the income target.')
 elif checklist_result['decision']=='CC SETUP VALID':
  st.success('The setup qualifies for contract selection. The contract must still pass Delta, OTM and liquidity checks.')

 a,b,c,d,e=st.columns(5)
 a.metric('Live / Extended',f"${s['spot']:.2f}",f"{s['day_pct']:+.2f}% vs {s.get('reference_close_label','Close')}")
 b.metric('RSI',f"{s['rsi']:.1f}")
 c.metric('VIX',f"{s['vix']:.1f}")
 d.metric('Distance to 60D High',f"{s['dist_high_pct']:.1f}%")
 e.metric('Quote Age',f"{s['quote_age_minutes']:.0f} min")

 tabs=st.tabs(['New CC','Existing CC','Open / Close Trade','Decision Logic'])
 with tabs[0]:
  if checklist_result['hard_blockers']>0:
   st.error('No contract recommendation is shown because the setup has a hard blocker.')
  elif err:st.warning(err)
  elif r.empty:st.warning('No contract currently meets the Delta, OTM and liquidity rules.')
  else:
   vv=normalize_recommendation_columns(r)
   required={'Expiry','Strike','DTE','Delta','OTM %','Spread %','OI','Premium / Contract'}
   missing=required.difference(vv.columns)
   if missing:
    st.error("Recommendation data is missing required fields: " + ", ".join(sorted(missing)))
    st.caption("Refresh the app after both app.py and engine.py have finished deploying.")
   else:
    vv['Expiry']=vv['Expiry'].apply(fmt_date)
    for _,q in vv.head(g['max_new']).iterrows():
     reason=(f"Delta {q['Delta']:.2f} fits the strategy; "
             f"OTM {q['OTM %']:.1f}%; Spread {q['Spread %']:.1f}%; OI {int(q['OI'])}")
     st.markdown(
      f"<div class='box'><h3>APPROVE: {q['Expiry']} ${q['Strike']:.0f}C</h3>"
      f"<p>DTE {int(q['DTE'])} · Delta {q['Delta']:.2f} · "
      f"Premium approximately ${q['Premium / Contract']:.0f}</p>"
      f"<p><b>Reason:</b> {reason}</p></div>",
      unsafe_allow_html=True
     )
    st.dataframe(vv,hide_index=True,use_container_width=True)
 with tabs[1]:
  managed=manage_pro(pos,t,x,s['spot'],cfg);show=['position_id','purpose','strategy_tag','reason','Expiry (DDMMYY)','Days Remaining','strike','contracts','credit_received','Live Mark','Mark Source','Profit %','Unrealized P/L','Current Delta','System Action','Action Reason']
  st.dataframe(managed[[z for z in show if z in managed]],hide_index=True,use_container_width=True)
  st.caption('Live Mark, Profit and Delta update automatically from the option chain whenever you refresh. The saved fallback mark is used only when a live contract quote is unavailable.')
 with tabs[2]:
  left,right=st.columns(2)
  with left:
   st.subheader('Open / Update CC')
   ids=pos.loc[pos.ticker==t,'position_id'].tolist();pid=st.selectbox('Position ID',ids)
   row=pos[pos.position_id==pid].iloc[0];expiry=st.text_input('Expiry DDMMYY',value=str(row.expiry) if pd.notna(row.expiry) else '');strike=st.number_input('Strike',value=float(row.strike) if pd.notna(row.strike) else 0.0);contracts=st.number_input('Contracts',min_value=1,value=int(row.contracts) if pd.notna(row.contracts) else 1);credit=st.number_input('Premium Received (per share)',value=float(row.credit_received) if pd.notna(row.credit_received) else 0.0,step=.01);mark=st.number_input('Fallback Mark (used only if live option quote is unavailable)',value=float(row.current_mark) if pd.notna(row.current_mark) else credit,step=.01);purpose=st.selectbox('Purpose',['Trading','Income','Defensive'],index=['Trading','Income','Defensive'].index(str(row.purpose)) if str(row.purpose) in ['Trading','Income','Defensive'] else 1);tag=st.selectbox('Strategy Tag',['Earnings','Income','Momentum','Defensive','High IV','Resistance']);reason=st.text_input('Why am I selling this?',value=str(row.reason) if pd.notna(row.reason) else '');event_done=st.checkbox('Event completed / Alpha disappeared',value=str(row.event_completed).lower() in ['true','1','yes'])
   if st.button('Save Position',type='primary'):
    if not reason.strip():st.error('An entry reason is required.')
    else:
     i=pos.index[pos.position_id==pid][0];new_open=str(pos.loc[i,'status']).upper()!='OPEN';pos.loc[i,['status','expiry','strike','contracts','credit_received','current_mark','opened_date','purpose','strategy_tag','reason','event_completed']]=['OPEN',fmt_date(expiry),strike,contracts,credit,mark,datetime.now().strftime('%d%m%y'),purpose,tag,reason,event_done]
     if new_open:
      journal.loc[len(journal)]={'trade_id':str(uuid.uuid4())[:8].upper(),'open_date':datetime.now().strftime('%d%m%y'),'close_date':'','ticker':t,'expiry':fmt_date(expiry),'strike':strike,'contracts':contracts,'purpose':purpose,'strategy_tag':tag,'reason':reason,'credit_received':credit,'debit_paid':'','realized_pnl':'','status':'OPEN','entry_grade':g['label'],'entry_score':g['score'],'notes':pid}
     save_all();st.cache_data.clear();st.success('Position saved. Live Mark, Profit and Delta will refresh automatically.');st.rerun()
  with right:
   st.subheader('Close CC')
   open_ids=pos.loc[(pos.ticker==t)&(pos.status.astype(str).str.upper()=='OPEN'),'position_id'].tolist()
   if not open_ids:st.info('There are no open covered calls.')
   else:
    close_id=st.selectbox('Close Position ID',open_ids);debit=st.number_input('Buy to Close Price (per share)',min_value=0.0,step=.01)
    if st.button('Save Close Trade'):
     i=pos.index[pos.position_id==close_id][0];rr=pos.loc[i];pnl=(float(rr.credit_received)-debit)*float(rr.contracts)*100;ji=journal.index[(journal.status.astype(str).str.upper()=='OPEN')&(journal.notes.astype(str)==close_id)]
     if len(ji):journal.loc[ji[-1],['close_date','debit_paid','realized_pnl','status']]=[datetime.now().strftime('%d%m%y'),debit,pnl,'CLOSED']
     pos.loc[i,['status','expiry','strike','credit_received','current_mark','opened_date','reason','event_completed','notes']]=['EMPTY','','','','','','',False,''];save_all();st.cache_data.clear();st.success(f'Position closed. Realized P/L ${pnl:,.0f}');st.rerun()
 with tabs[3]:
  for z in g['blockers']:st.error(z)
  for z in g['positive']:st.success(z)
  for z in g['caution']:st.warning(z)
  st.markdown("<div class='box'><h3>Core Exit Logic</h3><p><b>Trading CC：</b>Close when the event is complete, profit is at least 60%, or Delta is below 0.05.</p><p><b>Income CC 7–10 DTE：</b>60%: Consider BTC; 70%: BTC Now.</p><p><b>Income CC 30–180 DTE：</b>Delta below 0.20: Ignore; 0.20–0.29: Watch; 0.30–0.39: Prepare Roll; 0.40+: Priority Roll / Close.</p></div>",unsafe_allow_html=True)

elif page=='Journal':
 inc=income_summary(journal,cfg);c1,c2=st.columns(2);c1.metric('Monthly Realized Income',f"${inc['monthly']:,.0f}");c2.metric('YTD Realized Income',f"${inc['ytd']:,.0f}");st.dataframe(journal,hide_index=True,use_container_width=True);st.download_button('Download Journal CSV',journal.to_csv(index=False).encode(),file_name='oims_journal.csv')
else:
 st.header('Settings / Playbook');st.write(f"Monthly target：${cfg['system']['monthly_income_target']:,.0f}");st.write(f"Annual target：${cfg['system']['annual_income_target']:,.0f}");st.markdown('1. Every Covered Call must have a Purpose.  \n2. Exit because the original reason has disappeared.  \n3. Income target is a guide, not a reason to accept bad risk.  \n4. Long-term capital appreciation ranks above short-term premium.');st.warning('Streamlit local CSV files may reset after a cloud restart. Download the journal regularly until permanent storage is connected.')
