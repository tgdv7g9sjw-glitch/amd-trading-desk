from __future__ import annotations
from datetime import date
from math import erf, log, sqrt
from pathlib import Path
from typing import Any
import json
import numpy as np
import pandas as pd
import yfinance as yf

def cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))

def estimate_delta(s: float, k: float, t: float, r: float, iv: float) -> float:
    if min(s, k, t, iv) <= 0:
        return np.nan
    d1 = (log(s / k) + (r + iv * iv / 2) * t) / (iv * sqrt(t))
    return cdf(d1)

def history(symbol: str, period="1y") -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"{symbol} 沒有返回價格資料")
    return df

def get_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    amd = history(cfg["ticker"])
    qqq = history(cfg["benchmark"])
    smh = history(cfg["sector_etf"])
    vix = history(cfg["vix_ticker"])
    c = amd["Close"]
    chg = c.diff()
    avg_gain = chg.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    avg_loss = (-chg.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    tr = pd.concat([(amd.High-amd.Low), (amd.High-c.shift()).abs(), (amd.Low-c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    ret = c.pct_change()
    up_run = 0
    for x in ret.dropna().iloc[::-1]:
        if x > 0: up_run += 1
        else: break
    return {
        "spot": float(c.iloc[-1]),
        "day_pct": float(ret.iloc[-1]*100),
        "week_pct": float(c.pct_change(5).iloc[-1]*100),
        "month_pct": float(c.pct_change(21).iloc[-1]*100),
        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "rsi": float(rsi.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "rv20": float(ret.rolling(20).std().iloc[-1]*sqrt(252)*100),
        "high60": float(amd.High.tail(60).max()),
        "low20": float(amd.Low.tail(20).min()),
        "dist_high_pct": float((amd.High.tail(60).max()/c.iloc[-1]-1)*100),
        "dist_support_pct": float((c.iloc[-1]/amd.Low.tail(20).min()-1)*100),
        "qqq_trend": bool(qqq.Close.iloc[-1] > qqq.Close.ewm(span=20, adjust=False).mean().iloc[-1]),
        "smh_trend": bool(smh.Close.iloc[-1] > smh.Close.ewm(span=20, adjust=False).mean().iloc[-1]),
        "vix": float(vix.Close.iloc[-1]),
        "vix_day_pct": float(vix.Close.pct_change().iloc[-1]*100),
        "up_run": up_run,
        "history": amd.assign(EMA20=ema20, EMA50=ema50, RSI=rsi, ATR=atr),
    }

def earnings_date(cfg: dict[str, Any]):
    manual = str(cfg.get("manual",{}).get("next_earnings_date","") or "").strip()
    if manual:
        return pd.Timestamp(manual).date()
    try:
        cal = yf.Ticker(cfg["ticker"]).calendar
        if isinstance(cal, dict):
            value = cal.get("Earnings Date")
            if isinstance(value, (list, tuple)) and value:
                return pd.Timestamp(value[0]).date()
            if value is not None:
                return pd.Timestamp(value).date()
    except Exception:
        return None
    return None

def grade(snapshot: dict[str, Any], earn, cfg: dict[str, Any]) -> dict[str, Any]:
    r = cfg["risk"]
    score = 45
    positive, caution, blockers = [], [], []
    days = (earn-date.today()).days if earn else None

    if snapshot["day_pct"] <= r["hard_red_daily_drop_pct"]:
        blockers.append(f"AMD 單日下跌 {snapshot['day_pct']:.1f}%")
    if snapshot["vix_day_pct"] >= r["vix_jump_pct"]:
        blockers.append(f"VIX 單日急升 {snapshot['vix_day_pct']:.1f}%")
    if not snapshot["qqq_trend"] and not snapshot["smh_trend"]:
        blockers.append("QQQ及SMH同時低於20EMA")
    if snapshot["spot"] < snapshot["ema20"] and snapshot["day_pct"] < -2:
        blockers.append("AMD下跌並跌穿20EMA")
    if days is not None and -r["post_earnings_freeze_days"] <= days < 0:
        blockers.append("財報後冷靜期")

    if snapshot["day_pct"] >= r["strong_rise_pct"]:
        score += 20; positive.append("單日升超過5%")
    elif snapshot["day_pct"] >= 2:
        score += 9; positive.append("單日升幅理想")
    elif snapshot["day_pct"] < 0:
        score -= 8; caution.append("今日下跌，Premium不值得追")

    if snapshot["up_run"] >= 3:
        score += 14; positive.append(f"連升{snapshot['up_run']}日")
    elif snapshot["up_run"] >= 2:
        score += 9; positive.append("連升2日")

    if snapshot["dist_high_pct"] <= 4:
        score += 14; positive.append("接近60日高位／阻力")
    elif snapshot["dist_high_pct"] <= 8:
        score += 6; positive.append("距主要阻力不遠")

    if snapshot["rsi"] >= r["rsi_very_hot"]:
        score += 15; positive.append("RSI極熱")
    elif snapshot["rsi"] >= r["rsi_hot"]:
        score += 9; positive.append("RSI偏熱")
    elif snapshot["rsi"] < 48:
        score -= 9; caution.append("RSI偏低，反彈風險較高")

    if snapshot["smh_trend"]:
        score += 6; positive.append("SMH趨勢向上")
    else:
        score -= 8; caution.append("SMH低於20EMA")
    if snapshot["qqq_trend"]:
        score += 4
    else:
        score -= 5; caution.append("QQQ低於20EMA")

    if days is not None and 0 <= days <= 2:
        score += 10; positive.append("財報前1–2日，IV可能偏高")
    elif days is not None and 3 <= days <= 7:
        score += 4; caution.append("一星期內財報，只可小倉")

    if snapshot["vix"] >= 30:
        score -= 14; caution.append("VIX高於30")
    elif snapshot["vix"] >= 24:
        score -= 7; caution.append("VIX偏高")

    score = max(0, min(100, int(score)))
    if blockers:
        label, max_new = "RED", 0
    elif score >= 74 and len(positive) >= 3:
        label, max_new = "GREEN", 2
    elif score >= 53:
        label, max_new = "YELLOW", 1
    else:
        label, max_new = "RED", 0

    action = {
        "GREEN": "可以開倉，但最多2張；優先短期或中期其中一張。",
        "YELLOW": "最多1張，而且必須用保守Strike；冇靚價就唔做。",
        "RED": "禁止開新CC，只管理現有倉。"
    }[label]
    return dict(label=label, score=score, max_new=max_new, action=action,
                positive=positive, caution=caution, blockers=blockers,
                earnings=earn, days_to_earnings=days)

def option_chain(cfg, spot):
    t = yf.Ticker(cfg["ticker"])
    frames = []
    today = pd.Timestamp.today().normalize()
    for exp in list(t.options):
        dte = int((pd.Timestamp(exp)-today).days)
        if dte < 4 or dte > cfg["policy"]["long_dte"][1]+20:
            continue
        try: calls = t.option_chain(exp).calls.copy()
        except Exception: continue
        if calls.empty: continue
        calls["expiry"], calls["dte"] = exp, dte
        frames.append(calls)
    if not frames: return pd.DataFrame()
    x = pd.concat(frames, ignore_index=True)
    cols = ["strike","bid","ask","lastPrice","impliedVolatility","openInterest","volume"]
    for c in cols: x[c] = pd.to_numeric(x[c], errors="coerce")
    x["mid"] = np.where((x.bid>0)&(x.ask>0),(x.bid+x.ask)/2,x.lastPrice)
    x["spread_pct"] = np.where(x.mid>0,(x.ask-x.bid)/x.mid*100,np.nan)
    x["otm_pct"] = (x.strike/spot-1)*100
    x["delta"] = x.apply(lambda z: estimate_delta(spot,z.strike,max(z.dte/365,1/365),.04,z.impliedVolatility),axis=1)
    x["premium"] = x.mid*100
    x["annual_yield"] = (x.mid/spot)*365/x.dte*100
    return x

def recommendations(chain, snap, result, cfg):
    if chain.empty or result["label"]=="RED": return pd.DataFrame()
    p=cfg["policy"]; spot=snap["spot"]
    base=chain[(chain.strike>=spot*(1+p["minimum_otm_pct"]/100)) &
               (chain.openInterest.fillna(0)>=p["minimum_open_interest"]) &
               (chain.spread_pct.fillna(999)<=p["maximum_bid_ask_spread_pct"]) &
               (chain.mid>0)].copy()
    slots=[
      ("7–12日",p["short_dte"],p["preferred_short_delta"],False),
      ("21–40日",p["medium_dte"],p["preferred_medium_delta"],False),
      ("長期900+ A",p["long_dte"],p["preferred_long_delta"],True),
      ("長期900+ B",p["long_dte"],p["preferred_long_delta"],True)]
    rows=[]
    for name,dtes,deltas,protected in slots:
        z=base[base.dte.between(*dtes)&base.delta.between(*deltas)].copy()
        if protected: z=z[z.strike>=p["protected_strike"]]
        if z.empty: continue
        target=sum(deltas)/2
        z["rank"]=(35*(1-(z.delta-target).abs()/max(target,.01)).clip(0,1)
                   +25*(1-z.spread_pct.clip(0,30)/30)
                   +20*np.log1p(z.openInterest.fillna(0))/np.log(20000)
                   +20*z.annual_yield.clip(0,40)/40)
        q=z.sort_values(["rank","strike"],ascending=[False,False]).iloc[0]
        rows.append({"用途":name,"到期日":q.expiry,"DTE":int(q.dte),"Strike":float(q.strike),
                     "OTM %":float(q.otm_pct),"Delta估算":float(q.delta),
                     "Bid":float(q.bid),"Ask":float(q.ask),"Mid":float(q.mid),
                     "每張Premium":float(q.premium),"IV %":float(q.impliedVolatility*100),
                     "OI":int(q.openInterest or 0),"Spread %":float(q.spread_pct)})
    return pd.DataFrame(rows)

def position_actions(df, spot, cfg):
    if df.empty: return df
    out=df.copy(); actions=[]; pnls=[]
    p=cfg["policy"]
    for _,row in out.iterrows():
        if str(row.get("status","")).upper()!="OPEN":
            actions.append("空置"); pnls.append(np.nan); continue
        credit=pd.to_numeric(row.get("credit_received"),errors="coerce")
        mark=pd.to_numeric(row.get("current_mark"),errors="coerce")
        strike=pd.to_numeric(row.get("strike"),errors="coerce")
        expiry=pd.to_datetime(row.get("expiry"),errors="coerce")
        pnl=(credit-mark)/credit*100 if pd.notna(credit) and credit>0 and pd.notna(mark) else np.nan
        dte=(expiry.normalize()-pd.Timestamp.today().normalize()).days if pd.notna(expiry) else 999
        distance=(strike/spot-1)*100 if pd.notna(strike) else np.nan
        if pd.notna(pnl) and pnl>=p["take_profit_priority_pct"]: act=f"優先BTC｜已賺{pnl:.0f}%"
        elif pd.notna(pnl) and pnl>=p["take_profit_consider_pct"]: act=f"考慮BTC｜已賺{pnl:.0f}%"
        elif pd.notna(distance) and distance<=0: act="ITM｜立即評估Roll"
        elif dte<=p["roll_alert_dte"] and pd.notna(distance) and distance<p["roll_alert_distance_pct"]:
            act=f"Roll Alert｜剩{dte}日、距Strike {distance:.1f}%"
        else: act="Hold"
        actions.append(act); pnls.append(pnl)
    out["浮動利潤 %"]=pnls; out["系統建議"]=actions
    return out

def save_snapshot(path: str, snap: dict, result: dict, recs: pd.DataFrame):
    payload={k:v for k,v in snap.items() if k!="history"}
    payload["grade"]=result
    payload["recommendations"]=recs.to_dict("records")
    Path(path).write_text(json.dumps(payload,default=str,ensure_ascii=False,indent=2),encoding="utf-8")
