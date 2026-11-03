---
name: trade-setups
description: >-
  The survival plan's trade list for NSE: the momentum core portfolio (BUY / HOLD
  / SELL / WAIT) plus the top 10 swing setups across large, mid and small caps
  and ETFs. Shows a table with name, ticker, cap (Large/Mid/Small/ETF), setup,
  grade, entry, stoploss, target, exit date, holding time, R:R and quantity,
  then a bull-vs-bear debate on the best swing ideas. Also answers "how long
  should I hold X". Free data, no API key. Use when the user types
  /trade-setups or /trade-setup, or asks for "setups", "what to buy",
  "top stocks", "monthly review", "how long to hold".
argument-hint: "[--capital 500000] [--core 80] [--risk 1]"
---

# trade-setups

The scanner owns every number. You present them, debate the swing ideas, and
answer questions. Never invent or change a price, level, quantity or holding time.

## Steps

1. Run (pass the user's arguments; defaults: capital 500000, core 80, risk 1):

   ```bash
   tradingagents setups --capital 500000 --core 80 --risk 1 --markdown
   ```

   (Use `python -m cli.main setups ...` from the repo root if `tradingagents` is not on
   PATH.) It prints two Markdown tables and saves
   `~/.tradingagents/scans/setups-<date>.md` and `.json`.

2. Show the output's header and notes first (Yahoo lagging, regime OFF), then **both
   tables exactly as printed**: 1. CORE, 2. SWING. Keep every column: Name, Ticker,
   Cap, Setup, Grade, Entry, Stoploss, Target, Exit by, Hold, R:R, Qty, Call.

3. **Debate** the top 3 swing ideas (read `~/.tradingagents/scans/setups-<date>.json`,
   `swing.ideas[].bull`, `bear`, `news`, `earnings_date`). For each one, give a
   **Bull** (2 points), a **Bear** (2 points, answering the Bull) and a **Judge** (TAKE /
   CAUTION / HALF / SKIP). The Judge can be stricter than the scanner, never looser.

4. Close with what to do now, numbered:
   1. Core: if the regime is ON and today is review day (`core.review_on`), BUY or
      SELL as listed at the next open. Otherwise hold, and check stops only.
      If the regime is OFF: the core stays in LIQUIDBEES; the list is on deck.
   2. Swing: place SL buy orders (trigger = entry, limit = max) before 09:15 IST, then
      a GTT OCO with the stop and the target after the fill.
   3. Log fills with `/trade-journal`.

## Holding-time questions ("how long should I hold X?")

Answer from the data, never from a guess:

- A **core momentum** stock: no fixed time. Hold while it ranks in the top 40 at each
  month-end review, and sell on a -15% stop. In testing, the median hold was **62 days**,
  and half of all holds lasted **31 to 124 days** (1 to 4 months). Its next check is
  `core.review_on`.
- A **swing setup**: give its `hold` and `exit_by` from the JSON, plus the strategy record
  `swing.records[<strategy>].all`: `median_days` (typical hold), `median_days_to_target`
  (how fast winners got there), `p75_days`. The hard limit is `hold_sessions` (20 for
  breakout, pivot and pullback; 10 for RSI(2)). Exit at the close on `exit_by` if neither
  the stop nor the target has hit.
- A **stock in the journal**: run `tradingagents journal list`, find its strategy and
  buy date, and apply the matching rule above (sessions held so far versus the limit).

## Rules

- The strategy is in `docs/STRATEGY.md` (rules 1-22). Quote the rule numbers when
  the user asks why.
- Never say "sure", "guaranteed" or "multibagger". Momentum returned +15.1% a year with
  a -20% worst drop in testing, versus the Nifty's +11.3% and -38%. That is history, not
  a promise.
- Not investment advice; the user places every order.
