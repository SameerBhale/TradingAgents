"""Multibagger candidates: a long-term (3-5 year) watch list that grows over time.

NOT a promise and NOT backtested (free fundamentals have no point-in-time history). It is
a shortlist of businesses that look like past multibaggers did *before* they ran, built
from three documented sources:

- Motilal Oswal's annual Wealth Creation Study, "SQGLP": Size (small enough to grow
  many times), Quality (high ROE, low debt), Growth (sales and profit compounding),
  Longevity (growth that repeats year after year) and Price (a fair PEG).
- Christopher Mayer, *100 Baggers*: start small, keep a high return on equity while
  reinvesting, and prefer owner-operators (high promoter holding).
- Indian studies of 10x stocks (e.g. the 44 stocks up 1,000%+ since 2014): sales growth
  above 15%, EPS growth above 20-24%, high ROCE, PEG below about 1.4.

The screen, on every scanned stock (top-500 caps and liquid micro caps):

- Size: market cap Rs 500 - 30,000 crore.
- Quality: ROE >= 18%, debt/equity <= 50%, operating margin >= 12%, operating cash flow
  positive in at least two of the last three years.
- Growth: 3-year sales CAGR >= 15% and 3-year profit CAGR >= 20% (annual results).
- Longevity: sales grew in each of the last three years, and the latest year too.
- Price: P/E <= 60 and PEG (P/E / 3-year profit CAGR) <= 1.5.
- Chart: above a rising 200-day average, within 35% of the 52-week high (not a falling knife).
- Longevity over 5 years (when NSE's filings reach back that far): 5-year sales CAGR >= 12%
  and sales up in at least 4 of the last 5 years.
- Promoter pledge: no more than 20% of promoter shares pledged (NSE's pledge disclosure).
- Bonus (ranking only): promoter holding >= 40% (owner-operator), free cash flow positive.

Data: annual results from NSE's XBRL filings (FY2017 onward, official) merged with Yahoo's
last four years; promoter holding and pledge from NSE's shareholding filings.

The list is kept in ``~/.tradingagents/multibaggers.json``. Every run:

- a stock that passes and is not on the list is **added** (NEW), with the date and price;
- a stock on the list stays (**HOLD**) while it passes;
- one that fails a check is put on **REVIEW** (the reason is shown);
- one whose story breaks is **REMOVED** (kept in the history with the reason): ROE under
  12%, 3-year sales CAGR under 8%, debt/equity over 100%, over half of promoter shares
  pledged, or the price 35%+ under the price it was added at while below the 200-day average.
"""

from __future__ import annotations

import json
import os
from datetime import date

import numpy as np
import pandas as pd

from tradingagents.dataflows import india
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors import nse_results
from tradingagents.dataflows.vendors.yahoo.bulk import annual_statements, fundamentals_snapshot
from tradingagents.scanner import strategies as S
from tradingagents.scanner.data import MarketData

CR = 1e7  # one crore
MCAP_MIN_CR, MCAP_MAX_CR = 500.0, 30_000.0
ROE_MIN, DE_MAX, OPM_MIN = 0.18, 50.0, 0.12
SALES_CAGR_MIN, PROFIT_CAGR_MIN = 15.0, 20.0
PE_MAX, PEG_MAX = 60.0, 1.5
FROM_HIGH_MAX = 35.0
PROMOTER_MIN = 0.40
SALES5_CAGR_MIN = 12.0   # five-year sales CAGR, when the official history covers it
PLEDGE_MAX = 20.0        # % of promoter shares pledged
BREAK_PLEDGE = 50.0
# The story is broken: drop it from the list.
BREAK_ROE, BREAK_SALES_CAGR, BREAK_DE, BREAK_DRAWDOWN = 0.12, 8.0, 100.0, 35.0

PLAN = ("buy in 3 parts over 3-6 months, near the 50-day average; review every quarterly "
        "result; sell only when the story breaks (REMOVED)")


def _home() -> str:
    return os.path.dirname(get_config()["data_cache_dir"])


def list_path() -> str:
    return os.path.join(_home(), "multibaggers.json")


def load_list(path: str | None = None) -> dict:
    path = path or list_path()
    if not os.path.exists(path):
        return {"active": {}, "removed": []}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"active": {}, "removed": []}
    data.setdefault("active", {})
    data.setdefault("removed", [])
    return data


def save_list(data: dict, path: str | None = None) -> None:
    path = path or list_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    os.replace(tmp, path)


def _cagr(first: float, last: float, years: int) -> float | None:
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


