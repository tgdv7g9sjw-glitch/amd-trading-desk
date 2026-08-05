from __future__ import annotations
from datetime import date, datetime, time
from math import erf, log, sqrt
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

NY = ZoneInfo("America/New_York")

def cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))

def delta_est(s: float, k: float, t: float, r: float, iv: float) -> float:
    if min(s, k, t, iv) <= 0:
        return np.nan
    d1 = (log(s/k) + (r + iv*iv/2)*t) / (iv*sqrt(t))
    return cdf(d1)

def history(symbol: str, period: str = "1y") -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"{symbol} 沒有返回價格資料")
    return df

def market_session(now_ny: datetime | None = None) -> str:
    now_ny = now_ny or datetime.now(NY)
    if now_ny.weekday() >= 5:
        return "CLOSED"
    t = now_ny.time()
    if time(4,0) <= t < time(9,30):
        return "PRE-MARKET"
    if time(9,30) <= t < time(16,0):
        return "REGULAR"
    if time(16,0) <= t < time(20,0):
        return "AFTER-HOURS"
    return "CLOSED"

def extended_quote(symbol: str, previous_close: float) -> dict[str, Any]:
    ticker = yf.Ticker(symbol)
    session = market_session()
    price = np.nan
    quote_time = None
    source = "daily"

    try:
        intraday = ticker.history(period="5d", interval="1m", prepost=True, auto_adjust=False)
        intraday = intraday.dropna(subset=["Close"])
        if not intraday.empty:
            price = float(intraday["Close"].iloc[-1])
            quote_time = pd.Timestamp(intraday.index[-1]).to_pydatetime()
            source = "1m extended-hours"
    except Exception:
        pass

    if not np.isfinite(price):
        try:
            fast = ticker.fast_info
            candidate = getattr(fast, "last_price", None)
            if candidate is not None:
                price = float(candidate)
                quote_time = datetime.now(NY)
                source = "fast_info"
        except Exception:
            pass

    if not np.isfinite(price):
        price = previous_close
        quote_time = datetime.now(NY)
        source = "daily fallback"

    if quote_time.tzinfo is None:
        quote_time = quote_time.replace(tzinfo=NY)
    else:
        quote_time = quote_time.astimezone(NY)

    age = max(0.0, (datetime.now(NY)-quote_time).total_seconds()/60)
    return {
        "live_price": price,
        "extended_change_pct": (price/previous_close-1)*100 if previous_close else np.nan,
        "session": session,
        "quote_time_ny": quote_time,
        "quote_age_minutes": age,
        "quote_source": source,
        "is_stale": age > 20 and session in {"PRE-MARKET","REGULAR","AFTER-HOURS"},
    }

def get_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    amd = history(cfg["ticker"])
    qqq = history(cfg["benchmark"])
    smh = history(cfg["sector_etf"])
    vix = history(cfg["vix_ticker"])

    c = amd["Close"]
    diff = c.diff()
    gain = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100/(1 + gain/loss.replace(0,np.nan))
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ret = c.pct_change()

    up_run = 0
    for value in ret.dropna().iloc[::-1]:
        if value > 0: up_run += 1
        else: break

    previous_close = float(c.iloc[-1])
    ext = extended_quote(cfg["ticker"], previous_close)

    return {
        "spot": ext["live_price"],
        "regular_close": previous_close,
        "day_pct": ext["extended_change_pct"],
        "regular_day_pct": float(ret.iloc[-1]*100),
        "week_pct": float(c.pct_change(5).iloc[-1]*100),
        "rsi": float(rsi.iloc[-1]),
        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "high60": float(amd["High"].tail(60).max()),
        "dist_high_pct": float((amd["High"].tail(60).max()/ext["live_price"]-1)*100),
        "qqq_trend": bool(qqq["Close"].iloc[-1] > qqq["Close"].ewm(span=20,adjust=False).mean().iloc[-1]),
        "smh_trend": bool(smh["Close"].iloc[-1] > smh["Close"].ewm(span=20,adjust=False).mean().iloc[-1]),
        "vix": float(vix["Close"].iloc[-1]),
        "vix_day_pct": float(vix["Close"].pct_change().iloc[-1]*100),
        "up_run": up_run,
        "history": amd.assign(EMA20=ema20, EMA50=ema50),
        **ext,
    }

