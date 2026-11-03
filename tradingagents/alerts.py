"""Email alerts (Gmail) for setups, entries and exits, before, during and after market hours.

Setup (once):

1. Turn on 2-step verification for the Gmail account, then create an app password
   at https://myaccount.google.com/apppasswords (16 letters).
2. Put these in the project's ``.env`` (never commit it):

       TA_GMAIL_USER=you@gmail.com
       TA_GMAIL_APP_PASSWORD=abcdefghijklmnop
       TA_ALERT_TO=you@gmail.com          # optional; defaults to TA_GMAIL_USER

3. ``tradingagents alerts test`` sends a test mail.

Commands:

- ``alerts digest``: runs the setups scan and mails the two tables (schedule it for
  18:30 IST, after NSE publishes the bhavcopy, and/or 08:30 IST before the open).
- ``alerts watch``: during market hours, checks live prices every few minutes and mails:
  a swing buy-stop that triggered (price between "buy above" and "max"), one that ran past
  its max (do not chase), a value pick inside its buy zone, a journal position at its stop
  or target, and (``--gaps``) any liquid stock gapping up 6%+ on heavy volume (a possible
  episodic pivot). ``--once`` checks once and exits, for Windows Task Scheduler.

Each alert is mailed once per day (state in ``~/.tradingagents/alerts-state.json``).
Live prices are Yahoo's, which can be a few minutes late. Not investment advice.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from datetime import datetime, time as dtime
from email.message import EmailMessage

from tradingagents.dataflows import india
from tradingagents.dataflows.vendors.yahoo.bulk import intraday_quotes

logger = logging.getLogger(__name__)

MARKET_OPEN, MARKET_CLOSE = dtime(9, 15), dtime(15, 30)


# ---------------------------------------------------------------- email

def _settings() -> tuple[str, str, str]:
    user = os.environ.get("TA_GMAIL_USER", "").strip()
    password = os.environ.get("TA_GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to = os.environ.get("TA_ALERT_TO", "").strip() or user
    if not user or not password:
        raise RuntimeError(
            "Gmail is not set up: add TA_GMAIL_USER and TA_GMAIL_APP_PASSWORD (a Google app password) "
            "to the project's .env file. See `tradingagents alerts --help`."
        )
    return user, password, to


def md_to_html(text: str) -> str:
    from markdown_it import MarkdownIt

    body = MarkdownIt("commonmark").enable("table").render(text)
    style = ("body{font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#111}"
             "table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #ccc;padding:4px 6px;"
             "font-size:12px;vertical-align:top}th{background:#f2f2f2}blockquote{color:#555;margin:4px 0}")
    return f"<html><head><style>{style}</style></head><body>{body}</body></html>"


def send_email(subject: str, markdown_text: str) -> None:
    user, password, to = _settings()
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(markdown_text)
    msg.add_alternative(md_to_html(markdown_text), subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


# ---------------------------------------------------------------- state

def _state_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".tradingagents", "alerts-state.json")


def _load_state(today: str) -> dict:
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    return st if st.get("day") == today else {"day": today, "sent": []}


def _save_state(st: dict) -> None:
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as fh:
        json.dump(st, fh)


# ---------------------------------------------------------------- checks

def check_alerts(setups: dict, quotes: dict[str, dict], positions: list[dict]) -> list[dict]:
    """Pure logic: the alerts that today's prices trigger. ``quotes``: {symbol: {price, high}}."""
    out = []
    for i in setups.get("swing", {}).get("ideas", []):
        q = quotes.get(i["symbol"])
        if not q or i.get("grade") == "AVOID":
            continue
        tkr = i["symbol"].removesuffix(".NS")
        if i["entry"] <= q["price"] <= i["max_entry"]:
            out.append({"key": f"trig:{tkr}", "title": f"BUY TRIGGERED {tkr} at {q['price']:,.2f}",
                        "body": f"{i['strategy_label']} ({i['grade']}). Buy above {i['entry']:,.2f}, max "
                                f"{i['max_entry']:,.2f}; stoploss {i['stop']:,.2f}, target {i['target']:,.2f}. "
                                f"{i['verdict']}"})
        elif q["price"] > i["max_entry"]:
            out.append({"key": f"chase:{tkr}", "title": f"{tkr} ran past its max {i['max_entry']:,.2f}: do not chase",
                        "body": f"Now {q['price']:,.2f}. The setup is void for today unless it comes back under the max."})
    for v in setups.get("value", {}).get("picks", []):
        q = quotes.get(v["symbol"])
        if q and q["price"] <= v["max_entry"]:
            tkr = v["symbol"].removesuffix(".NS")
            out.append({"key": f"value:{tkr}", "title": f"VALUE BUY ZONE {tkr} at {q['price']:,.2f}",
                        "body": f"At or below {v['max_entry']:,.2f}. Stoploss {v['stop']:,.2f}, target "
                                f"{v['target']:,.2f}, hold {v['hold']}. {v.get('verdict', '')}"})
    for p in positions:
        q = quotes.get(p["symbol"])
        if not q:
            continue
        tkr = p["symbol"].removesuffix(".NS")
        if p.get("stop") and q["price"] <= p["stop"]:
            out.append({"key": f"stop:{tkr}", "title": f"STOPLOSS HIT {tkr} at {q['price']:,.2f}",
                        "body": f"Your stop is {p['stop']:,.2f} (bought {p['entry_price']:,.2f}). Exit as planned."})
        elif p.get("target") and q["price"] >= p["target"]:
            out.append({"key": f"target:{tkr}", "title": f"TARGET HIT {tkr} at {q['price']:,.2f}",
                        "body": f"Your target is {p['target']:,.2f} (bought {p['entry_price']:,.2f})."})
    return out


