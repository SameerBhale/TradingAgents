"""Value buys (medium and long term): quality growth at a fair price, in a stage-2 uptrend.

NOT backtested: free fundamentals (Yahoo) are a present-day snapshot with no history,
so this screen has no tested record. It is a shortlist for your own research (and
for the stock-report skill), not a rule-tested signal like the momentum core.

The method borrows from William O'Neil's CAN SLIM (current and annual earnings growth,
a leader, institutions buying) and Minervini's SEPA (buy only in a stage-2 uptrend):

Screen (large, mid and small caps, the 250 most traded):

- Chart: Minervini's stage 2 (above the 150 and 200-day averages, the 200-day rising,
  within 25% of the 52-week high): the market is already re-rating it.
- Quality: ROE >= 15%, debt/equity <= 100%, operating margin >= 10%.
- Growth: revenue and earnings growing. A profit jump over 100% on revenue growth under
  30% is treated as a one-off (a low base, an other-income gain, a commodity spike) and
  dropped, as is a cyclical (oil, metals, mining) at a P/E under 8: peak-cycle earnings.
- Price: P/E at or below its sector's median among the candidates, PEG <= 1.5.
- Plan (medium term): stop 10-15% below (under the 50-day average), target 2R
  (20-30%), hold 3-12 months, review on every quarterly result.
"""

from __future__ import annotations

import concurrent.futures as cf
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from tradingagents.dataflows import india
from tradingagents.dataflows.vendors import google_news
from tradingagents.dataflows.vendors.yahoo.bulk import fundamentals_snapshot
from tradingagents.scanner import strategies as S
from tradingagents.scanner.data import MarketData

STOP_MIN, STOP_MAX, TARGET_R = 10.0, 15.0, 2.0
CYCLICAL = ("oil", "gas", "metal", "mining", "steel", "coal", "petro", "refin")


@dataclass
class ValuePick:
    rank: int
    symbol: str
    name: str
    cap: str
    sector: str
    close: float
    pe: float | None
    sector_pe: float | None
    pb: float | None
    roe_pct: float | None
    debt_equity: float | None
    revenue_growth_pct: float | None
    earnings_growth_pct: float | None
    op_margin_pct: float | None
    dividend_yield_pct: float | None
    analyst_target: float | None
    analysts: int | None
    pattern: str
    entry: float
    max_entry: float
    stop: float
    target: float
    risk_pct: float
    reward_pct: float
    rr: float
    hold: str
    score: float
    concall: list[dict] = field(default_factory=list)
    why: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


def _pct(x):
    return None if x is None else round(float(x) * 100, 1)


def _pattern(ind: pd.DataFrame) -> str | None:
    """Stage 2 only: above the 150 and 200-day averages, the 200-day rising, near the high."""
    r = ind.iloc[-1]
    stage2 = (
        r["Close"] > r["sma150"] > r["sma200"] and r["sma200"] > ind["sma200"].iloc[-22]
        and r["Close"] >= r["high52_incl"] * 0.75
    )
    if not stage2:
        return None
    if r["Close"] >= r["high52_incl"] * 0.95:
        return "stage-2 uptrend, at its 52-week high"
    if r["Close"] > r["sma50"]:
        return "stage-2 uptrend, above the 50-day"
    return "stage-2 uptrend, resting at the 50-day"


def _concall(name: str) -> list[dict]:
    q = f'"{name}" concall OR "earnings call" OR guidance OR "management commentary"'
    try:
        items = google_news.headlines(q, days=60, limit=12)
    except Exception:
        return []
    # Keep headlines that name the company (the search also returns its peers).
    words = [w for w in name.lower().replace("(", " ").replace(")", " ").split() if w not in ("the", "of", "and")]
    key = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "")
    own = [it for it in items if key and key in it["title"].lower()]
    return [{"when": it["published"].astimezone(india.IST).strftime("%d %b"), "title": it["title"]}
            for it in own[:4]]


