"""NSE's official end-of-day files: the cash-market bhavcopy and the index closes.

Yahoo sometimes lags a session, or publishes a row with volume but no prices (seen on
2026-11-03). These files are NSE's own record of the session, published around
18:00 IST, so the scanner patches the missing days from here.

    bars = equity_bars(date(2026, 11, 3))      # {"RELIANCE": (o, h, l, c, v), ...}
    nifty = index_bar(date(2026, 11, 3))       # (o, h, l, c, 0) or None
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
from datetime import date

import pandas as pd
import requests

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
_BHAV = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
_INDEX = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv"
SERIES = ("EQ", "BE", "BZ")  # ETFs trade in EQ too


def _cache(name: str) -> str:
    folder = os.path.join(get_config()["data_cache_dir"], "nse")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name)


def _get(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
    except requests.RequestException as exc:
        logger.warning("NSE fetch failed: %s", exc)
        return None
    return r.content if r.status_code == 200 and r.content else None


def equity_bars(day: date) -> dict[str, tuple[float, float, float, float, float]]:
    """``{NSE symbol: (open, high, low, close, volume)}`` for one session; empty if unpublished."""
    path = _cache(f"bhav-{day:%Y%m%d}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path)
    else:
        raw = _get(_BHAV.format(ymd=f"{day:%Y%m%d}"))
        if raw is None:
            return {}
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                df = pd.read_csv(z.open(z.namelist()[0]))
        except (zipfile.BadZipFile, IndexError, ValueError):
            return {}
        df.to_csv(path, index=False)
    df = df[df["SctySrs"].isin(SERIES)]
    return {
        r.TckrSymb: (float(r.OpnPric), float(r.HghPric), float(r.LwPric), float(r.ClsPric), float(r.TtlTradgVol))
        for r in df.itertuples()
    }


def index_bar(day: date, name: str = "Nifty 50") -> tuple[float, float, float, float, float] | None:
    path = _cache(f"index-{day:%Y%m%d}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path)
    else:
        raw = _get(_INDEX.format(dmy=f"{day:%d%m%Y}"))
        if raw is None:
            return None
        try:
            df = pd.read_csv(io.BytesIO(raw))
        except ValueError:
            return None
        df.to_csv(path, index=False)
    df.columns = [c.strip() for c in df.columns]
    row = df[df["Index Name"].str.strip().str.lower() == name.lower()]
    if row.empty:
        return None
    r = row.iloc[0]
    return (float(r["Open Index Value"]), float(r["High Index Value"]), float(r["Low Index Value"]),
            float(r["Closing Index Value"]), 0.0)


def patch(frames: dict[str, pd.DataFrame], days: list[date], index_symbol: str = "^NSEI") -> list[date]:
    """Append NSE's bars for ``days`` to Yahoo frames that miss them (in place). Returns days patched."""
    patched = []
    for day in days:
        eq = equity_bars(day)
        nifty = index_bar(day)
        if not eq or nifty is None:
            continue
        ts = pd.Timestamp(day)
        for sym, df in frames.items():
            bar = nifty if sym == index_symbol else eq.get(sym.removesuffix(".NS"))
            if bar is None or (ts in df.index and pd.notna(df.at[ts, "Close"])):
                continue
            df = df[df.index != ts]
            row = pd.DataFrame([bar], columns=["Open", "High", "Low", "Close", "Volume"], index=[ts])
            frames[sym] = pd.concat([df, row]).sort_index()
        patched.append(day)
    return patched
