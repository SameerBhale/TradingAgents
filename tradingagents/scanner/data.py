"""One daily download serves every scan: large/mid/small-cap stocks, liquid ETFs and the Nifty."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from tradingagents.dataflows import india
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


def stock_universe() -> dict[str, india.IndianSecurity]:
    return {
        s.yahoo: s for s in india.nse_universe().values()
        if s.segment == "EQUITY" and s.series == "EQ" and india.cap_class(s.yahoo) in STOCK_CAPS
    }


# Cash-like and debt ETFs are parking places, not trades.
_NOT_TRADES = ("liquid", "1d rate", "overnight", "money market", "gilt", "bond", "g-sec", "gsec", "sdl",
               "treasury", "t-bill", "tbill", "debt", "crisil")


def etf_universe() -> dict[str, india.IndianSecurity]:
    return {
        s.yahoo: s for s in india.nse_universe().values()
        if s.segment == "ETF" and not any(w in s.name.lower() or w in s.symbol.lower() for w in _NOT_TRADES)
    }


def load(refresh: bool = False, progress=None, as_of: date | None = None) -> MarketData:
    stocks_u, etfs_u = stock_universe(), etf_universe()
    settled = india.market_status().last_completed_session
    raw = download_daily(
        list(stocks_u) + list(etfs_u) + [NIFTY], period="5y", stamp=settled.isoformat(),
        progress=progress, refresh=refresh, probe=NIFTY,
    )
    if NIFTY not in raw:
        raise RuntimeError("Yahoo returned no Nifty 50 data; try again shortly with --refresh.")
    cut = pd.Timestamp(min(as_of, settled) if as_of else settled)
    nifty = raw.pop(NIFTY)
    nifty = nifty[nifty.index <= cut]
    clip = {s: d[d.index <= cut] for s, d in raw.items()}
    stocks = {s: d for s, d in clip.items() if s in stocks_u and len(d) > 260}
    etfs = {s: d for s, d in clip.items() if s in etfs_u and len(d) > 260}
    return MarketData(stocks, etfs, nifty, settled, nifty.index[-1].date(), {**stocks_u, **etfs_u})
