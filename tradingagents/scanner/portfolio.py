"""Portfolio replay: trade a list of signals the way a person with one account would.

Each trade (from ``strategies.backtest``) carries its signal, entry and exit
dates, entry/exit/stop prices. The replay walks the calendar:

- capital starts at ``capital``; positions are sized so the loss at the stop is
  ``risk_pct`` of current equity, and at most ``max_weight`` of equity;
- at most ``max_positions`` are open at once; when more signals than free slots
  arrive on one day, the best ranked (``priority`` then tighter risk) are taken;
- cash must cover the position (no margin);
- drawdown brakes: below ``dd_half`` from the equity peak the risk is halved;
  below ``dd_stop`` no new trades until equity recovers above ``dd_half``;
- P&L is booked at the exit (equity is the realized curve) and costs are
  already inside each trade's net return.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Account:
    capital: float = 500_000.0
    risk_pct: float = 1.0
    max_positions: int = 6
    max_weight: float = 0.25
    dd_half: float | None = 10.0
    dd_stop: float | None = 20.0


def replay(trades: pd.DataFrame, acct: Account | None = None, priority: dict | None = None) -> dict:
    acct = acct or Account()
    if trades.empty:
        return {"trades": 0}
    priority = priority or {}
    t = trades.copy()
    t["prio"] = t["strategy"].map(priority).fillna(9)
    t["risk_frac"] = (t["entry"] - t["stop"]) / t["entry"]
    t = t[t["risk_frac"] > 0].sort_values(["entry_date", "prio", "risk_frac"])
    days = sorted(set(t["entry_date"]) | set(t["exit_date"]))
    by_entry = {d: g for d, g in t.groupby("entry_date")}  # noqa: C416
    equity = cash = acct.capital
    peak = equity
    open_pos: list[dict] = []
    held: set[str] = set()
    curve, taken = [], []
    halted, halted_days = False, 0
    for d in days:
        # Exits first (a slot freed today can be reused today).
        still = []
        for p in open_pos:
            if p["exit_date"] <= d:
                pnl = p["qty"] * p["entry"] * p["ret_pct"] / 100
                cash += p["qty"] * p["entry"] + pnl
                equity += pnl
                held.discard(p["symbol"])
                taken.append({**p, "pnl": pnl})
            else:
                still.append(p)
        open_pos = still
        peak = max(peak, equity)
        dd = (1 - equity / peak) * 100
        if acct.dd_stop is not None and dd >= acct.dd_stop:
            halted = True
        if halted:
            halted_days += 1
            if acct.dd_half is None or dd < acct.dd_half or halted_days >= 20:
                halted, halted_days = False, 0
                peak = equity  # restart the drawdown clock after a pause
        risk = acct.risk_pct
        if acct.dd_half is not None and dd >= acct.dd_half:
            risk /= 2
        if not halted and d in by_entry:
            for _, s in by_entry[d].iterrows():
                if len(open_pos) >= acct.max_positions or s["symbol"] in held:
                    continue
                per_share = s["entry"] - s["stop"]
                qty = int(min(equity * risk / 100 / per_share, equity * acct.max_weight / s["entry"]))
                if qty <= 0 or qty * s["entry"] > cash:
                    continue
                cash -= qty * s["entry"]
                held.add(s["symbol"])
                open_pos.append({**s.to_dict(), "qty": qty, "risk_used": risk})
        curve.append((d, equity, len(open_pos)))
    curve_df = pd.DataFrame(curve, columns=["date", "equity", "open"]).set_index("date")
    return summarize(curve_df, pd.DataFrame(taken), acct.capital)


def summarize(curve: pd.DataFrame, taken: pd.DataFrame, capital: float) -> dict:
    if taken.empty:
        return {"trades": 0}
    eq = curve["equity"]
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    peak = eq.cummax()
    dd = (1 - eq / peak) * 100
    wins = taken["pnl"] > 0
    streak = worst = 0
    for w in wins:
        streak = 0 if w else streak + 1
        worst = max(worst, streak)
    yearly = eq.groupby(eq.index.year).last()
    start_by_year = eq.groupby(eq.index.year).first()
    prev = yearly.shift(1).fillna(capital)
    yearly_ret = ((yearly / prev - 1) * 100).round(1)
    return {
        "trades": int(len(taken)),
        "trades_per_year": round(len(taken) / years, 1),
        "win_rate": round(float(wins.mean() * 100), 1),
        "final_equity": round(float(eq.iloc[-1]), 0),
        "total_return_pct": round(float((eq.iloc[-1] / capital - 1) * 100), 1),
        "cagr_pct": round(float(((eq.iloc[-1] / capital) ** (1 / years) - 1) * 100), 1),
        "max_drawdown_pct": round(float(dd.max()), 1),
        "worst_losing_streak": int(worst),
        "avg_open_positions": round(float(curve["open"].mean()), 1),
        "yearly_return_pct": {int(k): float(v) for k, v in yearly_ret.items()},
        "first_year_start": {int(k): float(v) for k, v in start_by_year.items()},
        "by_strategy": {k: round(float(v), 0) for k, v in taken.groupby("strategy")["pnl"].sum().items()},
        "profit_factor": round(float(taken.loc[wins, "pnl"].sum() / -taken.loc[~wins, "pnl"].sum()), 2)
        if (~wins).any() else float("inf"),
    }


def gate_by_recent_record(trades: pd.DataFrame, strategy: str, lookback_days: int = 182,
                          min_trades: int = 20, min_r: float = 0.05) -> pd.DataFrame:
    """Keep ``strategy``'s trades only on days its own trades CLOSED in the prior
    ``lookback_days`` averaged at least ``min_r`` (no look-ahead: only exits before
    the signal day count). Other strategies pass through."""
    mine = trades[trades["strategy"] == strategy].sort_values("exit_date")
    if mine.empty:
        return trades
    exits = mine["exit_date"].to_numpy()
    rs = mine["r"].to_numpy()
    keep = []
    for d in mine["signal_date"]:
        lo = d - pd.Timedelta(days=lookback_days)
        sel = (exits < np.datetime64(d)) & (exits >= np.datetime64(lo))
        keep.append(sel.sum() >= min_trades and rs[sel].mean() >= min_r)
    kept = mine[np.array(keep, dtype=bool)]
    return pd.concat([trades[trades["strategy"] != strategy], kept]).sort_values("entry_date")
