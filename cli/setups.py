"""`tradingagents setups`: the survival plan's two lists as tables.

1. CORE (default 80% of capital): the momentum portfolio, BUY / HOLD / SELL
   against your journal's open momentum trades.
2. SWING (default 20%): the top 10 swing setups (stocks and ETFs) with entry,
   stoploss, target, exit date and holding time.
"""

from __future__ import annotations

import json
import os

from rich import box
from rich.markdown import Markdown
from rich.table import Table

from cli.breakout import _inr
from cli.display import console
from cli.scan import scans_dir
from tradingagents.dataflows import india
from tradingagents.journal import Journal


def _held_momentum() -> dict[str, float]:
    j = Journal.load()
    return {t.symbol: t.entry_price for t in j.open_trades() if t.strategy == "momentum"}


def build(capital: float, core_pct: float, risk: float, top: int, refresh: bool, no_news: bool,
          progress=None) -> dict:
    from tradingagents.scanner import data as data_mod
    from tradingagents.scanner.daily import run_daily
    from tradingagents.scanner.momentum import core_picks

    md = data_mod.load(refresh=refresh, progress=progress)
    core_cap = capital * core_pct / 100
    swing_cap = capital - core_cap
    core = core_picks(md, core_cap, _held_momentum())
    swing = run_daily(capital=swing_cap, risk_pct=risk, top=top, with_news=not no_news, md=md)
    return {
        "as_of": str(md.last), "settled": str(md.settled), "capital": capital,
        "core_pct": core_pct, "core_capital": core_cap, "swing_capital": swing_cap,
        "core": core, "swing": swing,
    }


