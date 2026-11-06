"""The daily swing list: every NSE setup from six strategies, judged, planned and argued.

    from tradingagents.scanner.daily import run_daily
    result = run_daily(capital=500_000, risk_pct=1.0, top=10)

Verdicts (the ``grade`` field), in plain words:

- **GOOD**: the strategy is making money across NSE lately (last 12 months and last
  6 months positive per trade, counting only money-IN trades), money is flowing in
  (delivery % rising), results are not near, the news is clean.
- **OK**: one thing is off (money flow flat, results near, a mixed recent record, an
  institution selling in a bulk/block deal, or a weak market): take half size.
- **AVOID**: the strategy is losing money across NSE lately, or the news is bad.

Money OUT (delivery % falling under its 100-day average) drops the setup altogether.
The exit has no time limit: half at the target, the rest on a close below the 20 EMA.

10-year test (2017-2026, docs/STRATEGY.md): only the 52-week breakout made money in
every period; the VCP, flag, crossback and episodic pivot worked in rising markets and
lost in the weak 2024-26 one. So the verdict follows each strategy's live record.

Micro caps (below the top 500 by market cap) lost money on every strategy in the weak
2024-26 market, so they are scanned only when they trade Rs 25 crore+ a day, and they are
never GOOD: their verdict starts "MICRO CAP" and follows the strategy's record on micro
caps alone (AVOID when that record is losing or too thin).
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import pandas as pd

from tradingagents.dataflows import india
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors import google_news, nse_delivery
from tradingagents.dataflows.vendors.yahoo.bulk import next_earnings_date
from tradingagents.scanner import engine as E, strategies as S

NIFTY = "^NSEI"
ALLOWED_CAPS = ("Large", "Mid", "Small")
GRADE_ORDER = {"GOOD": 0, "OK": 1, "AVOID": 2}
GRADE_MEANING = {
    "GOOD": "GOOD: setup is working across NSE lately; take it",
    "OK": "OK: one risk to respect; half size",
    "AVOID": "AVOID: this setup is losing money lately or the news is bad",
}
RECORDS_VERSION = "v6"  # bump when the strategies change, so their records are recomputed
SWING_TARGET_BAND = (10.0, 20.0)
RECORDS_START = pd.Timestamp("2022-01-01")
EXIT_SHORT = "half at target, rest on 20-EMA close"
MONEY_TEXT = {
    "in": "IN (delivery % rising: funds accumulating)",
    "flat": "flat (delivery % not rising)",
    "exempt": "n/a (news gap)",
    "unknown": "no delivery data",
}

# Whole-word / phrase matches in headlines (case-insensitive). Crude by design:
# a flag says "read these headlines", it is not a sentiment model.
NEGATIVE_WORDS = (
    "fraud", "sebi notice", "sebi order", "sebi bans", "probe", "raid", "raids", "enforcement directorate",
    "income tax", "downgrade", "downgrades", "resigns", "resignation", "pledge", "default", "plunges",
    "crashes", "slumps", "tanks", "loss widens", "net loss", "penalty", "fined", "insolvency", "block deal",
    "stake sale", "offer for sale", "promoter sells", "misses estimates", "cuts target", "sell rating",
    "profit falls", "profit declines", "profit drops", "lower circuit",
)
POSITIVE_WORDS = (
    "order win", "bags order", "wins order", "secures order", "upgrade", "upgrades", "record high",
    "52-week high", "beats estimates", "profit jumps", "profit rises", "profit surges", "buyback",
    "bonus issue", "expansion", "approval", "buy rating", "raises target", "strong demand",
    "acquisition", "upper circuit",
)


def _matches(words, text: str) -> list[str]:
    return sorted({w for w in words if re.search(r"\b" + re.escape(w) + r"\b", text)})


@dataclass
class Idea:
    rank: int
    grade: str
    symbol: str
    name: str
    cap: str
    industry: str
    strategy: str
    strategy_label: str
    close: float
    entry_type: str
    entry: float
    max_entry: float
    stop: float
    target: float
    exit_rule: str
    risk_pct: float
    reward_pct: float
    rr: float
    hold_sessions: int
    exit_by: str
    quantity: int
    capital_needed: float
    max_loss: float
    size_note: str
    earnings_date: str | None
    earnings_in_window: bool
    hold: str = ""
    grade_meaning: str = ""
    news: list[dict] = field(default_factory=list)
    news_flag: str = "none found"
    bull: list[str] = field(default_factory=list)
    bear: list[str] = field(default_factory=list)
    verdict: str = ""
    tier: str = ""               # BEST / BETTER / GOOD / OK / AVOID (GOOD split by confirmations)
    confirmations: list[str] = field(default_factory=list)
    ud_ratio: float | None = None
    score: float = 0.0
    money_flow: str = ""          # in / flat / exempt / unknown (out is dropped)
    money_text: str = ""
    deliv_pct: float | None = None
    dp_trend: float | None = None
    deals: list[dict] = field(default_factory=list)


def hold_text(strategy: str, rec: dict) -> str:
    """How long to hold, from the strategy's own closed trades across NSE (no time limit)."""
    allr = rec.get("all", {})
    typ = allr.get("median_days")
    to_target = allr.get("median_days_to_target")
    if not typ:
        return "no time limit; trail the 20 EMA"
    text = f"typ. {typ:.0f} sessions"
    if to_target and to_target == to_target:  # not NaN
        text += f" (half sells at target in ~{to_target:.0f})"
    return text + "; no time limit"


