# The Survival Plan: rules, numbered

Built from 10 years of NSE data (Jan 2017 to Oct 2026), all 2,391 mainboard stocks. The
universe is chosen as of each date (the most traded stocks then, not today's), with
**0.30% round-trip costs**. The commands: `/trade-setups` (or `tradingagents setups`) and
`/trade-journal`. Research: [breakout_research.md](breakout_research.md).

## The numbers that chose the plan

| Strategy, 2017-2026, after costs | Return a year | Worst drop | Worst year |
|---|---|---|---|
| Nifty 50, buy and hold | +11.3% | -38.4% | -10% |
| Nifty 50 only above its 200-DMA, else liquid fund | +7.6% | -18.2% | -7% |
| Breakout swing account (1% risk, 10 slots) | +0.5% | -19.1% | -13% |
| **Momentum core (rules 1-10 below)** | **+15.1%** | **-20.1%** | **-10% (2018)** |

Momentum core, year by year: 2017 +6%, 2018 -10%, 2019 +2%, 2020 +28%, 2021 +51%,
2022 0%, 2023 +55%, 2024 +24%, 2025 +5%, 2026 (to Oct) +4%.

Every momentum variant tested (top 15/20/30 stocks, 6- or 12-month score, universe
of 100/150/250) returned +11.6% to +17.1% a year. That is why it is trusted: the result
does not hinge on one lucky setting. Breakout trades have a small edge per trade (+0.09R),
but the account barely grew over 10 years, so they are only the satellite.

## A. The momentum core (80% of capital)

1. **Universe**: the 100 most traded NSE stocks (20-day average traded value), price
   Rs 100 or more, each above its own 200-day average.
2. **Score**: the 12-month return, skipping the last month, divided by the annualized
   volatility of the last 12 months (risk-adjusted momentum, as in NSE's own momentum indices).
3. **Hold the top 20, equal weight**: core capital / 20 in each.
4. **Review once a month**, on the last trading day of the month, after 16:30 IST:
   run `/trade-setups`. Buy the new names at the next open.
5. **Keep a winner**: a holding stays while its rank is within the top 40. Sell it only
   when it falls out of the top 40, or below its 200-DMA, at a review.
6. **Market switch**: when the Nifty 50 closes a month below its 200-day average, sell
   the whole core and park it in a liquid ETF (LIQUIDBEES). Buy back at the first month-end
   with the Nifty above its 200-DMA.
7. **Stoploss: -15%** from your buy price, on a closing basis. After a stop, that slot
   waits in LIQUIDBEES until the next review.
8. **No target.** Momentum makes its money from the few stocks that run for months.
   Selling winners at a fixed target removes that.
9. **Holding time: 1 to 4 months.** The median hold in testing was 62 days (half of all
   holds lasted 31 to 124 days). Some winners stay a year or more while they stay in the top 40.
10. **Never** average down, add leverage or margin, or skip a review.

## B. The swing satellite (20% of capital)

11. Only **grade A** (52-week breakout) setups at full size. Trade grade B at full size
    only while it is marked B. Grade C: paper-trade it, or use half size if you must.
12. **Risk 1% of the swing capital per trade** (the quantity shown already does this),
    with at most 25% of the swing capital in one stock.
13. **Entry**: an SL buy order with trigger = entry and limit = max, for the next session
    only. No fill means no trade.
14. **Exit**: put the stoploss and target in a GTT OCO right after the fill. If neither
    hits, sell at the close on the exit-by date (20 sessions for breakouts and pullbacks,
    10 for RSI(2)).
15. **Holding time**: breakouts typically last about 13 sessions, and winners hit the target in
    about 8. Pullbacks last about 9 sessions; RSI(2) dips 2 to 4 sessions.
16. Results date inside the hold: skip the trade, halve the size, or sell before the results.

## C. Survival rules (the account as a whole)

17. **Start only with money you can watch fall 20-25%** without selling in panic. The
    tested worst drop was -20%, and the future can be worse.
18. **Account drawdown brake**: if your total equity is 10% below its peak, halve the
    swing risk to 0.5%. At 20% below, stop swing trades for a month. The core keeps
    following rules 1-10.
19. **At -30% from the peak** (worse than anything tested), stop everything and review.
    Something has changed.
20. **Idle cash goes to LIQUIDBEES** (about 6-7% a year), never into a savings account.
21. **Log every fill** in `/trade-journal` the same day, then check `journal stats` monthly
    against these numbers. A big gap from the backtest means you are not following the rules.
22. **Taxes**: the core holds about 2 months, so most gains are short-term (STCG 20%). Gains
    on holdings kept over 12 months are long-term (LTCG 12.5% above Rs 1.25 lakh a year).
    Budget for it.

## D. When to run what

| When | What |
|---|---|
| Every trading day after 16:30 IST | `/trade-setups`: new swing setups and core stop checks |
| Before 09:15 IST next morning | place the SL buy orders for swing setups; core BUYs at the open |
| Last trading day of the month, after 16:30 | core review: BUY / HOLD / SELL from `/trade-setups` |
| After every fill | `/trade-journal`: log it |
| Monthly | `tradingagents journal stats`: are you on plan? |

## Honest limits

- **Survivorship bias**: delisted stocks are missing from the data, so real results will be
  somewhat lower.
- **Momentum can lag the index for years**: 2017-2019 trailed the Nifty. The plan only works
  if you keep following it through those years.
- **Data**: the data is free and can lag (Yahoo). Always confirm prices in your broker.
- **Not advice**: past results are not a promise. This is software, not investment advice.