def earnings_date(cfg):
    manual = str(cfg.get("manual",{}).get("next_earnings_date","") or "").strip()
    if manual:
        return pd.Timestamp(manual).date()
    try:
        cal = yf.Ticker(cfg["ticker"]).calendar
        if isinstance(cal, dict):
            value = cal.get("Earnings Date")
            if isinstance(value,(list,tuple)) and value:
                return pd.Timestamp(value[0]).date()
            if value is not None:
                return pd.Timestamp(value).date()
    except Exception:
        pass
    return None

def grade(s, earn, cfg):
    r = cfg["risk"]
    score, pos, caution, blockers = 45, [], [], []
    days = (earn-date.today()).days if earn else None

    if s["day_pct"] <= r["hard_red_drop_pct"]:
        blockers.append(f"AMD相對上次收市下跌 {s['day_pct']:.1f}%")
    if s["vix_day_pct"] >= r["vix_jump_pct"]:
        blockers.append(f"VIX單日急升 {s['vix_day_pct']:.1f}%")
    if not s["qqq_trend"] and not s["smh_trend"]:
        blockers.append("QQQ及SMH同時低於20EMA")
    if s["spot"] < s["ema20"] and s["day_pct"] < -2:
        blockers.append("AMD下跌並低於20EMA")

    if s["day_pct"] >= r["strong_rise_pct"]:
        score += 20; pos.append("相對上次收市升超過5%")
    elif s["day_pct"] >= 2:
        score += 9; pos.append("即時升幅理想")
    elif s["day_pct"] < 0:
        score -= 8; caution.append("即時價格低於上次收市，唔值得追Premium")

    if s["up_run"] >= 3:
        score += 14; pos.append(f"日線連升{s['up_run']}日")
    elif s["up_run"] >= 2:
        score += 9; pos.append("日線連升2日")

    if s["dist_high_pct"] <= 4:
        score += 14; pos.append("接近60日高位／阻力")
    elif s["dist_high_pct"] <= 8:
        score += 6; pos.append("距主要阻力不遠")

    if s["rsi"] >= r["rsi_very_hot"]:
        score += 15; pos.append("日線RSI極熱")
    elif s["rsi"] >= r["rsi_hot"]:
        score += 9; pos.append("日線RSI偏熱")
    elif s["rsi"] < 48:
        score -= 9; caution.append("日線RSI偏低，反彈風險較高")

    if s["smh_trend"]:
        score += 6; pos.append("SMH日線趨勢向上")
    else:
        score -= 8; caution.append("SMH低於20EMA")
    if s["qqq_trend"]:
        score += 4
    else:
        score -= 5; caution.append("QQQ低於20EMA")

    if days is not None and 0 <= days <= 2:
        score += 10; pos.append("財報前1–2日")
    elif days is not None and 3 <= days <= 7:
        score += 4; caution.append("一星期內財報，只可小倉")

    if s["vix"] >= 30:
        score -= 14; caution.append("VIX高於30")
    elif s["vix"] >= 24:
        score -= 7; caution.append("VIX偏高")

    if s["session"] == "PRE-MARKET":
        caution.append("盤前Grade屬暫定，開市後要再Refresh確認")
    elif s["session"] == "AFTER-HOURS":
        caution.append("盤後Grade只作翌日參考")
    if s["is_stale"]:
        caution.append("即時報價超過20分鐘未更新")

    score = max(0,min(100,int(score)))
    if blockers:
        label,max_new = "RED",0
    elif score >= 74 and len(pos) >= 3:
        label,max_new = "GREEN",2
    elif score >= 53:
        label,max_new = "YELLOW",1
    else:
        label,max_new = "RED",0

    action = {"GREEN":"可以考慮開CC，但最多2張。",
              "YELLOW":"最多1張保守CC；冇靚價就唔做。",
              "RED":"禁止開新CC，只管理現有倉。"}[label]
    return {"label":label,"score":score,"max_new":max_new,"action":action,
            "positive":pos,"caution":caution,"blockers":blockers,
            "earnings":earn,"days_to_earnings":days}

