"""`tradingagents setups`: the short list, in two tables.

1. SWING (short term, days to weeks): the top 5 setups from six strategies (52-week
   breakout, Minervini VCP, Qullamaggie flag and episodic pivot, Kell EMA crossback,
   breakout + retest),
   stop 5-10%, target 10-20%, each with a plain GOOD / OK / AVOID verdict.
2. VALUE (medium to long term, 3-12 months): the top 3 quality-growth stocks at a fair
   price in a stage-2 uptrend, with concall headlines.

Micro caps trading Rs 25 crore+ a day are included (`--no-micro` leaves them out); they
are never GOOD and their verdict starts with a MICRO CAP caution.
The 3-5 year MULTIBAGGER CANDIDATES list has its own command (`tradingagents multibagger`,
/multibagger); here value picks already on that saved list are only tagged.
`--with-core` adds the momentum core portfolio. Every call is logged for
`tradingagents calls review`.
"""

from __future__ import annotations

import json
import os

from rich.markdown import Markdown

from cli.display import console
from cli.scan import scans_dir
from tradingagents.journal import Journal

# Sizing is not shown; run_daily still needs a nominal account for its internal fields.
_NOMINAL_CAPITAL = 100_000.0


def _held_momentum() -> dict[str, float]:
    j = Journal.load()
    return {t.symbol: t.entry_price for t in j.open_trades() if t.strategy == "momentum"}


def build(top: int = 5, value_top: int = 3, refresh: bool = False, no_news: bool = False,
          with_core: bool = False, mode: str = "balanced", progress=None, micro: bool = True,
          multibagger: bool = False) -> dict:
    from tradingagents import calls
    from tradingagents.scanner import data as data_mod
    from tradingagents.scanner.daily import run_daily
    from tradingagents.scanner.value import value_picks

    md = data_mod.load(refresh=refresh, progress=progress, with_micro=micro)
    swing = run_daily(capital=_NOMINAL_CAPITAL, risk_pct=1.0, top=top, with_news=not no_news, md=md)
    value = value_picks(md, top=value_top, with_news=not no_news) if value_top else {"picks": []}
    from tradingagents.scanner import multibagger as MB

    mb = MB.update(md) if multibagger else {"rows": []}
    # Tag value picks from the saved list (no fetching) when the list is not refreshed here.
    tagged = {r["symbol"] for r in mb["rows"]} if multibagger else MB.active_symbols()
    for v in value["picks"]:
        v["verdict"] = value_verdict(v)
        v["multibagger_candidate"] = v["symbol"] in tagged
        if v["multibagger_candidate"]:
            v["verdict"] += " [MULTIBAGGER CANDIDATE, 3-5 years]"
    core = {"picks": []}
    if with_core:
        from tradingagents.scanner.momentum import core_picks

        core = core_picks(md, _NOMINAL_CAPITAL, _held_momentum(), mode=mode)
    r = {"as_of": str(md.last), "settled": str(md.settled), "swing": swing, "value": value, "core": core,
         "mode": mode, "multibagger": mb, "sources": getattr(md, "sources", {})}
    r["new_calls_logged"] = calls.record(r)
    return r


def value_verdict(v: dict) -> str:
    concerns = []
    if v.get("cap") == "Micro":
        concerns.append("MICRO CAP caution: thin float, operator risk, weaker free data; half size")
    if v.get("cap") == "Small":
        concerns.append("small cap: bigger swings")
    if (v.get("earnings_growth_pct") or 0) > 100:
        concerns.append("profit doubled: check it repeats next quarter")
    if v.get("analyst_target") and v["analyst_target"] < v["entry"]:
        concerns.append(f"analysts' mean target {v['analyst_target']:,} is below the price")
    if not concerns:
        return "GOOD: quality growth at or below its sector P/E, in an uptrend"
    return "OK: " + "; ".join(concerns)


def _exit_text(i: dict) -> str:
    return "sell half at target, stop to cost; rest on a close below the 20-day EMA"


def _hold(i: dict, records: dict) -> str:
    rec = records.get(i["strategy"], {}).get("all", {})
    typ, hit = rec.get("median_days"), rec.get("median_days_to_target")
    if not typ:
        return "no time limit"
    text = f"~{typ:.0f} sessions"
    if hit and hit == hit:
        text += f" (target ~{hit:.0f})"
    return text + ", no limit"


