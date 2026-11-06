"""One daily download serves every scan: large/mid/small-cap stocks, liquid ETFs and the Nifty."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from tradingagents.dataflows import india
from tradingagents.dataflows.vendors import nse_bhav
from tradingagents.dataflows.vendors.yahoo.bulk import download_daily

NIFTY = "^NSEI"
LIQUID_ETF = "LIQUIDBEES.NS"
STOCK_CAPS = ("Large", "Mid", "Small")


@dataclass
class MarketData:
    stocks: dict[str, pd.DataFrame]
    etfs: dict[str, pd.DataFrame]
    nifty: pd.DataFrame
    settled: date          # last NSE session that has closed
    last: date             # the session the data actually reaches (Yahoo can lag)
    securities: dict[str, india.IndianSecurity]
    # Liquid micro caps (below the top 500), kept apart: they never enter the momentum
    # core, the market breadth or the RS rank, and the swing/value verdicts caution them.
    micro: dict[str, pd.DataFrame] = field(default_factory=dict)


def stock_universe() -> dict[str, india.IndianSecurity]:
    return {
        s.yahoo: s for s in india.nse_universe().values()
        if s.segment == "EQUITY" and s.series == "EQ" and india.cap_class(s.yahoo) in STOCK_CAPS
    }


# Micro caps are scanned only when they trade at least this much a day (20-day average).
MICRO_MIN_TURNOVER_CR = 25.0
_MICRO_PRESELECT_CR = 15.0   # loose cut on the last few bhavcopies, before the download


def micro_universe(settled: date, sessions: int = 5) -> dict[str, india.IndianSecurity]:
    """Micro caps (EQ series, price >= Rs 100) whose average traded value over the last
    ``sessions`` NSE bhavcopies is Rs 15 crore or more. The 20-day Rs 25 crore test is
    applied on the downloaded bars."""
    micros = {
        s.symbol.upper(): s for s in india.nse_universe().values()
        if s.segment == "EQUITY" and s.series == "EQ" and india.cap_class(s.yahoo) == "Micro"
    }
    if not micros:
        return {}
    total: dict[str, float] = {}
    days, day = 0, settled
    for _ in range(sessions * 2):
        if days >= sessions:
            break
        bars = nse_bhav.equity_bars(day)
        if bars:
            days += 1
            for sym, (_o, _h, _l, c, v) in bars.items():
                if sym in micros and c >= 100:
                    total[sym] = total.get(sym, 0.0) + c * v / 1e7
        day = india.previous_trading_day(day)
    if not days:
        return {}
    return {micros[s].yahoo: micros[s] for s, t in total.items() if t / days >= _MICRO_PRESELECT_CR}


# Cash-like and debt ETFs are parking places, not trades.
_NOT_TRADES = ("liquid", "1d rate", "overnight", "money market", "gilt", "bond", "g-sec", "gsec", "sdl",
               "treasury", "t-bill", "tbill", "debt", "crisil")


def etf_universe() -> dict[str, india.IndianSecurity]:
    return {
        s.yahoo: s for s in india.nse_universe().values()
        if s.segment == "ETF" and not any(w in s.name.lower() or w in s.symbol.lower() for w in _NOT_TRADES)
    }


def load(refresh: bool = False, progress=None, as_of: date | None = None,
         with_micro: bool = False) -> MarketData:
    stocks_u, etfs_u = stock_universe(), etf_universe()
    settled = india.market_status().last_completed_session
    raw = download_daily(
        list(stocks_u) + list(etfs_u) + [NIFTY], period="5y", stamp=settled.isoformat(),
        progress=progress, refresh=refresh, probe=NIFTY,
    )
    if NIFTY not in raw:
        raise RuntimeError("Yahoo returned no Nifty 50 data; try again shortly with --refresh.")
    # Yahoo lagging (or a row with volume but no prices): fill the gap from NSE's bhavcopy.
    missing, day = [], raw[NIFTY].index[-1].date()
    while (day := india.next_trading_day(day)) <= settled and len(missing) < 5:
        missing.append(day)
    if missing:
        nse_bhav.patch(raw, missing, NIFTY)
    cut = pd.Timestamp(min(as_of, settled) if as_of else settled)
    nifty = raw.pop(NIFTY)
    nifty = nifty[nifty.index <= cut]
    clip = {s: d[d.index <= cut] for s, d in raw.items()}
    stocks = {s: d for s, d in clip.items() if s in stocks_u and len(d) > 260}
    etfs = {s: d for s, d in clip.items() if s in etfs_u and len(d) > 260}
    micro, micro_u = {}, {}
    if with_micro:
        micro, micro_u = _load_micro(settled, missing, cut, refresh, progress)
    return MarketData(stocks, etfs, nifty, settled, nifty.index[-1].date(),
                      {**stocks_u, **etfs_u, **micro_u}, micro)


def _load_micro(settled: date, missing: list[date], cut: pd.Timestamp, refresh: bool, progress):
    """Liquid micro caps, downloaded on their own (so the main cache is untouched)."""
    try:
        micro_u = micro_universe(settled)
    except Exception:  # NSE unreachable: scan without micro caps rather than fail
        return {}, {}
    if not micro_u:
        return {}, {}
    raw = download_daily(list(micro_u), period="5y", stamp=settled.isoformat(),
                         progress=progress, refresh=refresh)
    if missing:
        nse_bhav.patch(raw, missing, NIFTY)
    out = {}
    for s, d in raw.items():
        d = d[d.index <= cut]
        if len(d) <= 260:
            continue
        turnover = float((d["Close"] * d["Volume"]).iloc[-20:].mean()) / 1e7
        if turnover >= MICRO_MIN_TURNOVER_CR:
            out[s] = d
    return out, {s: micro_u[s] for s in out}
