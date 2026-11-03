"""Breakout signals, trade plans and their simulation on daily bars.

Everything here is arithmetic on OHLCV frames: no network, no LLM. The same
functions produce today's signals and replay the rule over history, so the
record shown next to a pick is the record of exactly the rule that picked it.

Trade mechanics (one position per signal):

- Signal, on a settled daily close: the close clears the highest high of the
  prior ``lookback`` sessions on volume at least ``vol_mult`` x its 50-day
  average, in an uptrend (close > 50-DMA > 200-DMA), out of a base no wider
  than ``max_base_pct``, not already extended, with the stock above the
  liquidity and price floors (no penny stocks), and only while the market
  regime allows it.
- Entry, the next session: a buy-stop just above the signal day's high. It
  fills at the trigger, or at the open when the stock gaps over it, unless the
  open is more than ``max_gap_pct`` above the trigger (then the trade is
  skipped: no chasing).
- Stop: ``stop_atr`` x ATR(14) below the trigger, but never above the signal
  day's low and never risking more than ``max_risk_pct``.
- Exit (``exit_mode``): all at ``target_r`` x risk; or a trailing stop
  ``trail_atr`` x ATR under the highest close; or half at the target and half
  on the trail. Every leg is also closed after ``max_hold`` sessions. A bar
  that touches both the stop and the target counts as the stop; a gap through
  the stop fills at the open (worse than the stop).
- Costs: ``cost_pct`` round trip (STT, exchange and SEBI fees, stamp duty,
  GST and slippage on NSE delivery trades) is charged on every trade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Rules:
    lookback: int = 55            # breakout above the prior N-session high
    vol_mult: float = 1.5         # signal volume vs the 50-day average
    base_days: int = 20           # the consolidation before the breakout
    max_base_pct: float = 15.0    # base range (high-low)/close, %, at most
    max_extension_pct: float = 4.0  # close at most this far above the breakout level
    trend: bool = True            # close > 50-DMA > 200-DMA
    min_price: float = 100.0      # INR; nothing below: no penny stocks
    min_turnover_cr: float = 10.0  # 20-day average traded value, INR crore
    strong_close: float = 0.6     # close in the top 40% of the day's range
    # Market regime: "none"; "nifty50" (Nifty above its 50-DMA); "healthy"
    # (Nifty above its 200-DMA and at least min_breadth % of stocks above theirs).
    regime: str = "nifty50"
    min_breadth: float = 50.0
    min_rs: float | None = None   # 6-month return minus the Nifty's, at least (0.10 = +10 pts)
    stop_atr: float = 2.0
    max_risk_pct: float = 8.0
    target_r: float = 2.0
    # Exit: "target" (all at target_r), "trail" (trailing stop only) or
    # "hybrid" (half at target_r, the rest on the trailing stop).
    exit_mode: str = "target"
    trail_atr: float = 3.0
    max_hold: int = 20            # sessions
    max_gap_pct: float = 3.0
    cost_pct: float = 0.30        # round trip

    def describe(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in asdict(self).items())


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def indicators(df: pd.DataFrame, rules: Rules) -> pd.DataFrame:
    out = df.copy()
    c = out["Close"]
    out["sma20"] = c.rolling(20).mean()
    out["sma50"] = c.rolling(50).mean()
    out["sma200"] = c.rolling(200).mean()
    out["atr"] = _atr(out)
    out["vol50"] = out["Volume"].rolling(50).mean().shift(1)
    out["turnover_cr"] = (c * out["Volume"]).rolling(20).mean() / 1e7
    out["pivot"] = out["High"].rolling(rules.lookback).max().shift(1)
    base_hi = out["High"].rolling(rules.base_days).max().shift(1)
    base_lo = out["Low"].rolling(rules.base_days).min().shift(1)
    out["base_pct"] = (base_hi - base_lo) / c * 100
    out["ret126"] = c / c.shift(126) - 1
    out["ret63"] = c / c.shift(63) - 1
    out["high52"] = out["High"].rolling(250, min_periods=120).max()
    rng = (out["High"] - out["Low"]).replace(0, np.nan)
    out["close_pos"] = ((c - out["Low"]) / rng).fillna(1.0)
    return out


def market_frame(nifty: pd.DataFrame, universe: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per-day market state: Nifty trend, its 6-month return and breadth.

    Breadth is the share of the universe's stocks (with 200 sessions of
    history) closing above their own 200-day average.
    """
    c = nifty["Close"]
    above = pd.Series(0.0, index=c.index)
    counted = pd.Series(0.0, index=c.index)
    for df in universe.values():
        if len(df) < 220:
            continue
        s = df["Close"].reindex(c.index)
        sma = s.rolling(200, min_periods=180).mean()
        valid = sma.notna() & s.notna()
        above += ((s > sma) & valid).astype(float)
        counted += valid.astype(float)
    breadth = above / counted.replace(0, np.nan) * 100
    return pd.DataFrame({
        "nifty": c,
        "nifty_sma50": c.rolling(50).mean(),
        "nifty_sma200": c.rolling(200).mean(),
        "nifty_ret126": c / c.shift(126) - 1,
        "breadth": breadth,
    })