def _universe() -> dict[str, india.IndianSecurity]:
    return {
        s.yahoo: s for s in india.nse_universe().values()
        if s.segment == "EQUITY" and s.series == "EQ" and india.cap_class(s.yahoo) in ALLOWED_CAPS
    }


def _trading_days_after(day: date, n: int) -> date:
    for _ in range(n):
        day = india.next_trading_day(day)
    return day


def _size(capital: float, risk_pct: float, entry: float, stop: float, factor: float) -> int:
    per_share = entry - stop
    if per_share <= 0 or capital <= 0:
        return 0
    by_risk = math.floor(capital * risk_pct / 100 * factor / per_share)
    by_cash = math.floor(capital * 0.25 / entry)
    return max(0, min(by_risk, by_cash))


def _records(inds, market, stamp: str, min_turnover_cr: float | None = None, tag: str = "") -> dict:
    """Each strategy's record over every allowed stock: since 2022, 12 and 6 months.
    ``min_turnover_cr``: only signals on bars that traded at least that much (micro caps)."""
    folder = os.path.join(get_config()["data_cache_dir"], "bulk")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"records-{RECORDS_VERSION}{tag}-{stamp}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    last = market.index[-1]
    out = {}

    def summary(df):
        r = E.summarize(df)
        if r.get("trades"):
            hit = df["days_to_target"].dropna()
            r["median_days_to_target"] = float(hit.median()) if not hit.empty else float("nan")
        return r

    for name in S.STRATEGIES:
        trades = []
        for ind in inds.values():
            got = S.backtest(name, ind, market, RECORDS_START)
            if min_turnover_cr is not None:
                got = [t for t in got if ind.at[t["signal_date"], "turnover_cr"] >= min_turnover_cr]
            trades += got
        df = pd.DataFrame(trades)
        if df.empty:
            out[name] = {k: {"trades": 0} for k in ("all", "12m", "6m")}
            continue
        out[name] = {
            "all": summary(df),
            "12m": summary(df[df.signal_date >= last - timedelta(days=365)]),
            "6m": summary(df[df.signal_date >= last - timedelta(days=182)]),
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=float)
    return out


