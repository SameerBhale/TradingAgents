"""Five swing setups for NSE stocks, drawn from the best-documented swing traders.

All are long-only, daily-bar, delivery trades with a buy-stop entry (it fills only if
the move starts) and a stop of 5-10%. The exit has no time limit (Qullamaggie and
Minervini scale out and trail; they do not sell on a calendar):

- sell half at the 2R target (10-20%) and move the stop on the rest to the buy price;
- sell the rest at the next open after a close below the 20-day EMA (or at the stop).

Tested 2017-2026 on all large/mid/small caps: +0.23R a trade against +0.09R for the
old "2R target or sell after 20 sessions" (docs/STRATEGY.md).

Follow the money: delivery % (the share of volume taken into demat, which is what
funds do) from NSE's daily MTO file. ``dp_trend`` is the 20-day average delivery % over
the 100-day average. Money IN (>= 1.05) was better in every period, money OUT (< 1.00)
worst; episodic pivots are exempt (news days are full of intraday churn).

The five setups:

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
    max_hold: int | None     # None: no time limit (the trailing exit decides)
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


# Follow the money (delivery % trend). Episodic pivots are exempt.
MONEY_IN = 1.05
MONEY_OUT = 1.00
MONEY_EXEMPT = ("ep",)
EXIT_RULE = ("sell half at the target and move the stop to your buy price; "
             "sell the rest on a close below the 20-day EMA (next open)")


def add_delivery(ind: pd.DataFrame, deliv_pct: pd.Series | None) -> None:
    """Write NSE delivery % and its trend (20-day mean / 100-day mean) into ``ind``."""
    if deliv_pct is None or deliv_pct.dropna().empty:
        ind["deliv_pct"] = np.nan
        ind["dp_trend"] = np.nan
        return
    dp = deliv_pct.reindex(ind.index)
    ind["deliv_pct"] = dp
    ind["dp_trend"] = dp.rolling(20, min_periods=12).mean() / dp.rolling(100, min_periods=60).mean()


def money_flow(name: str, row: pd.Series) -> str:
    """'in', 'flat', 'out', 'exempt' or 'unknown' (no delivery data), from the delivery % trend."""
    if name in MONEY_EXEMPT:
        return "exempt"
    v = row.get("dp_trend", np.nan)
    if v is None or v != v:
        return "unknown"
    return "in" if v >= MONEY_IN else ("flat" if v >= MONEY_OUT else "out")


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
    return Setup(s.strategy, s.entry_type, s.entry, stop, target, s.exit_rule, None, s.exit_sma5)


def _raw_setup(name: str, row: pd.Series) -> Setup | None:
    if name == "breakout":
        p = E.plan_for(row, BREAKOUT_RULES)
        if p is None:
            return None
        return Setup(name, "stop", p.trigger, p.stop, p.target, EXIT_RULE, None)
    if name == "vcp":
        trigger = round(float(row["high10"]) * 1.001, 2)
        return _fixed(name, trigger, float(row["low10"]) * 0.998, 2.0)
    if name == "flag":
        trigger = round(float(row["high10"]) * 1.001, 2)
        return _fixed(name, trigger, float(row["low5"]) * 0.998, 2.0)
    if name == "ep":
        trigger = round(float(row["High"]) * 1.001, 2)
        return _fixed(name, trigger, float(row["Low"]) * 0.998, 2.0)
    if name == "crossback":
        trigger = round(float(row["High"]) * 1.001, 2)
        stop = min(float(row["low5"]), float(row["ema20"])) * 0.995
        return _fixed(name, trigger, stop, 2.0)
    raise ValueError(f"unknown strategy {name!r}")


def _fixed(name: str, trigger: float, stop: float, r: float) -> Setup | None:
    risk = trigger - stop
    if risk <= 0:
        return None
    return Setup(name, "stop", round(trigger, 2), round(stop, 2), round(trigger + r * risk, 2), EXIT_RULE, None)


def _leg(o, h, low, c, trail, e, n, stop, target):
    """One position from bar ``e``: (exit price, exit bar, outcome), or None while still open."""
    for j in range(e, n):
        if j > e and o[j] <= stop:
            return o[j], j, "stop"
        if low[j] <= stop:
            return stop, j, "stop"
        if target is not None:
            if j > e and o[j] >= target:
                return o[j], j, "target"
            if h[j] >= target:
                return target, j, "target"
        if trail is not None and j > e and c[j] < trail[j]:
            return (o[j + 1], j + 1, "trail") if j + 1 < n else None
    return None


def run_exit(o, h, low, c, ema20, e: int, entry: float, stop: float, target: float):
    """The swing exit from entry bar ``e``: half at ``target`` (then the stop moves to the
    buy price), the rest on a close below the 20-day EMA. Returns
    ``(gross return, exit bar, outcome)``, or None while the trade is still open."""
    n = len(o)
    a = _leg(o, h, low, c, None, e, n, stop, target)
    if a is None:
        return None
    if a[2] != "target":
        return a[0] / entry - 1, a[1], a[2]
    if a[1] + 1 >= n:
        return None
    b = _leg(o, h, low, c, ema20, a[1] + 1, n, entry, None)
    if b is None:
        return None
    gross = (a[0] / entry - 1 + b[0] / entry - 1) / 2
    return gross, b[1], "target/" + ("breakeven" if b[2] == "stop" else "trail")


def simulate(ind: pd.DataFrame, i: int, s: Setup, arrays) -> dict | None:
    """Replay one setup from signal bar ``i``. None: no fill, skipped, or still open."""
    o, h, low, c, ema20 = arrays
    n = len(o)
    e = i + 1
    if e >= n or h[e] < s.entry:
        return None
    entry = max(s.entry, o[e])
    if entry > s.entry * 1.03:
        return None  # gapped >3% over the trigger: no chasing
    risk = entry - s.stop
    if risk <= 0:
        return None
    target = entry + (s.target - s.entry)
    res = run_exit(o, h, low, c, ema20, e, entry, s.stop, target)
    if res is None:
        return None
    gross, j, outcome = res
    net = gross - COST_PCT / 100
    t_hit = None
    if outcome.startswith("target"):
        t_hit = next(k for k in range(e, j + 1) if h[k] >= target) - e + 1
    return {"entry_date": ind.index[e], "exit_date": ind.index[j], "entry": entry,
            "outcome": outcome, "days": j - e + 1, "ret_pct": net * 100, "r": net * entry / risk,
            "stop": s.stop, "days_to_target": t_hit}


def backtest(name: str, ind: pd.DataFrame, market: pd.DataFrame | None,
             start=None, end=None, money: bool = True) -> list[dict]:
    """Every closed trade of ``name`` on one stock. ``money``: only the trades the live scan
    can grade GOOD (money IN, or an exempt strategy, or a stock with no delivery data)."""
    mask = signals(name, ind, market).to_numpy()
    arrays = tuple(ind[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "ema20"))
    has_dp = "dp_trend" in ind and ind["dp_trend"].notna().any()
    trades, busy = [], -1
    for i in np.flatnonzero(mask):
        d = ind.index[i]
        if i <= busy or (start is not None and d < start) or (end is not None and d > end):
            continue
        row = ind.iloc[i]
        if money and has_dp and money_flow(name, row) not in ("in", "exempt"):
            continue
        s = setup_for(name, row)
        if s is None:
            continue
        t = simulate(ind, i, s, arrays)
        if t is None:
            continue
        t.update(signal_date=d, strategy=name)
        trades.append(t)
        busy = i + t["days"]
    return trades
