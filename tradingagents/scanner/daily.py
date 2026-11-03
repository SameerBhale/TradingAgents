"""The daily top-10: every NSE setup from four strategies, graded, planned and argued.

    from tradingagents.scanner.daily import run_daily
    result = run_daily(capital=500_000, risk_pct=1.0, top=10)

Grades (from testing on every NSE stock since 2022, see docs/breakout_research.md):

- **A**: a 52-week breakout. The only setup that stayed profitable after costs in
  both the 2022-24 rising market and the weak 2024-26 market.
- **B**: a pivot, pullback or RSI(2) setup whose strategy is profitable over its
  own last 6 months of trades across the market. These worked in rising markets
  and lost in weak ones, so they are traded only while their live record is positive.
- **C**: the same setups while their strategy's last 6 months are negative: shown to
  fill the list and for learning, at half size or as paper trades only.

Micro caps (below the Nifty Smallcap 250) are excluded: they lost money on every
strategy in the weak market.
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
from tradingagents.dataflows.vendors import google_news
from tradingagents.dataflows.vendors.yahoo.bulk import download_daily, next_earnings_date
from tradingagents.scanner import engine as E, strategies as S

NIFTY = "^NSEI"
ALLOWED_CAPS = ("Large", "Mid", "Small")
GRADE_ORDER = {"A": 0, "B": 1, "C": 2}

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
    news: list[dict] = field(default_factory=list)
    news_flag: str = "none found"
    bull: list[str] = field(default_factory=list)
    bear: list[str] = field(default_factory=list)
    verdict: str = ""
    score: float = 0.0


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


def _records(inds, market, stamp: str) -> dict:
    """Each strategy's record over every allowed stock: since 2022, 12 and 6 months."""
    folder = os.path.join(get_config()["data_cache_dir"], "bulk")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"records-{stamp}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    last = market.index[-1]
    out = {}
    for name in S.STRATEGIES:
        trades = []
        for ind in inds.values():
            trades += S.backtest(name, ind, market, pd.Timestamp("2022-01-01"))
        df = pd.DataFrame(trades)
        if df.empty:
            out[name] = {k: {"trades": 0} for k in ("all", "12m", "6m")}
            continue
        out[name] = {
            "all": E.summarize(df),
            "12m": E.summarize(df[df.signal_date >= last - timedelta(days=365)]),
            "6m": E.summarize(df[df.signal_date >= last - timedelta(days=182)]),
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=float)
    return out


def _grade(strategy: str, rec: dict) -> str:
    if strategy == "breakout":
        return "A"
    six, year = rec.get("6m", {}), rec.get("12m", {})
    working = (
        six.get("trades", 0) >= 20 and six.get("expectancy_r", -1) >= 0.05
        and year.get("trades", 0) >= 40 and year.get("expectancy_r", -1) > 0
    )
    return "B" if working else "C"


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


def _debate(idea: Idea, row: pd.Series, market_row: pd.Series, rec: dict) -> None:
    """A bull and a bear case built from the facts, so every idea is argued both ways."""
    rs = (row["ret126"] - market_row["nifty_ret126"]) * 100
    bull, bear = [], []
    if idea.strategy == "breakout":
        bull.append(f"New 52-week high on {row['Volume'] / row['vol50']:.1f}x average volume out of a "
                    f"{row['base_pct']:.0f}% base: buyers absorbed all supply from the past year.")
    elif idea.strategy == "pivot":
        bull.append(f"Coiling {(1 - row['Close'] / row['high52_incl']) * 100:.1f}% under its 52-week high in a "
                    f"{row['base_pct']:.0f}% base with volume drying up; the buy-stop fills only on a breakout.")
    elif idea.strategy == "pullback":
        bull.append("Uptrend intact (above 50 and 200-DMA); the dip to the 20-DMA was bought with a "
                    "close above the prior day's high.")
    else:
        bull.append(f"Short-term washout (RSI(2) {row['rsi2']:.0f}) inside a long-term uptrend; such dips "
                    "usually snap back to the 5-DMA within days.")
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
    six = rec.get("6m", {})
    if six.get("trades"):
        line = (f"{S.LABELS[idea.strategy]} across NSE, last 6 months: {six['trades']} trades, "
                f"{six['win_rate']:.0f}% won, {six['expectancy_r']:+.2f}R per trade.")
        (bull if six["expectancy_r"] > 0 else bear).append(line)
    if market_row["nifty"] < market_row["nifty_sma200"]:
        bear.append("Nifty is below its 200-DMA: a weak tape where breakouts fail more often.")
    if market_row["breadth"] < 40:
        bear.append(f"Only {market_row['breadth']:.0f}% of stocks are above their 200-DMA (poor breadth).")
    if idea.earnings_in_window:
        bear.append(f"Results due {idea.earnings_date}, inside the holding window: gap risk through the stop.")
    if idea.news_flag.startswith("negative"):
        bear.append(f"Headlines carry warning words ({idea.news_flag[10:]}). Read them before buying.")
    elif idea.news_flag.startswith("positive"):
        bull.append(f"Headlines supportive ({idea.news_flag[10:]}).")
    if idea.grade == "C":
        bear.append("Its strategy is losing money across the market lately: half size or paper trade.")
    idea.bull, idea.bear = bull, bear
    if idea.news_flag.startswith("negative"):
        idea.verdict = "SKIP unless the news checks out"
    elif idea.grade == "A" and not idea.earnings_in_window:
        idea.verdict = "TAKE (best-tested setup)"
    elif idea.grade == "C":
        idea.verdict = "PAPER / HALF SIZE"
    elif idea.earnings_in_window:
        idea.verdict = "CAUTION: results inside the hold"
    else:
        idea.verdict = "TAKE at normal size" if idea.grade == "B" else "TAKE"