BASIS_TOLERANCE = 0.10   # NSE and Yahoo must agree within 10% on an overlapping year to be merged


def merge_history(yahoo: dict, nse: list[dict]) -> dict:
    """One annual history per stock: NSE's official XBRL results (FY2017 onward) with
    Yahoo's last four years on top. NSE's older years are used only when both agree on the
    years they share (the same consolidated / standalone basis), so growth never spans a
    basis change. Lists are oldest first."""
    series = {k: dict(yahoo.get(k) or {}) for k in ("sales", "profit", "ocf", "fcf")}
    source = "Yahoo"
    official = {r["fy_end"]: r for r in nse if r.get("fy_end")}
    if official:
        overlap = [y for y in official if y in series["sales"] and official[y].get("revenue")]
        agree = overlap and all(abs(series["sales"][y] / official[y]["revenue"] - 1) <= BASIS_TOLERANCE
                                for y in overlap)
        if agree or not series["sales"]:
            for y, r in official.items():
                for key, col in (("sales", "revenue"), ("profit", "profit"), ("ocf", "ocf")):
                    if r.get(col) is not None:
                        series[key].setdefault(y, r[col])   # Yahoo wins on shared years
            first = min(official)[:4]
            source = f"NSE filings from FY{first} + Yahoo" if series["sales"] else "NSE filings"
        else:
            source = "Yahoo (NSE filings on a different basis)"
    out = {k: [v[y] for y in sorted(v)] for k, v in series.items()}
    out["years"] = sorted(series["sales"])
    out["source"] = source
    return out


def annual_history(symbols: list[str], stamp: str) -> dict[str, dict]:
    """Annual sales, profit and cash flow per symbol (NSE XBRL + Yahoo), plus NSE's promoter
    holding and pledge."""
    yahoo = annual_statements(symbols, stamp)
    out = {}
    for sym in symbols:  # NSE is paced inside the vendor; results are cached
        try:
            nse = nse_results.annual_results(sym)
        except Exception:
            nse = []
        try:
            own = nse_results.shareholding(sym)
        except Exception:
            own = {}
        out[sym] = {**merge_history(yahoo.get(sym) or {}, nse), **own}
    return out


def _chart(ind: pd.DataFrame) -> tuple[bool, str, float]:
    """(passes, words, % below the 52-week high) for a long-term uptrend."""
    r = ind.iloc[-1]
    sma200, prev = r["sma200"], ind["sma200"].iloc[-22] if len(ind) > 22 else np.nan
    below = (1 - r["Close"] / r["high52_incl"]) * 100 if r["high52_incl"] == r["high52_incl"] else np.nan
    if not (sma200 == sma200 and prev == prev):
        return False, "not enough history", below
    if r["Close"] <= sma200:
        return False, "below the 200-day average", below
    if sma200 <= prev:
        return False, "200-day average not rising", below
    if below > FROM_HIGH_MAX:
        return False, f"{below:.0f}% below its 52-week high", below
    return True, f"above a rising 200-day average, {below:.0f}% from its high", below


