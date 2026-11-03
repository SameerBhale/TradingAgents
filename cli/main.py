import sys
from enum import StrEnum
from typing import Annotated

import typer
from rich.markup import escape

from cli.display import console
from cli.models import AnalystType, AssetType
from cli.prompts import filter_analysts_for_asset_type, parse_analysts
from cli.run import run_analysis
from tradingagents.backtest import iter_grid, run_backtest, summarize
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.openai_client import SIGNED_IN_PROVIDERS
from tradingagents.portfolio import load_portfolio

# prompt_toolkit's win32 output module is importable only on Windows (it asserts
# the platform at import time), so gate on the platform rather than catching the
# failure — that way a genuinely broken prompt_toolkit on Windows still surfaces
# instead of silently disabling the handler below. Off Windows this stays an
# empty tuple, which `except` accepts and never matches (#1138).
if sys.platform == "win32":  # pragma: no cover - platform dependent
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError

    _NO_CONSOLE_ERRORS: tuple[type[BaseException], ...] = (NoConsoleScreenBufferError,)
else:
    _NO_CONSOLE_ERRORS = ()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
)


@app.callback(invoke_without_command=True)
def analyze(
    ctx: typer.Context,
    checkpoint: bool | None = typer.Option(
        None,
        "--checkpoint/--no-checkpoint",
        help="Enable/disable checkpoint-resume (save state after each node so a "
        "crashed run can resume). Omit to honor TRADINGAGENTS_CHECKPOINT_ENABLED.",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="Delete all saved checkpoints before running (force fresh start).",
    ),
    portfolio: str = typer.Option(
        None,
        "--portfolio",
        help="JSON file with current holdings and cash, so the trader, risk and "
        "portfolio agents size against your actual position.",
    ),
    ticker: str = typer.Option(
        None, "--ticker", help="Ticker to analyze, e.g. RELIANCE, TCS.NS, RELIANCE.BO or NIFTY; skips the prompt"
    ),
    date: str = typer.Option(None, "--date", help="Analysis date, YYYY-MM-DD; skips the prompt"),
    analysts: str = typer.Option(
        None, "--analysts", help="Comma-separated analysts, e.g. market,news; skips the prompt"
    ),
    save: bool | None = typer.Option(
        None, "--save/--no-save", help="Save the report under results_dir without asking"
    ),
    show: bool | None = typer.Option(
        None, "--show/--no-show", help="Show the full report at the end without asking"
    ),
    html: bool | None = typer.Option(
        None, "--html/--no-html",
        help="Save the report as one HTML page too, complete_report.html, without asking (default: yes)",
    ),
):
    """Run an analysis. This is what a bare `tradingagents` does.

    Flags answer their questions; with provider, models, depth and language also
    set through TRADINGAGENTS_* variables, the run asks nothing.
    """
    if ctx.invoked_subcommand is not None:
        return
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    portfolio_context = None
    if portfolio:
        try:
            portfolio_context = load_portfolio(portfolio)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None

    try:
        flags = {"ticker": ticker, "date": date, "analysts": analysts, "save": save, "show": show, "html": html}
        run_analysis(checkpoint=checkpoint, portfolio=portfolio_context, flags=flags)
    except _NO_CONSOLE_ERRORS:
        # A terminal with no console buffer cannot host the interactive prompts.
        # Emit one actionable line on stderr instead of a prompt_toolkit
        # traceback; plain text, since rich may not render here either (#1138).
        typer.echo(
            "Error: no Windows console available. The interactive CLI needs a real "
            "console buffer — run it from Windows Terminal, PowerShell, or cmd.exe "
            "rather than a piped or embedded terminal.",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def backtest(
    tickers: str = typer.Argument(..., help="Comma-separated tickers, e.g. NVDA,AAPL"),
    start: str = typer.Option(..., "--start", help="First analysis date, YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="Last analysis date, YYYY-MM-DD"),
    every: int = typer.Option(7, "--every", help="Days between analysis dates"),
    analysts: str = typer.Option(
        None, "--analysts", help="Comma-separated analysts to run: market, sentiment, news, fundamentals; omit for all the asset type allows"
    ),
    asset_type: str = typer.Option("stock", "--asset-type", help="stock or crypto"),
    portfolio: str = typer.Option(
        None, "--portfolio", help="JSON file with holdings and cash, held constant across the grid"
    ),
    run_id: str = typer.Option(
        None, "--run-id", help="Continue an earlier sweep: its cells are skipped and its log reused"
    ),
):
    """Score past decisions over a grid of tickers and dates."""

    try:
        dates = iter_grid(start, end, every)
        book = load_portfolio(portfolio) if portfolio else None
        kind = AssetType(asset_type.strip().lower())
        # The analysts are named and checked as for an analysis; without a
        # choice, every analyst the asset type allows runs.
        chosen = (parse_analysts(analysts, kind) if analysts
                  else filter_analysts_for_asset_type(list(AnalystType), kind))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    names = [t.strip() for t in tickers.split(",") if t.strip()]
    if not names:
        console.print("[red]No ticker to analyze; pass them comma-separated, e.g. NVDA,AAPL[/red]")
        raise typer.Exit(code=1)

    def show_progress(done, total, ticker, date):
        console.print(f"[dim][{done}/{total}] {ticker} {date}[/dim]")

    kwargs = {"asset_type": kind.value, "portfolio": book, "run_id": run_id, "progress": show_progress,
              "selected_analysts": [a.value for a in chosen]}

    try:
        result = run_backtest(names, dates, DEFAULT_CONFIG, **kwargs)
    except Exception as exc:  # a missing key or an unknown analyst is a setup error
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(summarize(result).render())
    console.print(f"\nRan {result.cells_run} cells, skipped {result.skipped}. Log: {result.log_path}")
    console.print(f"Continue or settle this sweep: --run-id {result.run_id}")
    for ticker, date, reason in result.failures:
        console.print(f"[yellow]failed:[/yellow] {ticker} {date}: {reason}")
    for ticker, reason in result.settlement_failures:
        console.print(f"[yellow]unsettled:[/yellow] {ticker}: {reason}")


@app.command()
def breakout(
    capital: float = typer.Option(500_000, "--capital", help="Your trading capital in INR, for position sizes"),
    risk: float = typer.Option(1.0, "--risk", help="Percent of capital to risk per trade (loss at the stoploss)"),
    top: int = typer.Option(5, "--top", help="Most breakout trades to show"),
    date: str = typer.Option(None, "--date", help="Scan as of an earlier session, YYYY-MM-DD (to review past signals)"),
    refresh: bool = typer.Option(False, "--refresh", help="Download fresh data even if today's is cached"),
    as_json: bool = typer.Option(False, "--json", help="Print the scan as JSON"),
    deep: int = typer.Option(
        0, "--deep",
        help="Also run the full multi-agent debate (Claude Fable 5.1) on the top N picks; needs ANTHROPIC_API_KEY",
    ),
):
    """Scan every NSE stock for breakouts: entry, stoploss, target, R:R and holding period.

    Free data, no API key. Run it after 16:00 IST (or before 09:00) and place the
    orders for the next session.
    """
    from cli.breakout import breakout_command

    try:
        code = breakout_command(capital, risk, top, date, refresh, as_json, deep)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    raise typer.Exit(code=code)


@app.command()
def scan(
    capital: float = typer.Option(500_000, "--capital", help="Your trading capital in INR, for position sizes"),
    risk: float = typer.Option(1.0, "--risk", help="Percent of capital to risk per trade"),
    top: int = typer.Option(10, "--top", help="How many ideas to list"),
    date: str = typer.Option(None, "--date", help="Ideas as of an earlier close, YYYY-MM-DD"),
    refresh: bool = typer.Option(False, "--refresh", help="Download fresh data even if today's is cached"),
    as_json: bool = typer.Option(False, "--json", help="Print the ideas as JSON"),
    no_news: bool = typer.Option(False, "--no-news", help="Skip the headline check (faster)"),
):
    """Top NSE trade ideas from four chart setups, graded, with news and a bull-vs-bear case.

    Every idea has entry, stoploss, target, reward:risk, exit date, size and its cap
    class. Free data, no API key. Run after 16:30 IST.
    """
    from cli.scan import scan_command

    try:
        code = scan_command(capital, risk, top, date, refresh, as_json, no_news)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    raise typer.Exit(code=code)


@app.command()
def setups(
    capital: float = typer.Option(500_000, "--capital", help="Your total trading capital in INR"),
    core: float = typer.Option(80.0, "--core", help="Percent of capital for the momentum core (rest: swing)"),
    risk: float = typer.Option(1.0, "--risk", help="Percent of the swing capital risked per swing trade"),
    top: int = typer.Option(10, "--top", help="How many swing setups to list"),
    refresh: bool = typer.Option(False, "--refresh", help="Download fresh data even if today's is cached"),
    as_json: bool = typer.Option(False, "--json", help="Print as JSON"),
    markdown: bool = typer.Option(False, "--markdown", help="Print the tables as Markdown"),
    no_news: bool = typer.Option(False, "--no-news", help="Skip the headline check (faster)"),
):
    """The survival plan: momentum core portfolio + top 10 swing setups (stocks and ETFs).

    Name, ticker, cap class, entry, stoploss, target, exit, holding time and quantity
    for each. Free data. Run after 16:30 IST; review the core on the last trading day
    of each month.
    """
    from cli.setups import setups_command

    try:
        code = setups_command(capital, core, risk, top, refresh, as_json, markdown, no_news)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    raise typer.Exit(code=code)


def _register_journal():
    from cli.journal import app as journal_app

    app.add_typer(journal_app, name="journal")


_register_journal()


@app.command()
def headlines(
    ticker: str = typer.Argument(..., help="Stock, e.g. RELIANCE or TCS.NS"),
    days: int = typer.Option(7, "--days", help="Look back this many days"),
):
    """Recent news headlines for a stock: Google News (India), then Yahoo Finance. Free."""
    from datetime import date as _date, timedelta

    from cli.prompts import parse_ticker
    from tradingagents.dataflows import india
    from tradingagents.dataflows.date_window import get_current_date
    from tradingagents.dataflows.india import IST
    from tradingagents.dataflows.vendors import google_news

    try:
        symbol = parse_ticker(ticker)
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    sec = india.lookup(symbol) if symbol.endswith(".NS") else None
    query = f'"{sec.name.replace(" Limited", "").replace(" Ltd", "")}"' if sec else symbol.split(".")[0]
    try:
        items = google_news.headlines(f"{query} share OR stock", days=days)
    except Exception:  # fall through to Yahoo
        items = []
    if items:
        print(f"Headlines for {symbol} ({sec.name if sec else symbol}), last {days} days, Google News India:")
        for it in items:
            stamp = it["published"].astimezone(IST).strftime("%d %b %H:%M IST")
            print(f"- [{stamp}] {it['title']}")
        return
    from tradingagents.dataflows.vendors.yahoo.news import get_news_yfinance

    end = get_current_date()
    start = (_date.fromisoformat(end) - timedelta(days=days)).isoformat()
    try:
        print(get_news_yfinance(symbol, start, end))
    except Exception as exc:  # the vendor reports an outage as an exception
        console.print(f"[yellow]No headlines found for {symbol}: {escape(str(exc))}[/yellow]")
        raise typer.Exit(code=1) from None


@app.command("market-status")
def market_status_command():
    """Where the NSE/BSE trading day stands now, on the IST clock, and upcoming holidays."""
    from datetime import date

    from tradingagents.dataflows import india

    status = india.market_status()
    console.print(status.describe())
    upcoming = [(d, n) for d, n in india.holidays().items() if date.fromisoformat(d) >= status.now.date()]
    if upcoming:
        console.print("\nUpcoming NSE/BSE trading holidays:")
        for day, name in upcoming[:8]:
            console.print(f"  {day} ({date.fromisoformat(day):%a})  {escape(name)}")


@app.command()
def symbols(
    query: str = typer.Argument(None, help="Part of an NSE symbol or company name, e.g. TATA or bank"),
    limit: int = typer.Option(25, "--limit", help="Most matches to list"),
    segment: str = typer.Option(None, "--segment", help="Only EQUITY, SME or ETF"),
):
    """Search the bundled universe of every NSE-listed equity, SME stock and ETF."""
    from tradingagents.dataflows import india

    universe = india.nse_universe()
    if not query:
        counts: dict[str, int] = {}
        for sec in universe.values():
            counts[sec.segment] = counts.get(sec.segment, 0) + 1
        console.print(f"{len(universe)} NSE securities: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
        console.print("Search with: tradingagents symbols <text>")
        return
    matches = india.search(query, limit=10_000)
    if segment:
        matches = [m for m in matches if m.segment == segment.strip().upper()]
    if not matches:
        console.print(f"[yellow]No NSE security matches {escape(query)!r}.[/yellow]")
        raise typer.Exit(code=1)
    for sec in matches[:limit]:
        console.print(f"{sec.yahoo:<20} {sec.segment:<7} {sec.series:<3} {escape(sec.name)}")
    if len(matches) > limit:
        console.print(f"[dim]... {len(matches) - limit} more; raise --limit to see them[/dim]")


# The plans `login` and `logout` take: the providers signed in to, not keyed.
Plan = StrEnum("Plan", {name: name for name in SIGNED_IN_PROVIDERS})


@app.command()
def login(plan: Annotated[Plan, typer.Argument(help="The plan to sign in with")]):
    """Sign in with your ChatGPT Plus or Pro plan, for the chatgpt provider."""
    from tradingagents.llm_clients import chatgpt_auth

    try:
        # One unwrapped line, so the sign-in address can be copied whole.
        email = chatgpt_auth.sign_in(
            say=lambda line: console.print(line, soft_wrap=True, markup=False, highlight=False))
    except chatgpt_auth.ChatGPTAuthError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]Signed in to ChatGPT as {escape(email)}.[/green]")


@app.command()
def logout(plan: Annotated[Plan, typer.Argument(help="The plan to sign out of")]):
    """Sign out of your ChatGPT plan: revoke this machine's access and forget it."""
    from tradingagents.llm_clients import chatgpt_auth

    outcome = chatgpt_auth.sign_out()
    if outcome == "revoked":
        console.print("Signed out of ChatGPT.")
    elif outcome == "forgotten":
        console.print("[yellow]Signed out here, but OpenAI could not be reached to revoke the sign-in; "
                      "it stays valid at OpenAI until it expires.[/yellow]")
    else:
        console.print("Not signed in to ChatGPT.")


if __name__ == "__main__":
    app()
