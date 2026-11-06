---
name: multibagger
description: >-
  The 3-5 year MULTIBAGGER CANDIDATES watch list for NSE: a saved list that grows as stocks
  pass an SQGLP / 100-bagger screen (Rs 500-30,000 cr market cap, ROE >= 18%, low debt,
  3-year sales CAGR >= 15% and profit CAGR >= 20%, sales up every year, fair PEG, low promoter
  pledge, above a rising 200-DMA) on official NSE filings + Yahoo. Each stock is NEW, HOLD,
  REVIEW or REMOVED, with the date and price it was added. Use only when the user types
  /multibagger or asks for "multibagger", "long term list", "3-5 year stocks".
argument-hint: "[--refresh] [--no-micro]"
---

# multibagger

Run only when asked (it is not part of /trade-setup, to save time).

```bash
tradingagents multibagger --markdown
```

(`python -m cli.main multibagger --markdown` if `tradingagents` is not on PATH.)

Show the header, the "Prices:" line and the table exactly as printed. Then, in plain words:

- **NEW**: passed every test today; it joins the list at today's price.
- **HOLD**: still passes. Nothing to do but review on each quarterly result.
- **REVIEW**: one test now fails (the Note says which); watch the next result.
- **REMOVED**: the story broke (ROE under 12%, sales growth under 8%, debt/equity over
  100%, over half of promoter shares pledged, or 35% under the added price and below the
  200-DMA); the reason is printed.

**Next in line** (shown under the list): stocks off the list that fail exactly one test
(named in "Missing test"). They join automatically the day that test passes; mention the
one or two closest (a small gap such as margin 11% vs 12%, or PEG 1.51 vs 1.5).

For each NEW stock write one line: why it qualifies (growth, ROE, owner holding) and the
biggest risk (valuation, a short history, a pledge, a cyclical business). Say how many years
of history the numbers rest on (the History column).

Plan: buy in 3 parts over 3-6 months near the 50-day average; review on every quarterly
result; sell only on REMOVED. Offer `stock-report` (a full PDF) for a NEW stock; run it only
on a yes.

Rules: call them "multibagger candidates", never multibaggers; say most will not become
one. Not backtested (free fundamentals have no point-in-time history). Not investment
advice; the user places every order.