def value_picks(md: MarketData, top: int = 3, with_news: bool = True) -> dict:
    rows = []
    for sym, d in md.stocks.items():
        if d.index[-1] != md.nifty.index[-1] or len(d) < 260:
            continue
        turnover = float((d["Close"] * d["Volume"]).iloc[-20:].mean())
        rows.append((sym, turnover))
    liquid = [s for s, _ in sorted(rows, key=lambda x: x[1], reverse=True)[:250]]
    inds = {s: S.indicators(md.stocks[s]) for s in liquid}
    sound = {s: p for s, ind in inds.items() if (p := _pattern(ind)) is not None}
    funds = fundamentals_snapshot(sorted(sound), stamp=str(md.last))

    cands = []
    for sym, pattern in sound.items():
        f = funds.get(sym) or {}
        pe, roe, de = f.get("trailingPE"), f.get("returnOnEquity"), f.get("debtToEquity")
        rg, eg, om = f.get("revenueGrowth"), f.get("earningsGrowth"), f.get("operatingMargins")
        if None in (pe, roe, rg, eg, om) or pe <= 0:
            continue
        if roe < 0.15 or (de is not None and de > 100) or om < 0.10 or rg <= 0 or eg <= 0:
            continue
        if eg > 1.0 and rg < 0.30:
            continue  # a one-off profit jump, not growth
        sector = (india.industry(sym) or f.get("sector") or "").lower()
        if pe < 8 and any(w in sector for w in CYCLICAL):
            continue  # a cyclical at peak earnings looks cheap right before it is not
        peg = pe / (eg * 100) if eg > 0 else np.inf
        if peg > 1.5:
            continue
        cands.append({"symbol": sym, "pattern": pattern, "f": f, "pe": pe, "roe": roe, "eg": eg, "rg": rg,
                      "om": om, "peg": peg, "sector": india.industry(sym) or f.get("sector") or "-"})
    if not cands:
        return {"picks": [], "screened": len(sound), "note": "No stock passed every quality, growth and price test."}
    df = pd.DataFrame(cands)
    df["sector_pe"] = df.groupby("sector")["pe"].transform("median")
    df = df[df["pe"] <= df["sector_pe"] * 1.05]
    for col, asc in (("roe", False), ("eg", False), ("rg", False), ("peg", True), ("om", False)):
        df[f"r_{col}"] = df[col].rank(ascending=asc, pct=True)
    df["score"] = df[[c for c in df.columns if c.startswith("r_")]].mean(axis=1)
    df = df.sort_values("score").head(top)

    picks = []
    for n, (_, c) in enumerate(df.iterrows(), 1):
        sym, f = c["symbol"], c["f"]
        ind = inds[sym]
        row = ind.iloc[-1]
        entry = round(float(row["Close"]), 2)
        stop = max(min(float(row["sma50"]) * 0.98, entry * (1 - STOP_MIN / 100)), entry * (1 - STOP_MAX / 100))
        risk = entry - stop
        target = entry + TARGET_R * risk
        sec = md.securities.get(sym)
        p = ValuePick(
            rank=n, symbol=sym, name=sec.name if sec else sym, cap=india.cap_class(sym), sector=c["sector"],
            close=entry, pe=round(c["pe"], 1), sector_pe=round(float(c["sector_pe"]), 1),
            pb=round(f["priceToBook"], 2) if f.get("priceToBook") else None, roe_pct=_pct(c["roe"]),
            debt_equity=round(f["debtToEquity"], 0) if f.get("debtToEquity") is not None else None,
            revenue_growth_pct=_pct(c["rg"]), earnings_growth_pct=_pct(c["eg"]), op_margin_pct=_pct(c["om"]),
            dividend_yield_pct=round(float(f["dividendYield"]), 2) if f.get("dividendYield") else None,
            analyst_target=round(f["targetMeanPrice"], 2) if f.get("targetMeanPrice") else None,
            analysts=f.get("numberOfAnalystOpinions"), pattern=c["pattern"],
            entry=entry, max_entry=round(entry * 1.01, 2), stop=round(stop, 2), target=round(target, 2),
            risk_pct=round(risk / entry * 100, 2), reward_pct=round((target / entry - 1) * 100, 2), rr=TARGET_R,
            hold="3-12 months; review on each quarterly result", score=round(float(c["score"]), 3),
        )
        p.why = [
            f"ROE {p.roe_pct}%, operating margin {p.op_margin_pct}%, debt/equity {p.debt_equity}%.",
            f"Earnings +{p.earnings_growth_pct}%, revenue +{p.revenue_growth_pct}% year on year.",
            f"P/E {p.pe} vs sector median {p.sector_pe}; PEG {c['peg']:.2f}.",
            f"Chart: {p.pattern}.",
        ]
        if p.analyst_target:
            p.why.append(f"Analyst mean target {p.analyst_target} ({p.analysts} analysts).")
        if c["eg"] > 1.0:
            p.risks.append("Earnings growth over 100% (revenue kept pace, so likely real); confirm in the concall.")
        if p.cap == "Small":
            p.risks.append("Small cap: thinner liquidity and larger swings.")
        p.risks.append("Fundamentals are today's Yahoo snapshot; confirm in the latest results.")
        picks.append(p)
    if with_news:
        with cf.ThreadPoolExecutor(max_workers=5) as pool:
            for p, news in zip(picks, pool.map(lambda x: _concall(x.name.replace(" Limited", "")), picks), strict=True):
                p.concall = news
    return {"picks": [asdict(p) for p in picks], "screened": len(sound), "passed": len(df),
            "note": "Value picks are not backtested: fundamentals are a present-day snapshot."}
