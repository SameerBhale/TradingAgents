"""Four simple swing setups for NSE stocks, one simulator, one honest record each.

All are long-only, daily-bar, delivery trades. Rules are the textbook versions
(no heavy tuning) and were tested on every NSE mainboard stock since 2022:

- ``breakout``: a close at a new 52-week high on volume out of a tight base
  (``engine.DEFAULT``-style rule). Buy-stop above the signal day's high.
- ``pivot``: the same tight base still just UNDER its 52-week high, volume
  drying up (Minervini-style volatility contraction). Buy-stop above the
  52-week high: it fills only if the breakout happens.
- ``pullback``: a strong uptrend dips to its 20-DMA and closes above the prior
  day's high (a reversal day). Buy-stop above that day's high; stop under the
  5-day low.
- ``rsi2``: Connors' RSI(2) dip: above the 200-DMA with RSI(2) under 10. Buy at
  the next open; exit at the first close above the 5-DMA, or after 10 sessions.

Every strategy shares: price >= Rs 100, 20-day turnover >= Rs 10 crore (no penny
or illiquid stocks), stop risk capped at 6-8%, and 0.30% round-trip costs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradingagents.scanner import engine as E

MIN_PRICE = 100.0
MIN_TURNOVER_CR = 10.0
COST_PCT = 0.30


@dataclass(frozen=True)
class Setup:
    """A trade plan from a signal bar."""
    strategy: str
    entry_type: str          # "stop": buy-stop at ``entry`` next session; "open": buy the next open
    entry: float             # trigger (stop entries) or reference price (the signal close)
    stop: float
    target: float | None     # fixed target, or None when the exit is a signal
    exit_rule: str           # plain words, for the report
    max_hold: int
    exit_sma5: bool = False  # exit at the first close above the 5-DMA

    @property
    def risk_pct(self) -> float:
        return (self.entry - self.stop) / self.entry * 100


STRATEGIES = ("breakout", "pivot", "pullback", "rsi2")
LABELS = {
    "breakout": "52-week breakout",
    "pivot": "Tight base, pre-breakout",
    "pullback": "Uptrend pullback to 20-DMA",
    "rsi2": "RSI(2) dip in uptrend",
}

BREAKOUT_RULES = E.Rules(
    lookback=250, vol_mult=1.5, base_days=20, max_base_pct=12.0, max_extension_pct=4.0,
    min_price=MIN_PRICE, min_turnover_cr=MIN_TURNOVER_CR, strong_close=0.6, regime="nifty50",
    min_rs=0.0, stop_atr=2.0, max_risk_pct=6.0, target_r=2.0, max_hold=20, cost_pct=COST_PCT,
)


def _rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0)


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    ind = E.indicators(df, BREAKOUT_RULES)
    c = ind["Close"]
    ind["sma5"] = c.rolling(5).mean()
    ind["rsi2"] = _rsi(c, 2)
    ind["rsi14"] = _rsi(c, 14)
    ind["low5"] = ind["Low"].rolling(5).min()
    ind["low10"] = ind["Low"].rolling(10).min()
    ind["high52_incl"] = ind["High"].rolling(250, min_periods=120).max()
    ind["vol10"] = ind["Volume"].rolling(10).mean()
    ind["touched20"] = (ind["Low"] <= ind["sma20"]).rolling(3).max().astype(bool)
    return ind


def _liquid(ind: pd.DataFrame) -> pd.Series:
    return (ind["Close"] >= MIN_PRICE) & (ind["turnover_cr"] >= MIN_TURNOVER_CR) & ind["atr"].notna()


def _trend(ind: pd.DataFrame) -> pd.Series:
    return (ind["Close"] > ind["sma50"]) & (ind["sma50"] > ind["sma200"])


def _market_ok(ind: pd.DataFrame, market: pd.DataFrame | None) -> pd.Series:
    if market is None:
        return pd.Series(True, index=ind.index)
    ok = market["nifty"] > market["nifty_sma50"]
    return ok.reindex(ind.index).fillna(False).astype(bool)


def _rs_ok(ind: pd.DataFrame, market: pd.DataFrame | None) -> pd.Series:
    if market is None:
        return pd.Series(True, index=ind.index)
    return (ind["ret126"] - market["nifty_ret126"].reindex(ind.index)) >= 0


def signals(name: str, ind: pd.DataFrame, market: pd.DataFrame | None) -> pd.Series:
    """Bars where strategy ``name`` signals, using only data through each bar."""
    if name == "breakout":
        return E.signal_mask(ind, BREAKOUT_RULES, market)
    base = _liquid(ind)
    if name == "pivot":
        h = ind["high52_incl"]
        m = (
            base & _trend(ind) & _market_ok(ind, market) & _rs_ok(ind, market)
            & (ind["base_pct"] <= 12.0)
            & (ind["Close"] >= h * 0.97) & (ind["High"] < h)  # just under, not through
            & (ind["vol10"] < ind["vol50"])                     # volume drying up
        )
        return m.fillna(False)
    if name == "pullback":
        m = (
            base & _trend(ind) & _market_ok(ind, market) & _rs_ok(ind, market)
            & ind["touched20"] & (ind["Close"] > ind["sma50"])
            & (ind["Close"] > ind["High"].shift(1))             # reversal day
            & (ind["rsi14"] < 65)
        )
        return m.fillna(False)
    if name == "rsi2":
        m = base & (ind["Close"] > ind["sma200"]) & (ind["rsi2"] < 10)
        return m.fillna(False)
    raise ValueError(f"unknown strategy {name!r}")


def setup_for(name: str, row: pd.Series) -> Setup | None:
    """The trade plan for a signal bar of strategy ``name``."""
    if name == "breakout":
        p = E.plan_for(row, BREAKOUT_RULES)
        if p is None:
            return None
        return Setup(name, "stop", p.trigger, p.stop, p.target,
                     "target 2R, or the close of session 20", 20)
    if name == "pivot":
        trigger = round(float(row["high52_incl"]) * 1.001, 2)
        stop = max(float(row["low10"]), trigger * 0.94)
        stop = min(stop, trigger - 1.0 * float(row["atr"]))
        stop = max(stop, trigger * 0.94)
        return _fixed(name, trigger, stop, 2.0, 20)
    if name == "pullback":
        trigger = round(float(row["High"]) * 1.001, 2)
        stop = max(float(row["low5"]) * 0.998, trigger * 0.94)
        return _fixed(name, trigger, stop, 2.0, 20)
    if name == "rsi2":
        ref = float(row["Close"])
        stop = max(ref - 2.5 * float(row["atr"]), ref * 0.92)
        return Setup(name, "open", round(ref, 2), round(stop, 2), round(float(row["sma5"]), 2),
                     "first close above the 5-DMA, or the close of session 10", 10, exit_sma5=True)
    raise ValueError(f"unknown strategy {name!r}")


def _fixed(name: str, trigger: float, stop: float, r: float, hold: int) -> Setup | None:
    risk = trigger - stop
    if risk <= 0:
        return None
    return Setup(name, "stop", round(trigger, 2), round(stop, 2), round(trigger + r * risk, 2),
                 f"target {r:g}R, or the close of session {hold}", hold)


def simulate(ind: pd.DataFrame, i: int, s: Setup, arrays) -> dict | None:
    """Replay one setup from signal bar ``i``. None: no fill, skipped, or still open."""
    o, h, low, c, sma5 = arrays
    n = len(o)
    e = i + 1
    if e >= n:
        return None
    if s.entry_type == "stop":
        if h[e] < s.entry:
            return None
        entry = max(s.entry, o[e])
        if entry > s.entry * 1.03:
            return None  # gapped >3% over the trigger: no chasing
    else:
        entry = o[e]
        if entry <= s.stop:
            return None
    risk = entry - s.stop
    if risk <= 0:
        return None
    target = None if s.target is None or s.exit_sma5 else entry + (s.target - s.entry)
    last = min(n, e + s.max_hold)
    exit_px, outcome, j = None, "time", e
    for j in range(e, last):
        if j > e and o[j] <= s.stop:
            exit_px, outcome = o[j], "stop"
            break
        if low[j] <= s.stop:
            exit_px, outcome = s.stop, "stop"
            break
        if target is not None:
            if j > e and o[j] >= target:
                exit_px, outcome = o[j], "target"
                break
            if h[j] >= target:
                exit_px, outcome = target, "target"
                break
        if s.exit_sma5 and c[j] > sma5[j]:
            exit_px, outcome = c[j], "target"
            break
    else:
        if e + s.max_hold > n:
            return None
        exit_px = c[j]
    net = exit_px / entry - 1 - COST_PCT / 100
    return {"entry_date": ind.index[e], "exit_date": ind.index[j], "entry": entry, "exit": exit_px,
            "outcome": outcome, "days": j - e + 1, "ret_pct": net * 100, "r": net * entry / risk}


def backtest(name: str, ind: pd.DataFrame, market: pd.DataFrame | None,
             start=None, end=None) -> list[dict]:
    mask = signals(name, ind, market).to_numpy()
    arrays = tuple(ind[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "sma5"))
    trades, busy = [], -1
    for i in np.flatnonzero(mask):
        d = ind.index[i]
        if i <= busy or (start is not None and d < start) or (end is not None and d > end):
            continue
        s = setup_for(name, ind.iloc[i])
        if s is None:
            continue
        t = simulate(ind, i, s, arrays)
        if t is None:
            continue
        t.update(signal_date=d, strategy=name)
        trades.append(t)
        busy = i + t["days"]
    return trades
