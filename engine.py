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

def decision_checklist(ticker, s, earn, cfg):
    risk = cfg["risk"]
    days_to_earnings = (earn - date.today()).days if earn else None
    checks = []

    def add(name, passed, actual, rule, importance="Normal", blocker=False, caution=False):
        if blocker and not passed:
            status = "BLOCK"
        elif caution:
            status = "CAUTION"
        else:
            status = "PASS" if passed else "FAIL"
        checks.append({
            "Status": status,
            "Condition": name,
            "Actual": actual,
            "Required / Preferred": rule,
            "Importance": importance,
            "Hard Blocker": bool(blocker and not passed),
        })

    add(
        "No sharp downside move",
        s["day_pct"] > risk["hard_red_drop_pct"],
        f"{s['day_pct']:+.2f}%",
        f"Must be above {risk['hard_red_drop_pct']:.0f}%",
        "Critical",
        blocker=True,
    )
    add(
        "VIX is not spiking",
        s["vix_day_pct"] < risk["vix_jump_pct"],
        f"{s['vix_day_pct']:+.2f}%",
        f"VIX daily move below +{risk['vix_jump_pct']:.0f}%",
        "Critical",
        blocker=True,
    )
    add(
        "Market and sector are not both weak",
        bool(s["benchmark_trend"] or s["sector_trend"]),
        f"Benchmark {'PASS' if s['benchmark_trend'] else 'FAIL'} / Sector {'PASS' if s['sector_trend'] else 'FAIL'}",
        "At least one trend above 20 EMA",
        "Critical",
        blocker=True,
    )
    add(
        "Strong up day",
        s["day_pct"] >= risk["strong_rise_pct"],
        f"{s['day_pct']:+.2f}%",
        f"Preferred: at least +{risk['strong_rise_pct']:.0f}%",
        "High",
    )
    add(
        "Multi-day run-up",
        s["up_run"] >= 2,
        f"{s['up_run']} consecutive up days",
        "Preferred: 2 or more days",
        "High",
    )
    add(
        "Near resistance / recent high",
        s["dist_high_pct"] <= 8,
        f"{s['dist_high_pct']:.1f}% below 60-day high",
        "Preferred: within 8%",
        "High",
    )
    add(
        "RSI is elevated",
        s["rsi"] >= risk["rsi_hot"],
        f"RSI {s['rsi']:.1f}",
        f"Preferred: RSI at least {risk['rsi_hot']}",
        "Medium",
    )
    add(
        "Sector trend supports the trade",
        bool(s["sector_trend"]),
        "Above 20 EMA" if s["sector_trend"] else "Below 20 EMA",
        "Preferred: above 20 EMA",
        "High",
    )
    add(
        "Benchmark trend supports the trade",
        bool(s["benchmark_trend"]),
        "Above 20 EMA" if s["benchmark_trend"] else "Below 20 EMA",
        "Preferred: above 20 EMA",
        "Medium",
    )
    add(
        "VIX level is controlled",
        s["vix"] < 24,
        f"VIX {s['vix']:.1f}",
        "Preferred: below 24",
        "Medium",
        caution=(24 <= s["vix"] < 30),
    )

    if days_to_earnings is None:
        checks.append({
            "Status": "CAUTION",
            "Condition": "Earnings date confirmed",
            "Actual": "Unavailable",
            "Required / Preferred": "Confirm before opening a new CC",
            "Importance": "High",
            "Hard Blocker": False,
        })
    else:
        add(
            "Earnings timing is favorable",
            0 <= days_to_earnings <= 2,
            f"{days_to_earnings} days to earnings",
            "Trading CC preferred 1–2 days before earnings",
            "Medium",
            caution=(3 <= days_to_earnings <= 7),
        )

    add(
        "Quote is current",
        not s["is_stale"],
        f"{s['quote_age_minutes']:.0f} minutes old",
        "Preferred: under 20 minutes",
        "Critical",
        caution=s["is_stale"],
    )

    return pd.DataFrame(checks)


