"""Daily OHLCV for a whole universe at once, for scanners and universe backtests.

Free Yahoo data through yfinance's batched, threaded download: no API key and
no paid plan. One pickle per (trading day, universe, period) is cached, so a
second scan the same day reads from disk.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import warnings

import pandas as pd
import yfinance as yf

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

_CHUNK = 150
STALE_TTL_SECONDS = 1800  # a lagging download is reused for 30 minutes


def _cache_path(symbols: list[str], period: str, stamp: str) -> str:
    digest = hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()[:12]
    folder = os.path.join(get_config()["data_cache_dir"], "bulk")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"daily-{stamp}-{period}-{digest}.pkl")


def _split(frame: pd.DataFrame | None, symbols: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if frame is None or frame.empty:
        return out
    if not isinstance(frame.columns, pd.MultiIndex):
        frame = pd.concat({symbols[0]: frame}, axis=1)
    level = 0 if set(symbols) & set(frame.columns.get_level_values(0)) else 1
    for sym in symbols:
        try:
            df = frame.xs(sym, axis=1, level=level).copy()
        except KeyError:
            continue
        if "Close" not in df.columns:
            continue
        df = df.dropna(subset=["Close"])
        if df.empty:
            continue
        idx = pd.to_datetime(df.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        df.index = idx.normalize()
        out[sym] = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    return out


def _download(chunk: list[str], period: str) -> pd.DataFrame:
    with warnings.catch_warnings():
        # yfinance's own pandas deprecation noise, not ours.
        warnings.filterwarnings("ignore", message=".*inplace keyword.*")
        return yf.download(
            chunk, period=period, interval="1d", auto_adjust=True,
            group_by="ticker", threads=True, progress=False,
        )


def download_daily(
    symbols: list[str],
    period: str = "3y",
    stamp: str | None = None,
    progress=None,
    refresh: bool = False,
    probe: str | None = None,
) -> dict[str, pd.DataFrame]:
    """``{symbol: OHLCV frame}`` of split/dividend-adjusted daily bars.

    ``stamp`` keys the cache (pass the date of the last settled session, so a
    run after the close refetches once and later runs that day reuse it).
    Symbols Yahoo returns nothing for are left out of the result.

    ``probe`` names a symbol (e.g. the Nifty) whose latest bar must reach
    ``stamp``: a cache that falls short is refetched, and a download that falls
    short (Yahoo lagging) is returned but not cached, so a later run retries.
    """

    def reaches(d: dict) -> bool:
        if not probe or not stamp:
            return True
        frame = d.get(probe)
        return frame is not None and not frame.empty and str(frame.index[-1].date()) >= stamp

    symbols = sorted(set(symbols))
    path = _cache_path(symbols, period, stamp) if stamp else None
    stale_path = path + ".stale" if path else None
    if path and not refresh and os.path.exists(path):
        try:
            cached = pd.read_pickle(path)
            if reaches(cached):
                return cached
        except Exception:  # a torn cache file is a miss
            logger.warning("bulk cache %s unreadable; refetching", path)
    # Yahoo lagging: reuse a short-lived copy instead of refetching every symbol on every run.
    if stale_path and not refresh and os.path.exists(stale_path)             and time.time() - os.path.getmtime(stale_path) < STALE_TTL_SECONDS:
        try:
            return pd.read_pickle(stale_path)
        except Exception:
            pass

    data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), _CHUNK):
        chunk = symbols[i : i + _CHUNK]
        frame = None
        for attempt in range(3):
            try:
                frame = _download(chunk, period)
                break
            except Exception as exc:  # rate limit or network: back off and retry
                logger.warning("bulk download failed (%s); retry %d", type(exc).__name__, attempt + 1)
                time.sleep(5 * (attempt + 1))
        data.update(_split(frame, chunk))
        if progress:
            progress(min(i + _CHUNK, len(symbols)), len(symbols))
    if path and data:
        if reaches(data):
            pd.to_pickle(data, path)
        else:
            pd.to_pickle(data, stale_path)
    return data


def next_earnings_date(symbol: str):
    """The next scheduled results date Yahoo lists for ``symbol``, or None."""
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*inplace keyword.*")
            cal = yf.Ticker(symbol).calendar or {}
    except Exception:  # unknown or unavailable: no date, not an error
        return None
    dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
    return min(dates) if dates else None


FUNDAMENTAL_FIELDS = (
    "trailingPE", "forwardPE", "priceToBook", "returnOnEquity", "returnOnAssets", "debtToEquity",
    "revenueGrowth", "earningsGrowth", "profitMargins", "operatingMargins", "marketCap",
    "dividendYield", "freeCashflow", "currentRatio", "recommendationMean", "recommendationKey",
    "targetMeanPrice", "numberOfAnalystOpinions", "heldPercentInsiders", "sector", "industry",
)


def fundamentals_snapshot(symbols: list[str], stamp: str, workers: int = 8) -> dict[str, dict]:
    """Today's Yahoo fundamentals for ``symbols`` (a present-day snapshot, not point-in-time).

    Cached per ``stamp`` (a date), so a second run the same day makes no requests.
    """
    import concurrent.futures as cf
    import json

    folder = os.path.join(get_config()["data_cache_dir"], "bulk")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"fundamentals-{stamp}.json")
    cache: dict[str, dict] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}
    missing = [s for s in symbols if s not in cache]

    def one(sym):
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*inplace keyword.*")
                info = yf.Ticker(sym).info or {}
        except Exception:  # unavailable: an empty record, retried tomorrow
            return sym, {}
        return sym, {k: info.get(k) for k in FUNDAMENTAL_FIELDS if info.get(k) is not None}

    if missing:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for sym, rec in pool.map(one, missing):
                cache[sym] = rec
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, default=str)
    return {s: cache.get(s, {}) for s in symbols}


def intraday_quotes(symbols: list[str]) -> dict[str, dict]:
    """Today's open, last price, high and volume from Yahoo's 5-minute bars."""
    out: dict[str, dict] = {}
    symbols = sorted(set(symbols))
    for k in range(0, len(symbols), 150):
        chunk = symbols[k:k + 150]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(chunk, period="1d", interval="5m", group_by="ticker", progress=False,
                             threads=True, auto_adjust=False)
        if df is None or df.empty:
            continue
        for sym in chunk:
            try:
                d = df[sym] if len(chunk) > 1 else df
                d = d.dropna(subset=["Close"])
            except KeyError:
                continue
            if d.empty:
                continue
            out[sym] = {"open": float(d["Open"].iloc[0]), "price": float(d["Close"].iloc[-1]),
                        "high": float(d["High"].max()), "volume": float(d["Volume"].sum())}
    return out
