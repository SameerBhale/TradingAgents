"""Five swing setups for NSE stocks, drawn from the best-documented swing traders.

All are long-only, daily-bar, delivery trades with a buy-stop entry (it fills only if
the move starts) and a stop of 5-10% with a 2R target (10-20%):

- ``breakout``: a close at a new 52-week high on volume out of a tight base. The
  original tested rule (``engine``): the one setup that held up in 2022-26.
- ``vcp``: Mark Minervini's SEPA. The stock passes his 8-point Trend Template (stage 2
  uptrend, RS rank >= 70, within 25% of the 52-week high, 30%+ above the low) and its
  base tightens in steps (each pullback shallower than the last) with volume drying up.
  Buy-stop above the pivot (the high of the tightest part); stop under its low.
- ``flag``: Kristjan Kullamagi's (Qullamaggie) high-tight breakout. A 30%+ run in the
  last 1-3 months, then a quiet, tightening flag riding the rising 10- and 20-day
  averages, in a volatile name (ADR >= 3%). Buy-stop above the flag high.
- ``crossback``: Oliver Kell's EMA crossback (2020 US Investing Champion, +941%): a
  stage-2 leader dips to its 10/20-day EMAs and closes back above the 10 EMA and the
  prior day's high. Buy-stop above that day; stop under the 5-day low / 20 EMA.
- ``ep``: Qullamaggie's episodic pivot. A gap-up day of 6%+ on 3x average volume after
  news (results, orders), closing strong, in a stock above its 200-DMA. Buy-stop above
  the day's high; stop under the day's low.

Shared filters: price >= Rs 100, 20-day turnover >= Rs 10 crore, the Nifty above its
50-DMA (except ``ep``: a big news gap can lead in a soft market), 0.30% round-trip costs.
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


STRATEGIES = ("breakout", "vcp", "flag", "ep", "crossback")
LABELS = {
    "breakout": "52-week high breakout",
    "vcp": "Minervini VCP (tight base, stage-2 uptrend)",
    "flag": "Qullamaggie flag (30%+ run, then tight flag)",
    "ep": "Episodic pivot (news gap-up on 3x volume)",
    "crossback": "Kell EMA crossback (leader dips to 10/20 EMA, reclaims)",
}
SOURCES = {
    "breakout": "52-week-high breakouts (Darvas, O'Neil); tested on NSE 2017-2026",
    "vcp": "Mark Minervini, Trade Like a Stock Market Wizard (SEPA, Trend Template, VCP)",
    "flag": "Kristjan Kullamagi (Qullamaggie), breakout setup",
    "ep": "Kristjan Kullamagi (Qullamaggie), episodic pivot",
    "crossback": "Oliver Kell, 2020 US Investing Champion (+941%): EMA crossback",
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


def _range_pct(high: pd.Series, low: pd.Series, n: int, skip: int = 0) -> pd.Series:
    """(highest high - lowest low) / highest high over ``n`` sessions ending ``skip`` sessions ago, %."""
    hi = high.shift(skip).rolling(n).max()
    lo = low.shift(skip).rolling(n).min()
    return (hi - lo) / hi * 100


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    ind = E.indicators(df, BREAKOUT_RULES)
    c, h, low = ind["Close"], ind["High"], ind["Low"]
    ind["sma5"] = c.rolling(5).mean()
    ind["sma10"] = c.rolling(10).mean()
    ind["sma150"] = c.rolling(150).mean()
    ind["ema10"] = c.ewm(span=10, adjust=False).mean()
    ind["ema20"] = c.ewm(span=20, adjust=False).mean()
    ind["rsi14"] = _rsi(c, 14)
    ind["low5"] = low.rolling(5).min()
    ind["low10"] = low.rolling(10).min()
    ind["high10"] = h.rolling(10).max()
    ind["high52_incl"] = h.rolling(250, min_periods=120).max()
    ind["low52"] = low.rolling(250, min_periods=120).min()
    ind["vol10"] = ind["Volume"].rolling(10).mean()
    ind["adr_pct"] = (h / low - 1).rolling(20).mean() * 100
    # VCP contractions: three windows, oldest to newest.
    ind["c1"] = _range_pct(h, low, 25, 25)   # sessions -50..-26
    ind["c2"] = _range_pct(h, low, 15, 10)   # sessions -25..-11
    ind["c3"] = _range_pct(h, low, 10, 0)    # the last 10 sessions
    # Qullamaggie: the run into the flag (low of sessions -70..-11 to the high of the last 40).
    ind["run_pct"] = (h.rolling(40).max() / low.shift(10).rolling(60).min() - 1) * 100
    ind["gap_pct"] = (ind["Open"] / c.shift(1) - 1) * 100
    ind["day_pct"] = (c / c.shift(1) - 1) * 100
    # IBD-style weighted 12-month return: the input to the cross-sectional RS rank.
    ind["rs_raw"] = (0.4 * (c / c.shift(63) - 1) + 0.2 * (c / c.shift(126) - 1)
                     + 0.2 * (c / c.shift(189) - 1) + 0.2 * (c / c.shift(250) - 1))
    ind["rs_rank"] = np.nan  # filled by add_rs_rank over the whole universe
    return ind


def add_rs_rank(inds: dict[str, pd.DataFrame]) -> None:
    """Minervini's relative-strength rank: each stock's weighted 12-month return as a
    percentile (0-99) of the whole universe on each date, written into ``ind["rs_rank"]``."""
    if not inds:
        return
    panel = pd.DataFrame({s: d["rs_raw"] for s, d in inds.items()})
    ranks = panel.rank(axis=1, pct=True) * 99
    for s, d in inds.items():
        d["rs_rank"] = ranks[s].reindex(d.index)


def _liquid(ind: pd.DataFrame) -> pd.Series:
    return (ind["Close"] >= MIN_PRICE) & (ind["turnover_cr"] >= MIN_TURNOVER_CR) & ind["atr"].notna()


def trend_template(ind: pd.DataFrame, min_rs: float = 70.0) -> pd.Series:
    """Minervini's 8-point Trend Template (a stage-2 uptrend)."""
    c = ind["Close"]
    rs = ind["rs_rank"]
    rs_ok = (rs >= min_rs) if rs.notna().any() else pd.Series(True, index=ind.index)
    return (
        (c > ind["sma150"]) & (c > ind["sma200"])                          # 1. above the 150 and 200-day
        & (ind["sma150"] > ind["sma200"])                                   # 2. 150 above 200
        & (ind["sma200"] > ind["sma200"].shift(22))                         # 3. 200-day rising a month
        & (ind["sma50"] > ind["sma150"]) & (ind["sma50"] > ind["sma200"])   # 4. 50 above both
        & (c > ind["sma50"])                                                # 5. above the 50-day
        & (c >= ind["low52"] * 1.30)                                        # 6. 30%+ above the 52-week low
        & (c >= ind["high52_incl"] * 0.75)                                  # 7. within 25% of the high
        & rs_ok                                                             # 8. RS rank >= 70
    )