def _money(i: dict) -> str:
    mf = i.get("money_flow", "")
    if mf == "in":
        return f"IN ({i['dp_trend']:.2f}x)"
    if mf == "flat":
        return f"flat ({i['dp_trend']:.2f}x)"
    return {"exempt": "n/a (news)", "unknown": "no data"}.get(mf, "-")


def _record(i: dict, records: dict, micro_records: dict | None = None) -> str:
    if i.get("cap") == "Micro" and micro_records:
        records = micro_records
    rec = records.get(i["strategy"], {}).get("12m", {})
    if not rec.get("trades"):
        return "-"
    return f"{rec['win_rate']:.0f}% won, {rec['expectancy_r']:+.2f}R"


def _sources_line(src: dict) -> str:
    if not src:
        return ""
    parts = [f"Upstox {src.get('upstox', 0)}", f"Yahoo {src.get('yahoo', 0)}"]
    if src.get("nse_patched"):
        parts.append(f"{src['nse_patched']} filled from NSE bhavcopy")
    parts.append(f"{src.get('nse_corrected', 0)} latest closes corrected to NSE's")
    return "Prices: " + ", ".join(parts) + ". Fundamentals: NSE XBRL filings + Yahoo."


def render_multibagger(mb: dict) -> list[str]:
    """The MULTIBAGGER CANDIDATES table (from multibagger.update)."""
    out: list[str] = []
    out += ["", f"## MULTIBAGGER CANDIDATES - long term watch list (3-5 years; {len(mb['rows'])} on the list)", "",
            f"Screened {mb['screened']} stocks, {mb['checked']} checked in depth, {mb['passed']} pass every test today. "
            f"New: {', '.join(x.removesuffix('.NS') for x in mb['added']) or 'none'}. "
            f"Removed: {', '.join(x.removesuffix('.NS') for x in mb['removed']) or 'none'}.", ""]
    if mb["rows"]:
        out += ["| Status | Name | Ticker | Cap | Mcap (Rs cr) | Added on | Added at | Now | Since added | ROE | "
                "Sales 3y / 5y CAGR | Profit 3y CAGR | Debt/equity | Promoter (pledged) | P/E (PEG) | History | Note |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for m in mb["rows"]:
            pe = f"{m['pe']} ({m['peg']})" if m.get("pe") else "-"
            out.append(
                f"| **{m['status']}** | {m['name']} | {m['symbol'].removesuffix('.NS')} | {m['cap']} | "
                f"{m['mcap_cr'] or 0:,.0f} | {m['added_on']} | {m['added_price']:,.2f} | {m['close']:,.2f} | "
                f"{m['since_added_pct']:+.1f}% | {m['roe_pct']}% | {m['sales_cagr_pct']}% / "
                f"{m.get('sales_5y_cagr_pct') if m.get('sales_5y_cagr_pct') is not None else '-'}% | "
                f"{m['profit_cagr_pct']}% | {m['de_pct']}% | "
                f"{m['promoter_pct'] if m['promoter_pct'] is not None else '-'}% "
                f"({m.get('pledged_pct') if m.get('pledged_pct') is not None else '-'}%) | {pe} | "
                f"{m.get('history') or '-'} | {m['note'] or m['chart']} |")
        out += ["", f"Plan: {mb['plan']}. {mb['note']}"]
    else:
        out.append("No stock passes every multibagger test yet; the list fills as stocks qualify.")
    for x in mb.get("removed_recent", [])[-3:]:
        out.append(f"\nRemoved {x['symbol'].removesuffix('.NS')} on {x['removed_on']} at {x['removed_price']:,.2f} "
                   f"(added {x['added_on']} at {x['added_price']:,.2f}): {x['reason']}.")
    return out


SHORT_SETUP = {"breakout": "52w breakout", "vcp": "VCP", "flag": "Q-flag", "ep": "Episodic pivot",
               "crossback": "EMA crossback", "retest": "BO+retest", "ct": "CT+retest"}


def _short_name(name: str) -> str:
    for w in (" Limited", " Ltd.", " Ltd", " Industries", " International", " Technologies", " Enterprises"):
        name = name.replace(w, "")
    return name.strip()


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip(" ;,") + "…"


def _first_reason(text: str) -> str:
    """The text up to the first "; " that is not inside brackets."""
    depth = 0
    for k, ch in enumerate(text):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0 and text.startswith("; ", k):
            return text[:k]
    return text


_GENERIC_BEAR = ("Micro cap", "Small cap")


def _brief_verdict(i: dict) -> str:
    """The verdict word plus its first reason, short (the full text stays in the saved .md)."""
    tier = i.get("tier") or i["grade"]
    head, _, rest = i["verdict"].partition(": ")
    micro = " MICRO" if i.get("cap") == "Micro" else ""
    reason = _first_reason(rest.split("; MICRO CAP caution")[0]) if rest else ""
    return f"**{tier}{micro}**" + (f": {_clip(reason, 70)}" if reason else "")


def render_brief(r: dict) -> str:
    """The compact list for chat: short tables, the exit rule once, Bull/Bear inline.
    About a third of the full Markdown; the full version is still saved to disk."""
    swing, value = r["swing"], r.get("value", {"picks": []})
    m = swing["market"]
    trend = "above" if m["nifty"] > m["nifty_sma200"] else "below"
    src = r.get("sources") or {}
    out = [f"# Setups {r['as_of']} | Nifty {m['nifty']:,.0f} ({trend} 200-DMA) | breadth {m['breadth_pct']:.0f}% | "
           f"scanned {swing.get('scanned', 0)} + {swing.get('micro_scanned', 0)} micro"]
    if src:
        out.append(f"Prices: Upstox {src.get('upstox', 0)}, Yahoo {src.get('yahoo', 0)}, "
                   f"NSE-corrected {src.get('nse_corrected', 0)}")
    out += [f"> {n}" for n in swing["notes"]]
    out += ["", "## SWING (buy-stop above; GTT OCO: stop + target for half; rest sells on a close below the 20-EMA)", "",
            "| # | Stock | Cap | Setup | Money | Setup 12m | Verdict | Buy above (max) | Stop | Target | Hold |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    recs, mrecs = swing["records"], swing.get("micro_records") or {}
    for i in swing["ideas"]:
        hold = _hold(i, recs).split(" (")[0].replace(" sessions", "d").replace(", no limit", "")
        out.append(
            f"| {i['rank']} | {_short_name(i['name'])} ({i['symbol'].removesuffix('.NS')}) | {i['cap']} | "
            f"{SHORT_SETUP.get(i['strategy'], i['strategy'])} | {_money(i)} | {_record(i, recs, mrecs)} | "
            f"{_brief_verdict(i)} | {i['entry']:,.2f} ({i['max_entry']:,.2f}) | {i['stop']:,.2f} -{i['risk_pct']:.1f}% | "
            f"{i['target']:,.2f} +{i['reward_pct']:.1f}% | {hold} |")
    if not swing["ideas"]:
        out.append("| - | No setup inside the 5-10% stop / 10-20% target bands today | | | | | | | | | |")
    top = [i for i in swing["ideas"] if i["grade"] != "AVOID"][:3]
    if top:
        out += ["", "Bull / Bear:"]
        for i in top:
            bull = _clip(i["bull"][0], 110) if i.get("bull") else "-"
            bears = [b for b in i.get("bear") or [] if not b.startswith(_GENERIC_BEAR)] or i.get("bear") or []
            bear = _clip(bears[0] if bears else "no bear point found", 110)
            extra = f" Results {i['earnings_date']}." if i.get("earnings_date") else ""
            out.append(f"- {i['symbol'].removesuffix('.NS')}: + {bull} / - {bear}{extra}")
    acc = (swing.get("money") or {}).get("accumulation") or []
    if acc:
        out += ["", "Money flow watch (not signals): " + ", ".join(
            f"{a['symbol'].removesuffix('.NS')} {a['dp_trend']:.2f}x" for a in acc)]
    if value["picks"]:
        out += ["", "## VALUE (3-12 months; limit buy at or below; review each quarterly result)", "",
                "| # | Stock | Cap | P/E (sector) | ROE | Sales / Profit gr. | Verdict | Buy at or below | Stop | Target |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for v in value["picks"]:
            word, _, why = v["verdict"].split(" [MULTIBAGGER")[0].partition(": ")
            concerns = [c for c in why.split("; ") if c and not c.startswith(("MICRO CAP", "thin float", "operator",
                                                                               "weaker free", "half size"))]
            word += " MICRO" if v.get("cap") == "Micro" else ""
            verdict = word + (f": {_clip(concerns[0], 45)}" if concerns and not word.startswith("GOOD") else "")
            tag = " [MB]" if v.get("multibagger_candidate") else ""
            out.append(
                f"| {v['rank']} | {_short_name(v['name'])} ({v['symbol'].removesuffix('.NS')}){tag} | {v['cap']} | "
                f"{v['pe']} ({v['sector_pe']}) | {v['roe_pct']}% | {v['revenue_growth_pct']}% / {v['earnings_growth_pct']}% | "
                f"**{verdict}** | {v['max_entry']:,.2f} | {v['stop']:,.2f} -{v['risk_pct']:.0f}% | "
                f"{v['target']:,.2f} +{v['reward_pct']:.0f}% |")
        v = value["picks"][0]
        if v.get("concall"):
            out.append(f"\n{v['symbol'].removesuffix('.NS')} news: " +
                       " | ".join(_clip(n["title"], 80) for n in v["concall"][:2]))
    out += ["", "BEST > BETTER > GOOD (full size) > OK (half) > AVOID. MICRO: half of that. [MB] = on the "
                "multibagger list. Not investment advice."]
    return "\n".join(out)


def render_markdown(r: dict) -> str:
    swing, value = r["swing"], r.get("value", {"picks": []})
    m = swing["market"]
    trend = "above" if m["nifty"] > m["nifty_sma200"] else "below"
    out = [
        f"# Trade setups - {r['as_of']} close",
        "",
        f"Nifty 50 {m['nifty']:,} ({trend} its 200-DMA {m['nifty_sma200']:,}; 50-DMA {m['nifty_sma50']:,}) | "
        f"{m['breadth_pct']:.0f}% of stocks above their 200-DMA | scanned {swing.get('scanned', 0)} large/mid/small "
        f"+ {swing.get('micro_scanned', 0)} liquid micro caps",
        _sources_line(r.get("sources") or {}),
        *[f"> {n}" for n in swing["notes"]],
        "",
        f"## SWING - top {len(swing['ideas'])} (short term: days to weeks; stop 5-10%, target 10-20%, "
        "no time limit)",
        "",
        "| # | Name | Ticker | Cap | Setup | Money flow | Setup's last 12m | Verdict | Buy above (max) | Stoploss | "
        "Target (sell half) | Exit | Hold |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i in swing["ideas"]:
        out.append(
            f"| {i['rank']} | {i['name']} | {i['symbol'].removesuffix('.NS')} | {i['cap']} | {i['strategy_label']} | "
            f"{_money(i)} | {_record(i, swing['records'], swing.get('micro_records'))} | **{i['verdict']}** | {i['entry']:,.2f} ({i['max_entry']:,.2f}) | {i['stop']:,.2f} (-{i['risk_pct']:.1f}%) | "
            f"{i['target']:,.2f} (+{i['reward_pct']:.1f}%) | {_exit_text(i)} | {_hold(i, swing['records'])} |"
        )
    if not swing["ideas"]:
        out.append("| - | No setup inside the 5-10% stop / 10-20% target bands today | | | | | | | | | | | |")
    money = swing.get("money", {})
    if money.get("accumulation") or money.get("deals"):
        out += ["", "## MONEY FLOW - where funds are buying (watch list, not a buy signal)", ""]
    if money.get("accumulation"):
        out += ["Stage-2 leaders with delivery % rising most (20-day average vs 100-day): buy only when one of "
                "them shows a setup above.", "",
                "| Name | Ticker | Cap | Close | Delivery trend | Last delivery % | RS rank | From 52w high |",
                "|---|---|---|---|---|---|---|---|"]
        for a in money["accumulation"]:
            out.append(f"| {a['name']} | {a['symbol'].removesuffix('.NS')} | {a['cap']} | {a['close']:,.2f} | "
                       f"{a['dp_trend']:.2f}x | {a['deliv_pct'] or '-'}% | {a['rs_rank'] or '-'} | "
                       f"{a['from_high_pct']:+.1f}% |")
    if money.get("accumulation") and not money.get("deals"):
        out += ["", "No bulk/block deal by an institution in a large/mid/small cap today."]
    if money.get("deals"):
        out += ["", "Today's bulk/block deals by institutions (large/mid/small caps):", "",
                "| Ticker | Deal | Side | Client | Qty | Price |", "|---|---|---|---|---|---|"]
        for d in money["deals"]:
            out.append(f"| {d['symbol']} | {d['kind']} | {d['side']} | {d['client']} | {d['qty']:,.0f} | "
                       f"{d['price']:,.2f} |")
    out += ["", f"## VALUE - top {len(value['picks'])} (medium to long term: 3-12 months)", ""]
    if value["picks"]:
        out += ["| # | Name | Ticker | Cap | Sector | P/E (sector) | ROE | Sales gr. | Profit gr. | Chart | Verdict | "
                "Buy at or below | Stoploss | Target | Hold |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for v in value["picks"]:
            out.append(
                f"| {v['rank']} | {v['name']} | {v['symbol'].removesuffix('.NS')} | {v['cap']} | {v['sector']} | "
                f"{v['pe']} ({v['sector_pe']}) | {v['roe_pct']}% | {v['revenue_growth_pct']}% | "
                f"{v['earnings_growth_pct']}% | {v['pattern']} | **{v['verdict']}** | {v['max_entry']:,.2f} | "
                f"{v['stop']:,.2f} (-{v['risk_pct']:.1f}%) | {v['target']:,.2f} (+{v['reward_pct']:.1f}%) | {v['hold']} |"
            )
        for v in value["picks"]:
            if v["concall"]:
                out.append(f"\n**{v['symbol'].removesuffix('.NS')} headlines:** " +
                           " | ".join(f"{n['when']}: {n['title']}" for n in v["concall"][:3]))
    else:
        out.append(value.get("note", "No value pick today."))
    if (r.get("multibagger") or {}).get("screened") is not None:
        out += render_multibagger(r["multibagger"])
    if r.get("core", {}).get("picks"):
        out += ["", "## CORE - momentum portfolio (monthly review)", "",
                "| # | Name | Ticker | Cap | Action | Stoploss | Review |", "|---|---|---|---|---|---|---|"]
        for p in r["core"]["picks"]:
            out.append(f"| {p['rank']} | {p['name']} | {p['symbol'].removesuffix('.NS')} | {p['cap']} | "
                       f"{p['action']} | {p['stop']:,.2f} (-15%) | {p['review_on']} |")
    out += [
        "",
        "Verdicts, best first: **BEST** GOOD plus all three extra checks (success rate 40%+, volume building up, "
        "RS leader); **BETTER** two of them; **GOOD** take it; **OK** one risk to respect, half size; **AVOID** the "
        "setup is losing money lately or the news is bad. **MICRO CAP** rows use the same scale on the setup's "
        "micro-cap record, at half the size you would use on a bigger stock. Money flow: delivery % trend (20-day vs 100-day average); IN is "
        "1.05x or more, money OUT setups are dropped. Swing entry: a stop-limit buy (trigger = buy above, "
        "limit = max) before 09:15; after the fill, a GTT OCO with the stoploss and the target for HALF the "
        "shares. When the target fills, move the stop on the rest to your buy price and sell it on a close below "
        "the 20-day EMA. No time limit. Not investment advice.",
    ]
    return "\n".join(out)


def setups_command(top: int, value_top: int, refresh: bool, as_json: bool, markdown: bool, no_news: bool,
                   with_core: bool = False, mode: str = "balanced", micro: bool = True,
                   multibagger: bool = False, brief: bool = False) -> int:
    def progress(done, total):
        if not (as_json or markdown):
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    r = build(top, value_top, refresh, no_news, with_core, mode, progress, micro, multibagger)
    stem = os.path.join(scans_dir(), f"setups-{r['as_of']}")
    md_text = render_markdown(r)
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1, default=float)
    with open(stem + ".md", "w", encoding="utf-8") as fh:
        fh.write(md_text)
    if as_json:
        print(json.dumps(r, indent=1, default=float))
    elif brief:
        print(render_brief(r))
    elif markdown:
        print(md_text)
    else:
        console.print(Markdown(md_text))
        console.print(f"[dim]Saved: {stem}.md[/dim]")
    return 0


def latest() -> dict:
    import glob

    files = sorted(glob.glob(os.path.join(scans_dir(), "setups-*.json")))
    if not files:
        raise ValueError("no saved setups yet: run /trade-setups (tradingagents setups) first")
    with open(files[-1], encoding="utf-8") as fh:
        return json.load(fh)


def allocate(amount: float, kind: str, picks: list[int] | None, risk: float) -> dict:
    """Size the latest list for ``amount`` of money: swing by risk, core and value equally."""
    import math

    r = latest()
    rows = []
    if kind == "swing":
        ideas = [i for i in r["swing"]["ideas"] if not picks or i["rank"] in picks]
        ideas = [i for i in ideas if i.get("grade") != "AVOID"]
        for i in ideas:
            per = i["entry"] - i["stop"]
            factor = 1.0 if i["grade"] == "GOOD" else 0.5
            qty = min(math.floor(amount * risk / 100 * factor / per), math.floor(amount * 0.25 / i["entry"]))
            rows.append({"rank": i["rank"], "symbol": i["symbol"], "grade": i["grade"], "entry": i["entry"],
                         "stop": i["stop"], "target": i["target"], "qty": qty, "capital": round(qty * i["entry"]),
                         "max_loss": round(qty * per), "exit_by": i["exit_by"]})
    elif kind == "core":
        items = [p for p in r.get("core", {}).get("picks", []) if not picks or p["rank"] in picks]
        if not items:
            raise ValueError("the latest list has no core picks: run `tradingagents setups --with-core`")
        frac = r["core"].get("invested_pct", 100) / 100 or 0.5
        for p in items:
            px = p["max_entry"] if p["action"].startswith("BUY") else p["close"]
            qty = math.floor(amount / max(len(items), 1) * frac / px)
            rows.append({"rank": p["rank"], "symbol": p["symbol"], "grade": "core", "entry": px, "stop": round(px * 0.85, 2),
                         "target": None, "qty": qty, "capital": round(qty * px), "max_loss": round(qty * px * 0.15),
                         "exit_by": f"review {p['review_on']}"})
    elif kind == "value":
        items = [v for v in r["value"]["picks"] if not picks or v["rank"] in picks]
        for v in items:
            qty = math.floor(amount / max(len(items), 1) / v["max_entry"])
            rows.append({"rank": v["rank"], "symbol": v["symbol"], "grade": "value", "entry": v["max_entry"],
                         "stop": v["stop"], "target": v["target"], "qty": qty, "capital": round(qty * v["max_entry"]),
                         "max_loss": round(qty * (v["max_entry"] - v["stop"])), "exit_by": v["hold"]})
    else:
        raise ValueError("--for must be swing, core or value")
    used = sum(x["capital"] for x in rows)
    return {"as_of": r["as_of"], "amount": amount, "for": kind, "rows": rows, "capital_used": used,
            "cash_left": round(amount - used), "max_total_loss": sum(x["max_loss"] for x in rows)}


def multibagger_command(as_json: bool = False, markdown: bool = False, refresh: bool = False,
                        micro: bool = True) -> int:
    """`tradingagents multibagger`: update the 3-5 year candidate list and show it."""
    from tradingagents.scanner import data as data_mod
    from tradingagents.scanner.multibagger import update

    def progress(done, total):
        if not (as_json or markdown):
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    md = data_mod.load(refresh=refresh, progress=progress, with_micro=micro)
    mb = update(md)
    text = "\n".join([f"# Multibagger candidates - {mb['as_of']} close", _sources_line(getattr(md, "sources", {})),
                      *render_multibagger(mb)])
    stem = os.path.join(scans_dir(), f"multibagger-{mb['as_of']}")
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(mb, fh, indent=1, default=float)
    with open(stem + ".md", "w", encoding="utf-8") as fh:
        fh.write(text)
    if as_json:
        print(json.dumps(mb, indent=1, default=float))
    elif markdown:
        print(text)
    else:
        console.print(Markdown(text))
        console.print(f"[dim]Saved: {stem}.md[/dim]")
    return 0