def _grade(strategy: str, rec: dict, min_year: int = 30, min_six: int = 15) -> str:
    """The strategy's standing from its live record across NSE: GOOD, OK or AVOID."""
    six, year = rec.get("6m", {}), rec.get("12m", {})
    y = year.get("expectancy_r", -1) if year.get("trades", 0) >= min_year else -1
    h = six.get("expectancy_r", -1) if six.get("trades", 0) >= min_six else -1
    if y > 0 and h >= 0:
        return "GOOD"
    if y > 0 or h > 0 or strategy == "breakout":  # breakouts held up in every tested period
        return "OK"
    return "AVOID"


def _record_reason(rec: dict) -> str:
    """Why a setup's own record only earns OK, in plain words."""
    six, year = rec.get("6m", {}), rec.get("12m", {})
    if year.get("trades", 0) < 30 or six.get("trades", 0) < 15:
        return (f"too few recent trades to confirm it ({year.get('trades', 0)} in 12 months; "
                f"{rec.get('all', {}).get('expectancy_r', 0):+.2f}R a trade since 2022)")
    return (f"this setup's recent record is mixed ({year['expectancy_r']:+.2f}R last 12 months, "
            f"{six.get('expectancy_r', 0):+.2f}R last 6)")


def _demote(grade: str) -> str:
    return {"GOOD": "OK", "OK": "AVOID"}.get(grade, grade)


def _news(idea: Idea, days: int = 10) -> None:
    sec_name = idea.name.replace(" Limited", "").replace(" Ltd", "").replace(".", "")
    try:
        items = google_news.headlines(f'"{sec_name}" share OR stock', days=days, limit=8)
    except Exception:
        items = []
    idea.news = [
        {"when": it["published"].astimezone(india.IST).strftime("%d %b"), "title": it["title"]}
        for it in items[:5]
    ]
    text = " ".join(it["title"].lower() for it in items)
    neg = _matches(NEGATIVE_WORDS, text)
    pos = _matches(POSITIVE_WORDS, text)
    if neg and not pos:
        idea.news_flag = "negative: " + ", ".join(neg[:4])
    elif neg and pos:
        idea.news_flag = "mixed: +" + ", ".join(pos[:2]) + " / -" + ", ".join(neg[:2])
    elif pos:
        idea.news_flag = "positive: " + ", ".join(pos[:4])
    elif items:
        idea.news_flag = f"neutral ({len(items)} headlines)"


# Micro caps are judged on the setup's record on micro caps alone (thinner, so lower
# trade minimums), on the same scale as everything else, with a caution on top.
MICRO_MIN_YEAR, MICRO_MIN_SIX = 15, 8
MICRO_CAUTION = ("MICRO CAP caution: thin float, operator and circuit risk, the stop can gap "
                 "badly; use half the size you would use on a bigger stock")

# What lifts a GOOD setup to BETTER or BEST: each is a check successful traders use.
WIN_RATE_MIN = 40.0      # the setup's own success rate over the last 12 months
UD_MIN, UD_WEAK = 1.2, 0.8   # O'Neil's up/down volume ratio (50 days): accumulation vs distribution
RS_MIN = 80.0            # IBD / Minervini relative-strength rank: a leader


def confirmations(idea: "Idea", row: pd.Series, rec: dict) -> list[str]:
    """The extra checks a GOOD setup passes, in plain words."""
    out = []
    win = rec.get("12m", {}).get("win_rate")
    if win is not None and win == win and win >= WIN_RATE_MIN:
        out.append(f"success rate {win:.0f}% over 12 months")
    ud = row.get("ud_ratio")
    if ud is not None and ud == ud and ud >= UD_MIN:
        out.append(f"volume building up (up-day volume {ud:.2f}x down-day volume)")
    rs = row.get("rs_rank")
    if rs is not None and rs == rs and rs >= RS_MIN:
        out.append(f"a market leader (RS rank {rs:.0f})")
    return out


def tier_of(grade: str, confirmed: list[str]) -> str:
    """GOOD split by how many extra checks it passes: 3 BEST, 2 BETTER, else GOOD."""
    if grade != "GOOD":
        return grade
    return {3: "BEST", 2: "BETTER"}.get(len(confirmed), "GOOD")