def checklist_summary(checks):
    hard_blockers = int(checks["Hard Blocker"].fillna(False).sum())
    passes = int((checks["Status"] == "PASS").sum())
    fails = int((checks["Status"] == "FAIL").sum())
    cautions = int((checks["Status"] == "CAUTION").sum())

    if hard_blockers > 0:
        decision = "NO NEW CC"
        explanation = f"{hard_blockers} hard blocker(s) must clear first."
    elif passes >= 6:
        decision = "CC SETUP VALID"
        explanation = "Most important conditions are present. Contract quality still needs approval."
    elif passes >= 4:
        decision = "WAIT / CONSERVATIVE ONLY"
        explanation = "The setup is incomplete. Only consider a very conservative contract."
    else:
        decision = "NO TRADE"
        explanation = "Too few favorable conditions are present."

    return {
        "hard_blockers": hard_blockers,
        "passes": passes,
        "fails": fails,
        "cautions": cautions,
        "decision": decision,
        "explanation": explanation,
    }


def grade(s,earn,cfg):
    r=cfg['risk'];score=45;pos=[];warn=[];block=[];days=(earn-date.today()).days if earn else None
    if s['day_pct']<=r['hard_red_drop_pct']:block.append(f"Price down {s['day_pct']:.1f}%")
    if s['vix_day_pct']>=r['vix_jump_pct']:block.append('VIX spiked sharply')
    if not s['benchmark_trend'] and not s['sector_trend']:block.append('Benchmark and sector trend both weakened')
    if s['day_pct']>=r['strong_rise_pct']:score+=20;pos.append('Price rose more than 5%')
    elif s['day_pct']>=2:score+=9;pos.append('Strong intraday gain')
    elif s['day_pct']<0:score-=8;warn.append('Live price is below the reference close')
    if s['up_run']>=2:score+=9;pos.append(f"Up for {s['up_run']} consecutive sessions")
    if s['dist_high_pct']<=4:score+=14;pos.append('Near the 60-day high')
    elif s['dist_high_pct']<=8:score+=6;pos.append('Close to a major resistance area')
    if s['rsi']>=r['rsi_very_hot']:score+=15;pos.append('RSI is extremely overbought')
    elif s['rsi']>=r['rsi_hot']:score+=9;pos.append('RSI is elevated')
    elif s['rsi']<48:score-=9;warn.append('RSI is weak')
    score+=6 if s['sector_trend'] else -8;score+=4 if s['benchmark_trend'] else -5
    if days is not None and 0<=days<=2:score+=10;pos.append('Earnings in 1–2 days')
    if s['session']=='PRE-MARKET':warn.append('Premarket grade is provisional')
    score=max(0,min(100,int(score)))
    if block:label,max_new='RED',0
    elif score>=74 and len(pos)>=3:label,max_new='GREEN',2
    elif score>=53:label,max_new='YELLOW',1
    else:label,max_new='RED',0
    return dict(label=label,score=score,max_new=max_new,action={'GREEN':'New covered calls may be considered','YELLOW':'At most one conservative covered call','RED':'Do not open a new covered call'}[label],positive=pos,caution=warn,blockers=block,earnings=earn)
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
    slots=[('7–12 DTE',n['short_dte'],n['short_delta']),('21–40 DTE',n['medium_dte'],n['medium_delta']),('90–180 DTE',n['long_dte'],n['long_delta'])]
    if ticker=='AMD':slots.append(('AMD Long-Dated 900+',n['long_dte'],n['long_delta']))
    for name,dtes,deltas in slots:
        z=b[b.dte.between(*dtes)&b.delta.between(*deltas)].copy()
        if name=='AMD Long-Dated 900+':z=z[z.strike>=900]
        if z.empty:continue
        target=sum(deltas)/2;z['rank']=45*(1-(z.delta-target).abs()/max(target,.01)).clip(0,1)+30*(1-z.spread.clip(0,30)/30)+25*np.log1p(z.openInterest.fillna(0))/np.log(20000);q=z.sort_values(['rank','strike'],ascending=[False,False]).iloc[0]
        rows.append({'Use Case':name,'Expiry':q.expiry,'DTE':int(q.dte),'Strike':float(q.strike),'OTM %':float(q.otm),'Delta':float(q.delta),'Bid':float(q.bid),'Ask':float(q.ask),'Mid':float(q.mid),'Premium / Contract':float(q.mid*100),'IV %':float(q.impliedVolatility*100),'OI':int(q.openInterest or 0),'Spread %':float(q.spread)})
    return pd.DataFrame(rows)
