from __future__ import annotations
from datetime import date, datetime, time
from math import erf, log, sqrt
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
NY=ZoneInfo("America/New_York")
def cdf(x): return 0.5*(1+erf(x/sqrt(2)))
def delta_est(s,k,t,r,iv):
    if min(s,k,t,iv)<=0:return np.nan
    d1=(log(s/k)+(r+iv*iv/2)*t)/(iv*sqrt(t));return cdf(d1)
def hist(symbol):
    d=yf.Ticker(symbol).history(period="1y",auto_adjust=True)
    if d.empty:
        raise RuntimeError(f"{symbol} no data")
    return d

def session(now=None):
    n=now or datetime.now(NY)
    t=n.time()
    if n.weekday()>=5:
        return "CLOSED"
    if time(4)<=t<time(9,30):
        return "PRE-MARKET"
    if time(9,30)<=t<time(16):
        return "REGULAR"
    if time(16)<=t<time(20):
        return "AFTER-HOURS"
    return "CLOSED"

def completed_daily_bars(daily):
    """Exclude today's unfinished daily candle during regular trading."""
    if daily.empty:
        return daily
    now=datetime.now(NY)
    idx=pd.DatetimeIndex(daily.index)
    if idx.tz is None:
        last_date=idx[-1].date()
    else:
        last_date=idx[-1].tz_convert(NY).date()
    if session(now)=="REGULAR" and last_date==now.date() and len(daily)>=2:
        return daily.iloc[:-1].copy()
    return daily.copy()

def reference_close(daily):
    """
    Correct comparison base:
    PRE/REGULAR -> previous completed regular-session close.
    AFTER-HOURS -> today's completed close.
    CLOSED -> latest completed close.
    """
    if daily.empty:
        raise RuntimeError("No daily data")
    now=datetime.now(NY)
    current_session=session(now)
    idx=pd.DatetimeIndex(daily.index)
    last_date=(idx[-1].date() if idx.tz is None else idx[-1].tz_convert(NY).date())

    if current_session=="REGULAR" and last_date==now.date() and len(daily)>=2:
        return float(daily["Close"].iloc[-2]), "Previous close"
    return float(daily["Close"].iloc[-1]), (
        "Today close" if current_session=="AFTER-HOURS" and last_date==now.date()
        else "Previous close"
    )

def quote(symbol,daily):
    base_close,base_label=reference_close(daily)
    price=np.nan
    qt=None
    src="daily fallback"
    try:
        d=yf.Ticker(symbol).history(
            period="5d",interval="1m",prepost=True,auto_adjust=False
        ).dropna(subset=["Close"])
        if not d.empty:
            price=float(d.Close.iloc[-1])
            qt=pd.Timestamp(d.index[-1]).to_pydatetime()
            src="1m extended-hours"
    except Exception:
        pass

    if not np.isfinite(price):
        try:
            candidate=getattr(yf.Ticker(symbol).fast_info,"last_price",None)
            if candidate is not None:
                price=float(candidate)
                qt=datetime.now(NY)
                src="fast_info"
        except Exception:
            pass

    if not np.isfinite(price):
        price=base_close
        qt=datetime.now(NY)

    qt=qt.replace(tzinfo=NY) if qt.tzinfo is None else qt.astimezone(NY)
    age=max(0,(datetime.now(NY)-qt).total_seconds()/60)

    return dict(
        spot=price,
        regular_close=base_close,
        reference_close_label=base_label,
        day_pct=(price/base_close-1)*100 if base_close else np.nan,
        session=session(),
        quote_time_ny=qt,
        quote_age_minutes=age,
        quote_source=src,
        is_stale=age>20 and session() in {"PRE-MARKET","REGULAR","AFTER-HOURS"},
    )

