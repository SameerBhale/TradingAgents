---
name: trade-journal
description: >-
  Trade journal for NSE trades: record buys (entry), sells (exit), stoploss and
  target hits, charges, P&L, R-multiple, capital used and free, and how long each
  trade has been held versus its plan. Use when the user types /trade-journal, or
  says "I bought", "I sold", "stoploss hit", "target hit", "log my trade",
  "my P&L", "my positions", "how much capital used", "how long have I held".
argument-hint: "[add | close | list | stats] ..."
---

# trade-journal

Run the journal commands for the user and show the results. Every number comes
from the command output.

## Commands

```bash
tradingagents journal capital 500000                       # once: total trading capital
tradingagents journal add DIVISLAB --price 10010 --qty 10 --stop 9512.3 --target 10975.38 --strategy breakout
tradingagents journal add --from-scan 1 --price 10010      # swing idea #1 of the latest scan (fills stop/target/qty)
tradingagents journal add CUPID --price 340.5 --qty 58 --stop 289.43 --strategy momentum   # core buy
tradingagents journal close 3 --price 10975.38             # sold trade #3 (target hit)
tradingagents journal close 3 --price 9512.3               # sold at the stoploss
tradingagents journal close 3 --price 10500 --qty 5        # partial sell
tradingagents journal close 3 --price 10500 --charges 42.7 # exact charges from the contract note
tradingagents journal list --all                           # positions, live price, P&L, R, days held
tradingagents journal stats                                # P&L, win rate, avg R, charges, capital used/free
tradingagents journal remove 3                             # delete a wrong entry
```

Add `--date YYYY-MM-DD` when the fill was not today.

## How to handle requests

1. **"I bought X at P"**: ask only for what is missing (quantity, and whether it was a
   core momentum buy or a swing setup). If it matches an idea in the latest
   `/trade-setups`, use `--from-scan <#>` (swing) or `--strategy momentum --stop <15%
   below>` (core). Then run `journal list` and show the row.
2. **"I sold X" / "stoploss hit" / "target hit"**: find the open trade's id with
   `journal list`, run `journal close <id> --price <fill>`, and report net P&L after
   charges, the R-multiple, and the days held.
3. **"My P&L" / "how am I doing"**: run `journal stats`. Compare it with the plan in
   `docs/STRATEGY.md`: about 45% winners on swing trades, losers kept near -1R, and core
   stops at -15%. Point out any rule being broken (losses bigger than -1.2R, holding past
   the exit-by date, too much capital in one stock).
4. **"How long should I hold X?"**: from `journal list`, take its strategy and days held.
   - Momentum core: hold while it ranks in the top 40 at each month-end review, and sell
     on -15%. The typical hold is 1-4 months (median 62 days in testing).
   - Swing: breakout and pullback exit by 20 sessions (breakouts typically last about 13,
     and winners reach target in about 8); RSI(2) exits by 10 sessions, usually 2-4. Say
     how many sessions remain.
5. **Alerts**: `journal list` flags open trades at or below their stop, or at or above
   their target. Tell the user plainly what to do (rule 14 / rule 7 in docs/STRATEGY.md).

## Rules

- Never make up a fill price or quantity: ask for it.
- Charges are estimated (about 0.23% plus Rs 15.93 per sell) unless `--charges` is
  given. Say so when reporting P&L.
- The journal file is `~/.tradingagents/journal.json` (set
  `TRADINGAGENTS_JOURNAL_PATH` to move it).