def _market_ok(ind: pd.DataFrame, market: pd.DataFrame | None) -> pd.Series:
    if market is None:
        return pd.Series(True, index=ind.index)
    ok = market["nifty"] > market["nifty_sma50"]
    return ok.reindex(ind.index).fillna(False).astype(bool)


def signals(name: str, ind: pd.DataFrame, market: pd.DataFrame | None) -> pd.Series:
    """Bars where strategy ``name`` signals, using only data through each bar."""
    if name == "breakout":
        return E.signal_mask(ind, BREAKOUT_RULES, market)
    base = _liquid(ind)
    c = ind["Close"]
    if name == "vcp":
        m = (
            base & trend_template(ind) & _market_ok(ind, market)
            & (ind["c1"] > ind["c2"]) & (ind["c2"] > ind["c3"])    # each contraction shallower
            & (ind["c1"] <= 35) & (ind["c3"] <= 10)                 # a sane base, a tight finish
            & (ind["vol10"] < ind["vol50"])                         # volume drying up
            & (c >= ind["high10"] * 0.95) & (c >= ind["high52_incl"] * 0.85)
        )
        return m.fillna(False)
    if name == "flag":
        m = (
            base & _market_ok(ind, market)
            & (ind["run_pct"] >= 30) & (ind["adr_pct"] >= 3.0)
            & (ind["sma10"] > ind["sma20"]) & (ind["sma20"] > ind["sma50"])
            & (c > ind["sma20"]) & (c > ind["sma200"])
            & (ind["c3"] <= 15) & (ind["vol10"] < ind["vol50"])     # a quiet, tight flag
            & (c >= ind["high10"] * 0.95)
        )
        return m.fillna(False)
    if name == "ep":
        m = (
            base & (c > ind["sma200"])
            & (ind["gap_pct"] >= 3.0) & (ind["day_pct"] >= 6.0)
            & (ind["Volume"] >= 3.0 * ind["vol50"]) & (ind["close_pos"] >= 0.6)
        )
        return m.fillna(False)
    if name == "crossback":
        touched = (ind["Low"] <= ind["ema20"] * 1.005).rolling(3).max().astype(bool)
        m = (
            base & _market_ok(ind, market) & trend_template(ind)
            & (ind["ema10"] > ind["ema20"]) & (ind["ema20"] > ind["sma50"])
            & touched & (c > ind["ema10"])                          # dipped to the EMAs, reclaimed
            & (c > ind["High"].shift(1)) & (ind["close_pos"] >= 0.6)
        )
        return m.fillna(False)
    raise ValueError(f"unknown strategy {name!r}")


