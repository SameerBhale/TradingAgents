---
name: trade-setups
description: >-
  The survival plan's trade list for NSE: the momentum core portfolio, the top 10
  swing setups (large, mid and small caps and ETFs; stop 5-10%, target 10-20%),
  and the best value buys (fundamentals plus chart plus concall headlines). Every
  row has name, ticker, cap, grade with its meaning, entry, stoploss, target, exit,
  holding time, quantity and an auditor's check. Then a Bull / Bear / Judge debate
  and an Auditor agent who says whether each call is correct. It sizes positions
  when the user gives an amount, and records feedback. Free data, no API key. Use
  for /trade-setups, /trade-setup, "setups", "what to buy", "value buy",
  "how long to hold", "invest Rs X in swing".
argument-hint: "[--capital 500000] [--core 80] [--risk 1] [--mode balanced]"
---

# trade-setups

The scanner owns every number. You present them, debate them, audit them and
answer questions. Never invent or change a price, level, quantity or holding time.

## 1. Run

```bash
tradingagents setups --capital 500000 --core 80 --risk 1 --mode balanced --markdown
```

Pass the user's arguments. `--mode` sets how the core behaves while the Nifty is below
its 200-DMA: `balanced` (default, half size), `safe` (wait in LIQUIDBEES) or
`aggressive` (full size). Use `python -m cli.main setups ...` if `tradingagents` is not
on PATH. The command saves `~/.tradingagents/scans/setups-<date>.json` and logs every
call for later review.

## 2. Show

The header and notes first (Yahoo lagging, regime). Then all three tables exactly as
printed: 1. CORE, 2. SWING, 3. VALUE. Every grade cell carries its meaning; keep it.
- **A**: 52-week breakout, the tested edge in rising and weak markets; full size.
- **B**: the strategy is profitable across NSE over the last 6 and 12 months; full size.
- **C**: the strategy is losing money lately; half size or paper trade.

Auditor statuses: **CORRECT** (no rule broken), **QUESTIONABLE** (check the noted
risk), **WRONG** (breaks a rule: do not take it).

## 3. Debate, then audit

For the top 3 swing ideas and the top 2 value buys, read the JSON (`swing.ideas[]`:
`bull`, `bear`, `news`, `earnings_date`, `audit`; `value.picks[]`: fundamentals,
`concall`, `why`, `risks`, `audit`):

- **Bull** (2 points) and **Bear** (2 points, answering the Bull's best one).
- **Judge**: TAKE / CAUTION / HALF / SKIP. It can be stricter than the scanner, never looser.
- **Auditor agent**: a separate check of the call itself. Is the call correct?
  Answer **AGREE** or **DISAGREE** with the Judge, in one line, after checking: the stop
  is 5-10% and the target 10-20% (swing); the grade matches the call (no TAKE on C);
  results are not inside the hold; the news does not contradict the call; for value,
  the concall headlines support the growth numbers (a one-off profit jump is not
  growth); and the trade fits the market regime. Name the rule from `docs/STRATEGY.md`
  that it breaks, if any.

For a deeper look at the best value buy, offer the `stock-report` skill (a full equity
research report as a PDF), and run it only if the user says yes.

## 4. Close: what to do now

1. Core: BUY / HOLD / SELL as listed at the next open on review day (`core.review_on`) or
   when you first start. Otherwise hold, and check the -15% stops.
2. Swing: an SL buy order (trigger = entry, limit = max) before 09:15 IST; after the fill,
   a GTT OCO with the stop and the target. Skip anything the Auditor marked WRONG.
3. Value: a limit buy at or below the entry shown, with the stop and target as a GTT OCO;
   review on the next quarterly result.
4. Then ask: "How much do you want to invest, and in which list (swing, core or value)?"

## 5. When the user gives an amount

"Rs 1,00,000 for swing" (or core, or value, optionally "only 1, 3 and 5"):

```bash
tradingagents allocate --amount 100000 --for swing --markdown            # every call except WRONG
tradingagents allocate --amount 100000 --for swing --picks 1,3,5 --markdown
```

Show the table: quantity, capital, max loss per stock, cash left, and the loss if every
stop hits. Remind them to log fills with `/trade-journal`.

## 6. Holding-time questions

- **Core momentum**: hold while it ranks in the top 40 at each month-end review, and sell
  on the -15% stop. The median hold in testing was 62 days (half lasted 31-124 days).
- **Swing**: give the setup's `hold` and `exit_by`, plus `swing.records[<strategy>].all`
  (`median_days`, `median_days_to_target`, `p75_days`). The limit is 20 sessions (10 for RSI(2)).
- **Value**: 1-3 months, reviewed on each quarterly result. This hold is not backtested; say so.
- **A position in the journal**: `tradingagents journal list`, then apply the matching rule.

## 7. Feedback: how the bot gets better

When the user says a call was good or bad, or why:

```bash
tradingagents calls feedback DIVISLAB "results gap hit the stop" --bad
tradingagents calls review                    # how past calls played out, by grade / strategy / auditor
```

Run `calls review` when asked "how good are your calls?". Report the hit rate and the
average return by grade and auditor status, and suggest a rule change only when a group
has 20 or more closed calls.

## Rules

- Never say "sure", "guaranteed" or "multibagger". In testing, the momentum core
  returned +14-15% a year with a ~-20% worst drop (Nifty: +11.3% / -38%). The value
  screen is not backtested. Say so when it matters.
- Not investment advice; the user places every order.
