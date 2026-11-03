"""`tradingagents scan`: the daily top-10 NSE trade ideas, as a table and cards."""

from __future__ import annotations

import json
import os
from datetime import datetime

from rich import box
from rich.panel import Panel
from rich.table import Table

from cli.breakout import _inr
from cli.display import console
from tradingagents.dataflows import india
from tradingagents.default_config import DEFAULT_CONFIG

GRADE_TEXT = {
    "GOOD": "GOOD = the setup is making money across NSE lately; take it",
    "OK": "OK = one risk to respect (results, mixed record, weak market); half size",
    "AVOID": "AVOID = the setup is losing money lately or the news is bad",
}
GRADE_STYLE = {"GOOD": "bold green", "OK": "yellow", "AVOID": "red"}
SHORT_SETUP = {"breakout": "BRK", "vcp": "VCP", "flag": "FLAG", "ep": "EP", "crossback": "XBK"}


def _short_verdict(v: str) -> str:
    for key, short in (("GOOD", "GOOD"), ("OK", "HALF"), ("AVOID", "AVOID")):
        if v.startswith(key):
            return short
    return v[:10]


def scans_dir() -> str:
    folder = os.path.join(os.path.dirname(DEFAULT_CONFIG["results_dir"]), "scans")
    os.makedirs(folder, exist_ok=True)
    return folder


def _rec(rec: dict) -> str:
    if not rec or not rec.get("trades"):
        return "no trades"
    return (f"{rec['trades']} trades, {rec['win_rate']:.0f}% won, {rec['expectancy_r']:+.2f}R/trade, "
            f"PF {rec['profit_factor']:.2f}")


def _entry_text(i: dict) -> str:
    if i["entry_type"] == "stop":
        return f"Buy-stop {i['entry']:,.2f} (max {i['max_entry']:,.2f})"
    return f"Buy at open ~{i['entry']:,.2f} (max {i['max_entry']:,.2f})"