# Swing stop band (percent below the entry). None leaves each strategy's own stop.
# 5-10% (targets 2R = 10-20%): tested 2017-2026 on a point-in-time universe, breakouts
# kept their edge (+0.53% / +0.71% / +0.04% per trade by period vs +0.53 / +0.48 / +0.11%).
STOP_MIN_PCT: float | None = 5.0
STOP_MAX_PCT: float | None = 10.0
TARGET_R = 2.0


def setup_for(name: str, row: pd.Series) -> Setup | None:
    """The trade plan for a signal bar of strategy ``name``, inside the stop band."""
    s = _raw_setup(name, row)
    if s is None or (STOP_MIN_PCT is None and STOP_MAX_PCT is None):
        return s
    stop = s.stop
    if STOP_MIN_PCT is not None:
        stop = min(stop, s.entry * (1 - STOP_MIN_PCT / 100))
    if STOP_MAX_PCT is not None:
        stop = max(stop, s.entry * (1 - STOP_MAX_PCT / 100))
    stop = round(stop, 2)
    target = s.target
    if not s.exit_sma5:
        target = round(s.entry + TARGET_R * (s.entry - stop), 2)
    return Setup(s.strategy, s.entry_type, s.entry, stop, target, s.exit_rule, s.max_hold, s.exit_sma5)


def _raw_setup(name: str, row: pd.Series) -> Setup | None:
    if name == "breakout":
        p = E.plan_for(row, BREAKOUT_RULES)
        if p is None:
            return None
        return Setup(name, "stop", p.trigger, p.stop, p.target,
                     "target 2R, or the close of session 20", 20)
    if name == "vcp":
        trigger = round(float(row["high10"]) * 1.001, 2)
        return _fixed(name, trigger, float(row["low10"]) * 0.998, 2.0, 20)
    if name == "flag":
        trigger = round(float(row["high10"]) * 1.001, 2)
        return _fixed(name, trigger, float(row["low5"]) * 0.998, 2.0, 20)
    if name == "ep":
        trigger = round(float(row["High"]) * 1.001, 2)
        return _fixed(name, trigger, float(row["Low"]) * 0.998, 2.0, 20)
    if name == "crossback":
        trigger = round(float(row["High"]) * 1.001, 2)
        stop = min(float(row["low5"]), float(row["ema20"])) * 0.995
        return _fixed(name, trigger, stop, 2.0, 20)
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
            "outcome": outcome, "days": j - e + 1, "ret_pct": net * 100, "r": net * entry / risk,
            "stop": s.stop}


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