def render_markdown(r: dict) -> str:
    core, swing = r["core"], r["swing"]
    m = swing["market"]
    rec = core["record"]
    out = [
        f"# Trade setups - {r['as_of']} close",
        "",
        f"Nifty 50 {m['nifty']:,} | 50-DMA {m['nifty_sma50']:,} | 200-DMA {m['nifty_sma200']:,} | "
        f"breadth {m['breadth_pct']:.0f}% | capital {_inr(r['capital'])}: core {_inr(r['core_capital'])} "
        f"({r['core_pct']:.0f}%), swing {_inr(r['swing_capital'])}",
        *[f"> {n}" for n in swing["notes"]],
        "",
        f"## 1. CORE - momentum portfolio ({r['core_pct']:.0f}% of capital)",
        "",
        f"Tested {rec['period']}: **+{rec['cagr_pct']}% a year, worst drop -{rec['max_drawdown_pct']}%** "
        f"(Nifty: +{rec['nifty_cagr_pct']}%, -{rec['nifty_max_drawdown_pct']}%). Next review: "
        f"**{core['review_on']}** (last trading day of the month).",
        "",
    ]
    if not core["regime_on"]:
        out += [f"**Market regime OFF**: the Nifty ({core['nifty']:,}) is below its 200-DMA "
                f"({core['nifty_sma200']:,}). Keep the core in LIQUIDBEES. The list below is ON DECK (WAIT): "
                f"what the core buys at the first month-end review with the Nifty back above its 200-DMA.", ""]
    if True:
        out += ["| # | Name | Ticker | Cap | Sector | Action | Entry | Stoploss | Target | Exit | Hold | Qty |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for p in core["picks"]:
            entry = (f"buy next open <= {p['max_entry']:,.2f}" if p["action"] == "BUY"
                     else f"~{p['close']:,.2f} when regime turns on" if p["action"] == "WAIT"
                     else f"bought {p['entry']:,.2f}")
            out.append(
                f"| {p['rank']} | {p['name']} | {p['symbol'].removesuffix('.NS')} | {p['cap']} | "
                f"{p['industry'] or '-'} | **{p['action']}** | {entry} | {p['stop']:,.2f} (-15%) | none: ride the trend | "
                f"monthly review {p['review_on']}: sell if rank > 40 | 1-4 months | {p['quantity']} |"
            )
    if core["sells"]:
        out += ["", "**SELL** (from your journal):"]
        out += [f"- {s['symbol'].removesuffix('.NS')}: {s['reason']}" for s in core["sells"]]
    out += [
        "",
        f"## 2. SWING - top {len(swing['ideas'])} setups ({100 - r['core_pct']:.0f}% of capital)",
        "",
        "| # | Name | Ticker | Cap | Setup | Grade | Entry | Stoploss | Target | Exit by | Hold | R:R | Qty | Call |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i in swing["ideas"]:
        entry = (f"buy-stop {i['entry']:,.2f} (max {i['max_entry']:,.2f})" if i["entry_type"] == "stop"
                 else f"buy open ~{i['entry']:,.2f}")
        out.append(
            f"| {i['rank']} | {i['name']} | {i['symbol'].removesuffix('.NS')} | {i['cap']} | {i['strategy_label']} | "
            f"{i['grade']} | {entry} | {i['stop']:,.2f} (-{i['risk_pct']:.1f}%) | {i['target']:,.2f} "
            f"(+{i['reward_pct']:.1f}%) | {i['exit_by']} | {i['hold']} | {i['rr']:.1f} | {i['quantity']} | {i['verdict']} |"
        )
    out += [
        "",
        "Grades: **A** 52-week breakout (tested edge in rising and weak markets); **B** setup whose strategy is "
        "profitable across NSE over the last 6 and 12 months; **C** strategy losing lately: half size or paper only.",
        "",
        "Order: core BUYs at the next open (limit = the max shown). Swing: SL buy order (trigger = entry, "
        "limit = max) for the next session, then a GTT OCO with the stoploss and target. Log every fill: "
        "`/trade-journal`. Rules: docs/STRATEGY.md. Not investment advice.",
    ]
    return "\n".join(out)


def _print(r: dict) -> None:
    core, swing = r["core"], r["swing"]
    console.print(f"[bold]Trade setups from the {r['as_of']} close[/bold]  |  {india.market_status().describe()}")
    for n in swing["notes"]:
        console.print(f"[yellow]Note:[/yellow] {n}")
    wide = console.width >= 130
    console.print(f"\n[bold cyan]1. CORE - momentum portfolio[/bold cyan] ({_inr(r['core_capital'])}, "
                  f"review {core['review_on']}; tested +{core['record']['cagr_pct']}%/yr, worst drop "
                  f"-{core['record']['max_drawdown_pct']}%)")
    if not core["regime_on"]:
        console.print("[red]Regime OFF: Nifty below its 200-DMA. Core stays in LIQUIDBEES. The list is ON DECK "
                      "(WAIT): bought at the first month-end review with the Nifty back above.[/red]")
    if wide:
        t = Table(box=box.SIMPLE_HEAD)
        for c in ("#", "Name", "Ticker", "Cap", "Action", "Entry", "Stoploss", "Target", "Exit", "Hold", "Qty"):
            t.add_column(c, no_wrap=c not in ("Name",))
        for p in core["picks"]:
            t.add_row(str(p["rank"]), p["name"][:28], p["symbol"].removesuffix(".NS"), p["cap"], p["action"],
                      f"{p['max_entry'] if p['action'] == 'BUY' else p['entry']:,.2f}", f"{p['stop']:,.2f}",
                      "none (trend)", f"review {p['review_on'][5:]}", "1-4 mo", str(p["quantity"]))
        console.print(t)
    else:
        for p in core["picks"]:
            console.print(f"{p['rank']:>2} [bold]{p['symbol'].removesuffix('.NS')}[/bold] {p['name'][:30]} "
                          f"({p['cap']}) [bold]{p['action']}[/bold]")
            console.print(f"    Entry {p['max_entry'] if p['action'] == 'BUY' else p['entry']:,.2f} | Stop "
                          f"{p['stop']:,.2f} | Target: none | Exit: review {p['review_on'][5:]} | Hold 1-4 mo | "
                          f"Qty {p['quantity']}")
    for s in core["sells"]:
        console.print(f"[red]SELL {s['symbol'].removesuffix('.NS')}[/red]: {s['reason']}")

    console.print(f"\n[bold cyan]2. SWING - top {len(swing['ideas'])} setups[/bold cyan] ({_inr(r['swing_capital'])})")
    if wide:
        t = Table(box=box.SIMPLE_HEAD)
        for c in ("#", "Name", "Ticker", "Cap", "Setup", "Gr", "Entry", "Stoploss", "Target", "Exit by", "Hold",
                  "R:R", "Qty", "Call"):
            t.add_column(c, no_wrap=c not in ("Name", "Hold"))
        for i in swing["ideas"]:
            t.add_row(str(i["rank"]), i["name"][:24], i["symbol"].removesuffix(".NS"), i["cap"], i["strategy"],
                      i["grade"], f"{i['entry']:,.2f}", f"{i['stop']:,.2f}", f"{i['target']:,.2f}", i["exit_by"][5:],
                      i["hold"], f"{i['rr']:.1f}", str(i["quantity"]), i["verdict"].split(" (")[0].split(":")[0])
        console.print(t)
    else:
        for i in swing["ideas"]:
            console.print(f"{i['rank']:>2}{i['grade']} [bold]{i['symbol'].removesuffix('.NS')}[/bold] {i['name'][:26]} "
                          f"({i['cap']}, {i['strategy']}) -> {i['verdict'].split(' (')[0]}")
            console.print(f"    Entry {i['entry']:,.2f} | Stop {i['stop']:,.2f} | Tgt {i['target']:,.2f} | "
                          f"R:R {i['rr']:.1f} | Exit by {i['exit_by'][5:]} | Qty {i['quantity']}")
            console.print(f"    Hold: {i['hold']}")
    console.print("[dim]Grades: A breakout (tested edge), B strategy working lately, C half size/paper. "
                  "Rules: docs/STRATEGY.md. Not investment advice.[/dim]")


def setups_command(capital: float, core_pct: float, risk: float, top: int, refresh: bool, as_json: bool,
                   markdown: bool, no_news: bool) -> int:
    def progress(done, total):
        if not (as_json or markdown):
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    r = build(capital, core_pct, risk, top, refresh, no_news, progress)
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
        _print(r)
        console.print(f"[dim]Saved: {stem}.md[/dim]")
    return 0


def show_markdown(text: str) -> None:
    console.print(Markdown(text))
