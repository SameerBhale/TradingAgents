"""The NSE breakout scan: today's signals, each with a full trade plan and the
rule's own historical record.

    from tradingagents.scanner.breakout import run_scan
    result = run_scan(capital=500_000, risk_pct=1.0)

The rule (``DEFAULT_RULES``) was chosen on 2022 - mid-2024 NSE data and then
checked on mid-2024 - 2026, a weak, choppy market, where it stayed positive
after costs while looser breakout rules and random entries lost money. See
``docs/breakout_research.md`` for the numbers and the caveats.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import pandas as pd

from tradingagents.dataflows import india
from tradingagents.dataflows.vendors.yahoo.bulk import download_daily, next_earnings_date
from tradingagents.scanner import engine as E

DEFAULT_RULES = E.Rules(
    lookback=250,          # a new 52-week high
    vol_mult=1.5,          # on at least 1.5x the 50-day average volume
    base_days=20,
    max_base_pct=12.0,     # out of a tight 4-week base
    max_extension_pct=4.0,
    trend=True,            # close > 50-DMA > 200-DMA
    min_price=100.0,       # no penny stocks: INR 100 and up
    min_turnover_cr=10.0,  # and INR 10 crore+ traded a day
    strong_close=0.6,
    regime="nifty50",      # only while the Nifty 50 is above its 50-DMA
    min_rs=0.0,            # beating the Nifty over 6 months
    stop_atr=2.0,
    max_risk_pct=6.0,
    target_r=2.0,
    exit_mode="target",
    max_hold=20,
    max_gap_pct=3.0,
    cost_pct=0.30,
)

HISTORY_PERIOD = "5y"
NIFTY = "^NSEI"


@dataclass
class Pick:
    symbol: str
    name: str
    signal_date: str
    close: float
    entry: float                 # buy-stop trigger for the next session
    max_entry: float             # do not fill above this (no chasing)
    stop: float
    target: float
    risk_pct: float
    reward_pct: float
    rr: float
    quantity: int
    capital_needed: float
    max_loss: float              # at the stop, before costs and slippage
    exit_by: str                 # time exit: close the trade at this session's close
    hold_sessions: int
    volume_ratio: float
    base_pct: float
    rs_vs_nifty_pct: float
    turnover_cr: float
    week52_high: float
    stock_history: dict = field(default_factory=dict)
    score: float = 0.0
    earnings_date: str | None = None
    earnings_in_window: bool = False


@dataclass
class ScanResult:
    as_of: str
    market: dict
    regime_ok: bool
    picks: list[Pick]
    watchlist: list[dict]
    record_all: dict
    record_12m: dict
    record_recent: dict
    universe_size: int
    scanned: int
    rules: dict
    notes: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["picks"] = [asdict(p) for p in self.picks]
        return d


def _universe() -> dict[str, india.IndianSecurity]:
    """NSE mainboard equities in the normal EQ series (excludes SME, ETFs, T2T)."""
    return {
        s.yahoo: s for s in india.nse_universe().values()
        if s.segment == "EQUITY" and s.series == "EQ"
    }


def _settled_session(now=None) -> date:
    return india.market_status(now).last_completed_session


def _trading_days_after(day: date, n: int) -> date:
    for _ in range(n):
        day = india.next_trading_day(day)
    return day


def _clip(frame: pd.DataFrame, last: date) -> pd.DataFrame:
    """Bars through the last settled session only: never a forming candle."""
    return frame[frame.index <= pd.Timestamp(last)]


def _size(capital: float, risk_pct: float, entry: float, stop: float) -> int:
    per_share = entry - stop
    if per_share <= 0 or capital <= 0:
        return 0
    by_risk = math.floor(capital * risk_pct / 100 / per_share)
    by_cash = math.floor(capital * 0.25 / entry)  # at most 25% of capital in one stock
    return max(0, min(by_risk, by_cash))


def run_scan(
    capital: float = 500_000.0,
    risk_pct: float = 1.0,
    top: int = 5,
    rules: E.Rules = DEFAULT_RULES,
    refresh: bool = False,
    progress=None,
    as_of: date | None = None,
) -> ScanResult:
    """Scan every NSE EQ stock for today's breakouts and plan each trade."""
    universe = _universe()
    settled = _settled_session()
    last = min(as_of, settled) if as_of else settled
    raw = download_daily(
        list(universe) + [NIFTY], period=HISTORY_PERIOD, stamp=settled.isoformat(),
        progress=progress, refresh=refresh,
    )
    if NIFTY not in raw:
        raise RuntimeError("Yahoo returned no Nifty 50 data; try again in a few minutes (--refresh).")
    nifty = _clip(raw.pop(NIFTY), last)
    data = {s: _clip(df, last) for s, df in raw.items()}
    data = {s: df for s, df in data.items() if len(df) > 260}
    market = E.market_frame(nifty, data)
    notes: list[str] = []

    signal_day = market.index[-1]
    if signal_day.date() != last:
        notes.append(
            f"Yahoo's latest Nifty bar is {signal_day.date()}, not the last settled session "
            f"{last}; the data may lag. Re-run later with --refresh."
        )
    m = market.iloc[-1]
    regime_ok = bool(E.regime_ok(market, rules).iloc[-1])
    market_state = {
        "nifty": round(float(m["nifty"]), 2),
        "nifty_sma50": round(float(m["nifty_sma50"]), 2),
        "nifty_sma200": round(float(m["nifty_sma200"]), 2),
        "nifty_ret_6m_pct": round(float(m["nifty_ret126"]) * 100, 1),
        "breadth_pct": round(float(m["breadth"]), 1),
    }

    picks: list[Pick] = []
    watch: list[dict] = []
    all_trades: list[dict] = []
    for sym, df in data.items():
        ind = E.indicators(df, rules)
        trades = E.backtest_symbol(ind, rules, market)
        for t in trades:
            t["symbol"] = sym
        all_trades.extend(trades)
        if ind.index[-1] != signal_day:
            continue
        row = ind.iloc[-1]
        sig = bool(E.signal_mask(ind.iloc[-260:], rules, market).iloc[-1])
        if sig:
            plan = E.plan_for(row, rules)
            if plan is None:
                continue
            qty = _size(capital, risk_pct, plan.trigger, plan.stop)
            sec = universe[sym]
            hist = E.summarize(trades)
            pick = Pick(
                symbol=sym, name=sec.name, signal_date=str(signal_day.date()),
                close=round(float(row["Close"]), 2), entry=plan.trigger,
                max_entry=round(plan.trigger * (1 + rules.max_gap_pct / 100), 2),
                stop=plan.stop, target=plan.target, risk_pct=round(plan.risk_pct, 2),
                reward_pct=round((plan.target / plan.trigger - 1) * 100, 2), rr=round(plan.rr, 2),
                quantity=qty, capital_needed=round(qty * plan.trigger, 0),
                max_loss=round(qty * (plan.trigger - plan.stop), 0),
                exit_by=str(_trading_days_after(signal_day.date(), rules.max_hold)),
                hold_sessions=rules.max_hold,
                volume_ratio=round(float(row["Volume"] / row["vol50"]), 2),
                base_pct=round(float(row["base_pct"]), 1),
                rs_vs_nifty_pct=round(float(row["ret126"] - m["nifty_ret126"]) * 100, 1),
                turnover_cr=round(float(row["turnover_cr"]), 1),
                week52_high=round(float(row["high52"]), 2),
                stock_history={k: hist.get(k) for k in ("trades", "win_rate", "expectancy_r")},
            )
            # Research: tighter bases and tighter stops followed through best.
            pick.score = round(-(pick.base_pct + pick.risk_pct), 2)
            picks.append(pick)
        elif (
            row["Close"] >= rules.min_price and row["turnover_cr"] >= rules.min_turnover_cr
            and row["Close"] > row["sma50"] > row["sma200"] and row["base_pct"] <= rules.max_base_pct
            and pd.notna(row["pivot"]) and row["Close"] >= row["pivot"] * 0.97
        ):
            level = float(row["pivot"])
            above = row["Close"] > level
            watch.append({
                "symbol": sym, "name": universe[sym].name, "close": round(float(row["Close"]), 2),
                "breakout_level": round(level, 2),
                "distance_pct": round(float(level / row["Close"] - 1) * 100, 2),
                "base_pct": round(float(row["base_pct"]), 1),
                "volume_ratio": round(float(row["Volume"] / row["vol50"]), 2),
                "status": "above the 52-week high without the volume or strong close; needs a "
                          "confirming close" if above else "below the 52-week high; alert on a close above it",
            })

    picks.sort(key=lambda p: p.score, reverse=True)
    picks = picks[:top]
    for p in picks:
        when = next_earnings_date(p.symbol)
        if when is not None:
            p.earnings_date = str(when)
            p.earnings_in_window = p.signal_date < p.earnings_date <= p.exit_by
    watch.sort(key=lambda w: (w["distance_pct"], w["base_pct"]))
    trades = pd.DataFrame(all_trades)
    year_ago = pd.Timestamp(last - timedelta(days=365))
    recent = pd.Timestamp(last - timedelta(days=182))
    if not regime_ok:
        notes.append(
            "Market filter is OFF: the Nifty 50 is below its 50-day average. The rule takes no "
            "new trades in this regime (breakouts mostly failed in such markets). Watch the list; wait."
        )
    return ScanResult(
        as_of=str(signal_day.date()),
        market=market_state,
        regime_ok=regime_ok,
        picks=picks,
        watchlist=watch[:15],
        record_all=E.summarize(trades) if not trades.empty else {"trades": 0},
        record_12m=E.summarize(trades[trades.signal_date >= year_ago]) if not trades.empty else {"trades": 0},
        record_recent=E.summarize(trades[trades.signal_date >= recent]) if not trades.empty else {"trades": 0},
        universe_size=len(universe),
        scanned=len(data),
        rules=asdict(rules),
        notes=notes,
    )
