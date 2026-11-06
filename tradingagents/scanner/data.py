"""One daily download serves every scan: large/mid/small-cap stocks, liquid ETFs and the Nifty.

Price sources, in order (``TRADINGAGENTS_PRICE_SOURCE=yahoo`` uses Yahoo alone):

1. Upstox's public candle API (split/bonus-adjusted, no key needed): the main source.
2. Yahoo Finance for any symbol Upstox returns nothing (or too little history) for.
3. NSE's bhavcopy, the exchange's own record: fills sessions both lag and cross-checks
   the latest close (a bar more than 1% off NSE's close is replaced by NSE's).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import os

import pandas as pd

from tradingagents.dataflows import india
from tradingagents.dataflows.vendors import nse_bhav, upstox
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
    sources: dict[str, int] = field(default_factory=dict)   # bars by source, for the report


def price_source() -> str:
    return os.getenv("TRADINGAGENTS_PRICE_SOURCE", "upstox").strip().lower()


CROSSCHECK_PCT = 1.0


def fetch_prices(secs: dict[str, india.IndianSecurity], settled: date, refresh: bool = False,
                 progress=None, nifty: bool = False) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Daily bars for ``secs`` (and the Nifty), Upstox first, then Yahoo, then NSE's bhavcopy.
    Returns the frames and how many symbols came from each source."""
    stamp = settled.isoformat()
    raw: dict[str, pd.DataFrame] = {}
    used = {"upstox": 0, "yahoo": 0, "nse_patched": 0, "nse_corrected": 0}
    if price_source() == "upstox":
        keys = {sym: upstox.equity_key(sec.isin) for sym, sec in secs.items() if sec.isin}
        if nifty:
            keys[NIFTY] = upstox.NIFTY_KEY
        try:
            got = upstox.download_daily(keys, years=5, stamp=stamp, progress=progress, refresh=refresh)
        except Exception:  # Upstox down: Yahoo carries the whole run
            got = {}
        raw = {k: v for k, v in got.items() if len(v) > 260}
        used["upstox"] = len(raw)
    rest = [s for s in secs if s not in raw] + ([NIFTY] if nifty and NIFTY not in raw else [])
    if rest:
        yahoo = download_daily(rest, period="5y", stamp=stamp, progress=progress, refresh=refresh,
                               probe=NIFTY if NIFTY in rest else None)
        used["yahoo"] = sum(1 for s in yahoo if s != NIFTY)
        raw.update(yahoo)
    # Sessions some frames lack (either source can lag a day): fill them from NSE.
    lasts = [d.index[-1].date() for d in raw.values() if len(d)]
    if lasts:
        day, missing = min(lasts), []
        while (day := india.next_trading_day(day)) <= settled and len(missing) < 5:
            missing.append(day)
        if missing:
            before = {s: len(d) for s, d in raw.items()}
            nse_bhav.patch(raw, missing, NIFTY)
            used["nse_patched"] = sum(1 for s, d in raw.items() if len(d) > before.get(s, 0))
    used["nse_corrected"] = _crosscheck(raw, settled)
    return raw, used


def _crosscheck(frames: dict[str, pd.DataFrame], day: date) -> int:
    """Replace a latest bar more than CROSSCHECK_PCT off NSE's own close. Returns how many."""
    try:
        bars = nse_bhav.equity_bars(day)
    except Exception:
        return 0
    if not bars:
        return 0
    ts, fixed = pd.Timestamp(day), 0
    for sym, df in frames.items():
        bar = bars.get(sym.removesuffix(".NS"))
        if bar is None or ts not in df.index or not bar[3]:
            continue
        close = df.at[ts, "Close"]
        if close == close and abs(close / bar[3] - 1) * 100 <= CROSSCHECK_PCT:
            continue
        df.loc[ts, ["Open", "High", "Low", "Close", "Volume"]] = list(bar)
        fixed += 1
    return fixed


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
    raw, sources = fetch_prices({**stocks_u, **etfs_u}, settled, refresh, progress, nifty=True)
    if NIFTY not in raw:
        raise RuntimeError("No Nifty 50 data from Upstox or Yahoo; try again shortly with --refresh.")
    cut = pd.Timestamp(min(as_of, settled) if as_of else settled)
    nifty = raw.pop(NIFTY)
    nifty = nifty[nifty.index <= cut]
    clip = {s: d[d.index <= cut] for s, d in raw.items()}
    stocks = {s: d for s, d in clip.items() if s in stocks_u and len(d) > 260}
    etfs = {s: d for s, d in clip.items() if s in etfs_u and len(d) > 260}
    micro, micro_u = {}, {}
    if with_micro:
        micro, micro_u = _load_micro(settled, cut, refresh, progress, sources)
    return MarketData(stocks, etfs, nifty, settled, nifty.index[-1].date(),
                      {**stocks_u, **etfs_u, **micro_u}, micro, sources)


def _load_micro(settled: date, cut: pd.Timestamp, refresh: bool, progress, sources: dict):
    """Liquid micro caps, downloaded on their own (so the main cache is untouched)."""
    try:
        micro_u = micro_universe(settled)
    except Exception:  # NSE unreachable: scan without micro caps rather than fail
        return {}, {}
    if not micro_u:
        return {}, {}
    raw, used = fetch_prices(micro_u, settled, refresh, progress)
    for k, v in used.items():
        sources[k] = sources.get(k, 0) + v
    out = {}
    for s, d in raw.items():
        d = d[d.index <= cut]
        if len(d) <= 260:
            continue
        turnover = float((d["Close"] * d["Volume"]).iloc[-20:].mean()) / 1e7
        if turnover >= MICRO_MIN_TURNOVER_CR:
            out[s] = d
    return out, {s: micro_u[s] for s in out}
