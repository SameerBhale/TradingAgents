"""The Indian equity market: IST clock, NSE/BSE sessions, holidays and symbols.

NSE and BSE run the same capital-market timetable, in IST (UTC+05:30, no
daylight saving):

    09:00 - 09:08   pre-open order entry (call auction)
    09:08 - 09:15   pre-open matching / buffer
    09:15 - 15:30   normal market
    15:30 - 15:40   closing price calculation
    15:40 - 16:00   post-close session (trades at the closing price)

Trading days are Monday to Friday, less the exchange holidays bundled in
``data/india/nse_holidays.json`` (refresh with ``scripts/update_india_data.py``).

Symbols: Yahoo quotes NSE listings as ``<SYMBOL>.NS`` and BSE listings as
``<SYMBOL>.BO`` (by trading symbol: Yahoo serves no data under a numeric BSE
scrip code such as ``500325``). ``resolve_india_symbol`` turns what an Indian
trader types (``RELIANCE``, ``NSE:TCS``, ``BSE:RELIANCE``, ``NIFTY``) into those.
The bundled universe (``data/india/nse_symbols.csv``) lists every NSE mainboard
equity, SME Emerge equity and ETF.
"""

from __future__ import annotations

import csv
import functools
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), "IST")

PRE_OPEN_START = time(9, 0)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
POST_CLOSE_END = time(16, 0)
# Yahoo's daily candle for an NSE/BSE session carries the official closing
# price only once the exchange has computed it after the close.
CLOSE_SETTLED = time(16, 0)

_DATA = Path(__file__).resolve().parent / "data" / "india"

# Index and benchmark aliases as Indian traders and TradingView write them.
INDEX_ALIASES = {
    "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "NIFTY_50": "^NSEI", "NSEI": "^NSEI",
    "BANKNIFTY": "^NSEBANK", "NIFTYBANK": "^NSEBANK", "NIFTY_BANK": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS", "NIFTYFIN": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "NIFTYNEXT50": "^NSMIDCP", "NIFTYJR": "^NSMIDCP",
    "NIFTYIT": "^CNXIT", "CNXIT": "^CNXIT",
    "NIFTYPHARMA": "^CNXPHARMA", "NIFTYAUTO": "^CNXAUTO", "NIFTYFMCG": "^CNXFMCG",
    "NIFTYMETAL": "^CNXMETAL", "NIFTYREALTY": "^CNXREALTY", "NIFTYENERGY": "^CNXENERGY",
    "NIFTYPSUBANK": "^CNXPSUBANK", "NIFTYMEDIA": "^CNXMEDIA", "NIFTYINFRA": "^CNXINFRA",
    "NIFTY100": "^CNX100", "NIFTY200": "^CNX200", "NIFTY500": "^CRSLDX",
    "NIFTYMIDCAP50": "^NSEMDCP50", "NIFTYMIDCAP100": "NIFTY_MIDCAP_100.NS",
    "NIFTYMIDCAP": "NIFTY_MIDCAP_100.NS", "NIFTYSMALLCAP100": "^CNXSC",
    "INDIAVIX": "^INDIAVIX", "VIX_INDIA": "^INDIAVIX",
    "SENSEX": "^BSESN", "BSESN": "^BSESN", "BSE500": "BSE-500.BO",
}

_EXCHANGE_PREFIX = re.compile(r"^(NSE|BSE)\s*:\s*(.+)$")
_LONG_SUFFIX = re.compile(r"^(.+)\.(NSE|BSE)$")
# BSE scrip codes: six digits. Yahoo has no data under them (it quotes BSE by
# trading symbol), so they are refused with a pointer rather than guessed at.
_BSE_CODE = re.compile(r"^\d{6}(\.BO)?$")


# --------------------------------------------------------------------------
# Clock and sessions
# --------------------------------------------------------------------------


def now_ist() -> datetime:
    """The current time in IST."""
    return datetime.now(IST)


def today_ist() -> date:
    """Today's date in India, whatever the machine's own time zone."""
    return now_ist().date()