def regime_ok(market: pd.DataFrame, rules: Rules) -> pd.Series:
    """True on the days the market regime lets the rule take new trades."""
    if rules.regime == "none":
        return pd.Series(True, index=market.index)
    if rules.regime == "nifty50":
        return market["nifty"] > market["nifty_sma50"]
    if rules.regime == "healthy":
        return (market["nifty"] > market["nifty_sma200"]) & (market["breadth"] >= rules.min_breadth)
    raise ValueError(f"unknown regime {rules.regime!r}")


def signal_mask(ind: pd.DataFrame, rules: Rules, market: pd.DataFrame | None = None) -> pd.Series:
    c = ind["Close"]
    m = (
        (c > ind["pivot"])
        & (ind["Volume"] >= rules.vol_mult * ind["vol50"])
        & (ind["base_pct"] <= rules.max_base_pct)
        & (c <= ind["pivot"] * (1 + rules.max_extension_pct / 100))
        & (c >= rules.min_price)
        & (ind["turnover_cr"] >= rules.min_turnover_cr)
        & (ind["close_pos"] >= rules.strong_close)
        & ind["atr"].notna()
    )
    if rules.trend:
        m &= (c > ind["sma50"]) & (ind["sma50"] > ind["sma200"])
    if market is not None:
        m &= regime_ok(market, rules).reindex(ind.index).fillna(False).astype(bool)
        if rules.min_rs is not None:
            rs = ind["ret126"] - market["nifty_ret126"].reindex(ind.index)
            m &= rs >= rules.min_rs
    return m.fillna(False)


@dataclass
class Plan:
    trigger: float
    stop: float
    target: float
    risk_pct: float

    @property
    def rr(self) -> float:
        return (self.target - self.trigger) / (self.trigger - self.stop)


def plan_for(row: pd.Series, rules: Rules) -> Plan | None:
    """The trade plan for a signal bar, or None when the risk is too wide."""
    trigger = round(float(row["High"]) * 1.001, 2)
    stop = min(trigger - rules.stop_atr * float(row["atr"]), float(row["Low"]))
    stop = max(stop, trigger * (1 - rules.max_risk_pct / 100))
    risk = trigger - stop
    if risk <= 0:
        return None
    target = trigger + rules.target_r * risk
    return Plan(round(trigger, 2), round(stop, 2), round(target, 2), risk / trigger * 100)


def _arrays(ind: pd.DataFrame):
    return tuple(ind[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "atr"))


def _run_leg(o, h, low, c, e, n, entry, stop, target, trail, max_hold):
    """One position from bar ``e``: (exit price, outcome, exit bar), or None while still open."""
    initial, best = stop, entry
    for j in range(e, min(n, e + max_hold)):
        hit = "stop" if stop <= initial else "trail"
        if j > e and o[j] <= stop:
            return o[j], hit, j
        if low[j] <= stop:
            return stop, hit, j
        if target is not None:
            if j > e and o[j] >= target:
                return o[j], "target", j
            if h[j] >= target:
                return target, "target", j
        if trail is not None:
            best = max(best, c[j])
            stop = max(stop, best - trail)
    if e + max_hold > n:
        return None
    j = e + max_hold - 1
    return c[j], "time", j


