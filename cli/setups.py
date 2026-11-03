"""`tradingagents setups`: the survival plan's lists as tables.

1. CORE: the momentum portfolio, BUY / HOLD / SELL against your journal's open
   momentum trades (mode safe / balanced / aggressive when the market is weak).
2. SWING: the top 10 swing setups (stocks and ETFs), stop 5-10%, target 10-20%.
3. VALUE: the best quality-growth-at-a-fair-price buys in a sound chart, with
   concall headlines (not backtested).

Every call is checked by the auditor and logged for `tradingagents calls review`.
"""

from __future__ import annotations

import json
import os

from rich.markdown import Markdown

from cli.breakout import _inr
from cli.display import console
from cli.scan import scans_dir
from tradingagents.journal import Journal

MODE_TEXT = {
    "safe": "safe: nothing bought while the Nifty is below its 200-DMA",
    "balanced": "balanced: half size while the Nifty is below its 200-DMA",
    "aggressive": "aggressive: full size always",
}


def _held_momentum() -> dict[str, float]:
    j = Journal.load()
    return {t.symbol: t.entry_price for t in j.open_trades() if t.strategy == "momentum"}


def build(capital: float, core_pct: float, risk: float, top: int, refresh: bool, no_news: bool,
          mode: str = "balanced", value_top: int = 5, progress=None) -> dict:
    from tradingagents import calls
    from tradingagents.scanner import data as data_mod
    from tradingagents.scanner.audit import audit_core, audit_value
    from tradingagents.scanner.daily import run_daily
    from tradingagents.scanner.momentum import core_picks
    from tradingagents.scanner.value import value_picks

    md = data_mod.load(refresh=refresh, progress=progress)
    core_cap = capital * core_pct / 100
    swing_cap = capital - core_cap
    core = core_picks(md, core_cap, _held_momentum(), mode=mode)
    for p in core["picks"]:
        p["audit"] = audit_core(p, core["regime_on"], mode)
    swing = run_daily(capital=swing_cap, risk_pct=risk, top=top, with_news=not no_news, md=md)
    value = value_picks(md, top=value_top, with_news=not no_news) if value_top else {"picks": []}
    for v in value["picks"]:
        v["audit"] = audit_value(v)
    r = {"as_of": str(md.last), "settled": str(md.settled), "capital": capital, "core_pct": core_pct,
         "core_capital": core_cap, "swing_capital": swing_cap, "mode": mode,
         "core": core, "swing": swing, "value": value}
    r["new_calls_logged"] = calls.record(r)
    return r


def _audit_cell(a: dict) -> str:
    if not a:
        return "-"
    detail = "; ".join(a.get("wrong", []) + a.get("doubts", []))
    return a["status"] + (f": {detail}" if detail else "")