@functools.lru_cache(maxsize=1)
def holidays() -> dict[str, str]:
    """NSE capital-market trading holidays, ``YYYY-MM-DD`` -> occasion."""
    try:
        return json.loads((_DATA / "nse_holidays.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_trading_day(day: date) -> bool:
    """Whether NSE/BSE hold a normal session on ``day``."""
    return day.weekday() < 5 and day.isoformat() not in holidays()


def holiday_name(day: date) -> str | None:
    return holidays().get(day.isoformat())


def next_trading_day(day: date) -> date:
    """The first trading day after ``day``."""
    day += timedelta(days=1)
    while not is_trading_day(day):
        day += timedelta(days=1)
    return day


def previous_trading_day(day: date) -> date:
    """The last trading day before ``day``."""
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


@dataclass(frozen=True)
class MarketStatus:
    phase: str  # "pre-open", "open", "closing", "post-close", "closed"
    now: datetime
    is_trading_day: bool
    last_completed_session: date
    next_open: datetime
    note: str = ""

    @property
    def is_open(self) -> bool:
        return self.phase == "open"

    def describe(self) -> str:
        stamp = self.now.strftime("%a %d %b %Y, %H:%M IST")
        phases = {
            "pre-open": "pre-open session (09:00-09:15 IST)",
            "open": "market OPEN (09:15-15:30 IST)",
            "closing": "closing price calculation (15:30-15:40 IST)",
            "post-close": "post-close session (15:40-16:00 IST)",
            "closed": "market CLOSED",
        }
        text = f"NSE/BSE at {stamp}: {phases[self.phase]}"
        if self.note:
            text += f" - {self.note}"
        if self.phase != "open":
            text += f". Next open: {self.next_open.strftime('%a %d %b %Y, %H:%M IST')}"
        text += f". Last completed session: {self.last_completed_session.isoformat()}"
        return text


def _at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=IST)


def market_status(now: datetime | None = None) -> MarketStatus:
    """Where the NSE/BSE trading day stands at ``now`` (default: the present)."""
    now = (now or now_ist()).astimezone(IST)
    day, clock = now.date(), now.timetz().replace(tzinfo=None)
    trading = is_trading_day(day)
    note = ""
    if not trading:
        note = holiday_name(day) or "weekend"
        if holiday_name(day) and day.weekday() >= 5:
            note += " (weekend)"

    last_done = day if trading and clock >= CLOSE_SETTLED else previous_trading_day(day)

    if trading and clock < MARKET_OPEN:
        next_open = _at(day, MARKET_OPEN)
    else:
        next_open = _at(next_trading_day(day), MARKET_OPEN)

    if not trading:
        phase = "closed"
    elif PRE_OPEN_START <= clock < MARKET_OPEN:
        phase = "pre-open"
    elif MARKET_OPEN <= clock < MARKET_CLOSE:
        phase = "open"
    elif MARKET_CLOSE <= clock < time(15, 40):
        phase = "closing"
    elif time(15, 40) <= clock < POST_CLOSE_END:
        phase = "post-close"
    else:
        phase = "closed"
    return MarketStatus(phase, now, trading, last_done, next_open, note)


def session_settled(day: date, now: datetime | None = None) -> bool:
    """Whether ``day``'s daily candle is final: its session has closed and settled."""
    now = (now or now_ist()).astimezone(IST)
    return now >= _at(day, CLOSE_SETTLED)


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IndianSecurity:
    symbol: str
    name: str
    series: str
    segment: str  # EQUITY, SME or ETF
    isin: str
    listing_date: str

    @property
    def yahoo(self) -> str:
        return f"{self.symbol}.NS"


@functools.lru_cache(maxsize=1)
def nse_universe() -> dict[str, IndianSecurity]:
    """Every bundled NSE security, keyed by NSE symbol."""
    try:
        with open(_DATA / "nse_symbols.csv", encoding="utf-8", newline="") as fh:
            return {
                row["symbol"].upper(): IndianSecurity(**row)
                for row in csv.DictReader(fh)
                if row.get("symbol")
            }
    except OSError:
        return {}


@functools.lru_cache(maxsize=1)
def _caps() -> dict[str, tuple[str, str]]:
    try:
        with open(_DATA / "nse_marketcap.csv", encoding="utf-8", newline="") as fh:
            return {r["symbol"].upper(): (r["cap"], r["industry"]) for r in csv.DictReader(fh)}
    except OSError:
        return {}


def cap_class(symbol: str) -> str:
    """SEBI size band: Large (top 100), Mid (101-250), Small (251-500), Micro (below)."""
    s = symbol.strip().upper().removesuffix(".NS")
    return _caps().get(s, ("Micro", ""))[0]


def industry(symbol: str) -> str:
    s = symbol.strip().upper().removesuffix(".NS")
    return _caps().get(s, ("", ""))[1]


def lookup(symbol: str) -> IndianSecurity | None:
    """The NSE security a symbol (bare or ``.NS``) names, or None."""
    s = symbol.strip().upper()
    if s.endswith(".NS"):
        s = s[:-3]
    return nse_universe().get(s)


def search(query: str, limit: int = 25) -> list[IndianSecurity]:
    """NSE securities whose symbol or name contains ``query`` (symbol matches first)."""
    q = query.strip().upper()
    if not q:
        return []
    universe = nse_universe().values()
    exact = [s for s in universe if s.symbol == q]
    by_symbol = [s for s in universe if q in s.symbol and s.symbol != q]
    by_name = [s for s in universe if q in s.name.upper() and q not in s.symbol]
    by_symbol.sort(key=lambda s: (not s.symbol.startswith(q), len(s.symbol), s.symbol))
    return (exact + by_symbol + by_name)[:limit]


def resolve_india_symbol(raw: str, *, bare_to_nse: bool = True) -> str | None:
    """The Yahoo symbol for an Indian listing, or None when ``raw`` names none.

    - ``NIFTY``, ``BANKNIFTY``, ``SENSEX``... -> the Yahoo index symbol
    - ``NSE:TCS`` / ``TCS.NSE`` -> ``TCS.NS``; ``BSE:RELIANCE`` / ``RELIANCE.BSE`` -> ``RELIANCE.BO``
    - ``RELIANCE`` (a listed NSE symbol) -> ``RELIANCE.NS`` when ``bare_to_nse``
    """
    s = raw.strip().upper()
    if not s:
        return None
    if s in INDEX_ALIASES:
        return INDEX_ALIASES[s]
    if m := _EXCHANGE_PREFIX.match(s):
        exchange, code = m.group(1), m.group(2).strip()
        if code in INDEX_ALIASES:
            return INDEX_ALIASES[code]
        return f"{code}.NS" if exchange == "NSE" else f"{code}.BO"
    if m := _LONG_SUFFIX.match(s):
        return f"{m.group(1)}.NS" if m.group(2) == "NSE" else f"{m.group(1)}.BO"
    if not bare_to_nse:
        return None
    if s in nse_universe():
        return f"{s}.NS"
    return None


def bse_code_hint(raw: str) -> str | None:
    """A pointer for a numeric BSE scrip code, which Yahoo cannot price, else None."""
    s = raw.strip().upper()
    if s.startswith("BSE:"):
        s = s[4:].strip()
    if _BSE_CODE.match(s):
        return (
            f"{raw.strip()} looks like a BSE scrip code; Yahoo prices BSE listings by "
            "trading symbol. Use e.g. RELIANCE.BO (BSE) or RELIANCE / RELIANCE.NS (NSE)."
        )
    return None


def is_indian_symbol(symbol: str) -> bool:
    s = symbol.strip().upper()
    return s.endswith((".NS", ".BO")) or s in set(INDEX_ALIASES.values())


def exchange_note(symbol: str) -> str:
    """Market facts every agent should weigh for an Indian listing ('' otherwise)."""
    s = symbol.strip().upper()
    if not is_indian_symbol(s):
        return ""
    if s.endswith(".NS"):
        venue = "the National Stock Exchange of India (NSE)"
    elif s.endswith(".BO"):
        venue = "BSE (Bombay Stock Exchange)"
    else:
        venue = "an Indian exchange (NSE/BSE index)"
    sec = lookup(s) if s.endswith(".NS") else None
    segment = ""
    if sec and sec.segment == "SME":
        segment = (
            " It trades on the NSE Emerge SME platform: lot-based trading, thin "
            "liquidity and wide spreads are normal."
        )
    elif sec and sec.series in ("BE", "BZ"):
        segment = (
            f" It is in the {sec.series} series (trade-for-trade, compulsory delivery; "
            "no intraday netting)."
        )
    return (
        f" Market: it is listed on {venue}; prices are in Indian rupees (INR). "
        "Sessions run 09:15-15:30 IST, Monday to Friday, less exchange holidays, with a "
        "09:00-09:15 pre-open auction; daily bars close at 15:30 IST. Settlement is T+1. "
        "Weigh India-specific drivers: price bands / circuit limits, FII and DII flows, "
        "RBI policy, the rupee, SEBI regulation, promoter holding and pledges, and "
        "quarterly results filed with the exchanges." + segment
    )