def snapshot(ticker,cfg):
    s=cfg["stocks"][ticker]
    stock_raw=hist(ticker)
    stock=completed_daily_bars(stock_raw)
    bench=completed_daily_bars(hist(s["benchmark"]))
    sector=completed_daily_bars(hist(s["sector_etf"]))
    vix=completed_daily_bars(hist(cfg["vix_ticker"]))

    c=stock.Close
    diff=c.diff()
    g=diff.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    l=(-diff.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=100-100/(1+g/l.replace(0,np.nan))
    e20=c.ewm(span=20,adjust=False).mean()
    e50=c.ewm(span=50,adjust=False).mean()
    ret=c.pct_change()
    run=0
    for x in ret.dropna().iloc[::-1]:
        if x>0:
            run+=1
        else:
            break

    q=quote(ticker,stock_raw)
    return {
        **q,
        'ticker':ticker,
        'week_pct':float(c.pct_change(5).iloc[-1]*100),
        'rsi':float(rsi.iloc[-1]),
        'ema20':float(e20.iloc[-1]),
        'ema50':float(e50.iloc[-1]),
        'dist_high_pct':float((stock.High.tail(60).max()/q['spot']-1)*100),
        'benchmark_trend':bool(
            bench.Close.iloc[-1]>bench.Close.ewm(span=20,adjust=False).mean().iloc[-1]
        ),
        'sector_trend':bool(
            sector.Close.iloc[-1]>sector.Close.ewm(span=20,adjust=False).mean().iloc[-1]
        ),
        'vix':float(vix.Close.iloc[-1]),
        'vix_day_pct':float(vix.Close.pct_change().iloc[-1]*100),
        'up_run':run,
        'history':stock.assign(EMA20=e20,EMA50=e50),
    }
def earnings(ticker,cfg):
    m=str(cfg.get('manual_earnings',{}).get(ticker,'') or '').strip()
    if m:return pd.Timestamp(m).date()
    try:
        c=yf.Ticker(ticker).calendar
        if isinstance(c,dict):
            v=c.get('Earnings Date')
            if isinstance(v,(list,tuple)) and v:return pd.Timestamp(v[0]).date()
            if v is not None:return pd.Timestamp(v).date()
    except Exception:pass
    return None
def grade(s,earn,cfg):
    r=cfg['risk'];score=45;pos=[];warn=[];block=[];days=(earn-date.today()).days if earn else None
    if s['day_pct']<=r['hard_red_drop_pct']:block.append(f"跌 {s['day_pct']:.1f}%")
    if s['vix_day_pct']>=r['vix_jump_pct']:block.append('VIX急升')
    if not s['benchmark_trend'] and not s['sector_trend']:block.append('Benchmark及Sector同時轉弱')
    if s['day_pct']>=r['strong_rise_pct']:score+=20;pos.append('升超過5%')
    elif s['day_pct']>=2:score+=9;pos.append('即時升幅理想')
    elif s['day_pct']<0:score-=8;warn.append('即時價低於收市')
    if s['up_run']>=2:score+=9;pos.append(f"連升{s['up_run']}日")
    if s['dist_high_pct']<=4:score+=14;pos.append('接近60日高')
    elif s['dist_high_pct']<=8:score+=6;pos.append('距阻力不遠')
    if s['rsi']>=r['rsi_very_hot']:score+=15;pos.append('RSI極熱')
    elif s['rsi']>=r['rsi_hot']:score+=9;pos.append('RSI偏熱')
    elif s['rsi']<48:score-=9;warn.append('RSI偏低')
    score+=6 if s['sector_trend'] else -8;score+=4 if s['benchmark_trend'] else -5
    if days is not None and 0<=days<=2:score+=10;pos.append('財報前1–2日')
    if s['session']=='PRE-MARKET':warn.append('盤前Grade屬暫定')
    score=max(0,min(100,int(score)))
    if block:label,max_new='RED',0
    elif score>=74 and len(pos)>=3:label,max_new='GREEN',2
    elif score>=53:label,max_new='YELLOW',1
    else:label,max_new='RED',0
    return dict(label=label,score=score,max_new=max_new,action={'GREEN':'可以考慮開CC','YELLOW':'最多1張保守CC','RED':'禁止開新CC'}[label],positive=pos,caution=warn,blockers=block,earnings=earn)
def chain(ticker,cfg,spot):
    t=yf.Ticker(ticker);today=pd.Timestamp.today().normalize();frames=[]
    for exp in list(t.options):
        dte=int((pd.Timestamp(exp)-today).days)
        if dte<4 or dte>200:continue
        try:c=t.option_chain(exp).calls.copy()
        except Exception:continue
        if c.empty:continue
        c['expiry']=exp;c['dte']=dte;frames.append(c)
    if not frames:return pd.DataFrame()
    x=pd.concat(frames,ignore_index=True)
    for col in ['strike','bid','ask','lastPrice','impliedVolatility','openInterest','volume']:x[col]=pd.to_numeric(x[col],errors='coerce')
    x['mid']=np.where((x.bid>0)&(x.ask>0),(x.bid+x.ask)/2,x.lastPrice);x['spread']=np.where(x.mid>0,(x.ask-x.bid)/x.mid*100,np.nan);x['otm']=(x.strike/spot-1)*100;x['delta']=x.apply(lambda z:delta_est(spot,z.strike,max(z.dte/365,1/365),.04,z.impliedVolatility),axis=1)
    return x
def recs(ticker,x,s,g,cfg):
    if g['label']=='RED' or x.empty:return pd.DataFrame()
    sc=cfg['stocks'][ticker];n=cfg['new_cc'];b=x[(x.strike>=s['spot']*(1+sc['minimum_otm_pct']/100))&(x.openInterest.fillna(0)>=n['minimum_open_interest'])&(x.spread.fillna(999)<=n['maximum_spread_pct'])&(x.mid>0)].copy();rows=[]
    slots=[('7–12日',n['short_dte'],n['short_delta']),('21–40日',n['medium_dte'],n['medium_delta']),('90–180日',n['long_dte'],n['long_delta'])]
    if ticker=='AMD':slots.append(('AMD長期900+',n['long_dte'],n['long_delta']))
    for name,dtes,deltas in slots:
        z=b[b.dte.between(*dtes)&b.delta.between(*deltas)].copy()
        if name=='AMD長期900+':z=z[z.strike>=900]
        if z.empty:continue
        target=sum(deltas)/2;z['rank']=45*(1-(z.delta-target).abs()/max(target,.01)).clip(0,1)+30*(1-z.spread.clip(0,30)/30)+25*np.log1p(z.openInterest.fillna(0))/np.log(20000);q=z.sort_values(['rank','strike'],ascending=[False,False]).iloc[0]
        rows.append({'用途':name,'到期日':q.expiry,'DTE':int(q.dte),'Strike':float(q.strike),'OTM %':float(q.otm),'Delta':float(q.delta),'Bid':float(q.bid),'Ask':float(q.ask),'Mid':float(q.mid),'每張Premium':float(q.mid*100),'IV %':float(q.impliedVolatility*100),'OI':int(q.openInterest or 0),'Spread %':float(q.spread)})
    return pd.DataFrame(rows)
def manage(pos,ticker,x,spot,cfg):
    p=pos[pos.ticker.astype(str).str.upper()==ticker].copy();m=cfg['management'];actions=[];ds=[];profits=[];dtes=[]
    for _,r in p.iterrows():
        if str(r.status).upper()!='OPEN':actions.append('EMPTY');ds.append(np.nan);profits.append(np.nan);dtes.append(np.nan);continue
        exp=pd.to_datetime(r.expiry,errors='coerce');strike=pd.to_numeric(r.strike,errors='coerce');credit=pd.to_numeric(r.credit_received,errors='coerce');mark=pd.to_numeric(r.current_mark,errors='coerce');dte=(exp.normalize()-pd.Timestamp.today().normalize()).days if pd.notna(exp) else np.nan;profit=(credit-mark)/credit*100 if pd.notna(credit) and credit>0 and pd.notna(mark) else np.nan;z=x[(x.expiry.astype(str)==str(exp.date()))&(x.strike==strike)] if not x.empty and pd.notna(exp) and pd.notna(strike) else pd.DataFrame();delta=float(z.iloc[0].delta) if not z.empty else np.nan
        if pd.notna(dte) and dte<=10:
            a=f"BTC NOW｜Profit {profit:.0f}%" if pd.notna(profit) and profit>=70 else (f"CONSIDER BTC｜Profit {profit:.0f}%" if pd.notna(profit) and profit>=60 else 'HOLD｜未到60% Profit')
        elif pd.notna(dte) and 30<=dte<=180:
            a='CHECK DELTA' if pd.isna(delta) else (f"IGNORE / HOLD｜Delta {delta:.2f}" if delta<.20 else (f"WATCH｜Delta {delta:.2f}" if delta<.30 else (f"PREPARE ROLL｜Delta {delta:.2f}" if delta<.40 else f"PRIORITY ROLL / CLOSE｜Delta {delta:.2f}")))
        else:a='WATCH'
        actions.append(a);ds.append(delta);profits.append(profit);dtes.append(dte)
    p['DTE']=dtes;p['Current Delta']=ds;p['Profit %']=profits;p['System Action']=actions;return p

def parse_ddmmyy(v):
    if v is None or (isinstance(v,float) and np.isnan(v)): return pd.NaT
    t=str(v).strip(); d=''.join(c for c in t if c.isdigit())
    if len(d)==6:
        try:return pd.to_datetime(d,format='%d%m%y')
        except Exception:pass
    return pd.to_datetime(t,errors='coerce',dayfirst=True)

def fmt_date(v):
    t=parse_ddmmyy(v);return '' if pd.isna(t) else t.strftime('%d%m%y')

def income_summary(journal,cfg):
    j=journal.copy()
    if j.empty:return {'monthly':0.0,'ytd':0.0,'monthly_target':cfg['system']['monthly_income_target'],'annual_target':cfg['system']['annual_income_target'],'by_stock':pd.Series(dtype=float)}
    j['realized_pnl']=pd.to_numeric(j['realized_pnl'],errors='coerce').fillna(0);j['close_ts']=j['close_date'].apply(parse_ddmmyy);j=j[j.status.astype(str).str.upper()=='CLOSED']
    now=pd.Timestamp.today();m=j[(j.close_ts.dt.year==now.year)&(j.close_ts.dt.month==now.month)];y=j[j.close_ts.dt.year==now.year]
    return {'monthly':float(m.realized_pnl.sum()),'ytd':float(y.realized_pnl.sum()),'monthly_target':cfg['system']['monthly_income_target'],'annual_target':cfg['system']['annual_income_target'],'by_stock':y.groupby('ticker').realized_pnl.sum().sort_values(ascending=False)}

def manage_pro(pos,ticker,x,spot,cfg):
    p=pos[pos.ticker.astype(str).str.upper()==ticker].copy();m=cfg['management'];rows=[]
    for _,r in p.iterrows():
        if str(r.status).upper()!='OPEN':
            rows.append({**r.to_dict(),'Expiry (DDMMYY)':'','剩餘日數':np.nan,'Current Delta':np.nan,'Profit %':np.nan,'System Action':'EMPTY','Action Reason':'未開倉'});continue
        exp=parse_ddmmyy(r.expiry);strike=pd.to_numeric(r.strike,errors='coerce');credit=pd.to_numeric(r.credit_received,errors='coerce');mark=pd.to_numeric(r.current_mark,errors='coerce');dte=(exp.normalize()-pd.Timestamp.today().normalize()).days if pd.notna(exp) else np.nan;profit=(credit-mark)/credit*100 if pd.notna(credit) and credit>0 and pd.notna(mark) else np.nan
        z=x[(x.expiry.astype(str)==str(exp.date()))&(x.strike==strike)] if not x.empty and pd.notna(exp) and pd.notna(strike) else pd.DataFrame();delta=float(z.iloc[0].delta) if not z.empty else np.nan
        purpose=str(r.get('purpose','Income')).title();done=str(r.get('event_completed',False)).lower() in {'true','1','yes'}
        if purpose=='Trading':
            triggers=[]
            if done:triggers.append('事件完成')
            if pd.notna(profit) and profit>=m['trading_profit_trigger_pct']:triggers.append(f'Profit {profit:.0f}%')
            if pd.notna(delta) and delta<m['trading_delta_trigger']:triggers.append(f'Delta {delta:.2f}<0.05')
            action='BTC NOW' if triggers else 'HOLD';reason=('Trading Alpha已完成：'+'；'.join(triggers)) if triggers else 'Trading事件仍未完成'
        elif purpose=='Defensive':
            action='CONSIDER BTC' if pd.notna(delta) and delta<.10 else 'HOLD';reason='防守目的已大致完成' if action!='HOLD' else '防守目的仍存在'
        elif pd.notna(dte) and dte<=10:
            action='BTC NOW' if pd.notna(profit) and profit>=70 else ('CONSIDER BTC' if pd.notna(profit) and profit>=60 else 'HOLD');reason='短期Income CC睇Profit'
        elif pd.notna(dte) and 30<=dte<=180:
            action='CHECK DELTA' if pd.isna(delta) else ('IGNORE / HOLD' if delta<.20 else ('WATCH' if delta<.30 else ('PREPARE ROLL' if delta<.40 else 'PRIORITY ROLL / CLOSE')));reason=f'Income CC主要睇Delta {delta:.2f}' if pd.notna(delta) else '抓唔到Delta'
        else:action,reason='WATCH','DTE不在主要規則範圍'
        rows.append({**r.to_dict(),'Expiry (DDMMYY)':fmt_date(exp),'剩餘日數':dte,'Current Delta':delta,'Profit %':profit,'System Action':action,'Action Reason':reason})
    return pd.DataFrame(rows)