def manage(pos,ticker,x,spot,cfg):
    p=pos[pos.ticker.astype(str).str.upper()==ticker].copy();m=cfg['management'];actions=[];ds=[];profits=[];dtes=[]
    for _,r in p.iterrows():
        if str(r.status).upper()!='OPEN':actions.append('EMPTY');ds.append(np.nan);profits.append(np.nan);dtes.append(np.nan);continue
        exp=pd.to_datetime(r.expiry,errors='coerce');strike=pd.to_numeric(r.strike,errors='coerce');credit=pd.to_numeric(r.credit_received,errors='coerce');mark=pd.to_numeric(r.current_mark,errors='coerce');dte=(exp.normalize()-pd.Timestamp.today().normalize()).days if pd.notna(exp) else np.nan;profit=(credit-mark)/credit*100 if pd.notna(credit) and credit>0 and pd.notna(mark) else np.nan;z=x[(x.expiry.astype(str)==str(exp.date()))&(x.strike==strike)] if not x.empty and pd.notna(exp) and pd.notna(strike) else pd.DataFrame();delta=float(z.iloc[0].delta) if not z.empty else np.nan
        if pd.notna(dte) and dte<=10:
            a=f"BTC NOW | Profit {profit:.0f}%" if pd.notna(profit) and profit>=70 else (f"CONSIDER BTC | Profit {profit:.0f}%" if pd.notna(profit) and profit>=60 else 'HOLD | Profit below 60%')
        elif pd.notna(dte) and 30<=dte<=180:
            a='CHECK DELTA' if pd.isna(delta) else (f"IGNORE / HOLD | Delta {delta:.2f}" if delta<.20 else (f"WATCH | Delta {delta:.2f}" if delta<.30 else (f"PREPARE ROLL | Delta {delta:.2f}" if delta<.40 else f"PRIORITY ROLL / CLOSE | Delta {delta:.2f}")))
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


def live_contract_quote(chain_df, expiry_value, strike_value):
    """
    Match an open call against the live option chain.
    Returns live mid, delta and quote source. Falls back cleanly if unavailable.
    """
    expiry_ts = parse_ddmmyy(expiry_value)
    strike = pd.to_numeric(strike_value, errors="coerce")

    if chain_df is None or chain_df.empty or pd.isna(expiry_ts) or pd.isna(strike):
        return np.nan, np.nan, "Manual fallback"

    expiry_iso = str(expiry_ts.date())
    expiry_series = chain_df["expiry"].astype(str)
    strike_series = pd.to_numeric(chain_df["strike"], errors="coerce")

    matched = chain_df[
        (expiry_series == expiry_iso) &
        (np.isclose(strike_series, float(strike), atol=0.001))
    ]

    if matched.empty:
        return np.nan, np.nan, "Manual fallback"

    row = matched.iloc[0]
    bid = pd.to_numeric(row.get("bid"), errors="coerce")
    ask = pd.to_numeric(row.get("ask"), errors="coerce")
    last = pd.to_numeric(row.get("lastPrice"), errors="coerce")
    stored_mid = pd.to_numeric(row.get("mid"), errors="coerce")
    delta = pd.to_numeric(row.get("delta"), errors="coerce")

    if pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > 0:
        mid = (float(bid) + float(ask)) / 2
        source = "Live Bid/Ask Mid"
    elif pd.notna(stored_mid) and stored_mid >= 0:
        mid = float(stored_mid)
        source = "Option Chain Mid"
    elif pd.notna(last) and last >= 0:
        mid = float(last)
        source = "Last Trade"
    else:
        mid = np.nan
        source = "Manual fallback"

    return mid, (float(delta) if pd.notna(delta) else np.nan), source