def render_markdown(r: dict) -> str:
    m = r["market"]
    lines = [
        f"# NSE top {len(r['ideas'])} trade ideas - {r['as_of']} close",
        "",
        f"Nifty 50 {m['nifty']:,} (50-DMA {m['nifty_sma50']:,}, 200-DMA {m['nifty_sma200']:,}, 6m "
        f"{m['nifty_ret_6m_pct']:+.1f}%) | breadth {m['breadth_pct']:.0f}% of stocks above 200-DMA | "
        f"{r['scanned']} large/mid/small caps scanned, {r['candidates']} setups found. "
        f"Capital {_inr(r['capital'])}, risk {r['risk_pct']}% per trade.",
        "",
        "| # | Grade | Stock | Cap | Sector | Setup | Entry | Stoploss | Target / exit | R:R | Exit by | Qty | Capital | Max loss | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i in r["ideas"]:
        lines.append(
            f"| {i['rank']} | {i['grade']} | **{i['symbol'].removesuffix('.NS')}** | {i['cap']} | "
            f"{i['industry'] or '-'} | {i['strategy_label']} | {_entry_text(i)} | {i['stop']:,.2f} "
            f"(-{i['risk_pct']:.1f}%) | {i['target']:,.2f} (+{i['reward_pct']:.1f}%) | {i['rr']:.1f} | "
            f"{i['exit_by']} | {i['quantity']} | {i['capital_needed']:,.0f} | {i['max_loss']:,.0f} | {i['verdict']} |"
        )
    lines += ["", "Grades: " + "; ".join(GRADE_TEXT.values()), ""]
    for i in r["ideas"]:
        lines += [
            f"## {i['rank']}. {i['symbol'].removesuffix('.NS')} - {i['name']} ({i['cap']} cap, grade {i['grade']})",
            f"- **Plan**: {_entry_text(i)}; stop {i['stop']:,.2f}; exit: {i['exit_rule']} "
            f"(target {i['target']:,.2f}); hold up to {i['hold_sessions']} sessions, exit by {i['exit_by']}. "
            f"Size: {i['quantity']} shares ({i['size_note']}).",
            "- **Bull agent**: " + " ".join(i["bull"]),
            "- **Bear agent**: " + (" ".join(i["bear"]) or "No material objection found."),
            f"- **Judge**: {i['verdict']}",
            f"- **Results date**: {i['earnings_date'] or 'not announced'}"
            + (" - INSIDE the holding window" if i["earnings_in_window"] else ""),
            f"- **News check**: {i['news_flag']}",
            *[f"  - {n['when']}: {n['title']}" for n in i["news"][:3]],
            "",
        ]
    lines += ["## Strategy records (every large/mid/small cap on NSE, after 0.3% costs)", ""]
    for name, rec in r["records"].items():
        lines.append(f"- **{name}**: last 6m {_rec(rec['6m'])}; last 12m {_rec(rec['12m'])}; "
                     f"since 2022 {_rec(rec['all'])}")
    if r["notes"]:
        lines += ["", "## Notes", *[f"- {n}" for n in r["notes"]]]
    lines += ["", "Not investment advice. Free Yahoo/Google data can lag; confirm prices in your broker."]
    return "\n".join(lines)


def _print(r: dict) -> None:
    m = r["market"]
    console.print(Panel(
        f"Ideas from the [bold]{r['as_of']}[/bold] close  |  {india.market_status().describe()}\n"
        f"Nifty 50 {m['nifty']:,} (50-DMA {m['nifty_sma50']:,}, 200-DMA {m['nifty_sma200']:,}, "
        f"6m {m['nifty_ret_6m_pct']:+.1f}%)  |  breadth {m['breadth_pct']:.0f}%  |  "
        f"{r['scanned']} large/mid/small caps, {r['candidates']} setups",
        title="NSE Top Trade Ideas", border_style="cyan",
    ))
    t = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False, padding=(0, 1))
    for col in ("#", "Stock", "Cap", "Setup", "Entry", "Stop", "Target", "R:R", "Exit", "Qty", "Call"):
        t.add_column(col, no_wrap=True, overflow="crop")
    for i in r["ideas"]:
        t.add_row(
            f"[{GRADE_STYLE[i['grade']]}]{i['rank']}{i['grade']}[/]", i["symbol"].removesuffix(".NS")[:10],
            i["cap"][0], SHORT_SETUP[i["strategy"]], f"{i['entry']:.2f}", f"{i['stop']:.2f}", f"{i['target']:.2f}",
            f"{i['rr']:.1f}", i["exit_by"][5:], str(i["quantity"]), _short_verdict(i["verdict"]),
        )
    if console.width >= 110:
        console.print(t)
    else:  # narrow terminal: two lines per idea, nothing cropped
        for i in r["ideas"]:
            style = GRADE_STYLE[i["grade"]]
            console.print(
                f"[{style}]{i['rank']:>2}{i['grade']}[/] [bold]{i['symbol'].removesuffix('.NS')}[/bold]  "
                f"{i['cap']} cap  {i['strategy_label']}  -> [bold]{_short_verdict(i['verdict'])}[/bold]"
            )
            console.print(
                f"    Entry {i['entry']:.2f} | Stop {i['stop']:.2f} | Tgt {i['target']:.2f} | "
                f"R:R {i['rr']:.1f} | Exit {i['exit_by'][5:]} | Qty {i['quantity']}"
            )
    console.print("  #: rank + verdict.  Cap: L large (top 100), M mid (101-250), S small (251-500).  "
                  "Setup: BRK 52-wk breakout, VCP Minervini, FLAG Qullamaggie flag, EP episodic pivot, XBK Kell crossback.  Entry: buy-stop for "
                  "the next session.  Exit: last day to hold (MM-DD).  Call: GOOD, HALF = half size, AVOID.")
    for g, text in GRADE_TEXT.items():
        console.print(f"  [{GRADE_STYLE[g]}]{text}[/]")
    for i in r["ideas"]:
        body = (
            f"[bold]Plan[/bold]  {_entry_text(i)}  |  stop {_inr(i['stop'])} (-{i['risk_pct']:.1f}%)  |  "
            f"target {_inr(i['target'])} (+{i['reward_pct']:.1f}%)  |  R:R {i['rr']:.1f}\n"
            f"[bold]Exit[/bold]  {i['exit_rule']}; exit by {i['exit_by']}\n"
            f"[bold]Size[/bold]  {i['quantity']} shares = {_inr(i['capital_needed'])}, max loss ~{_inr(i['max_loss'])} "
            f"({i['size_note']})\n"
            f"[green]Bull:[/green] {' '.join(i['bull'])}\n"
            f"[red]Bear:[/red] {' '.join(i['bear']) or 'No material objection found.'}\n"
            f"[bold]Judge:[/bold] {i['verdict']}   |   results: {i['earnings_date'] or 'not announced'}"
            f"{' (INSIDE hold)' if i['earnings_in_window'] else ''}   |   news: {i['news_flag']}"
        )
        if i["news"]:
            body += "\n[dim]" + "\n".join(f"{n['when']}: {n['title']}" for n in i["news"][:2]) + "[/dim]"
        console.print(Panel(body, title=f"#{i['rank']} {i['symbol'].removesuffix('.NS')} - {i['name']} | "
                            f"{i['cap']} cap | {i['industry'] or '-'} | {i['strategy_label']} | grade {i['grade']}",
                            border_style=GRADE_STYLE[i["grade"]].split()[-1]))
    console.print("[bold]Strategy records[/bold] (all large/mid/small caps, after costs):")
    for name, rec in r["records"].items():
        console.print(f"  {name:<9} 6m: {_rec(rec['6m'])} | 12m: {_rec(rec['12m'])}")
    for n in r["notes"]:
        console.print(f"[yellow]Note:[/yellow] {n}")
    console.print("[dim]Not investment advice. Confirm prices in your broker before ordering. "
                  "Log your trades: tradingagents journal add ...[/dim]")


def scan_command(capital: float, risk: float, top: int, date: str | None, refresh: bool,
                 as_json: bool, no_news: bool) -> int:
    from tradingagents.scanner.daily import run_daily

    as_of = datetime.strptime(date, "%Y-%m-%d").date() if date else None
    status = india.market_status()
    if not as_json and status.phase in ("pre-open", "open", "closing", "post-close"):
        console.print(f"[yellow]Market is {status.phase}: today's candle is not final. Using the "
                      f"{status.last_completed_session} close; re-run after 16:30 IST.[/yellow]")

    def progress(done, total):
        if not as_json:
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    r = run_daily(capital=capital, risk_pct=risk, top=top, refresh=refresh, progress=progress,
                  as_of=as_of, with_news=not no_news)
    stem = os.path.join(scans_dir(), f"top-{r['as_of']}")
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    with open(stem + ".md", "w", encoding="utf-8") as fh:
        fh.write(render_markdown(r))
    if as_json:
        print(json.dumps(r, indent=1))
    else:
        _print(r)
        console.print(f"[dim]Saved: {stem}.md (full table) and .json[/dim]")
    return 0
