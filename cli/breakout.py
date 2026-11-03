"""`tradingagents breakout`: the NSE breakout scan, printed as trade plans."""

from __future__ import annotations

import json
import os
from datetime import datetime

from rich.panel import Panel
from rich.table import Table

from cli.display import console
from tradingagents.dataflows import india
from tradingagents.default_config import DEFAULT_CONFIG


def _inr(x: float) -> str:
    """Indian digit grouping: 1234567.8 -> 12,34,567.80."""
    neg, x = x < 0, abs(float(x))
    whole, frac = f"{x:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    s = ",".join(groups + [tail]) if groups else tail
    return f"{'-' if neg else ''}Rs {s}.{frac}"


def _record_line(label: str, rec: dict) -> str:
    if not rec or not rec.get("trades"):
        return f"{label}: no closed trades"
    return (
        f"{label}: {rec['trades']} trades, {rec['win_rate']:.0f}% winners, "
        f"{rec['expectancy_r']:+.2f}R per trade ({rec['avg_ret_pct']:+.2f}% avg after costs), "
        f"avg win {rec['avg_win_pct']:+.1f}% / avg loss {rec['avg_loss_pct']:+.1f}%, "
        f"profit factor {rec['profit_factor']:.2f}, median hold {rec['median_days']:.0f} sessions"
    )


def render_markdown(result: dict, capital: float, risk_pct: float) -> str:
    """The scan as Markdown: saved next to the JSON and read by the Claude skill."""
    m = result["market"]
    lines = [
        f"# NSE breakout scan - signals on the {result['as_of']} close",
        "",
        f"Universe: {result['universe_size']} NSE mainboard stocks (EQ series), "
        f"{result['scanned']} with a full year of data. No penny stocks: price >= Rs 100, "
        "turnover >= Rs 10 crore/day.",
        "",
        "## Market",
        f"- Nifty 50 {m['nifty']:,} | 50-DMA {m['nifty_sma50']:,} | 200-DMA {m['nifty_sma200']:,} | "
        f"6-month {m['nifty_ret_6m_pct']:+.1f}%",
        f"- Breadth: {m['breadth_pct']:.0f}% of stocks above their 200-DMA",
        f"- Market filter: {'ON - new trades allowed' if result['regime_ok'] else 'OFF - no new trades'}",
        "",
        "## The rule's record (same rule, every NSE stock, after 0.3% costs)",
        f"- {_record_line('Last 6 months', result['record_recent'])}",
        f"- {_record_line('Last 12 months', result['record_12m'])}",
        f"- {_record_line('Since 2022', result['record_all'])}",
        "",
    ]
    picks = result["picks"]
    lines.append(f"## Breakout signals ({len(picks)})")
    if not picks:
        lines += [
            "",
            "No stock passed every rule on this close. That is the rule working: it fires about "
            "8-10 times a month across the whole market and stays out otherwise. Do not force a trade.",
        ]
    for i, p in enumerate(picks, 1):
        lines += [
            "",
            f"### {i}. {p['symbol']} - {p['name']}",
            f"- **Entry**: buy-stop at {_inr(p['entry'])} next session (just above the signal day's high). "
            f"Do not buy above {_inr(p['max_entry'])}; if it never trades at {_inr(p['entry'])}, no trade.",
            f"- **Stoploss**: {_inr(p['stop'])} ({p['risk_pct']:.1f}% risk)",
            f"- **Target**: {_inr(p['target'])} (+{p['reward_pct']:.1f}%), reward:risk {p['rr']:.1f} : 1",
            f"- **Holding period**: up to {p['hold_sessions']} sessions; if neither stop nor target hits, "
            f"exit at the close on {p['exit_by']}",
            f"- **Size** (capital {_inr(capital)}, risk {risk_pct}% per trade): {p['quantity']} shares = "
            f"{_inr(p['capital_needed'])}; loss at the stop about {_inr(p['max_loss'])}",
            f"- Why: closed {p['close']} at a new 52-week high on {p['volume_ratio']:.1f}x average volume, "
            f"out of a {p['base_pct']:.1f}% base; 6-month return {p['rs_vs_nifty_pct']:+.1f} pts vs the Nifty; "
            f"turnover Rs {p['turnover_cr']:.0f} cr/day",
            *([f"- **RESULTS RISK**: quarterly results due {p['earnings_date']}, inside the holding window. "
               "A results gap can jump the stoploss. Skip it, halve the size, or exit before the results."]
              if p.get("earnings_in_window") else []),
            f"- This stock's own record on the rule: {p['stock_history'].get('trades') or 0} past trades"
            + (f", {p['stock_history']['win_rate']:.0f}% winners, {p['stock_history']['expectancy_r']:+.2f}R"
               if p["stock_history"].get("trades") else ""),
        ]
    if result["watchlist"]:
        lines += ["", "## Watchlist: tight bases at or near a 52-week high (not signals yet)", ""]
        lines += ["| Stock | Close | 52-wk high (breakout level) | Distance | Base | Volume vs avg |",
                  "|---|---|---|---|---|---|"]
        for w in result["watchlist"][:10]:
            lines.append(
                f"| {w['symbol']} | {w['close']} | {w['breakout_level']} | {w['distance_pct']:+.2f}% | "
                f"{w['base_pct']:.1f}% | {w['volume_ratio']:.1f}x |"
            )
    if result["notes"]:
        lines += ["", "## Notes", *[f"- {n}" for n in result["notes"]]]
    lines += [
        "",
        "Not investment advice. A rule with a positive past record can lose money for months; size "
        "every trade so a run of 6-8 losses is survivable. Prices are free Yahoo data and can lag; "
        "check the quote in your broker before placing the order.",
    ]
    return "\n".join(lines)