def _debate(idea: Idea, row: pd.Series, market_row: pd.Series, rec: dict, mrec: dict | None = None) -> None:
    """A bull and a bear case built from the facts, so every idea is argued both ways."""
    rs = (row["ret126"] - market_row["nifty_ret126"]) * 100
    bull, bear = [], []
    if idea.strategy == "breakout":
        bull.append(f"New 52-week high on {row['Volume'] / row['vol50']:.1f}x average volume out of a "
                    f"{row['base_pct']:.0f}% base: buyers absorbed all supply from the past year.")
    elif idea.strategy == "vcp":
        bull.append(f"Minervini VCP: base tightened {row['c1']:.0f}% -> {row['c2']:.0f}% -> {row['c3']:.0f}% with "
                    f"volume drying up; passes all 8 Trend Template points (RS rank {row['rs_rank']:.0f}).")
    elif idea.strategy == "flag":
        bull.append(f"Qullamaggie flag: ran {row['run_pct']:.0f}% in 1-3 months, now a {row['c3']:.0f}% flag riding "
                    f"the rising 10/20-day averages (ADR {row['adr_pct']:.1f}%).")
    elif idea.strategy == "ep":
        bull.append(f"Episodic pivot: gapped {row['gap_pct']:.1f}% and closed {row['day_pct']:+.1f}% on "
                    f"{row['Volume'] / row['vol50']:.1f}x average volume: big news, big buyers.")
    elif idea.strategy in ("retest", "ct"):
        bull.append(f"Breakout + retest of the {S.RETEST_KINDS.get(int(row['rt_kind']), 'level')} at "
                    f"{row['rt_level']:,.2f}: broke it {row['rt_age']:.0f} sessions ago, "
                    f"pulled back to {row['rt_low']:,.2f} on {row['rt_pullvol']:.2f}x the breakout volume and held it; "
                    "old resistance is now support.")
    else:
        bull.append(f"Kell EMA crossback: a stage-2 leader (RS rank {row['rs_rank']:.0f}) dipped to its 20 EMA "
                    "and closed back above the 10 EMA and the prior day's high.")
    if rs > 0:
        bull.append(f"Outperformed the Nifty by {rs:.0f} pts over 6 months.")
    else:
        bear.append(f"Lagged the Nifty by {abs(rs):.0f} pts over 6 months.")
    if idea.rr >= 2:
        bull.append(f"Reward {idea.rr:.1f}x the risk, risk only {idea.risk_pct:.1f}% to the stop.")
    elif idea.rr < 1.2:
        bear.append(f"Thin reward:risk ({idea.rr:.1f} : 1) - one stop-out erases a win.")
    if idea.cap == "Large":
        bull.append("Large cap: deep liquidity, tight spreads, stop fills close to the price.")
    elif idea.cap == "Small":
        bear.append("Small cap: wider swings and gap risk; the stop can fill worse than planned.")
    elif idea.cap == "Micro":
        bear.append("Micro cap (below the top 500): thin float, operator and circuit risk; the stop can gap.")
    year = rec.get("12m", {})
    if year.get("trades"):
        line = (f"{S.LABELS[idea.strategy]} across NSE, last 12 months: {year['trades']} trades, "
                f"{year['win_rate']:.0f}% won, {year['expectancy_r']:+.2f}R per trade.")
        (bull if year["expectancy_r"] > 0 else bear).append(line)
    if market_row["nifty"] < market_row["nifty_sma200"]:
        bear.append("Nifty is below its 200-DMA: a weak tape where breakouts fail more often.")
    if market_row["breadth"] < 40:
        bear.append(f"Only {market_row['breadth']:.0f}% of stocks are above their 200-DMA (poor breadth).")
    if idea.money_flow == "in":
        bull.append(f"Money flowing in: delivery % is {idea.dp_trend:.2f}x its 100-day average "
                    f"({idea.deliv_pct:.0f}% delivered on the last day) - funds taking delivery, not day traders.")
    elif idea.money_flow == "flat":
        bear.append(f"Money flow flat: delivery % is only {idea.dp_trend:.2f}x its 100-day average; "
                    "no sign of funds accumulating yet.")
    inst_buy = [d for d in idea.deals if d["institution"] and d["side"] == "BUY"]
    inst_sell = [d for d in idea.deals if d["institution"] and d["side"] == "SELL"]
    for d in inst_buy[:2]:
        bull.append(f"{d['kind'].title()} deal: {d['client']} bought {d['qty']:,.0f} shares at {d['price']:,.2f}.")
    for d in inst_sell[:2]:
        bear.append(f"{d['kind'].title()} deal: {d['client']} sold {d['qty']:,.0f} shares at {d['price']:,.2f}.")
    if idea.earnings_in_window:
        bear.append(f"Results due {idea.earnings_date}, inside the typical hold: gap risk through the stop.")
    if idea.news_flag.startswith("negative"):
        bear.append(f"Headlines carry warning words ({idea.news_flag[10:]}). Read them before buying.")
    elif idea.news_flag.startswith("positive"):
        bull.append(f"Headlines supportive ({idea.news_flag[10:]}).")
    idea.bull, idea.bear = bull, bear
    # The verdict, in one plain sentence.
    micro = idea.cap == "Micro"
    if micro:
        rec = mrec or {}
        grade = _grade(idea.strategy, rec, MICRO_MIN_YEAR, MICRO_MIN_SIX)
    else:
        grade = _grade(idea.strategy, rec)
    ud = row.get("ud_ratio")
    idea.ud_ratio = _num(ud)
    if ud is not None and ud == ud:
        if ud >= UD_MIN:
            bull.append(f"Volume building up: up-day volume is {ud:.2f}x down-day volume over 50 days (accumulation).")
        elif ud < UD_WEAK:
            bear.append(f"Down-day volume is heavier ({ud:.2f}x): sellers have been in control (distribution).")
    reasons = []
    if idea.news_flag.startswith("negative"):
        grade, reasons = "AVOID", [f"bad headlines ({idea.news_flag[10:]})"]
    else:
        where = "on micro caps" if micro else "across NSE"
        if grade == "AVOID":
            reasons.append(f"this setup has lost money {where} over the last 6-12 months")
        elif grade == "OK":
            reasons.append(_record_reason(rec) + (" (micro-cap record)" if micro else ""))
        if ud is not None and ud == ud and ud < UD_WEAK and grade == "GOOD":
            grade = "OK"
            reasons.append(f"down-day volume heavier than up-day ({ud:.2f}x)")
        if idea.money_flow in ("flat", "unknown"):
            grade = "OK" if grade == "GOOD" else grade
            reasons.append("money flow is flat (delivery % not rising)" if idea.money_flow == "flat"
                           else "no delivery data to confirm buying")
        if inst_sell and grade == "GOOD":
            grade = "OK"
            reasons.append(f"an institution sold in a {inst_sell[0]['kind']} deal")
        if idea.earnings_in_window:
            grade = _demote(grade) if grade == "GOOD" else grade
            reasons.append(f"results on {idea.earnings_date} fall inside the typical hold (gap risk)")
        if market_row["nifty"] < market_row["nifty_sma200"] and grade == "GOOD":
            grade = "OK"
            reasons.append("Nifty is still below its 200-DMA")
    idea.grade, idea.grade_meaning = grade, GRADE_MEANING[grade]
    idea.confirmations = confirmations(idea, row, rec) if grade == "GOOD" else []
    idea.tier = tier_of(grade, idea.confirmations)
    if grade == "GOOD":
        why = {"breakout": "the best-tested setup (made money in every period since 2017)"}.get(
            idea.strategy, "this setup is making money " + ("on micro caps" if micro else "across NSE") + " lately")
        if idea.money_flow == "in":
            why += "; money flowing in"
        if idea.confirmations:
            why += "; " + "; ".join(idea.confirmations)
        text = f"{idea.tier}: {why}" + (f"; {'; '.join(reasons)}" if reasons else "")
    elif grade == "OK":
        text = "OK, half size: " + ("; ".join(reasons) or "one risk to respect")
    else:
        text = "AVOID: " + "; ".join(reasons)
    if micro:
        head, _, rest = text.partition(": ")
        text = f"{head} (MICRO CAP): {rest}; {MICRO_CAUTION}"
    idea.verdict = text


