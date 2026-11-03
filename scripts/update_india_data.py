"""Refresh the bundled NSE symbol universe and trading-holiday calendar.

    python scripts/update_india_data.py

Writes, under ``tradingagents/dataflows/data/india/``:

- ``nse_symbols.csv``: every NSE-listed security a run can analyze: mainboard
  equities (series EQ/BE/BZ), SME Emerge equities (SM/ST/SZ) and ETFs, with
  ISIN and listing date.
- ``nse_holidays.json``: NSE capital-market trading holidays, as NSE publishes
  them (current calendar year; previous years already in the file are kept).

Both sources are NSE's public archives. BSE-only scrips need no list: a BSE
scrip code such as ``500325`` resolves to ``500325.BO`` by rule.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parents[1] / "tradingagents" / "dataflows" / "data" / "india"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SME_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
FIELDS = ["symbol", "name", "series", "segment", "isin", "listing_date"]
# SEBI's size bands (rank by market cap: 1-100 large, 101-250 mid, 251+ small),
# as NSE's index lists carry them; below the Smallcap 250 is micro cap.
CAP_LISTS = {
    "Large": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "Mid": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "Small": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    "Micro": "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
}


def _csv(session: requests.Session, url: str) -> list[dict[str, str]]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    rows = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    # NSE's headers carry stray spaces and mixed case; key on a normalized form.
    return [
        {(k or "").strip().upper().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
        for row in rows
    ]


def _date(value: str) -> str:
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(value.title(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def fetch_symbols(session: requests.Session) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for row in _csv(session, EQUITY_URL):
        found[row["SYMBOL"]] = {
            "symbol": row["SYMBOL"], "name": row["NAME_OF_COMPANY"], "series": row["SERIES"],
            "segment": "EQUITY", "isin": row["ISIN_NUMBER"], "listing_date": _date(row["DATE_OF_LISTING"]),
        }
    for row in _csv(session, SME_URL):
        found.setdefault(row["SYMBOL"], {
            "symbol": row["SYMBOL"], "name": row["NAME_OF_COMPANY"], "series": row["SERIES"],
            "segment": "SME", "isin": row["ISIN_NUMBER"], "listing_date": _date(row["DATE_OF_LISTING"]),
        })
    for row in _csv(session, ETF_URL):
        found.setdefault(row["SYMBOL"], {
            "symbol": row["SYMBOL"], "name": row.get("UNDERLYING_ASSET") or row.get("SECURITYNAME", ""),
            "series": "EQ", "segment": "ETF", "isin": row.get("ISINNUMBER", ""),
            "listing_date": _date(row.get("DATEOFLISTING", "")),
        })
    return sorted((r for r in found.values() if r["symbol"]), key=lambda r: r["symbol"])


def fetch_caps(session: requests.Session) -> list[dict[str, str]]:
    rows = []
    for cap, url in CAP_LISTS.items():
        for row in _csv(session, url):
            rows.append({"symbol": row["SYMBOL"], "cap": cap, "industry": row.get("INDUSTRY", "")})
    return rows


def fetch_holidays(session: requests.Session) -> dict[str, str]:
    # The API refuses requests without the cookies its home page sets.
    session.get("https://www.nseindia.com/", timeout=30)
    response = session.get(HOLIDAY_URL, headers={"Referer": "https://www.nseindia.com/"}, timeout=30)
    response.raise_for_status()
    return {
        _date(h["tradingDate"]): h["description"].strip()
        for h in response.json().get("CM", [])
        if _date(h["tradingDate"])
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    symbols = fetch_symbols(session)
    with open(OUT / "nse_symbols.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(symbols)
    print(f"nse_symbols.csv: {len(symbols)} securities")

    caps = fetch_caps(session)
    with open(OUT / "nse_marketcap.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "cap", "industry"])
        writer.writeheader()
        writer.writerows(caps)
    print(f"nse_marketcap.csv: {len(caps)} classified")

    holiday_file = OUT / "nse_holidays.json"
    known = json.loads(holiday_file.read_text(encoding="utf-8")) if holiday_file.exists() else {}
    try:
        known.update(fetch_holidays(session))
    except (requests.RequestException, ValueError) as exc:
        print(f"holidays not refreshed ({exc}); keeping {len(known)} known dates", file=sys.stderr)
    holiday_file.write_text(json.dumps(dict(sorted(known.items())), indent=2) + "\n", encoding="utf-8")
    print(f"nse_holidays.json: {len(known)} holidays")
    return 0


if __name__ == "__main__":
    sys.exit(main())
