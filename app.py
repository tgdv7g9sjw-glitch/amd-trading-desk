from datetime import datetime
from pathlib import Path
import uuid
import pandas as pd
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh
from engine import snapshot,earnings,grade,chain,recs,manage_pro,income_summary,fmt_date,parse_ddmmyy

BASE=Path(__file__).resolve().parent
st.set_page_config(page_title='OIMS v1.0',page_icon='◢',layout='wide')
cfg=yaml.safe_load((BASE/'config.yaml').read_text())
st_autorefresh(interval=int(cfg['system']['auto_refresh_minutes'])*60000,limit=None,key='auto')
st.markdown("""<style>.stApp{background:#080B12;color:#F7F8FC}.block-container{max-width:1500px;padding-top:1rem}h1,h2,h3,p,span,label,[data-testid='stMarkdownContainer']{color:#F7F8FC}.hero,.box{padding:20px 23px;border:1px solid #2B3550;border-radius:18px;background:#111725;margin-bottom:14px}.hero *,.box *{color:#FFF!important}.big{font-size:40px;font-weight:800}[data-testid='stMetric']{border:1px solid #2B3550;padding:13px;border-radius:14px;background:#141B2B}[data-testid='stMetric'] *{color:#FFF!important}</style>""",unsafe_allow_html=True)

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

page=st.sidebar.radio('Menu',['Overview','Stocks','Journal','Settings'])
if st.sidebar.button('🔄 Refresh全部資料',use_container_width=True):st.cache_data.clear();st.rerun()

if page=='Overview':
 inc=income_summary(journal,cfg)
 st.markdown("<div class='hero'><div>OPTIONS INCOME MANAGEMENT SYSTEM</div><div class='big'>Portfolio Overview</div><div>Never sacrifice long-term capital appreciation for short-term premium.</div></div>",unsafe_allow_html=True)
 c1,c2=st.columns(2)
 with c1:
  st.write(f"**本月收入：${inc['monthly']:,.0f} / ${inc['monthly_target']:,.0f}**");st.progress(min(1.0,inc['monthly']/inc['monthly_target']) if inc['monthly_target'] else 0)
 with c2:
  st.write(f"**YTD收入：${inc['ytd']:,.0f} / ${inc['annual_target']:,.0f}**");st.progress(min(1.0,inc['ytd']/inc['annual_target']) if inc['annual_target'] else 0)
 st.subheader("Today's Decisions")
 cols=st.columns(4)
 for col,t in zip(cols,cfg['stocks'].keys()):
  with col:
   try:
    s,g,x,r,e,ts=load(t,cfg);opened=int(pd.to_numeric(pos.loc[(pos.ticker==t)&(pos.status.astype(str).str.upper()=='OPEN'),'contracts'],errors='coerce').fillna(0).sum());cap=max(0,int(cfg['stocks'][t]['max_cc'])-opened);allowed=min(cap,g['max_new']);icon={'GREEN':'🟢','YELLOW':'🟡','RED':'🔴'}[g['label']]
    st.markdown(f"<div class='box'><h3>{t}</h3><div class='big'>{icon} {g['label']}</div><p>{cfg['stocks'][t]['income_role']}</p><p>今日最多：<b>{allowed}張</b></p><p>${s['spot']:.2f}</p></div>",unsafe_allow_html=True)
   except Exception as ex:st.error(f'{t}: {ex}')
 st.subheader('YTD Income by Stock')
 if inc['by_stock'].empty:st.info('未有已平倉交易紀錄。')
 else:st.bar_chart(inc['by_stock'])

