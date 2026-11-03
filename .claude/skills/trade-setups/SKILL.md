---
name: trade-setups
description: >-
  NSE trade list in two short tables: the top 5 swing setups (short term; stop
  5-10%, target 10-20%) from five strategies taken from champion traders
  (52-week breakout, Minervini VCP, Qullamaggie flag and episodic pivot, Oliver
  Kell EMA crossback), and the top 3 value buys (medium/long term, 3-12 months;
  quality growth at a fair price in a stage-2 uptrend, with concall headlines).
  Every row has name, ticker, cap, entry, stoploss, target, exit, holding time and
  a plain GOOD / OK / AVOID verdict. No money or quantity. Free data, no API key.
  Use for /trade-setups, /trade-setup, "setups", "what to buy", "swing setups",
  "value buy", "how long to hold".
argument-hint: "[--top 5] [--value 3] [--with-core] [--refresh]"
---

# trade-setups

The scanner owns every number. You present them, add a short Bull / Bear / Judge on
the best ideas, and answer questions. Never invent or change a price, level or date.

## 1. Run

```bash
tradingagents setups --markdown
```

(`python -m cli.main setups --markdown` if `tradingagents` is not on PATH.) Defaults:
top 5 swing, top 3 value. Pass the user's arguments. `--with-core` adds the momentum
core portfolio only when the user asks for it. Missing Yahoo sessions are filled from
NSE's bhavcopy (published around 18:00 IST); if the header date is older than the
last session, say so and re-run with `--refresh` after 18:00.

## 2. Show

The header line and notes, then both tables exactly as printed: **SWING** (short term)
and **VALUE** (medium to long term). Do not add capital, money, quantity or sizing
columns, and do not ask how much the user wants to invest.

Verdicts, in plain words (they replace the old grades and the auditor):
- **GOOD**: this setup is making money across NSE lately; take it.
- **OK**: one risk to respect (results inside the hold, a mixed recent record, or the
  Nifty below its 200-DMA); half size.
- **AVOID**: the setup is losing money across NSE lately, or the news is bad.

## 3. Bull / Bear / Judge (short)

For the top 3 swing ideas and the top value buy, read the JSON
(`~/.tradingagents/scans/setups-<date>.json`: `swing.ideas[]` `bull`, `bear`, `news`,
`earnings_date`; `value.picks[]` `why`, `risks`, `concall`) and write one line each:

- **Bull**: the best reason to take it.
- **Bear**: the best reason not to, answering the Bull.
- **Judge**: TAKE / HALF / SKIP, never looser than the verdict. Say plainly whether
  the setup is good or bad *today* and why. For value, check that the concall
  headlines support the growth (a one-off profit jump is not growth).

## 4. Close: what to do now

1. Swing: a stop-limit buy (trigger = "buy above", limit = max) before 09:15 IST; after
   the fill, a GTT OCO with the stoploss and target. Breakouts: selling on a close below
   the 20-day EMA tested better than the fixed target (see docs/STRATEGY.md); the
   target stays the default. Skip anything marked AVOID.
2. Value: a limit buy at or below the price shown, stoploss and target as a GTT OCO;
   review on every quarterly result.
3. Offer `stock-report` (a full PDF) for the top value buy; run it only on a yes.

## 5. Holding time

- **Swing**: the row's Hold (median sessions from the strategy's own trades) and its
  sell-by date; the limit is 20 sessions.
- **Value**: 3-12 months, reviewed on each quarterly result. Not backtested; say so.
- **A journal position**: `tradingagents journal list`, then the matching rule.

## 6. Live market questions

When the user asks for live updates ("what's happening now", "did PAYTM trigger",
"live", "update"), run:

```bash
tradingagents alerts status          # add --gaps for today's gap-ups across NSE
```

Show the table, then one line per pick that changed: TRIGGERED (buy is in), RAN PAST MAX
(do not chase), STOPLOSS / TARGET HIT, value IN BUY ZONE. Never re-run the full scan
during market hours to make new swing setups: setups come from a settled close.

## 7. Alerts (Gmail)

If the user asks for alerts: `tradingagents alerts test`, `alerts digest` (mail the
list) and `alerts watch --gaps` (live buy triggers, do-not-chase, value buy zone,
stop/target hits, gap-ups during market hours). Setup is in
`tradingagents/alerts.py`; `scripts/register_alerts.ps1` schedules them on Windows.

## 8. Feedback

When the user says a call was good or bad:

```bash
tradingagents calls feedback DIVISLAB "results gap hit the stop" --bad
tradingagents calls review     # how past calls played out, by verdict and strategy
```

Suggest a rule change only when a group has 20 or more closed calls.

## Rules

- Never say "sure", "guaranteed" or "multibagger". Champion returns (Kell +941%,
  Minervini +155%) came from concentration, leverage and discretion; the mechanical
  versions here earn a small edge per trade (docs/STRATEGY.md).
- Not investment advice; the user places every order.