def manage_pro(pos,ticker,x,spot,cfg):
    p = pos[pos.ticker.astype(str).str.upper() == ticker].copy()
    m = cfg["management"]
    rows = []

    for _, r in p.iterrows():
        if str(r.status).upper() != "OPEN":
            rows.append({
                **r.to_dict(),
                "Expiry (DDMMYY)": "",
                "Days Remaining": np.nan,
                "Live Mark": np.nan,
                "Mark Source": "",
                "Current Delta": np.nan,
                "Profit %": np.nan,
                "Unrealized P/L": np.nan,
                "System Action": "EMPTY",
                "Action Reason": "Position is empty",
            })
            continue

        exp = parse_ddmmyy(r.expiry)
        credit = pd.to_numeric(r.credit_received, errors="coerce")
        manual_mark = pd.to_numeric(r.current_mark, errors="coerce")
        contracts = pd.to_numeric(r.contracts, errors="coerce")
        dte = (
            (exp.normalize() - pd.Timestamp.today().normalize()).days
            if pd.notna(exp) else np.nan
        )

        live_mark, delta, mark_source = live_contract_quote(
            x, r.expiry, r.strike
        )
        effective_mark = live_mark if pd.notna(live_mark) else manual_mark

        profit = (
            (credit - effective_mark) / credit * 100
            if pd.notna(credit) and credit > 0 and pd.notna(effective_mark)
            else np.nan
        )
        unrealized = (
            (credit - effective_mark) * contracts * 100
            if pd.notna(credit) and pd.notna(effective_mark) and pd.notna(contracts)
            else np.nan
        )

        purpose = str(r.get("purpose", "Income")).title()
        done = str(r.get("event_completed", False)).lower() in {
            "true", "1", "yes"
        }

        if purpose == "Trading":
            triggers = []
            if done:
                triggers.append("Event completed")
            if pd.notna(profit) and profit >= m["trading_profit_trigger_pct"]:
                triggers.append(f"Profit {profit:.0f}%")
            if pd.notna(delta) and delta < m["trading_delta_trigger"]:
                triggers.append(f"Delta {delta:.2f} < 0.05")

            action = "BTC NOW" if triggers else "HOLD"
            reason = (
                "Trading alpha completed: " + ", ".join(triggers)
                if triggers else "Trading event thesis is still active"
            )

        elif purpose == "Defensive":
            action = (
                "CONSIDER BTC"
                if pd.notna(delta) and delta < 0.10
                else "HOLD"
            )
            reason = (
                "Defensive objective is largely complete"
                if action != "HOLD"
                else "Defensive objective remains active"
            )

        elif pd.notna(dte) and dte <= 10:
            if pd.notna(profit) and profit >= 70:
                action = "BTC NOW"
            elif pd.notna(profit) and profit >= 60:
                action = "CONSIDER BTC"
            else:
                action = "HOLD"
            reason = "Short-dated income CC is managed by profit target"

        elif pd.notna(dte) and 30 <= dte <= 180:
            if pd.isna(delta):
                action = "CHECK DELTA"
                reason = "Delta is temporarily unavailable"
            elif delta < 0.20:
                action = "IGNORE / HOLD"
                reason = f"Income CC is managed primarily by Delta {delta:.2f}"
            elif delta < 0.30:
                action = "WATCH"
                reason = f"Income CC is managed primarily by Delta {delta:.2f}"
            elif delta < 0.40:
                action = "PREPARE ROLL"
                reason = f"Income CC is managed primarily by Delta {delta:.2f}"
            else:
                action = "PRIORITY ROLL / CLOSE"
                reason = f"Income CC is managed primarily by Delta {delta:.2f}"

        else:
            action = "WATCH"
            reason = "DTE is outside the primary rule set"

        rows.append({
            **r.to_dict(),
            "Expiry (DDMMYY)": fmt_date(exp),
            "Days Remaining": dte,
            "Live Mark": effective_mark,
            "Mark Source": mark_source if pd.notna(live_mark) else "Manual fallback",
            "Current Delta": delta,
            "Profit %": profit,
            "Unrealized P/L": unrealized,
            "System Action": action,
            "Action Reason": reason,
        })

    return pd.DataFrame(rows)