def _num(v) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if v != v else round(v, 2)


def _delivery(index: pd.DatetimeIndex) -> pd.DataFrame:
    """NSE delivery % (date x symbol) for the sessions the records and the scan need."""
    days = [d.date() for d in index if d >= RECORDS_START - timedelta(days=200)]
    try:
        return nse_delivery.history(days, workers=6)
    except Exception:  # delivery is a filter, never a reason to fail the scan
        return pd.DataFrame()


def money_snapshot(inds: dict, market: pd.DataFrame, universe: dict, deals: dict, top: int = 5) -> dict:
    """Where the money is going, today. Not trade signals: a watch list.

    - ``accumulation``: stage-2 leaders (Trend Template) with the strongest delivery %
      trend, i.e. funds taking delivery for a month while the stock holds its uptrend.
    - ``deals``: today's bulk/block deals by institutions in large/mid/small caps.
    """
    day = market.index[-1]
    rows = []
    for sym, ind in inds.items():
        if ind.index[-1] != day or "dp_trend" not in ind:  # ETFs carry no delivery column
            continue
        row = ind.iloc[-1]
        dpt = row.get("dp_trend")
        if dpt is None or dpt != dpt or dpt < S.MONEY_IN:
            continue
        if not (row["Close"] >= S.MIN_PRICE and row["turnover_cr"] >= S.MIN_TURNOVER_CR):
            continue
        if not bool(S.trend_template(ind.iloc[-30:]).iloc[-1]):
            continue
        sec = universe.get(sym)
        rows.append({
            "symbol": sym, "name": sec.name if sec else sym, "cap": india.cap_class(sym),
            "close": round(float(row["Close"]), 2), "dp_trend": round(float(dpt), 2),
            "deliv_pct": _num(row.get("deliv_pct")), "rs_rank": _num(row.get("rs_rank")),
            "from_high_pct": round((float(row["Close"]) / float(row["high52_incl"]) - 1) * 100, 1),
        })
    rows.sort(key=lambda r: (r["dp_trend"], r["rs_rank"] or 0), reverse=True)
    inst = []
    for sym, items in deals.items():
        if india.cap_class(sym) not in ALLOWED_CAPS:
            continue
        for d in items:
            if d["institution"]:
                inst.append({"symbol": sym, **d})
    inst.sort(key=lambda d: d["qty"] * d["price"], reverse=True)
    return {"accumulation": rows[:top], "deals": inst[:8]}