def option_chain(cfg, spot):
    ticker = yf.Ticker(cfg["ticker"])
    today = pd.Timestamp.today().normalize()
    frames = []
    for expiry in list(ticker.options):
        dte = int((pd.Timestamp(expiry)-today).days)
        if dte < 4 or dte > cfg["policy"]["long_dte"][1]+20:
            continue
        try:
            calls = ticker.option_chain(expiry).calls.copy()
        except Exception:
            continue
        if calls.empty: continue
        calls["expiry"],calls["dte"] = expiry,dte
        frames.append(calls)
    if not frames:
        return pd.DataFrame()

    x = pd.concat(frames,ignore_index=True)
    for col in ["strike","bid","ask","lastPrice","impliedVolatility","openInterest","volume"]:
        x[col] = pd.to_numeric(x[col],errors="coerce")
    x["mid"] = np.where((x["bid"]>0)&(x["ask"]>0),(x["bid"]+x["ask"])/2,x["lastPrice"])
    x["spread"] = np.where(x["mid"]>0,(x["ask"]-x["bid"])/x["mid"]*100,np.nan)
    x["otm"] = (x["strike"]/spot-1)*100
    x["delta"] = x.apply(lambda z: delta_est(spot,z["strike"],max(z["dte"]/365,1/365),.04,z["impliedVolatility"]),axis=1)
    return x

def recommendations(chain,s,result,cfg):
    if result["label"]=="RED" or chain.empty:
        return pd.DataFrame()
    p = cfg["policy"]
    base = chain[
        (chain["strike"] >= s["spot"]*(1+p["minimum_otm_pct"]/100)) &
        (chain["openInterest"].fillna(0) >= p["minimum_open_interest"]) &
        (chain["spread"].fillna(999) <= p["maximum_spread_pct"]) &
        (chain["mid"] > 0)
    ].copy()

    slots = [
        ("7–12日",p["short_dte"],p["short_delta"],False),
        ("21–40日",p["medium_dte"],p["medium_delta"],False),
        ("長期900+ A",p["long_dte"],p["long_delta"],True),
        ("長期900+ B",p["long_dte"],p["long_delta"],True),
    ]
    rows = []
    for name,dtes,deltas,protected in slots:
        z = base[base["dte"].between(*dtes)&base["delta"].between(*deltas)].copy()
        if protected:
            z = z[z["strike"] >= p["protected_strike"]]
        if z.empty:
            continue
        target = sum(deltas)/2
        z["rank"] = 45*(1-(z["delta"]-target).abs()/max(target,.01)).clip(0,1) + 30*(1-z["spread"].clip(0,30)/30) + 25*np.log1p(z["openInterest"].fillna(0))/np.log(20000)
        q = z.sort_values(["rank","strike"],ascending=[False,False]).iloc[0]
        rows.append({
            "用途":name,"到期日":q["expiry"],"DTE":int(q["dte"]),
            "Strike":float(q["strike"]),"OTM %":float(q["otm"]),
            "Delta估算":float(q["delta"]),"Bid":float(q["bid"]),
            "Ask":float(q["ask"]),"Mid":float(q["mid"]),
            "每張Premium":float(q["mid"]*100),"IV %":float(q["impliedVolatility"]*100),
            "OI":int(q["openInterest"] or 0),"Spread %":float(q["spread"])
        })
    return pd.DataFrame(rows)