def gap_alerts(quotes: dict[str, dict], prev: dict[str, dict], minutes_open: float) -> list[dict]:
    """Possible episodic pivots: up 6%+ with a gap of 3%+ and volume on pace for 3x normal."""
    out = []
    pace = max(minutes_open, 15) / 375.0
    for sym, q in quotes.items():
        p = prev.get(sym)
        if not p or not p.get("close") or not p.get("vol50") or q.get("open") is None:
            continue
        gap = q["open"] / p["close"] - 1
        move = q["price"] / p["close"] - 1
        if gap >= 0.03 and move >= 0.06 and q["volume"] >= 3 * p["vol50"] * pace and q["price"] >= 100:
            tkr = sym.removesuffix(".NS")
            out.append({"key": f"gap:{tkr}", "title": f"GAP-UP {tkr} {move * 100:+.1f}% on heavy volume",
                        "body": f"Opened {gap * 100:+.1f}%, now {q['price']:,.2f}; volume on pace for "
                                f"{q['volume'] / (p['vol50'] * pace):.1f}x normal. A possible episodic pivot: "
                                "check the news; the plan is a buy above today's high after the close confirms."})
    return out


def _positions() -> list[dict]:
    from tradingagents.journal import Journal

    j = Journal.load()
    return [{"symbol": t.symbol if t.symbol.endswith(".NS") else t.symbol + ".NS", "stop": t.stop,
             "target": t.target, "entry_price": t.entry_price} for t in j.open_trades()]


def _prev_day_stats(symbols: list[str]) -> dict[str, dict]:
    from tradingagents.scanner import data as data_mod

    md = data_mod.load()
    out = {}
    for s in symbols:
        d = md.stocks.get(s)
        if d is None or len(d) < 60:
            continue
        out[s] = {"close": float(d["Close"].iloc[-1]), "vol50": float(d["Volume"].iloc[-50:].mean())}
    return out