def run_daily(capital: float = 500_000.0, risk_pct: float = 1.0, top: int = 10,
              refresh: bool = False, progress=None, as_of: date | None = None,
              with_news: bool = True, md=None) -> dict:
    from tradingagents.scanner import data as data_mod

    md = md or data_mod.load(refresh=refresh, progress=progress, as_of=as_of)
    last = md.settled if as_of is None else min(as_of, md.settled)
    universe = md.securities
    nifty = md.nifty
    market = E.market_frame(nifty, md.stocks)
    inds = {s: S.indicators(d) for s, d in md.stocks.items()}
    micro_inds = {s: S.indicators(d) for s, d in getattr(md, "micro", {}).items()}
    S.add_rs_rank(inds, micro_inds)
    deliv = _delivery(market.index)
    for sym, ind in {**inds, **micro_inds}.items():
        col = sym.removesuffix(".NS")
        S.add_delivery(ind, deliv[col] if col in deliv else None)
    records = _records(inds, market, f"{md.last.isoformat()}-{len(inds)}")
    micro_records = (_records(micro_inds, market, f"{md.last.isoformat()}-{len(micro_inds)}",
                              min_turnover_cr=data_mod.MICRO_MIN_TURNOVER_CR, tag="-micro")
                     if micro_inds else {})
    core_inds = dict(inds)
    inds.update({s: S.indicators(d) for s, d in md.etfs.items()})
    inds.update(micro_inds)
    day = market.index[-1]
    mrow = market.iloc[-1]

    def horizon(name: str) -> int:
        """Sessions to check for results: the strategy's 75th-percentile hold (no sell-by date)."""
        p75 = records[name].get("all", {}).get("p75_days")
        return int(p75) if p75 and p75 == p75 else 30

    raw_ideas: list[tuple[Idea, pd.Series]] = []
    for sym, ind in inds.items():
        if ind.index[-1] != day:
            continue
        tail = ind.iloc[-260:]
        row = ind.iloc[-1]
        if sym in micro_inds and not row["turnover_cr"] >= data_mod.MICRO_MIN_TURNOVER_CR:
            continue
        if S.has_jump(tail):
            continue  # a demerger or unadjusted split in the last year: its levels are not real
        for name in S.STRATEGIES:
            if not bool(S.signals(name, tail, market).iloc[-1]):
                continue
            s = S.setup_for(name, row)
            if s is None or s.entry <= s.stop:
                continue
            mf = S.money_flow(name, row) if sym not in md.etfs else "unknown"
            if mf == "out":
                continue  # money leaving (delivery % falling): the worst group in every period
            if sym in micro_inds:
                grade = _grade(name, micro_records.get(name, {}), MICRO_MIN_YEAR, MICRO_MIN_SIX)
            else:
                grade = _grade(name, records[name])
            factor = 1.0 if grade == "GOOD" else 0.5
            target = s.target if s.target is not None else s.entry
            reward = target - s.entry
            rr = reward / (s.entry - s.stop) if reward > 0 else 0.0
            if not SWING_TARGET_BAND[0] - 0.05 <= reward / s.entry * 100 <= SWING_TARGET_BAND[1] + 0.05:
                continue  # outside the 10-20% target band
            qty = _size(capital, risk_pct, s.entry, s.stop, factor)
            sec = universe[sym]
            is_etf = sym in md.etfs
            idea = Idea(
                rank=0, grade=grade, symbol=sym, name=sec.name,
                cap="ETF" if is_etf else india.cap_class(sym),
                industry="ETF" if is_etf else india.industry(sym), strategy=name,
                strategy_label=S.LABELS[name],
                close=round(float(row["Close"]), 2), entry_type=s.entry_type, entry=s.entry,
                max_entry=round(s.entry * 1.03, 2) if s.entry_type == "stop" else round(s.entry * 1.01, 2),
                stop=s.stop, target=round(target, 2), exit_rule=s.exit_rule,
                risk_pct=round(s.risk_pct, 2), reward_pct=round(reward / s.entry * 100, 2), rr=round(rr, 2),
                hold_sessions=horizon(name), exit_by=EXIT_SHORT,
                quantity=qty, capital_needed=round(qty * s.entry, 0),
                max_loss=round(qty * (s.entry - s.stop), 0),
                size_note="half size" if factor < 1 else "full size",
                earnings_date=None, earnings_in_window=False,
                hold=hold_text(name, records[name]), grade_meaning=GRADE_MEANING[grade],
                money_flow=mf, money_text=MONEY_TEXT[mf],
                deliv_pct=_num(row.get("deliv_pct")), dp_trend=_num(row.get("dp_trend")),
            )
            year = records[name].get("12m", {})
            rs = row.get("rs_rank")
            idea.score = (
                -GRADE_ORDER[grade] * 10
                + (year.get("expectancy_r", 0) or 0) * 5
                + (0 if rs is None or rs != rs else (rs - 50) / 50)   # leaders first
                - idea.risk_pct * 0.2
                + min(rr, 3) * 0.3
                + {"Large": 0.3, "Mid": 0.2, "Small": 0.0, "ETF": 0.3, "Micro": -0.5}.get(idea.cap, 0.0)
                + {"in": 1.0, "exempt": 0.3}.get(mf, 0.0)
            )
            raw_ideas.append((idea, row))

    # One idea per stock: its best-graded strategy.
    best: dict[str, tuple[Idea, pd.Series]] = {}
    for idea, row in sorted(raw_ideas, key=lambda x: x[0].score, reverse=True):
        best.setdefault(idea.symbol, (idea, row))
    ranked = sorted(best.values(), key=lambda x: x[0].score, reverse=True)
    shortlist = ranked[: max(top * 2, top)]

    todays_deals = nse_delivery.deals() if with_news else {}

    def enrich(pair):
        idea, _ = pair
        idea.deals = todays_deals.get(idea.symbol.removesuffix(".NS"), [])
        when = None if idea.cap == "ETF" else next_earnings_date(idea.symbol)
        if when is not None and str(when) > str(day.date()):  # a past date is not the next one
            idea.earnings_date = str(when)
            idea.earnings_in_window = idea.earnings_date <= str(
                _trading_days_after(day.date(), idea.hold_sessions))
        if with_news:
            _news(idea)
        return pair

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        shortlist = list(pool.map(enrich, shortlist))
    for idea, row in shortlist:
        before = GRADE_ORDER[idea.grade]
        _debate(idea, row, mrow, records[idea.strategy], micro_records.get(idea.strategy))
        idea.score -= (GRADE_ORDER[idea.grade] - before) * 10 + (1 if idea.earnings_in_window else 0)
    tier_bonus = {"BEST": 2.0, "BETTER": 1.0}
    for idea, _ in shortlist:
        idea.score += tier_bonus.get(idea.tier, 0.0)
    shortlist.sort(key=lambda x: x[0].score, reverse=True)
    ideas = [i for i, _ in shortlist[:top]]
    for n, idea in enumerate(ideas, 1):
        idea.rank = n

    regime = bool(mrow["nifty"] > mrow["nifty_sma50"])
    notes = []
    if day.date() < last:
        notes.append(
            f"Yahoo has not published the {last} close yet (latest bar: {day.date()}), so these ideas "
            f"are from the {day.date()} close. Re-run in a while (add --refresh) for the {last} close."
        )
    if not regime:
        notes.append("Nifty is below its 50-DMA: breakout, VCP, flag and crossback setups are switched off; "
                      "only episodic pivots (news gaps) can appear. Trade small or stay out.")
    if not any(i.grade == "GOOD" for i in ideas):
        notes.append("No GOOD setup today: every candidate carries at least one risk. Half size, or wait.")
    market_state = {
        "nifty": round(float(mrow["nifty"]), 2), "nifty_sma50": round(float(mrow["nifty_sma50"]), 2),
        "nifty_sma200": round(float(mrow["nifty_sma200"]), 2),
        "nifty_ret_6m_pct": round(float(mrow["nifty_ret126"]) * 100, 1),
        "breadth_pct": round(float(mrow["breadth"]), 1), "filter_on": regime,
    }
    return json.loads(json.dumps({
        "as_of": str(day.date()),
        "market": market_state,
        "ideas": [asdict(i) for i in ideas],
        "candidates": len(best),
        "scanned": len(md.stocks),
        "etfs_scanned": len(md.etfs),
        "records": records,
        "micro_records": micro_records,
        "micro_scanned": len(micro_inds),
        "money": money_snapshot(core_inds, market, universe, todays_deals),
        "notes": notes,
        "capital": capital, "risk_pct": risk_pct,
    }, default=float))
