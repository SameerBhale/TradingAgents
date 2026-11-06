---
name: trade-setups
description: >-
  NSE trade list: top 5 swing setups (stop 5-10%, target 10-20% for half, rest trailed on
  the 20 EMA, no time limit) from seven strategies (52-week breakout, Minervini VCP,
  Qullamaggie flag and episodic pivot, Kell EMA crossback, breakout + retest, CT + retest)
  and top 3 value buys (3-12 months), with BEST / BETTER / GOOD / OK / AVOID verdicts; liquid
  micro caps included with a caution. No money or quantity. Use for /trade-setups,
  /trade-setup, "setups", "what to buy", "swing setups", "value buy", "how long to hold".
argument-hint: "[--top 5] [--value 3] [--with-core] [--no-micro] [--refresh]"
---

# trade-setups

The scanner owns every number: never invent or change a price, level or date.

## Run

```bash
tradingagents setups --brief
```

Pass the user's arguments. `--with-core` only when asked. The multibagger list is NOT part
of this (it is /multibagger). If the header date is older than the last session, say so
and re-run with `--refresh` after 18:00 IST. Do not open the JSON or docs unless the user
asks "why" about a pick (`~/.tradingagents/scans/setups-<date>.json`, docs/STRATEGY.md).

## Reply

1. The output as printed (tables, Bull / Bear lines). No money, quantity or sizing columns;
   never ask how much the user will invest.
2. One **Judge** line each for the top 3 swing ideas and the top value buy: TAKE / HALF /
   SKIP, never looser than the verdict, saying plainly why it is good or bad *today*.
   For a MICRO row, repeat the caution in plain words (thin float, operator and circuit
   risk, the stop can gap; half size). For value, a one-off profit jump is not growth.
3. What to do: swing = stop-limit buy (trigger = buy above, limit = max) before 09:15;
   after the fill a GTT OCO with the stop and the target for HALF; when the target fills,
   stop to cost and sell the rest on a close below the 20-day EMA. Value = limit buy at or
   below the price, stop and target as a GTT OCO, review each quarterly result. Skip AVOID.
   Offer `stock-report` for the top value buy (run it only on a yes).

Verdicts: BEST (GOOD + success rate 40%+, volume building up, RS 80+), BETTER (two of
those), GOOD (setup making money lately, money flow IN, no results in the hold, clean
news), OK (one risk; half size), AVOID (setup losing lately or bad news). Money flow =
delivery % 20-day / 100-day average: say "funds are taking delivery".

## Other requests

- Live ("did X trigger", "update"): `tradingagents alerts status [--gaps]`; one line per
  change (TRIGGERED, RAN PAST MAX = do not chase, STOP / TARGET HIT, value IN BUY ZONE).
  Never re-run the scan during market hours.
- Alerts: `tradingagents alerts test | digest | watch --gaps` (scripts/register_alerts.ps1).
- Feedback: `tradingagents calls feedback SYMBOL "why" --good|--bad`, `calls review`;
  suggest a rule change only when a group has 20+ closed calls.
- A held position: `tradingagents journal list`, then its rule (swing: the 20-EMA exit;
  value: 3-12 months, reviewed each quarter, not backtested).

## Rules

Never say "sure", "guaranteed" or call a stock a multibagger. The edge per trade is small
(docs/STRATEGY.md). Not investment advice; the user places every order.
