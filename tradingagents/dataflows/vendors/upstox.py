"""Upstox's public historical-candle API: daily NSE bars without an account or API key.

    bars = daily("NSE_EQ|INE002A01018", date(2021, 11, 5), date(2026, 11, 5))
    frames = download_daily({"RELIANCE.NS": "INE002A01018"}, years=5, stamp="2026-11-05")

Prices are adjusted for splits and bonuses (checked on RELIANCE's 1:1 bonus of Oct 2024)
but not for dividends, so they match what a broker shows. Demergers are not adjusted
(neither by Yahoo): the scanner guards against one-day jumps of 40%+ separately.
Upstox can lag the latest equity session by a day; the loader fills it from NSE's
bhavcopy, as it does for Yahoo.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import logging
import os
import time
from datetime import date, timedelta
from urllib.parse import quote

import pandas as pd
import requests

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

_URL = "https://api.upstox.com/v3/historical-candle/{key}/days/1/{to}/{frm}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
NIFTY_KEY = "NSE_INDEX|Nifty 50"


def equity_key(isin: str) -> str:
    return f"NSE_EQ|{isin}"


def daily(key: str, start: date, end: date, retries: int = 3) -> pd.DataFrame:
    """OHLCV bars for one instrument, oldest first (empty when Upstox has none)."""
    url = _URL.format(key=quote(key, safe=""), to=end.isoformat(), frm=start.isoformat())
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
        except requests.RequestException as exc:
            logger.warning("upstox fetch failed (%s); retry %d", type(exc).__name__, attempt + 1)
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:  # rate limited: back off
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            return _empty()
        try:
            candles = r.json().get("data", {}).get("candles", [])
        except ValueError:
            return _empty()
        return _frame(candles)
    return _empty()


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"], dtype=float)


def _frame(candles: list) -> pd.DataFrame:
    if not candles:
        return _empty()
    df = pd.DataFrame([c[:6] for c in candles], columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts").str[:10]), name=None)
    df = df[~df.index.duplicated(keep="last")].sort_index().astype(float)
    return df.dropna(subset=["Close"])


def _cache_path(keys: list[str], years: int, stamp: str) -> str:
    digest = hashlib.sha1(",".join(sorted(keys)).encode()).hexdigest()[:12]
    folder = os.path.join(get_config()["data_cache_dir"], "bulk")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"upstox-{stamp}-{years}y-{digest}.pkl")


def download_daily(keys: dict[str, str], years: int = 5, stamp: str | None = None, progress=None,
                   refresh: bool = False, workers: int = 8) -> dict[str, pd.DataFrame]:
    """``{symbol: OHLCV}`` for ``{symbol: upstox instrument key}``. Cached per ``stamp``.
    Symbols Upstox returns nothing for are left out (the caller falls back to Yahoo)."""
    end = date.fromisoformat(stamp) if stamp else date.today()
    start = end - timedelta(days=int(365.25 * years) + 5)
    path = _cache_path(list(keys.values()), years, stamp) if stamp else None
    if path and not refresh and os.path.exists(path):
        try:
            return pd.read_pickle(path)
        except Exception:
            logger.warning("upstox cache %s unreadable; refetching", path)
    out: dict[str, pd.DataFrame] = {}
    items = sorted(keys.items())
    done = 0
    # The end date is inclusive on Upstox's side; ask one day past it so the latest bar comes back.
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(daily, key, start, end + timedelta(days=1)): sym for sym, key in items}
        for fut in cf.as_completed(futures):
            sym = futures[fut]
            try:
                df = fut.result()
            except Exception:
                df = _empty()
            if not df.empty:
                out[sym] = df[df.index <= pd.Timestamp(end)]
            done += 1
            if progress and done % 100 == 0:
                progress(done, len(items))
    if path and out:
        pd.to_pickle(out, path)
    return out
