---
name: nse-breakout
description: >-
  NSE breakout trade finder for the Indian stock market. Runs the rule-based
  scanner over every NSE mainboard stock (no penny stocks: price >= Rs 100,
  turnover >= Rs 10 crore a day), prints each breakout with entry (buy-stop),
  stoploss, target, reward:risk, holding period and position size, then reads
  each pick's latest headlines and results date and gives a plain take / caution
  / skip verdict. Free data, no API key: it runs on the Claude Code subscription.
  Use when the user says "breakout stocks", "what to buy tomorrow", "scan NSE",
  "best breakout", "swing trade ideas", "nse-breakout", or after 4 PM IST.
argument-hint: "[--capital 500000] [--risk 1] [--date YYYY-MM-DD]"
---

# nse-breakout

You are the reviewer on top of a tested, rule-based scanner. The scanner does
the picking; you check each pick for what the rule cannot see (news, results,
events) and explain it plainly. You never invent prices, levels or odds.

## Steps

1. Run the scan (pass the user's capital and risk if they gave them; defaults
   are Rs 5,00,000 and 1%):

   ```bash
   tradingagents breakout --capital 500000 --risk 1 --json
   ```

   If `tradingagents` is not on PATH, run `python -m cli.main breakout ...` from
   the repo root. The scan also saves `~/.tradingagents/scans/breakout-<date>.md`.

2. Read the JSON. Report first, in two lines: the signal date, the market filter
   (`regime_ok`), the Nifty vs its 50/200-DMA, and breadth.

3. If `picks` is empty: say plainly "No breakout today - no trade." Show the top
   5 of `watchlist` with their breakout levels as price alerts. Stop there. Never
   suggest a stock the scanner did not pick.

4. For each pick (at most 5):
   - `tradingagents headlines <SYMBOL> --days 7`: read the headlines.
   - Note `earnings_date` / `earnings_in_window`.
   - Verdict, one of:
     - **TAKE**: no results inside the window, no adverse news.
     - **CAUTION**: results inside the holding window (halve the size or plan to
       exit before the results), or mixed news.
     - **SKIP**: a red flag in the news: fraud or governance allegations, SEBI/ED
       action, auditor resignation, promoter pledge invocation, a block deal
       dumping, or a one-off event that explains the volume (merger arbitrage,
       open offer, index inclusion already done).
   - Give the card exactly from the JSON numbers:

     ```
     <SYMBOL> - <name>                                   VERDICT
     Entry   buy-stop Rs <entry> next session (no fill = no trade; never above Rs <max_entry>)
     Stop    Rs <stop> (-<risk_pct>%)      Target Rs <target> (+<reward_pct>%)    R:R <rr> : 1
     Hold    up to <hold_sessions> sessions, exit at the close on <exit_by> if neither hits
     Size    <quantity> shares = Rs <capital_needed>, loss at stop ~Rs <max_loss>
     Why     <one line from the JSON + the headline that matters>
     ```

5. Close with the rule's record from `record_recent` and `record_12m` (trades,
   win rate, expectancy in R, profit factor) in one line, and the order-placing
   steps: place the entry as an SL buy order (trigger = entry, limit = max_entry)
   before 09:15 IST; once filled, place the stoploss as an SL-M sell at the stop
   and a limit sell at the target (or a GTT OCO on Zerodha/Upstox/Groww); cancel
   the entry if it has not filled by the close.

## Rules

- Numbers come only from the scanner JSON. Do not round them into new levels.
- Never call a pick "sure", "guaranteed" or a "multibagger". About 45% of this
  rule's trades win; the edge is that winners average about +7% and losers
  about -4.5%. Say so when asked about odds.
- If the market filter is OFF, there are no picks by design: say "stay out".
- Not investment advice; the user decides and places every order.