def _print(result: dict, capital: float, risk_pct: float) -> None:
    m = result["market"]
    status = india.market_status()
    console.print(Panel(
        f"Signals on the [bold]{result['as_of']}[/bold] close  |  {status.describe()}\n"
        f"Nifty 50 {m['nifty']:,}  (50-DMA {m['nifty_sma50']:,}, 200-DMA {m['nifty_sma200']:,}, "
        f"6m {m['nifty_ret_6m_pct']:+.1f}%)  |  breadth {m['breadth_pct']:.0f}% above 200-DMA\n"
        f"Market filter: " + ("[green]ON - new trades allowed[/green]" if result["regime_ok"]
                              else "[red]OFF - no new trades; wait[/red]"),
        title="NSE Breakout Scanner", border_style="cyan",
    ))
    console.print("[bold]The rule's own record[/bold] (every NSE stock, after costs):")
    for label, key in (("Last 6 months", "record_recent"), ("Last 12 months", "record_12m"),
                       ("Since 2022", "record_all")):
        console.print("  " + _record_line(label, result[key]))

    picks = result["picks"]
    if picks:
        console.print(f"\n[bold green]Breakout trades for the next session: {len(picks)}[/bold green]")
        for i, p in enumerate(picks, 1):
            hist = p["stock_history"]
            console.print(Panel(
                f"[bold]ENTRY[/bold]     buy-stop {_inr(p['entry'])}  (do not pay above {_inr(p['max_entry'])};"
                f" no fill = no trade)\n"
                f"[bold]STOPLOSS[/bold]  {_inr(p['stop'])}   (-{p['risk_pct']:.1f}%)\n"
                f"[bold]TARGET[/bold]    {_inr(p['target'])}   (+{p['reward_pct']:.1f}%)    "
                f"[bold]REWARD:RISK[/bold] {p['rr']:.1f} : 1\n"
                f"[bold]HOLD[/bold]      up to {p['hold_sessions']} sessions; else exit at the close on "
                f"{p['exit_by']}\n"
                f"[bold]SIZE[/bold]      {p['quantity']} shares = {_inr(p['capital_needed'])}; loss at stop "
                f"~{_inr(p['max_loss'])} ({risk_pct}% risk)\n"
                f"[dim]Why: new 52-week high at {p['close']} on {p['volume_ratio']:.1f}x volume, "
                f"{p['base_pct']:.1f}% base, {p['rs_vs_nifty_pct']:+.1f} pts vs Nifty (6m), "
                f"Rs {p['turnover_cr']:.0f} cr/day. Past trades on this stock: {hist.get('trades') or 0}"
                + (f", {hist['win_rate']:.0f}% won" if hist.get("trades") else "") + "[/dim]"
                + (f"\n[bold red]RESULTS RISK[/bold red]: results due {p['earnings_date']}, inside the holding "
                   "window; a results gap can jump the stop. Skip, halve the size, or exit before results."
                   if p.get("earnings_in_window") else ""),
                title=f"#{i}  {p['symbol']}  {p['name']}", border_style="green",
            ))
    else:
        console.print(
            "\n[yellow]No breakout passed every rule on this close.[/yellow] The rule fires about 8-10 "
            "times a month across the whole market; most days are no-trade days. Do not force one."
        )
    if result["watchlist"]:
        wt = Table(title="Watchlist: tight bases at/near a 52-week high (alert levels, not signals)")
        for col in ("Stock", "Close", "Breakout level", "Distance", "Base", "Vol vs avg"):
            wt.add_column(col)
        for w in result["watchlist"][:10]:
            wt.add_row(w["symbol"], f"{w['close']}", f"{w['breakout_level']}", f"{w['distance_pct']:+.2f}%",
                       f"{w['base_pct']:.1f}%", f"{w['volume_ratio']:.1f}x")
        console.print(wt)
    for note in result["notes"]:
        console.print(f"[yellow]Note:[/yellow] {note}")
    console.print(
        "[dim]Not investment advice. Free Yahoo data, can lag: confirm the quote in your broker. "
        "Place the entry as a buy-stop (SL-M/SL order) for the next session, and the stoploss as soon "
        "as it fills.[/dim]"
    )


