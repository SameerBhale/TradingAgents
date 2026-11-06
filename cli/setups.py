"""`tradingagents setups`: the short list, in two tables.

1. SWING (short term, days to weeks): the top 5 setups from six strategies (52-week
   breakout, Minervini VCP, Qullamaggie flag and episodic pivot, Kell EMA crossback,
   breakout + retest),
   stop 5-10%, target 10-20%, each with a plain GOOD / OK / AVOID verdict.
2. VALUE (medium to long term, 3-12 months): the top 3 quality-growth stocks at a fair
   price in a stage-2 uptrend, with concall headlines.

Micro caps trading Rs 25 crore+ a day are included (`--no-micro` leaves them out); they
are never GOOD and their verdict starts with a MICRO CAP caution.
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
          with_core: bool = False, mode: str = "balanced", progress=None, micro: bool = True) -> dict:
    from tradingagents import calls
    from tradingagents.scanner import data as data_mod
    from tradingagents.scanner.daily import run_daily
    from tradingagents.scanner.value import value_picks

    md = data_mod.load(refresh=refresh, progress=progress, with_micro=micro)
    swing = run_daily(capital=_NOMINAL_CAPITAL, risk_pct=1.0, top=top, with_news=not no_news, md=md)
    value = value_picks(md, top=value_top, with_news=not no_news) if value_top else {"picks": []}
    for v in value["picks"]:
        v["verdict"] = value_verdict(v)
    core = {"picks": []}
    if with_core:
        from tradingagents.scanner.momentum import core_picks

        core = core_picks(md, _NOMINAL_CAPITAL, _held_momentum(), mode=mode)
    r = {"as_of": str(md.last), "settled": str(md.settled), "swing": swing, "value": value, "core": core,
         "mode": mode}
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
                   with_core: bool = False, mode: str = "balanced", micro: bool = True) -> int:
    def progress(done, total):
        if not (as_json or markdown):
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    r = build(top, value_top, refresh, no_news, with_core, mode, progress, micro)
    stem = os.path.join(scans_dir(), f"setups-{r['as_of']}")
    md_text = render_markdown(r)
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1, default=float)
    with open(stem + ".md", "w", encoding="utf-8") as fh:
        fh.write(md_text)
    if as_json:
        print(json.dumps(r, indent=1, default=float))
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