def market_open_now(now: datetime | None = None) -> bool:
    now = now or india.now_ist()
    return india.is_trading_day(now.date()) and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def watch(interval_min: int = 5, once: bool = False, gaps: bool = False, dry_run: bool = False,
          log=print) -> int:
    """Check prices during market hours and mail new alerts. Returns how many were sent."""
    from cli.setups import latest

    sent_total = 0
    prev = None
    while True:
        now = india.now_ist()
        if not market_open_now(now):
            log(f"{now:%H:%M} IST: market closed.")
            if once:
                return sent_total
            if now.time() > MARKET_CLOSE or not india.is_trading_day(now.date()):
                return sent_total
            time.sleep(60)
            continue
        setups = latest()
        positions = _positions()
        watch_syms = ([i["symbol"] for i in setups["swing"]["ideas"]]
                      + [v["symbol"] for v in setups["value"]["picks"]] + [p["symbol"] for p in positions])
        universe = []
        if gaps:
            from tradingagents.scanner.data import stock_universe

            universe = list(stock_universe())
            prev = prev or _prev_day_stats(universe)
        quotes = intraday_quotes(watch_syms + universe)
        alerts = check_alerts(setups, quotes, positions)
        if gaps:
            opened = datetime.combine(now.date(), MARKET_OPEN, tzinfo=now.tzinfo)
            alerts += gap_alerts({s: quotes[s] for s in universe if s in quotes}, prev,
                                 (now - opened).total_seconds() / 60)
        st = _load_state(str(now.date()))
        new = [a for a in alerts if a["key"] not in st["sent"]]
        if new:
            subject = new[0]["title"] if len(new) == 1 else f"{len(new)} trade alerts: " + ", ".join(
                a["title"].split(" at ")[0] for a in new[:3])
            body = f"Alerts at {now:%H:%M} IST (setups list of {setups['as_of']}):\n\n" + "\n\n".join(
                f"**{a['title']}**  \n{a['body']}" for a in new) + "\n\nNot investment advice."
            if dry_run:
                log(subject + "\n" + body)  # a dry run never marks alerts as sent
            else:
                send_email(subject, body)
                st["sent"] += [a["key"] for a in new]
                _save_state(st)
            sent_total += len(new)
        log(f"{now:%H:%M} IST: {len(quotes)} quotes, {len(new)} new alert(s).")
        if once:
            return sent_total
        time.sleep(interval_min * 60)


def swing_status(i: dict, price: float, high: float | None = None) -> str:
    """Where a swing setup stands at ``price`` (``high``: today's high so far)."""
    high = price if high is None else high
    if high < i["entry"]:
        return f"WAITING: {(i['entry'] / price - 1) * 100:.1f}% below the trigger"
    if price <= i["stop"]:
        return "STOPLOSS HIT"
    if price >= i["target"]:
        return "TARGET HIT"
    if price > i["max_entry"]:
        return "RAN PAST MAX: do not chase"
    if price >= i["entry"]:
        return "TRIGGERED: inside the buy zone"
    return "TRIGGERED, then faded below the trigger"


def value_status(v: dict, price: float) -> str:
    if price <= v["stop"]:
        return "BELOW STOPLOSS: skip"
    if price <= v["max_entry"]:
        return "IN BUY ZONE"
    return f"ABOVE BUY ZONE by {(price / v['max_entry'] - 1) * 100:.1f}%: wait"