def top_recommendation(recs,result):
    if result["label"]=="RED":
        return "今日唔開新CC。"
    if recs.empty:
        return "今日冇合約同時符合Delta、Strike及流動性規則。"
    allowed = min(result["max_new"],len(recs))
    chosen = recs.head(allowed)
    parts = []
    for _,r in chosen.iterrows():
        parts.append(f"{r['到期日']} ${r['Strike']:.0f}C｜Delta {r['Delta估算']:.2f}｜Premium約 ${r['每張Premium']:.0f}")
    return "；".join(parts)

def position_actions(df,spot,cfg):
    out = df.copy()
    actions,pnls,dtes,distances = [],[],[],[]
    p = cfg["policy"]
    for _,row in out.iterrows():
        if str(row.get("status","")).upper()!="OPEN":
            actions.append("空置")
            pnls.append(np.nan)
            dtes.append(np.nan)
            distances.append(np.nan)
            continue

        credit = pd.to_numeric(row.get("credit_received"),errors="coerce")
        mark = pd.to_numeric(row.get("current_mark"),errors="coerce")
        strike = pd.to_numeric(row.get("strike"),errors="coerce")
        expiry = pd.to_datetime(row.get("expiry"),errors="coerce")
        pnl = (credit-mark)/credit*100 if pd.notna(credit) and credit>0 and pd.notna(mark) else np.nan
        dte = (expiry.normalize()-pd.Timestamp.today().normalize()).days if pd.notna(expiry) else np.nan
        distance = (strike/spot-1)*100 if pd.notna(strike) else np.nan

        if pd.notna(pnl) and pnl>=p["take_profit_priority_pct"]:
            action=f"優先BTC｜已賺{pnl:.0f}%"
        elif pd.notna(pnl) and pnl>=p["take_profit_consider_pct"]:
            action=f"考慮BTC｜已賺{pnl:.0f}%"
        elif pd.notna(distance) and distance<=0:
            action="ITM｜立即評估Roll"
        elif pd.notna(dte) and dte<=p["roll_alert_dte"] and pd.notna(distance) and distance<p["roll_alert_distance_pct"]:
            action=f"Roll Alert｜剩{int(dte)}日、距Strike {distance:.1f}%"
        else:
            action="Hold"

        actions.append(action)
        pnls.append(pnl)
        dtes.append(dte)
        distances.append(distance)

    out["DTE"]=dtes
    out["距Strike %"]=distances
    out["浮動利潤 %"]=pnls
    out["系統建議"]=actions
    return out


def portfolio_summary(positions,cfg,result):
    if positions.empty:
        open_contracts = 0
        total_credit = 0.0
        floating_pnl = 0.0
    else:
        open_mask = positions["status"].astype(str).str.upper().eq("OPEN")
        open_contracts = int(
            pd.to_numeric(positions.loc[open_mask,"contracts"],errors="coerce")
            .fillna(0).sum()
        )
        total_credit = 0.0
        floating_pnl = 0.0
        for _,row in positions.loc[open_mask].iterrows():
            contracts = pd.to_numeric(row.get("contracts"),errors="coerce")
            credit = pd.to_numeric(row.get("credit_received"),errors="coerce")
            mark = pd.to_numeric(row.get("current_mark"),errors="coerce")
            if pd.notna(contracts) and pd.notna(credit):
                total_credit += contracts*credit*100
            if pd.notna(contracts) and pd.notna(credit) and pd.notna(mark):
                floating_pnl += contracts*(credit-mark)*100

    max_cc = int(cfg["portfolio"]["max_covered_calls"])
    remaining_capacity = max(0,max_cc-open_contracts)
    allowed_today = min(remaining_capacity,int(result["max_new"]))

    return {
        "open_cc":open_contracts,
        "remaining_capacity":remaining_capacity,
        "allowed_today":allowed_today,
        "total_credit":total_credit,
        "floating_pnl":floating_pnl,
    }
