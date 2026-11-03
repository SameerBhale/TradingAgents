"""`tradingagents journal ...`: record entries and exits, see P&L and capital used."""

from __future__ import annotations

import glob
import json
import os
from datetime import date

import typer
from rich.table import Table

from cli.breakout import _inr
from cli.display import console
from tradingagents.journal import Journal

app = typer.Typer(help="Your trade journal: entries, exits, charges, P&L and capital used.",
                  no_args_is_help=True)


def _symbol(raw: str) -> str:
    from cli.prompts import parse_ticker

    return parse_ticker(raw)


def _latest_scan_idea(rank: int) -> dict:
    from cli.scan import scans_dir

    files = sorted(glob.glob(os.path.join(scans_dir(), "top-*.json")))
    if not files:
        raise ValueError("no saved scan yet: run `tradingagents scan` first")
    with open(files[-1], encoding="utf-8") as fh:
        ideas = json.load(fh)["ideas"]
    for idea in ideas:
        if idea["rank"] == rank:
            return idea
    raise ValueError(f"the latest scan ({os.path.basename(files[-1])}) has no idea #{rank}")


def _money(x) -> str:
    if x is None:
        return "-"
    color = "green" if x > 0 else "red" if x < 0 else "white"
    return f"[{color}]{_inr(x)}[/{color}]"


@app.command()
def capital(amount: float = typer.Argument(..., help="Your trading capital in INR, e.g. 500000")):
    """Set your trading capital (used for return and free-capital figures)."""
    j = Journal.load()
    j.capital = amount
    j.save()
    console.print(f"Capital set to {_inr(amount)}. Journal: {j.path}")


@app.command()
def add(
    symbol: str = typer.Argument(None, help="Stock, e.g. DIVISLAB (omit with --from-scan)"),
    price: float = typer.Option(..., "--price", help="Your actual buy price (fill)"),
    qty: int = typer.Option(None, "--qty", help="Shares bought (default: the scan's quantity)"),
    stop: float = typer.Option(None, "--stop", help="Stoploss"),
    target: float = typer.Option(None, "--target", help="Target"),
    on: str = typer.Option(None, "--date", help="Buy date YYYY-MM-DD (default today)"),
    strategy: str = typer.Option("", "--strategy", help="Setup name, e.g. breakout"),
    notes: str = typer.Option("", "--notes", help="Anything to remember"),
    from_scan: int = typer.Option(None, "--from-scan", help="Fill symbol, stop, target, qty from idea #N of the latest scan"),
):
    """Record a buy."""
    try:
        if from_scan:
            idea = _latest_scan_idea(from_scan)
            symbol = symbol or idea["symbol"]
            stop = stop if stop is not None else idea["stop"]
            target = target if target is not None else idea["target"]
            qty = qty or idea["quantity"]
            strategy = strategy or idea["strategy"]
            notes = notes or f"scan {idea['grade']}-grade idea; exit by {idea['exit_by']}"
        if not symbol or not qty:
            raise ValueError("give a symbol and --qty (or use --from-scan N)")
        j = Journal.load()
        t = j.add(symbol=_symbol(symbol), entry_date=on or date.today().isoformat(), entry_price=price,
                  qty=qty, stop=stop, target=target, strategy=strategy, notes=notes)
        j.save()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Added #{t.id}: bought {t.qty} {t.symbol} at {_inr(t.entry_price)} = {_inr(t.capital_used)}"
                  + (f", stop {_inr(t.stop)}" if t.stop else "") + (f", target {_inr(t.target)}" if t.target else ""))


@app.command()
def close(
    trade_id: int = typer.Argument(..., help="Trade number from `journal list`"),
    price: float = typer.Option(..., "--price", help="Your actual sell price"),
    on: str = typer.Option(None, "--date", help="Sell date YYYY-MM-DD (default today)"),
    charges: float = typer.Option(None, "--charges", help="Total charges from your contract notes (default: estimated)"),
    qty: int = typer.Option(None, "--qty", help="Sell only part of the position"),
):
    """Record a sell (full or partial)."""
    try:
        j = Journal.load()
        t = j.close(trade_id, price, on or date.today().isoformat(), charges, qty)
        j.save()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    r = t.r_multiple()
    console.print(f"Closed #{t.id} {t.symbol}: {t.qty} at {_inr(price)}; net P&L {_money(t.net_pnl())} "
                  f"after charges {_inr(t.total_charges())}" + (f", {r:+.2f}R" if r is not None else ""))