def simulate(ind: pd.DataFrame, i: int, plan: Plan, rules: Rules, arrays=None) -> dict | None:
    """Replay a signal at bar ``i`` forward; None when it never filled, was skipped
    or is still open."""
    o, h, low, c, atr = arrays if arrays is not None else _arrays(ind)
    n = len(o)
    e = i + 1
    if e >= n:
        return None
    if h[e] < plan.trigger:
        return None  # the buy-stop never triggered: no trade
    entry = max(plan.trigger, o[e])
    if entry > plan.trigger * (1 + rules.max_gap_pct / 100):
        return None  # gapped too far over the trigger: skip, do not chase
    risk = entry - plan.stop
    if risk <= 0:
        return None
    target = entry + rules.target_r * risk
    trail = rules.trail_atr * atr[i]
    if rules.exit_mode == "target":
        legs = [_run_leg(o, h, low, c, e, n, entry, plan.stop, target, None, rules.max_hold)]
    elif rules.exit_mode == "trail":
        legs = [_run_leg(o, h, low, c, e, n, entry, plan.stop, None, trail, rules.max_hold)]
    elif rules.exit_mode == "hybrid":
        legs = [
            _run_leg(o, h, low, c, e, n, entry, plan.stop, target, None, rules.max_hold),
            _run_leg(o, h, low, c, e, n, entry, plan.stop, None, trail, rules.max_hold),
        ]
    else:
        raise ValueError(f"unknown exit_mode {rules.exit_mode!r}")
    if any(leg is None for leg in legs):
        return None
    gross = float(np.mean([px / entry - 1 for px, _, _ in legs]))
    net = gross - rules.cost_pct / 100
    j = max(leg[2] for leg in legs)
    return {
        "entry_date": ind.index[e], "exit_date": ind.index[j], "entry": entry,
        "exit": float(np.mean([px for px, _, _ in legs])),
        "outcome": "/".join(dict.fromkeys(leg[1] for leg in legs)), "days": j - e + 1,
        "ret_pct": net * 100, "r": net * entry / risk,
    }


def backtest_symbol(ind: pd.DataFrame, rules: Rules, market=None, start=None, end=None) -> list[dict]:
    """Every trade the rule took on one stock, one position at a time."""
    mask = signal_mask(ind, rules, market)
    idx = np.flatnonzero(mask.to_numpy())
    trades, busy_until = [], -1
    arrays = _arrays(ind)
    for i in idx:
        d = ind.index[i]
        if (start is not None and d < start) or (end is not None and d > end) or i <= busy_until:
            continue
        plan = plan_for(ind.iloc[i], rules)
        if plan is None:
            continue
        t = simulate(ind, i, plan, rules, arrays)
        if t is None:
            continue
        t["signal_date"] = d
        trades.append(t)
        busy_until = i + t["days"]
    return trades


def summarize(trades: list[dict] | pd.DataFrame) -> dict:
    df = pd.DataFrame(trades)
    if df.empty:
        return {"trades": 0}
    wins = df[df["r"] > 0]
    losses = df[df["r"] <= 0]
    loss_sum = -losses["r"].sum()
    pf = wins["r"].sum() / loss_sum if loss_sum > 0 else float("inf")
    hit_target = df["outcome"].str.contains("target")
    return {
        "trades": int(len(df)),
        "win_rate": float((df["r"] > 0).mean() * 100),
        "target_rate": float(hit_target.mean() * 100),
        "stop_rate": float((df["outcome"] == "stop").mean() * 100),
        "expectancy_r": float(df["r"].mean()),
        "avg_ret_pct": float(df["ret_pct"].mean()),
        "avg_win_pct": float(wins["ret_pct"].mean()) if not wins.empty else float("nan"),
        "avg_loss_pct": float(losses["ret_pct"].mean()) if not losses.empty else float("nan"),
        "median_days": float(df["days"].median()),
        "p75_days": float(df["days"].quantile(0.75)),
        "median_days_to_target": float(df.loc[hit_target, "days"].median())
        if hit_target.any() else float("nan"),
        "profit_factor": float(pf),
    }
