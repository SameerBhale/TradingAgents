"""The momentum core: the survival strategy's main engine (see docs/STRATEGY.md).

Rules (tested on 10 years of NSE data, 2017-2026, point-in-time universe, after
0.3% round-trip costs: +15.1% a year, worst drawdown -20.1%, worst year -10%;
Nifty 50 buy-and-hold: +11.3% a year, worst drawdown -38%):

1. Universe: the 100 most traded NSE stocks (20-day average traded value),
   price >= Rs 100, each above its own 200-day average.
2. Score: risk-adjusted momentum = the 12-month return skipping the last month,
   divided by the annualized volatility of the last 12 months.
3. Hold the top 20, equal weight. Review on the last trading day of each month:
   keep a holding while its rank stays within 40; replace those that fall out.
4. Regime: when the Nifty 50 closes the month below its 200-day average, sell
   everything and park in a liquid ETF (LIQUIDBEES) until it is back above.
5. Stoploss: -15% from your buy price, checked on closes; after a stop, the slot
   waits in LIQUIDBEES until the next monthly review.
6. Holding time: no target. In testing a position was held a median of 62 days
   (half of them 31-124 days), i.e. 1-4 months, until it dropped out of the top 40.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd

from tradingagents.dataflows import india
from tradingagents.scanner.data import MarketData

TOP_UNIVERSE = 100
TOP_N = 20
KEEP_RANK = 40
STOP_PCT = 15.0
MIN_PRICE = 100.0
HOLD_TEXT = "1-4 months (median ~2 months); sell only at a monthly review or on the stop"
MODES = {
    # regime off ->  fraction of the core kept in stocks; tested 2017-2026 after costs
    "safe": {"invested_when_off": 0.0, "cagr_pct": 15.1, "max_drawdown_pct": 20.1},
    "balanced": {"invested_when_off": 0.5, "cagr_pct": 14.3, "max_drawdown_pct": 20.7},
    "aggressive": {"invested_when_off": 1.0, "cagr_pct": 13.2, "max_drawdown_pct": 32.4},
}
RECORD = {
    "period": "Jan 2017 - Oct 2026", "cagr_pct": 15.1, "max_drawdown_pct": 20.1, "worst_year_pct": -10.0,
    "nifty_cagr_pct": 11.3, "nifty_max_drawdown_pct": 38.4, "median_hold_days": 62,
    "yearly_pct": {2017: 6, 2018: -10, 2019: 2, 2020: 28, 2021: 51, 2022: 0, 2023: 55, 2024: 24, 2025: 5, 2026: 4},
}


@dataclass
class CorePick:
    rank: int
    symbol: str
    name: str
    cap: str
    industry: str
    close: float
    score: float
    ret_12_1_pct: float
    vol_pct: float
    action: str            # BUY / HOLD / SELL
    entry: float           # your buy price if held, else the latest close (buy at next open)
    max_entry: float
    stop: float
    quantity: int
    capital_needed: float
    hold: str
    review_on: str


def month_end(day: date) -> date:
    """The last NSE trading day of ``day``'s month."""
    d = (pd.Timestamp(day) + pd.offsets.MonthEnd(0)).date()
    while not india.is_trading_day(d):
        d = india.previous_trading_day(d)
    return d


def _action(on: bool, invested: float, held: bool) -> str:
    if on:
        return "HOLD" if held else "BUY"
    if invested == 0:
        return "SELL (regime off)" if held else "WAIT"
    if invested < 1:
        return "HOLD (half)" if held else "BUY (half size)"
    return "HOLD" if held else "BUY"


