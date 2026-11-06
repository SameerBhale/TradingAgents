---
name: trade-setups
description: >-
  NSE trade list in two short tables: the top 5 swing setups (short term; stop
  5-10%, target 10-20% for half, the rest trailed on the 20 EMA, no time limit;
  filtered by NSE delivery-% money flow) from six strategies (52-week breakout,
  Minervini VCP, Qullamaggie flag and episodic pivot, Oliver Kell EMA crossback,
  breakout + retest), micro caps trading Rs 25 crore+ a day included with a caution, and the top 3 value buys (medium/long term, 3-12 months;
  quality growth at a fair price in a stage-2 uptrend, with concall headlines).
  Every row has name, ticker, cap, entry, stoploss, target, exit, holding time and
  a plain GOOD / OK / AVOID verdict. No money or quantity. Free data, no API key.
  Use for /trade-setups, /trade-setup, "setups", "what to buy", "swing setups",
  "value buy", "how long to hold".
argument-hint: "[--top 5] [--value 3] [--with-core] [--no-micro] [--refresh]"
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

Data: prices from Upstox (Yahoo as fallback, NSE bhavcopy fills and corrects the latest
close); fundamentals from NSE XBRL filings + Yahoo; promoter holding and pledge from NSE.
The header's "Prices:" line says how many came from each. Stocks with a 40%+ one-day jump
(a demerger or unadjusted split) in the last year are skipped by the swing scan.

## 2. Show

The header line and notes, then the tables exactly as printed: **SWING** (short term),
**MONEY FLOW** (watch list: stage-2 leaders where delivery % is rising, plus today's
institutional bulk/block deals; not buy signals) and **VALUE** (medium to long term). A
value pick already on the saved multibagger list is tagged [MULTIBAGGER CANDIDATE]; the
list itself is shown only by /multibagger (do not run it here). Do not add capital, money, quantity or sizing
columns, and do not ask how much the user wants to invest.

Verdicts, in plain words, best first (the `tier` field; `grade` stays GOOD/OK/AVOID):
- **BEST**: GOOD plus all three extra checks: the setup's success rate is 40%+ over 12
  months, volume is building up (up-day volume 1.2x+ down-day volume over 50 days,
  O'Neil's accumulation test) and the stock is a leader (RS rank 80+). Full size.
- **BETTER**: GOOD plus two of those checks. Full size.
- **GOOD**: the setup is making money lately, funds are taking delivery (money flow IN),
  no results inside the hold, the news is clean. Full size.
- **OK**: one risk to respect (money flow flat, results inside the typical hold, a mixed
  or too-thin recent record, an institution selling, down-day volume heavier, or the
  Nifty below its 200-DMA); half size.
- **AVOID**: the setup is losing money lately, or the news is bad.

Money flow (docs/STRATEGY.md): delivery % 20-day average / 100-day average. IN (>= 1.05)
is needed for GOOD; flat caps it at OK; OUT is dropped by the scanner. Explain it as
"funds are taking delivery" in plain words.

**Micro caps** (below the top 500, scanned only when they trade Rs 25 crore+ a day) get
the same scale, judged on the setup's record on micro caps alone, and the verdict says
"(MICRO CAP)" with a caution: thin float, operator and circuit risk, the stop can gap;
half the size you would use on a bigger stock. Always repeat that caution in plain words.
`--no-micro` leaves them out.

Breakout + retest setups (`retest` for horizontal levels, `ct` for trendlines): a fresh
breakout on 1.5x volume after 20+ sessions under the level, a move 4%+ above it, a
lighter-volume pullback that tests the level and holds it, then a bounce over the prior
day's high. Old resistance turned support. The level is one of: all-time high, 52-week
high, flag and pole, ascending triangle, cup and handle / base rim, or a CT (falling
trendline); the Bull line names which.

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
   the fill, a GTT OCO with the stoploss and the target for HALF the shares. When the
   target fills, move the stop on the rest to the buy price and sell it on a close below
   the 20-day EMA. No time limit. Skip anything marked AVOID.
2. Value: a limit buy at or below the price shown, stoploss and target as a GTT OCO;
   review on every quarterly result.
3. Offer `stock-report` (a full PDF) for the top value buy; run it only on a yes.

## 5. Holding time

- **Swing**: the row's Hold (median sessions from the strategy's own trades). There is no
  time limit: the 20-day EMA decides when the second half is sold.
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

- Never say "sure" or "guaranteed", and never call a stock a multibagger: only "multibagger
  candidate" (the list's label), and say most candidates will not become one. Champion returns (Kell +941%,
  Minervini +155%) came from concentration, leverage and discretion; the mechanical
  versions here earn a small edge per trade (docs/STRATEGY.md).
- Not investment advice; the user places every order.
