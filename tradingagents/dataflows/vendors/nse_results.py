"""Official company data from NSE: annual results (XBRL filings) and shareholding.

    years = annual_results("SJS")      # [{"fy_end": "2024-03-31", "basis": "Consolidated",
                                        #   "revenue": ..., "profit": ..., "ocf": ..., ...}, ...]
    own = shareholding("SJS")          # {"promoter_pct": 19.99, "pledged_pct": 4.79, "as_of": ...}

The results come from the XBRL file each company files with NSE (FY2017 onward in the
current format). Companies that moved to SEBI's 2025 "integrated filing" may not list
their latest years here; the caller merges Yahoo's last four years on top. One basis is
used per company (consolidated when the company files it, else standalone), so growth is
never computed across a basis change. XBRL files never change, so each is cached forever.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime

import requests

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

_HOME = "https://www.nseindia.com/"
_RESULTS = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={sym}&period=Annual"
_HOLDING = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={sym}"
_PLEDGE = "https://www.nseindia.com/api/corporate-pledgedata?index=equities&symbol={sym}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json,*/*"}

_lock = threading.Lock()
_session: requests.Session | None = None
_last_call = 0.0
_MIN_GAP = 0.35  # seconds between NSE calls: NSE blocks bursts


def _folder(*parts: str) -> str:
    path = os.path.join(get_config()["data_cache_dir"], "nse", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def _get(url: str, as_json: bool = True):
    """One polite GET through a cookie session (NSE's API needs the home-page cookies)."""
    global _session, _last_call
    for attempt in range(3):
        with _lock:
            if _session is None:
                _session = requests.Session()
                _session.headers.update(_HEADERS)
                try:
                    _session.get(_HOME, timeout=20)
                except requests.RequestException:
                    pass
            wait = _MIN_GAP - (time.time() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.time()
            sess = _session
        try:
            r = sess.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.warning("NSE fetch failed (%s)", type(exc).__name__)
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (401, 403):  # cookies expired: start a fresh session
            with _lock:
                _session = None
            time.sleep(2)
            continue
        if r.status_code != 200:
            return None
        if not as_json:
            return r.text
        try:
            return r.json()
        except ValueError:
            return None
    return None


# --- XBRL ---------------------------------------------------------------------------

_CONTEXT = re.compile(r"<(?:\w+:)?context\b[^>]*\bid=\"([^\"]+)\"(.*?)</(?:\w+:)?context>", re.S)
_START = re.compile(r"<(?:\w+:)?startDate>([^<]+)<")
_END = re.compile(r"<(?:\w+:)?endDate>([^<]+)<")
_INSTANT = re.compile(r"<(?:\w+:)?instant>([^<]+)<")
FIELDS = {
    "revenue": ("RevenueFromOperations",),
    "profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLoss"),
    "pbt": ("ProfitBeforeTax",),
    "finance_costs": ("FinanceCosts",),
    "ocf": ("CashFlowsFromUsedInOperatingActivities",),
    "equity": ("EquityAttributableToOwnersOfParent", "Equity"),
    "borrowings_nc": ("BorrowingsNoncurrent",),
    "borrowings_c": ("BorrowingsCurrent",),
}


def _value(xml: str, tag: str, ctx: str) -> float | None:
    m = re.search(rf"<[\w\-]+:{tag}\b[^>]*contextRef=\"{re.escape(ctx)}\"[^>]*>([^<]*)<", xml)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_xbrl(xml: str) -> dict:
    """The full-year numbers of one annual-results XBRL file (rupees), or {} when unreadable."""
    durations, instants = {}, {}
    # NSE files label every context with the quarter's dates; the real period of each
    # column is in its DateOfStart/EndOfReportingPeriod facts, so those win.
    starts = dict(re.findall(r"DateOfStartOfReportingPeriod\b[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]+)<", xml))
    ends = dict(re.findall(r"DateOfEndOfReportingPeriod\b[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]+)<", xml))
    for cid in starts.keys() & ends.keys():
        durations[cid] = (starts[cid].strip(), ends[cid].strip())
    for cid, body in _CONTEXT.findall(xml):
        s, e, i = _START.search(body), _END.search(body), _INSTANT.search(body)
        if s and e and cid not in durations:
            durations[cid] = (s.group(1).strip(), e.group(1).strip())
        elif i:
            instants[cid] = i.group(1).strip()
    # The full year: the longest duration (about 12 months) ending last.
    best, best_days = None, 0
    for cid, (s, e) in durations.items():
        try:
            days = (date.fromisoformat(e[:10]) - date.fromisoformat(s[:10])).days
        except ValueError:
            continue
        if days > best_days or (days == best_days and best and e > durations[best][1]):
            best, best_days = cid, days
    if best is None or best_days < 330:
        return {}
    fy_end = durations[best][1][:10]
    inst = next((c for c, d in instants.items() if d[:10] == fy_end), None)
    out = {"fy_end": fy_end}
    for key, tags in FIELDS.items():
        ctx = inst if key in ("equity", "borrowings_nc", "borrowings_c") else best
        if ctx is None:
            continue
        for tag in tags:
            v = _value(xml, tag, ctx)
            if v is not None:
                out[key] = v
                break
    nature = re.search(r"NatureOfReportStandaloneConsolidated\b[^>]*>([^<]+)<", xml)
    if nature:
        out["basis"] = nature.group(1).strip()
    return out if "revenue" in out else {}


def _xbrl(url: str) -> dict:
    name = re.sub(r"[^\w.]", "_", url.rsplit("/", 1)[-1])
    path = os.path.join(_folder("xbrl"), name + ".json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    xml = _get(url, as_json=False)
    if not xml:
        return {}
    parsed = parse_xbrl(xml)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh)
    return parsed


def _monthly(name: str, sym: str, fetch):
    """A per-symbol JSON cached for the current month."""
    path = os.path.join(_folder(name), f"{sym}-{date.today():%Y-%m}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    data = fetch()
    if data is not None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return data


def annual_results(symbol: str) -> list[dict]:
    """Up to ~8 years of official annual results, oldest first, on one basis."""
    sym = symbol.removesuffix(".NS").upper()
    filings = _monthly("results", sym, lambda: _get(_RESULTS.format(sym=sym))) or []
    rows = [f for f in filings if isinstance(f, dict) and str(f.get("xbrl", "")).endswith(".xml")
            and f.get("toDate")]
    if not rows:
        return []
    consolidated = [f for f in rows if f.get("consolidated", "").lower() == "consolidated"]
    basis = "Consolidated" if consolidated else "Non-Consolidated"
    pick = consolidated or [f for f in rows if f.get("consolidated", "").lower() != "consolidated"]
    by_year: dict[str, dict] = {}
    for f in pick:
        try:
            fy = datetime.strptime(f["toDate"], "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        if fy in by_year:
            continue  # the first listed is the latest filing for that year (a revision)
        parsed = _xbrl(f["xbrl"])
        if parsed and parsed.get("fy_end") == fy:
            parsed["basis"] = basis
            by_year[fy] = parsed
    return [by_year[k] for k in sorted(by_year)]


def shareholding(symbol: str) -> dict:
    """Promoter holding (latest quarter) and the share of promoter shares pledged, from NSE."""
    sym = symbol.removesuffix(".NS").upper()

    def fetch():
        out = {}
        hold = _get(_HOLDING.format(sym=sym))
        if isinstance(hold, list) and hold:
            try:
                out["promoter_pct"] = float(hold[0].get("pr_and_prgrp"))
                out["as_of"] = hold[0].get("date")
            except (TypeError, ValueError):
                pass
        pledge = _get(_PLEDGE.format(sym=sym))
        rows = pledge.get("data") if isinstance(pledge, dict) else None
        if rows:
            try:
                out["pledged_pct"] = float(str(rows[0].get("percSharesPledged", "0")).strip() or 0)
            except ValueError:
                pass
        elif out:
            out["pledged_pct"] = 0.0  # nothing disclosed: no pledge
        return out or None

    return _monthly("holding", sym, fetch) or {}