elif page=='Stocks':
 t=st.selectbox('股票',list(cfg['stocks']))
 s,g,x,r,err,ts=load(t,cfg);icon={'GREEN':'🟢','YELLOW':'🟡','RED':'🔴'}[g['label']]
 st.markdown(f"<div class='hero'><div>{t} · {s['session']} · {ts:%d%m%y %H:%M}</div><div class='big'>{icon} {g['label']} · {g['score']}/100</div><div>{g['action']}</div></div>",unsafe_allow_html=True)
 a,b,c,d,e=st.columns(5);a.metric('即時/盤前',f"${s['spot']:.2f}",f"{s['day_pct']:+.2f}%");b.metric('RSI',f"{s['rsi']:.1f}");c.metric('VIX',f"{s['vix']:.1f}");d.metric('距60日高',f"{s['dist_high_pct']:.1f}%");e.metric('報價Age',f"{s['quote_age_minutes']:.0f}分")
 tabs=st.tabs(['New CC','Existing CC','Open / Close Trade','Why'])
 with tabs[0]:
  if err:st.warning(err)
  elif r.empty:st.warning('今日冇合約同時符合Delta、OTM及流動性規則。')
  else:
   vv=r.copy();vv['到期日']=vv['到期日'].apply(fmt_date)
   for _,q in vv.head(g['max_new']).iterrows():
    reason=f"Delta {q['Delta']:.2f}符合策略；OTM {q['OTM %']:.1f}%；Spread {q['Spread %']:.1f}%；OI {q['OI']}"
    st.markdown(f"<div class='box'><h3>APPROVE：{q['到期日']} ${q['Strike']:.0f}C</h3><p>DTE {q['DTE']} · Delta {q['Delta']:.2f} · Premium約 ${q['每張Premium']:.0f}</p><p><b>原因：</b>{reason}</p></div>",unsafe_allow_html=True)
   st.dataframe(vv,hide_index=True,use_container_width=True)
 with tabs[1]:
  managed=manage_pro(pos,t,x,s['spot'],cfg);show=['position_id','purpose','strategy_tag','reason','Expiry (DDMMYY)','剩餘日數','strike','contracts','Profit %','Current Delta','System Action','Action Reason']
  st.dataframe(managed[[z for z in show if z in managed]],hide_index=True,use_container_width=True)
  st.caption('Current Mark及Event Completed可以在下面Open / Close Trade頁更新。')
 with tabs[2]:
  left,right=st.columns(2)
  with left:
   st.subheader('Open / Update CC')
   ids=pos.loc[pos.ticker==t,'position_id'].tolist();pid=st.selectbox('Position ID',ids)
   row=pos[pos.position_id==pid].iloc[0];expiry=st.text_input('Expiry DDMMYY',value=str(row.expiry) if pd.notna(row.expiry) else '');strike=st.number_input('Strike',value=float(row.strike) if pd.notna(row.strike) else 0.0);contracts=st.number_input('Contracts',min_value=1,value=int(row.contracts) if pd.notna(row.contracts) else 1);credit=st.number_input('Premium received（每股）',value=float(row.credit_received) if pd.notna(row.credit_received) else 0.0,step=.01);mark=st.number_input('Current mark（每股）',value=float(row.current_mark) if pd.notna(row.current_mark) else credit,step=.01);purpose=st.selectbox('Purpose',['Trading','Income','Defensive'],index=['Trading','Income','Defensive'].index(str(row.purpose)) if str(row.purpose) in ['Trading','Income','Defensive'] else 1);tag=st.selectbox('Strategy Tag',['Earnings','Income','Momentum','Defensive','High IV','Resistance']);reason=st.text_input('Why am I selling this?',value=str(row.reason) if pd.notna(row.reason) else '');event_done=st.checkbox('Event completed / Alpha disappeared',value=str(row.event_completed).lower() in ['true','1','yes'])
   if st.button('Save Position',type='primary'):
    if not reason.strip():st.error('必須填寫開倉原因。')
    else:
     i=pos.index[pos.position_id==pid][0];new_open=str(pos.loc[i,'status']).upper()!='OPEN';pos.loc[i,['status','expiry','strike','contracts','credit_received','current_mark','opened_date','purpose','strategy_tag','reason','event_completed']]=['OPEN',fmt_date(expiry),strike,contracts,credit,mark,datetime.now().strftime('%d%m%y'),purpose,tag,reason,event_done]
     if new_open:
      journal.loc[len(journal)]={'trade_id':str(uuid.uuid4())[:8].upper(),'open_date':datetime.now().strftime('%d%m%y'),'close_date':'','ticker':t,'expiry':fmt_date(expiry),'strike':strike,'contracts':contracts,'purpose':purpose,'strategy_tag':tag,'reason':reason,'credit_received':credit,'debit_paid':'','realized_pnl':'','status':'OPEN','entry_grade':g['label'],'entry_score':g['score'],'notes':pid}
     save_all();st.success('已儲存並更新History。');st.rerun()
  with right:
   st.subheader('Close CC')
   open_ids=pos.loc[(pos.ticker==t)&(pos.status.astype(str).str.upper()=='OPEN'),'position_id'].tolist()
   if not open_ids:st.info('目前冇Open CC。')
   else:
    close_id=st.selectbox('Close Position ID',open_ids);debit=st.number_input('Buy to Close price（每股）',min_value=0.0,step=.01)
    if st.button('Save Close Trade'):
     i=pos.index[pos.position_id==close_id][0];rr=pos.loc[i];pnl=(float(rr.credit_received)-debit)*float(rr.contracts)*100;ji=journal.index[(journal.status.astype(str).str.upper()=='OPEN')&(journal.notes.astype(str)==close_id)]
     if len(ji):journal.loc[ji[-1],['close_date','debit_paid','realized_pnl','status']]=[datetime.now().strftime('%d%m%y'),debit,pnl,'CLOSED']
     pos.loc[i,['status','expiry','strike','credit_received','current_mark','opened_date','reason','event_completed','notes']]=['EMPTY','','','','','','',False,''];save_all();st.success(f'已平倉，Realized P/L ${pnl:,.0f}');st.rerun()
 with tabs[3]:
  for z in g['blockers']:st.error(z)
  for z in g['positive']:st.success(z)
  for z in g['caution']:st.warning(z)
  st.markdown("<div class='box'><h3>核心退出邏輯</h3><p><b>Trading CC：</b>事件完成、Profit≥60%或Delta&lt;0.05，代表Alpha已完成。</p><p><b>Income CC 7–10 DTE：</b>60% Consider BTC；70% BTC Now。</p><p><b>Income CC 30–180 DTE：</b>Delta&lt;0.20 Ignore；0.20–0.29 Watch；0.30–0.39 Prepare Roll；≥0.40 Priority Roll/Close。</p></div>",unsafe_allow_html=True)

elif page=='Journal':
 inc=income_summary(journal,cfg);c1,c2=st.columns(2);c1.metric('本月已實現收入',f"${inc['monthly']:,.0f}");c2.metric('YTD已實現收入',f"${inc['ytd']:,.0f}");st.dataframe(journal,hide_index=True,use_container_width=True);st.download_button('Download Journal CSV',journal.to_csv(index=False).encode(),file_name='oims_journal.csv')
else:
 st.header('Settings / Playbook');st.write(f"Monthly target：${cfg['system']['monthly_income_target']:,.0f}");st.write(f"Annual target：${cfg['system']['annual_income_target']:,.0f}");st.markdown('1. Every Covered Call must have a Purpose.  \n2. Exit because the original reason has disappeared.  \n3. Income target is a guide, not a reason to accept bad risk.  \n4. Long-term capital appreciation ranks above short-term premium.');st.warning('Streamlit免費雲端CSV有機會重置。請定期下載Journal；下一版應接永久Database。')
