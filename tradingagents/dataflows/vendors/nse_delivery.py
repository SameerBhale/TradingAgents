"""Follow the money: NSE's delivery position and bulk/block deals, free from NSE archives.

Delivery % is the share of the day's traded quantity that was actually taken into (or
out of) demat, not squared off intraday. Funds buy for delivery; day traders do not. So
a rising price on heavy volume *and* high delivery is the footprint of real buying.
NSE publishes it every session (the MTO file), with history back to the 2000s, which
is what lets the scanner backtest it.

Bulk deals (one client trading 0.5%+ of a company's shares in a day) and block deals
(a single 5 crore+ trade in the block window) name the buyer and seller. NSE serves
only the current day freely (its history API refuses scripts), so they are shown as a
live note, never backtested.

    delivery(date(2026, 11, 3))            # {"RELIANCE": (traded_qty, deliv_qty, deliv_pct)}
    history(days)                          # DataFrame: date x symbol of deliv_pct
    deals()                                # today's bulk + block deals, by symbol
"""

from __future__ import annotations

import io
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import requests

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
_MTO = "https://nsearchives.nseindia.com/archives/equities/mto/MTO_{dmy}.DAT"
_BULK = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
_BLOCK = "https://nsearchives.nseindia.com/content/equities/block.csv"

# Names that mark an institution (fund, insurer, bank, FPI) in a bulk/block deal.
_INSTITUTION = re.compile(
    r"MUTUAL FUND|\bMF\b|ASSET MANAGEMENT|AMC|INSURANCE|ASSURANCE|PENSION|PROVIDENT|"
    r"\bFUND\b|FUNDS|INVESTMENT TRUST|SOVEREIGN|GOVERNMENT OF|MONETARY AUTHORITY|"
    r"BANK\b|SECURITIES PLC|SOCIETE GENERALE|GOLDMAN|MORGAN STANLEY|CITIGROUP|BNP PARIBAS|"
    r"NOMURA|JPMORGAN|J P MORGAN|MERRILL|UBS|CLSA|VANGUARD|BLACKROCK|ISHARES|NORGES|"
    r"ABU DHABI|GIC PTE|TEMASEK|SBI LIFE|HDFC LIFE|ICICI PRUDENTIAL"
)


def _folder() -> str:
    path = os.path.join(get_config()["data_cache_dir"], "nse", "mto")
    os.makedirs(path, exist_ok=True)
    return path


def _parse_mto(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) != 7 or parts[0] != "20" or parts[3] != "EQ":
            continue
        try:
            rows.append((parts[2], float(parts[4]), float(parts[5]), float(parts[6])))
        except ValueError:
            continue
    return pd.DataFrame(rows, columns=["symbol", "traded", "deliv", "deliv_pct"])


def _load(day: date, fetch: bool = True) -> pd.DataFrame | None:
    path = os.path.join(_folder(), f"mto-{day:%Y%m%d}.csv")
    if os.path.exists(path):
        try:
            return pd.read_csv(path)
        except (OSError, ValueError):
            pass
    if not fetch:
        return None
    try:
        r = requests.get(_MTO.format(dmy=f"{day:%d%m%Y}"), headers=_HEADERS, timeout=20)
    except requests.RequestException as exc:
        logger.warning("NSE delivery fetch failed for %s: %s", day, exc)
        return None
    if r.status_code != 200 or not r.text.startswith("Security Wise"):
        return None
    df = _parse_mto(r.text)
    if not df.empty:
        df.to_csv(path, index=False)
    return df


def delivery(day: date) -> dict[str, tuple[float, float, float]]:
    """``{symbol: (traded qty, delivered qty, delivery %)}`` for one session; empty if unpublished."""
    df = _load(day)
    if df is None:
        return {}
    return {r.symbol: (r.traded, r.deliv, r.deliv_pct) for r in df.itertuples()}


def history(days, workers: int = 4, fetch: bool = True, progress=None) -> pd.DataFrame:
    """Delivery % as a ``date x symbol`` frame over ``days`` (missing sessions are NaN)."""
    days = sorted(set(days))
    if not days:
        return pd.DataFrame()
    combined = os.path.join(_folder(), f"history-{days[0]:%Y%m%d}-{days[-1]:%Y%m%d}-{len(days)}.pkl")
    if os.path.exists(combined):
        try:
            return pd.read_pickle(combined)
        except (OSError, ValueError):
            pass
    frames: dict[pd.Timestamp, pd.Series] = {}

    def one(d):
        return d, _load(d, fetch=fetch)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for k, (d, df) in enumerate(pool.map(one, days)):
            if df is not None and not df.empty:
                frames[pd.Timestamp(d)] = df.set_index("symbol")["deliv_pct"]
            if progress and k % 100 == 0:
                progress(k, len(days))
    if not frames:
        return pd.DataFrame()
    out = pd.DataFrame(frames).T.sort_index()
    out = out[~out.index.duplicated()]
    if pd.Timestamp(days[-1]) in out.index:  # cache only once the last session is published
        out.to_pickle(combined)
    return out


def _csv(url: str) -> pd.DataFrame:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.BytesIO(r.content))
    except (requests.RequestException, ValueError) as exc:
        logger.warning("NSE deals fetch failed: %s", exc)
        return pd.DataFrame()
    df.columns = [c.strip() for c in df.columns]
    return df


def is_institution(client: str) -> bool:
    return bool(_INSTITUTION.search(str(client).upper()))


def deals() -> dict[str, list[dict]]:
    """Today's bulk and block deals: ``{symbol: [{kind, client, side, qty, price, institution}]}``."""
    out: dict[str, list[dict]] = {}
    for kind, url in (("bulk", _BULK), ("block", _BLOCK)):
        df = _csv(url)
        if df.empty or "Symbol" not in df:
            continue
        for r in df.to_dict("records"):
            price_col = next((c for c in r if c.startswith("Trade Price")), None)
            client = str(r.get("Client Name", "")).strip()
            out.setdefault(str(r["Symbol"]).strip(), []).append({
                "kind": kind, "date": str(r.get("Date", "")), "client": client,
                "side": str(r.get("Buy/Sell", "")).strip().upper(),
                "qty": float(r.get("Quantity Traded", 0) or 0),
                "price": float(r.get(price_col, 0) or 0) if price_col else 0.0,
                "institution": is_institution(client),
            })
    return out