def live_status(gaps: bool = False) -> str:
    """A Markdown snapshot of the latest list (and journal positions) at live prices."""
    from cli.setups import latest

    now = india.now_ist()
    setups = latest()
    positions = _positions()
    syms = ([i["symbol"] for i in setups["swing"]["ideas"]] + [v["symbol"] for v in setups["value"]["picks"]]
            + [p["symbol"] for p in positions] + ["^NSEI"])
    universe = []
    if gaps:
        from tradingagents.scanner.data import stock_universe

        universe = list(stock_universe())
    quotes = intraday_quotes(syms + universe)
    state = "market open" if market_open_now(now) else "market closed: last traded prices"
    out = [f"# Live status - {now:%d %b %H:%M} IST ({state})", ""]
    if "^NSEI" in quotes:
        q = quotes["^NSEI"]
        prev = setups["swing"]["market"]["nifty"]
        out += [f"Nifty 50 {q['price']:,.2f} ({(q['price'] / prev - 1) * 100:+.2f}% vs the list's close {prev:,.2f})", ""]
    out += [f"## Swing (list of {setups['as_of']})", "", "| # | Ticker | Verdict | Price | Buy above (max) | Stoploss | Target | Status |",
            "|---|---|---|---|---|---|---|---|"]
    for i in setups["swing"]["ideas"]:
        q = quotes.get(i["symbol"])
        status = swing_status(i, q["price"], q["high"]) if q else "no live price"
        out.append(f"| {i['rank']} | {i['symbol'].removesuffix('.NS')} | {i['grade']} | "
                   f"{q['price']:,.2f} | {i['entry']:,.2f} ({i['max_entry']:,.2f}) | {i['stop']:,.2f} | "
                   f"{i['target']:,.2f} | **{status}** |" if q else
                   f"| {i['rank']} | {i['symbol'].removesuffix('.NS')} | {i['grade']} | - | {i['entry']:,.2f} | "
                   f"{i['stop']:,.2f} | {i['target']:,.2f} | {status} |")
    out += ["", "## Value", "", "| # | Ticker | Price | Buy at or below | Stoploss | Status |", "|---|---|---|---|---|---|"]
    for v in setups["value"]["picks"]:
        q = quotes.get(v["symbol"])
        out.append(f"| {v['rank']} | {v['symbol'].removesuffix('.NS')} | {q['price']:,.2f} | {v['max_entry']:,.2f} | "
                   f"{v['stop']:,.2f} | **{value_status(v, q['price'])}** |" if q else
                   f"| {v['rank']} | {v['symbol'].removesuffix('.NS')} | - | {v['max_entry']:,.2f} | {v['stop']:,.2f} | no live price |")
    if positions:
        out += ["", "## Your open positions (journal)", "", "| Ticker | Bought | Price | P&L | Stoploss | Target | Status |",
                "|---|---|---|---|---|---|---|"]
        for p in positions:
            q = quotes.get(p["symbol"])
            if not q:
                continue
            st = ("STOPLOSS HIT" if p.get("stop") and q["price"] <= p["stop"] else
                  "TARGET HIT" if p.get("target") and q["price"] >= p["target"] else "holding")
            out.append(f"| {p['symbol'].removesuffix('.NS')} | {p['entry_price']:,.2f} | {q['price']:,.2f} | "
                       f"{(q['price'] / p['entry_price'] - 1) * 100:+.1f}% | {p.get('stop') or '-'} | "
                       f"{p.get('target') or '-'} | **{st}** |")
    if gaps:
        opened = datetime.combine(now.date(), MARKET_OPEN, tzinfo=now.tzinfo)
        minutes = max((min(now, datetime.combine(now.date(), MARKET_CLOSE, tzinfo=now.tzinfo)) - opened)
                      .total_seconds() / 60, 15)
        found = gap_alerts({s: quotes[s] for s in universe if s in quotes}, _prev_day_stats(universe), minutes)
        out += ["", "## Gap-ups now (possible episodic pivots)", ""]
        out += [f"- **{a['title']}**: {a['body']}" for a in found] or ["- none"]
    out += ["", "Prices from Yahoo, can be a few minutes late. Not investment advice."]
    return "\n".join(out)


def digest(dry_run: bool = False, refresh: bool = False) -> str:
    """Run the setups scan and mail the tables. Returns the Markdown."""
    from cli.setups import build, render_markdown

    r = build(refresh=refresh)
    text = render_markdown(r)
    good = sum(1 for i in r["swing"]["ideas"] if i["grade"] == "GOOD")
    subject = (f"Trade setups {r['as_of']}: {len(r['swing']['ideas'])} swing ({good} GOOD), "
               f"{len(r['value']['picks'])} value")
    if not dry_run:
        send_email(subject, text)
    return text