def run_daily(capital: float = 500_000.0, risk_pct: float = 1.0, top: int = 10,
              refresh: bool = False, progress=None, as_of: date | None = None,
              with_news: bool = True) -> dict:
    universe = _universe()
    settled = india.market_status().last_completed_session
    last = min(as_of, settled) if as_of else settled
    raw = download_daily(list(universe) + [NIFTY], period="5y", stamp=settled.isoformat(),
                         progress=progress, refresh=refresh, probe=NIFTY)
    if NIFTY not in raw:
        raise RuntimeError("Yahoo returned no Nifty 50 data; try again shortly with --refresh.")
    cut = pd.Timestamp(last)
    nifty = raw.pop(NIFTY)
    nifty = nifty[nifty.index <= cut]
    data = {s: d[d.index <= cut] for s, d in raw.items() if s in universe}
    data = {s: d for s, d in data.items() if len(d) > 260}
    market = E.market_frame(nifty, data)
    inds = {s: S.indicators(d) for s, d in data.items()}
    records = _records(inds, market, f"{last.isoformat()}-{len(inds)}")
    day = market.index[-1]
    mrow = market.iloc[-1]

    raw_ideas: list[tuple[Idea, pd.Series]] = []
    for sym, ind in inds.items():
        if ind.index[-1] != day:
            continue
        tail = ind.iloc[-260:]
        row = ind.iloc[-1]
        for name in S.STRATEGIES:
            if not bool(S.signals(name, tail, market).iloc[-1]):
                continue
            s = S.setup_for(name, row)
            if s is None or s.entry <= s.stop:
                continue
            grade = _grade(name, records[name])
            factor = 0.5 if grade == "C" else 1.0
            target = s.target if s.target is not None else s.entry
            reward = target - s.entry
            rr = reward / (s.entry - s.stop) if reward > 0 else 0.0
            qty = _size(capital, risk_pct, s.entry, s.stop, factor)
            sec = universe[sym]
            idea = Idea(
                rank=0, grade=grade, symbol=sym, name=sec.name, cap=india.cap_class(sym),
                industry=india.industry(sym), strategy=name, strategy_label=S.LABELS[name],
                close=round(float(row["Close"]), 2), entry_type=s.entry_type, entry=s.entry,
                max_entry=round(s.entry * 1.03, 2) if s.entry_type == "stop" else round(s.entry * 1.01, 2),
                stop=s.stop, target=round(target, 2), exit_rule=s.exit_rule,
                risk_pct=round(s.risk_pct, 2), reward_pct=round(reward / s.entry * 100, 2), rr=round(rr, 2),
                hold_sessions=s.max_hold, exit_by=str(_trading_days_after(day.date(), s.max_hold)),
                quantity=qty, capital_needed=round(qty * s.entry, 0),
                max_loss=round(qty * (s.entry - s.stop), 0),
                size_note="half size (strategy not working lately)" if factor < 1 else "full size",
                earnings_date=None, earnings_in_window=False,
            )
            six = records[name].get("6m", {})
            idea.score = (
                -GRADE_ORDER[grade] * 10
                + (six.get("expectancy_r", 0) or 0) * 5
                - idea.risk_pct * 0.2
                + min(rr, 3) * 0.3
                + {"Large": 0.3, "Mid": 0.2, "Small": 0.0}[idea.cap]
            )
            raw_ideas.append((idea, row))

    # One idea per stock: its best-graded strategy.
    best: dict[str, tuple[Idea, pd.Series]] = {}
    for idea, row in sorted(raw_ideas, key=lambda x: x[0].score, reverse=True):
        best.setdefault(idea.symbol, (idea, row))
    ranked = sorted(best.values(), key=lambda x: x[0].score, reverse=True)
    shortlist = ranked[: max(top * 2, top)]

    def enrich(pair):
        idea, _ = pair
        when = next_earnings_date(idea.symbol)
        if when is not None and str(when) > str(day.date()):  # a past date is not the next one
            idea.earnings_date = str(when)
            idea.earnings_in_window = idea.earnings_date <= idea.exit_by
        if with_news:
            _news(idea)
        return pair

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        shortlist = list(pool.map(enrich, shortlist))
    for idea, row in shortlist:
        if idea.news_flag.startswith("negative"):
            idea.score -= 3
        if idea.earnings_in_window:
            idea.score -= 1
        _debate(idea, row, mrow, records[idea.strategy])
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
        notes.append("Nifty is below its 50-DMA: breakout, pivot and pullback setups are switched off; "
                      "only RSI(2) dips can appear. Trade small or stay out.")
    if not any(i.grade == "A" for i in ideas):
        notes.append("No grade-A breakout today. Grade B/C ideas are weaker: their strategies lost money "
                     "in the weak 2024-26 market. Prefer half size or paper trades.")
    return json.loads(json.dumps({
        "as_of": str(day.date()),
        "market": {
            "nifty": round(float(mrow["nifty"]), 2), "nifty_sma50": round(float(mrow["nifty_sma50"]), 2),
            "nifty_sma200": round(float(mrow["nifty_sma200"]), 2),
            "nifty_ret_6m_pct": round(float(mrow["nifty_ret126"]) * 100, 1),
            "breadth_pct": round(float(mrow["breadth"]), 1), "filter_on": regime,
        },
        "ideas": [asdict(i) for i in ideas],
        "candidates": len(best),
        "scanned": len(inds),
        "records": records,
        "notes": notes,
        "capital": capital, "risk_pct": risk_pct,
    }, default=float))