@app.command()
def remove(trade_id: int = typer.Argument(..., help="Trade number to delete (a mistaken entry)")):
    """Delete a trade entered by mistake."""
    j = Journal.load()
    try:
        t = j.get(trade_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    j.trades.remove(t)
    j.save()
    console.print(f"Removed #{trade_id} ({t.symbol}).")


def _live_prices(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    from tradingagents.dataflows.vendors.yahoo.bulk import download_daily

    data = download_daily(symbols, period="5d")
    return {s: float(d["Close"].iloc[-1]) for s, d in data.items() if not d.empty}


@app.command("list")
def list_(
    all_: bool = typer.Option(False, "--all", help="Include closed trades"),
    live: bool = typer.Option(True, "--live/--no-live", help="Show open positions at the latest price"),
):
    """Show open positions (and closed trades with --all)."""
    j = Journal.load()
    trades = j.trades if all_ else j.open_trades()
    if not trades:
        console.print("No trades yet. Add one: tradingagents journal add DIVISLAB --price 9999.99 --qty 10 --stop 9512.3")
        return
    prices = _live_prices([t.symbol for t in j.open_trades()]) if live else {}
    tb = Table(title=f"Trade journal ({j.path})")
    for col in ("#", "Stock", "Setup", "Bought", "Qty", "Capital", "Stop", "Target", "Sold / now",
                "Net P&L", "R", "Days"):
        tb.add_column(col)
    for t in trades:
        now = t.exit_price if not t.is_open else prices.get(t.symbol)
        pnl = t.net_pnl() if not t.is_open else (t.net_pnl(now) if now else None)
        r = t.r_multiple() if not t.is_open else (t.r_multiple(now) if now else None)
        sold = (f"{t.exit_price:,.2f} {t.exit_date}" if not t.is_open
                else (f"[dim]now {now:,.2f}[/dim]" if now else "open"))
        tb.add_row(str(t.id), t.symbol.removesuffix(".NS"), t.strategy or "-",
                   f"{t.entry_price:,.2f} {t.entry_date}", str(t.qty), f"{t.capital_used:,.0f}",
                   f"{t.stop:,.2f}" if t.stop else "-", f"{t.target:,.2f}" if t.target else "-", sold,
                   _money(pnl), f"{r:+.2f}" if r is not None else "-", str(t.holding_days()))
    if console.width >= 120:
        console.print(tb)
    else:  # narrow terminal: two lines per trade
        console.print(f"Trade journal: {j.path}")
        for t in trades:
            now = t.exit_price if not t.is_open else prices.get(t.symbol)
            pnl = t.net_pnl() if not t.is_open else (t.net_pnl(now) if now else None)
            r = t.r_multiple() if not t.is_open else (t.r_multiple(now) if now else None)
            state = f"sold {t.exit_price:,.2f} on {t.exit_date}" if not t.is_open else (
                f"open, now {now:,.2f}" if now else "open")
            console.print(f"#{t.id} [bold]{t.symbol.removesuffix('.NS')}[/bold] {t.strategy or ''}: "
                          f"{t.qty} @ {t.entry_price:,.2f} on {t.entry_date} = {_inr(t.capital_used)}; {state}")
            console.print(f"    stop {t.stop or '-'} | target {t.target or '-'} | net P&L {_money(pnl)}"
                          + (f" | {r:+.2f}R" if r is not None else "") + f" | {t.holding_days()} days")
    for t in j.open_trades():
        now = prices.get(t.symbol)
        if now and t.stop and now <= t.stop:
            console.print(f"[red]#{t.id} {t.symbol} is at/below its stop ({now:,.2f} <= {t.stop:,.2f}): exit.[/red]")
        elif now and t.target and now >= t.target:
            console.print(f"[green]#{t.id} {t.symbol} reached its target ({now:,.2f} >= {t.target:,.2f}).[/green]")


@app.command()
def stats(live: bool = typer.Option(True, "--live/--no-live", help="Value open positions at the latest price")):
    """Your results: P&L, win rate, average R, charges, capital used and free."""
    j = Journal.load()
    prices = _live_prices([t.symbol for t in j.open_trades()]) if live else {}
    s = j.stats(prices)
    rows = [
        ("Capital", _inr(s["capital"]) if s["capital"] else "not set (journal capital 500000)"),
        ("Closed trades", f"{s['closed_trades']} ({s['wins']} won, {s['losses']} lost"
         + (f", {s['win_rate']}% win rate)" if s["win_rate"] is not None else ")")),
        ("Realized P&L (after charges)", _money(s["realized_pnl"])),
        ("Charges paid", _inr(s["charges_paid"])),
        ("Average win / loss", f"{_money(s['avg_win'])} / {_money(s['avg_loss'])}"),
        ("Profit factor", str(s["profit_factor"] or "-")),
        ("Average R per trade", f"{s['avg_r']:+.2f}R" if s["avg_r"] is not None else "-"),
        ("Best / worst trade", f"{_money(s['best'])} / {_money(s['worst'])}"),
        ("Return on capital", f"{s['return_on_capital_pct']:+.2f}%" if s["return_on_capital_pct"] is not None else "-"),
        ("Open positions", f"{s['open_trades']}, capital deployed {_inr(s['capital_deployed'])}"),
        ("Unrealized P&L (open)", _money(s["unrealized_pnl"]) if s["unrealized_pnl"] is not None else "-"),
        ("Free capital", _inr(s["capital_free"]) if s["capital_free"] is not None else "-"),
        ("Total capital used (all trades)", _inr(s["total_capital_used"])),
    ]
    tb = Table(title="Journal stats", show_header=False)
    tb.add_column("", style="bold")
    tb.add_column("")
    for k, v in rows:
        tb.add_row(k, v)
    console.print(tb)