def ranking(md: MarketData) -> pd.DataFrame:
    """Every eligible stock's risk-adjusted momentum as of the latest close, best first."""
    rows = []
    for sym, d in md.stocks.items():
        c = d["Close"]
        if len(c) < 260 or c.index[-1] != md.nifty.index[-1]:
            continue
        turnover = float((c * d["Volume"]).iloc[-20:].mean())
        price = float(c.iloc[-1])
        sma200 = float(c.iloc[-200:].mean())
        ret = float(c.iloc[-22] / c.iloc[-253] - 1)
        vol = float(c.pct_change().iloc[-252:].std() * np.sqrt(252))
        rows.append({"symbol": sym, "close": price, "turnover": turnover, "above200": price > sma200,
                     "ret": ret, "vol": vol, "score": ret / vol if vol > 0 else np.nan})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["close"] >= MIN_PRICE]
    df = df.nlargest(TOP_UNIVERSE, "turnover")
    df = df[df["above200"]].dropna(subset=["score"]).sort_values("score", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    return df


def regime_on(md: MarketData) -> bool:
    c = md.nifty["Close"]
    return bool(c.iloc[-1] > c.iloc[-200:].mean())


def core_picks(md: MarketData, core_capital: float, held: dict[str, float] | None = None,
               mode: str = "balanced") -> dict:
    """The target portfolio now, with BUY/HOLD/SELL against ``held`` ({symbol: buy price}).

    ``mode`` sets what happens while the Nifty is below its 200-DMA: "safe" buys
    nothing (WAIT), "balanced" buys at half size, "aggressive" at full size.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    held = held or {}
    rank = ranking(md)
    review = month_end(md.last)
    if review <= md.last:
        review = month_end((pd.Timestamp(md.last) + pd.offsets.MonthBegin(1)).date())
    on = regime_on(md)
    ranks = dict(zip(rank["symbol"], rank["rank"], strict=False)) if not rank.empty else {}
    keep = [s for s in held if ranks.get(s, 10**9) <= KEEP_RANK]
    fresh = [s for s in rank["symbol"] if s not in keep][: max(0, TOP_N - len(keep))]
    target = keep + fresh  # with the regime off this is the on-deck list, all WAIT
    invested = 1.0 if on else MODES[mode]["invested_when_off"]
    per_slot = core_capital / TOP_N * invested
    picks: list[CorePick] = []
    info = rank.set_index("symbol") if not rank.empty else pd.DataFrame()
    for sym in target:
        r = info.loc[sym]
        buy = held.get(sym)
        entry = round(buy if buy else float(r["close"]), 2)
        qty = int(per_slot // float(r["close"]))
        sec = md.securities.get(sym)
        picks.append(CorePick(
            rank=int(r["rank"]), symbol=sym, name=sec.name if sec else sym, cap=india.cap_class(sym),
            industry=india.industry(sym), close=round(float(r["close"]), 2), score=round(float(r["score"]), 2),
            ret_12_1_pct=round(float(r["ret"]) * 100, 1), vol_pct=round(float(r["vol"]) * 100, 1),
            action=_action(on, invested, bool(buy)), entry=entry,
            max_entry=round(float(r["close"]) * 1.01, 2) if not buy else entry,
            stop=round(entry * (1 - STOP_PCT / 100), 2), quantity=qty,
            capital_needed=round(qty * float(r["close"]), 0), hold=HOLD_TEXT, review_on=str(review),
        ))
    picks.sort(key=lambda p: p.rank)
    sells = []
    for sym, buy in held.items():
        if sym in target and (on or invested > 0):
            continue
        last = md.stocks.get(sym)
        px = float(last["Close"].iloc[-1]) if last is not None else None
        why = ("market regime OFF (Nifty below its 200-DMA), safe mode: move to LIQUIDBEES" if not on and invested == 0
               else f"rank {ranks.get(sym, 'unranked')} is outside the top {KEEP_RANK} or below its 200-DMA")
        sells.append({"symbol": sym, "buy_price": buy, "close": px, "reason": why})
    for p in picks:  # a held stock already through its stop
        if p.action == "HOLD" and p.close <= p.stop:
            p.action = "SELL (stop hit)"
    c = md.nifty["Close"]
    return {
        "regime_on": on,
        "mode": mode, "invested_pct": round(invested * 100),
        "modes": MODES,
        "nifty": round(float(c.iloc[-1]), 2), "nifty_sma200": round(float(c.iloc[-200:].mean()), 2),
        "review_on": str(review),
        "core_capital": core_capital,
        "picks": [asdict(p) for p in picks],
        "sells": sells,
        "record": RECORD,
        "rules": __doc__,
    }