def evaluate(sym: str, ind: pd.DataFrame, f: dict, hist: dict) -> dict:
    """Every check for one stock: the numbers, what failed, and whether the story broke."""
    sales, profit = hist.get("sales") or [], hist.get("profit") or []
    ocf, fcf = hist.get("ocf") or [], hist.get("fcf") or []
    mcap = (f.get("marketCap") or 0) / CR
    roe, de, opm = f.get("returnOnEquity"), f.get("debtToEquity"), f.get("operatingMargins")
    pe = f.get("trailingPE")
    # Promoter holding and pledge: NSE's own shareholding filing; Yahoo's insider % is a stand-in.
    promoter = hist["promoter_pct"] / 100 if hist.get("promoter_pct") is not None else f.get("heldPercentInsiders")
    pledged = hist.get("pledged_pct")
    years = min(len(sales), len(profit)) - 1
    sales_cagr = _cagr(sales[-4] if len(sales) >= 4 else (sales[0] if sales else None),
                       sales[-1] if sales else None, min(3, len(sales) - 1)) if len(sales) >= 2 else None
    profit_cagr = _cagr(profit[-4] if len(profit) >= 4 else (profit[0] if profit else None),
                        profit[-1] if profit else None, min(3, len(profit) - 1)) if len(profit) >= 2 else None
    grew_every_year = len(sales) >= 3 and all(b > a for a, b in zip(sales[-4:], sales[-3:]))
    ocf_ok = sum(1 for x in ocf[-3:] if x > 0) >= 2 if ocf else False
    peg = pe / profit_cagr if pe and profit_cagr and profit_cagr > 0 else None
    # Longevity over five years when the official history reaches that far.
    sales5 = _cagr(sales[-6], sales[-1], 5) if len(sales) >= 6 else None
    up_years5 = sum(1 for a, b in zip(sales[-6:], sales[-5:]) if b > a) if len(sales) >= 6 else None
    chart_ok, chart, below = _chart(ind)
    fails = []
    if not MCAP_MIN_CR <= mcap <= MCAP_MAX_CR:
        fails.append(f"market cap Rs {mcap:,.0f} cr outside Rs {MCAP_MIN_CR:,.0f}-{MCAP_MAX_CR:,.0f} cr")
    if roe is None or roe < ROE_MIN:
        fails.append(f"ROE {roe * 100:.0f}% under 18%" if roe is not None else "no ROE data")
    if de is not None and de > DE_MAX:
        fails.append(f"debt/equity {de:.0f}% over 50%")
    if opm is None or opm < OPM_MIN:
        fails.append(f"operating margin {opm * 100:.0f}% under 12%" if opm is not None else "no margin data")
    if not ocf_ok:
        fails.append("operating cash flow not positive in 2 of the last 3 years")
    if sales_cagr is None or sales_cagr < SALES_CAGR_MIN:
        fails.append(f"3-year sales CAGR {sales_cagr:.0f}% under 15%" if sales_cagr is not None else "no sales history")
    if profit_cagr is None or profit_cagr < PROFIT_CAGR_MIN:
        fails.append(f"3-year profit CAGR {profit_cagr:.0f}% under 20%" if profit_cagr is not None else "no profit history")
    if not grew_every_year or (f.get("revenueGrowth") is not None and f["revenueGrowth"] <= 0):
        fails.append("sales did not grow every year")
    if pe is None or pe <= 0 or pe > PE_MAX:
        fails.append(f"P/E {pe:.0f} over 60" if pe and pe > 0 else "no positive P/E")
    if peg is None or peg > PEG_MAX:
        fails.append(f"PEG {peg:.2f} over 1.5" if peg is not None else "no PEG")
    if not chart_ok:
        fails.append(f"chart: {chart}")
    if sales5 is not None and sales5 < SALES5_CAGR_MIN:
        fails.append(f"5-year sales CAGR {sales5:.0f}% under {SALES5_CAGR_MIN:.0f}%")
    if up_years5 is not None and up_years5 < 4:
        fails.append(f"sales grew in only {up_years5} of the last 5 years")
    if pledged is not None and pledged > PLEDGE_MAX:
        fails.append(f"{pledged:.0f}% of promoter shares pledged (over {PLEDGE_MAX:.0f}%)")
    broken = []
    if roe is not None and roe < BREAK_ROE:
        broken.append(f"ROE fell to {roe * 100:.0f}%")
    if sales_cagr is not None and sales_cagr < BREAK_SALES_CAGR:
        broken.append(f"sales growth slowed to {sales_cagr:.0f}% a year")
    if de is not None and de > BREAK_DE:
        broken.append(f"debt/equity rose to {de:.0f}%")
    if pledged is not None and pledged > BREAK_PLEDGE:
        broken.append(f"{pledged:.0f}% of promoter shares pledged")
    score = 0.0
    for v, lo in ((roe, ROE_MIN), (sales_cagr and sales_cagr / 100, 0.15), (profit_cagr and profit_cagr / 100, 0.20)):
        if v:
            score += min(v / lo, 3.0)
    if peg:
        score += max(0.0, 2.0 - peg)
    if promoter is not None and promoter >= PROMOTER_MIN:
        score += 0.5
    if fcf and fcf[-1] > 0:
        score += 0.5
    return {
        "symbol": sym, "close": round(float(ind["Close"].iloc[-1]), 2),
        "sma200": round(float(ind["sma200"].iloc[-1]), 2) if ind["sma200"].iloc[-1] == ind["sma200"].iloc[-1] else None,
        "mcap_cr": round(mcap, 0), "roe_pct": _p(roe), "de_pct": round(de, 0) if de is not None else None,
        "opm_pct": _p(opm), "sales_cagr_pct": _r(sales_cagr), "profit_cagr_pct": _r(profit_cagr),
        "years": years, "pe": _r(pe), "peg": round(peg, 2) if peg is not None else None,
        "promoter_pct": _p(promoter), "pledged_pct": _r(pledged), "sales_5y_cagr_pct": _r(sales5),
        "up_years_5": up_years5, "history": f"{len(sales)} years ({hist.get('source', 'Yahoo')})",
        "fcf_positive": bool(fcf and fcf[-1] > 0), "chart": chart,
        "from_high_pct": _r(below), "fails": fails, "broken": broken, "passes": not fails,
        "score": round(score, 2),
    }