def _deep_dive(picks: list[dict], limit: int) -> None:
    """Run the full TradingAgents debate on the top picks (needs an LLM API key)."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.llm_clients.api_key_env import get_api_key_env

    config = DEFAULT_CONFIG.copy()
    provider = config.get("llm_provider", "anthropic")
    key_env = get_api_key_env(provider)
    if key_env and not os.environ.get(key_env):
        console.print(
            f"[yellow]--deep needs {key_env} (the {provider} API is billed per use). The scan above "
            "needs no key. To review the picks with no API bill, run the /nse-breakout skill inside "
            "Claude Code instead.[/yellow]"
        )
        return
    graph = TradingAgentsGraph(debug=False, config=config)
    for p in picks[:limit]:
        console.print(f"\n[cyan]Deep analysis of {p['symbol']} with {config['deep_think_llm']}...[/cyan]")
        try:
            _, rating = graph.propagate(p["symbol"], p["signal_date"])
        except Exception as exc:  # one failed analysis does not end the others
            console.print(f"[red]{p['symbol']}: {exc}[/red]")
            continue
        console.print(f"[bold]{p['symbol']}: agents' rating {rating}[/bold] "
                      f"(full report under {config['results_dir']})")


def breakout_command(capital: float, risk: float, top: int, date: str | None, refresh: bool,
                     as_json: bool, deep: int) -> int:
    from tradingagents.scanner.breakout import run_scan

    status = india.market_status()
    if not as_json and status.phase in ("pre-open", "open", "closing", "post-close"):
        console.print(
            f"[yellow]The market is {status.phase} now; today's candle is not final. This scan uses the "
            f"last settled close ({status.last_completed_session}). Run again after 16:00 IST for today's "
            "signals.[/yellow]"
        )
    as_of = datetime.strptime(date, "%Y-%m-%d").date() if date else None

    def progress(done, total):
        if not as_json:
            console.print(f"[dim]Downloading daily bars {done}/{total}...[/dim]")

    result = run_scan(capital=capital, risk_pct=risk, top=top, refresh=refresh,
                      progress=progress, as_of=as_of).to_dict()
    result = json.loads(json.dumps(result, default=float))

    folder = os.path.join(os.path.dirname(DEFAULT_CONFIG["results_dir"]), "scans")
    os.makedirs(folder, exist_ok=True)
    stem = os.path.join(folder, f"breakout-{result['as_of']}")
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    with open(stem + ".md", "w", encoding="utf-8") as fh:
        fh.write(render_markdown(result, capital, risk))

    if as_json:
        print(json.dumps(result, indent=1))
    else:
        _print(result, capital, risk)
        console.print(f"[dim]Saved: {stem}.md and .json[/dim]")
    if deep and result["picks"]:
        _deep_dive(result["picks"], deep)
    return 0