def render_markdown(r: dict) -> str:
    core, swing, value = r["core"], r["swing"], r.get("value", {"picks": []})
    m = swing["market"]
    mode = core.get("mode", r.get("mode", "balanced"))
    mrec = core["modes"][mode]
    out = [
        f"# Trade setups - {r['as_of']} close",
        "",
        f"Nifty 50 {m['nifty']:,} | 50-DMA {m['nifty_sma50']:,} | 200-DMA {m['nifty_sma200']:,} | "
        f"breadth {m['breadth_pct']:.0f}% | capital {_inr(r['capital'])}: core {_inr(r['core_capital'])} "
        f"({r['core_pct']:.0f}%), swing {_inr(r['swing_capital'])}",
        *[f"> {n}" for n in swing["notes"]],
        "",
        f"## 1. CORE - momentum portfolio ({r['core_pct']:.0f}% of capital, mode {MODE_TEXT[mode]})",
        "",
        f"Tested 2017-2026 in {mode} mode: **+{mrec['cagr_pct']}% a year, worst drop -{mrec['max_drawdown_pct']}%** "
        f"(Nifty: +{core['record']['nifty_cagr_pct']}%, -{core['record']['nifty_max_drawdown_pct']}%). "
        f"Regime: **{'ON' if core['regime_on'] else 'OFF'}** (Nifty {core['nifty']:,} vs 200-DMA "
        f"{core['nifty_sma200']:,}), {core['invested_pct']}% of the core invested. Next review: **{core['review_on']}**.",
        "",
        "| # | Name | Ticker | Cap | Sector | Action | Entry | Stoploss | Target | Exit | Hold | Qty | Auditor |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in core["picks"]:
        entry = (f"bought {p['entry']:,.2f}" if p["action"].startswith(("HOLD", "SELL"))
                 else f"next open <= {p['max_entry']:,.2f}" if p["action"].startswith("BUY")
                 else f"~{p['close']:,.2f}")
        out.append(
            f"| {p['rank']} | {p['name']} | {p['symbol'].removesuffix('.NS')} | {p['cap']} | {p['industry'] or '-'} | "
            f"**{p['action']}** | {entry} | {p['stop']:,.2f} (-15%) | none: ride the trend | review "
            f"{p['review_on']}; sell if rank > 40 | 1-4 months | {p['quantity']} | {_audit_cell(p.get('audit', {}))} |"
        )
    if core["sells"]:
        out += ["", "**SELL** (from your journal):"]
        out += [f"- {s['symbol'].removesuffix('.NS')}: {s['reason']}" for s in core["sells"]]
    out += [
        "",
        f"## 2. SWING - top {len(swing['ideas'])} setups ({100 - r['core_pct']:.0f}% of capital; stop 5-10%, target 10-20%)",
        "",
        "| # | Name | Ticker | Cap | Setup | Grade (meaning) | Entry | Stoploss | Target | Exit by | Hold | R:R | Qty | Call | Auditor |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i in swing["ideas"]:
        entry = (f"buy-stop {i['entry']:,.2f} (max {i['max_entry']:,.2f})" if i["entry_type"] == "stop"
                 else f"buy open ~{i['entry']:,.2f}")
        out.append(
            f"| {i['rank']} | {i['name']} | {i['symbol'].removesuffix('.NS')} | {i['cap']} | {i['strategy_label']} | "
            f"{i['grade_meaning']} | {entry} | {i['stop']:,.2f} (-{i['risk_pct']:.1f}%) | {i['target']:,.2f} "
            f"(+{i['reward_pct']:.1f}%) | {i['exit_by']} | {i['hold']} | {i['rr']:.1f} | {i['quantity']} | "
            f"{i['verdict']} | {_audit_cell(i.get('audit', {}))} |"
        )
    if not swing["ideas"]:
        out.append("| - | No setup inside the 5-10% stop / 10-20% target bands today | | | | | | | | | | | | | |")
    out += ["", "## 3. VALUE - best value buys (quality + growth at a fair price, sound chart; not backtested)", ""]
    if value["picks"]:
        out += ["| # | Name | Ticker | Cap | Sector | P/E (sector) | ROE | D/E | Sales gr. | Profit gr. | Chart | Entry | Stoploss | Target | Hold | Auditor |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for v in value["picks"]:
            out.append(
                f"| {v['rank']} | {v['name']} | {v['symbol'].removesuffix('.NS')} | {v['cap']} | {v['sector']} | "
                f"{v['pe']} ({v['sector_pe']}) | {v['roe_pct']}% | {v['debt_equity']}% | {v['revenue_growth_pct']}% | "
                f"{v['earnings_growth_pct']}% | {v['pattern']} | <= {v['max_entry']:,.2f} | {v['stop']:,.2f} "
                f"(-{v['risk_pct']:.1f}%) | {v['target']:,.2f} (+{v['reward_pct']:.1f}%) | {v['hold']} | "
                f"{_audit_cell(v.get('audit', {}))} |"
            )
        for v in value["picks"]:
            if v["concall"]:
                out.append(f"\n**{v['symbol'].removesuffix('.NS')} concall / management headlines:** " +
                           " | ".join(f"{n['when']}: {n['title']}" for n in v["concall"][:3]))
    else:
        out.append(value.get("note", "No value pick today."))
    out += [
        "",
        "Grades: **A** 52-week breakout, tested edge in rising and weak markets (full size); **B** strategy "
        "profitable across NSE over the last 6 and 12 months (full size); **C** strategy losing lately (half "
        "size or paper). Auditor: **CORRECT** no rule broken; **QUESTIONABLE** check the noted risk; "
        "**WRONG** breaks a rule: do not take it.",
        "",
        "To invest: tell me the amount and the list (e.g. \"Rs 1,00,000 for swing\"), or run "
        "`tradingagents allocate --amount 100000 --for swing`. Log fills with `/trade-journal`. "
        "Rules: docs/STRATEGY.md. Not investment advice.",
    ]
    return "\n".join(out)


def setups_command(capital: float, core_pct: float, risk: float, top: int, refresh: bool, as_json: bool,
                   markdown: bool, no_news: bool, mode: str = "balanced", value_top: int = 5) -> int:
    def progress(done, total):
        if not (as_json or markdown):
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    r = build(capital, core_pct, risk, top, refresh, no_news, mode, value_top, progress)
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
        ideas = [i for i in ideas if i.get("audit", {}).get("status") != "WRONG"]
        for i in ideas:
            per = i["entry"] - i["stop"]
            factor = 0.5 if i["grade"] == "C" else 1.0
            qty = min(math.floor(amount * risk / 100 * factor / per), math.floor(amount * 0.25 / i["entry"]))
            rows.append({"rank": i["rank"], "symbol": i["symbol"], "grade": i["grade"], "entry": i["entry"],
                         "stop": i["stop"], "target": i["target"], "qty": qty, "capital": round(qty * i["entry"]),
                         "max_loss": round(qty * per), "exit_by": i["exit_by"]})
    elif kind == "core":
        items = [p for p in r["core"]["picks"] if not picks or p["rank"] in picks]
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