def _p(x):
    return round(float(x) * 100, 1) if x is not None else None


def _r(x):
    return round(float(x), 1) if x is not None and x == x else None


def _prefilter(f: dict) -> bool:
    """Cheap snapshot checks before the annual statements are fetched."""
    mcap = (f.get("marketCap") or 0) / CR
    roe, de = f.get("returnOnEquity"), f.get("debtToEquity")
    return (MCAP_MIN_CR <= mcap <= MCAP_MAX_CR and roe is not None and roe >= ROE_MIN
            and (de is None or de <= DE_MAX))


def update(md: MarketData, today: date | None = None, path: str | None = None) -> dict:
    """Screen every scanned stock, update the saved list and return it for the report."""
    today = today or md.last
    stamp = str(md.last)
    pool = {**md.stocks, **getattr(md, "micro", {})}
    pool = {s: d for s, d in pool.items() if d.index[-1] == md.nifty.index[-1] and len(d) >= 260}
    data = load_list(path)
    active = data["active"]
    funds = fundamentals_snapshot(sorted(pool), stamp=stamp)
    shortlist = sorted({s for s, f in funds.items() if _prefilter(f)} | (set(active) & set(pool)))
    hist = annual_history(shortlist, stamp)
    inds = {s: S.indicators(pool[s]) for s in shortlist}
    results = {s: evaluate(s, inds[s], funds.get(s) or {}, hist.get(s) or {}) for s in shortlist}

    added, removed = [], []
    for sym, res in results.items():
        sec = md.securities.get(sym)
        name = sec.name if sec else sym
        if sym in active:
            entry = active[sym]
            drawdown = (1 - res["close"] / entry["added_price"]) * 100
            broken = list(res["broken"])
            if drawdown >= BREAK_DRAWDOWN and res["sma200"] and res["close"] < res["sma200"]:
                broken.append(f"price {drawdown:.0f}% under where it was added, below the 200-day average")
            if broken:
                data["removed"].append({**entry, "removed_on": str(today), "removed_price": res["close"],
                                        "reason": "; ".join(broken)})
                removed.append(sym)
                del active[sym]
                continue
            entry.update(status="HOLD" if res["passes"] else "REVIEW",
                         note="" if res["passes"] else "; ".join(res["fails"][:2]),
                         last_checked=str(today), last=res)
        elif res["passes"]:
            active[sym] = {"symbol": sym, "name": name, "cap": india.cap_class(sym), "added_on": str(today),
                           "added_price": res["close"], "status": "NEW", "note": "", "last_checked": str(today),
                           "last": res}
            added.append(sym)
    # Anything on the list that no longer has data today stays as it was, marked for review.
    for sym, entry in active.items():
        if sym not in results and entry.get("last_checked") != str(today):
            entry.update(status="REVIEW", note="no fresh data today")
    save_list(data, path)
    rows = []
    for sym, e in active.items():
        last = e.get("last", {})
        now = last.get("close", e["added_price"])
        rows.append({**{k: e[k] for k in ("symbol", "name", "cap", "added_on", "added_price", "status", "note")},
                     "close": now, "since_added_pct": round((now / e["added_price"] - 1) * 100, 1),
                     **{k: last.get(k) for k in ("mcap_cr", "roe_pct", "de_pct", "sales_cagr_pct", "profit_cagr_pct",
                                                  "pe", "peg", "promoter_pct", "pledged_pct", "sales_5y_cagr_pct",
                                                  "up_years_5", "history", "fcf_positive", "chart", "score")}})
    order = {"NEW": 0, "HOLD": 1, "REVIEW": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 3), -(r["score"] or 0)))
    return {"as_of": stamp, "rows": rows, "added": added, "removed": removed,
            "removed_recent": data["removed"][-5:], "screened": len(pool), "checked": len(shortlist),
            "passed": sum(1 for r in results.values() if r["passes"]), "plan": PLAN,
            "note": "Not backtested and not a promise: a long-term watch list built from the SQGLP / "
                    "100-bagger traits. Most candidates will not become multibaggers."}


def active_symbols(path: str | None = None) -> set[str]:
    return set(load_list(path)["active"])
