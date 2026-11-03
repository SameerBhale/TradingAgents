---
name: nse-breakout
description: >-
  NSE top-10 trade ideas for the Indian stock market, with a bull-vs-bear agent
  debate on each. Runs the tested scanner over every large, mid and small cap on
  NSE (no penny or micro caps) across four chart setups (52-week breakout,
  pre-breakout pivot, pullback to the 20-DMA, RSI(2) dip), reads each stock's
  headlines and results date, then argues each idea bull vs bear and judges it.
  Every idea has entry, stoploss, target, reward:risk, exit date, size, cap
  class and grade. Free data, no API key. Also logs trades in the journal. Use
  when the user says "top stocks", "what to buy tomorrow", "scan NSE", "breakout
  stocks", "swing trade ideas", "nse-breakout", "log my trade", "my P&L".
argument-hint: "[--capital 500000] [--risk 1] [--top 10]"
---

# nse-breakout

You run a tested, rule-based scanner, then act as three agents on each idea:
a **Bull** who argues for the trade, a **Bear** who attacks it, and a **Judge**
who decides. The scanner owns the numbers; you never invent or change a price,
level, quantity or odds.

## Steps

1. Run the scan with the user's capital and risk (defaults Rs 5,00,000 and 1%):

   ```bash
   tradingagents scan --capital 500000 --risk 1 --top 10 --json
   ```

   (`python -m cli.main scan ...` from the repo root if `tradingagents` is not on PATH.)
   It also saves `~/.tradingagents/scans/top-<date>.md`.

2. Open with two lines: the close the ideas are from (`as_of`), the Nifty vs its
   50/200-DMA, breadth, and every line in `notes` (e.g. Yahoo lagging).

3. Print the full table, one row per idea, numbers exactly from the JSON:

   | # | Grade | Stock | Cap | Sector | Setup | Entry | Stoploss | Target | R:R | Exit by | Qty | Capital | Max loss | Call |

   Entry: "buy-stop X (max Y)" for stop entries, "buy at open ~X (max Y)" for
   RSI(2). Explain the grades once: A = 52-week breakout (profitable in both
   rising and weak markets in testing); B = setup whose strategy is profitable
   across NSE over the last 6 and 12 months; C = strategy losing lately, so half
   size or paper trade only.

4. For each idea, read its `news` (run `tradingagents headlines <SYMBOL> --days 7`
   for the top 5 if you need more), `earnings_date`, `bull`, `bear` and the
   strategy record in `records`. Then write the debate, short:
   - **Bull**: the strongest 2-3 points for the trade (chart, relative strength,
     news, reward:risk).
   - **Bear**: the strongest 2-3 points against it (market tape, results inside
     the hold, negative news, the strategy's recent record, small-cap gap risk).
     The Bear must answer the Bull's best point.
   - **Judge**: TAKE / CAUTION / HALF / SKIP in one line, why. SKIP on fraud,
     governance, SEBI/ED action, auditor exit, pledge invocation, or a one-off
     event that explains the move (open offer, merger arbitrage). The Judge may
     be stricter than the scanner's `verdict`, never looser.

5. Finish with:
   - **Ranking**: which 1-3 ideas the Judge likes best and why (grade A first).
   - The strategy records (`records`: 6m and 12m trades, win rate, R per trade).
   - Order steps: SL buy order (trigger = entry, limit = max) placed before
     09:15 IST, valid for the day; once filled, a GTT OCO with the stop and the
     target (Zerodha/Upstox/Groww); cancel if not filled by the close; exit at the
     close on the exit-by date if neither hit.
   - Journal: `tradingagents journal add --from-scan <#> --price <fill>` after a
     buy, `tradingagents journal close <id> --price <sell>` after a sell,
     `tradingagents journal stats` for P&L and capital used.

## Journal requests

When the user says they bought or sold, run the journal command for them
(`journal add` / `journal close` with their fill price, quantity and date), then
`tradingagents journal list` and show the result. For "my P&L" or "how am I
doing": `tradingagents journal stats`.

## Rules

- Numbers only from the scanner JSON or the journal output.
- Never "sure", "guaranteed" or "multibagger". In testing the breakout rule won
  about 45% of trades; its edge is that winners (~+7%) are bigger than losers
  (~-4.5%). Expect losing streaks. Grade C setups lost money lately: say so.
- If fewer than 10 ideas came back, show what came back; never pad the list.
- Not investment advice; the user decides and places every order.
