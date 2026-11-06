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
6. **Market switch**: when the Nifty 50 closes a month below its 200-day average, the
   core changes size by mode. Choose with `--mode`:

   | Mode | Core while the Nifty is below its 200-DMA | Return a year | Worst drop |
   |---|---|---|---|
   | safe | 0% in stocks, all in LIQUIDBEES | +15.1% | -20.1% |
   | **balanced (default)** | 50% in stocks, 50% in LIQUIDBEES | +14.3% | -20.7% |
   | aggressive | 100% in stocks | +13.2% | -32.4% |
7. **Stoploss: -15%** from your buy price, on a closing basis. After a stop, that slot
   waits in LIQUIDBEES until the next review.
8. **No target.** Momentum makes its money from the few stocks that run for months.
   Selling winners at a fixed target removes that.
9. **Holding time: 1 to 4 months.** The median hold in testing was 62 days (half of all
   holds lasted 31 to 124 days). Some winners stay a year or more while they stay in the top 40.
10. **Never** average down, add leverage or margin, or skip a review.

## B. Swing setups (short term)

Six setups, each from a documented trader or a common Indian price-action practice, all long-only on daily bars with a buy-stop
entry (no fill, no trade):

| Setup | Source | Rule in one line |
|---|---|---|
| 52-week breakout | Darvas / O'Neil | close at a new 52-week high on 1.5x volume out of a base of 12% or less |
| Minervini VCP | Mark Minervini, US Investing Champion 1997 (+155%) | passes the 8-point Trend Template (stage 2, RS rank >= 70), base tightens in steps (e.g. 20% -> 10% -> 4%) on drying volume |
| Qullamaggie flag | Kristjan Kullamagi | a 30%+ run in 1-3 months, then a tight flag on the rising 10/20-day averages, ADR >= 3% |
| Episodic pivot | Kristjan Kullamagi | a 3%+ gap and 6%+ day on 3x volume after news, closing strong, above the 200-DMA |
| Kell EMA crossback | Oliver Kell, US Investing Champion 2020 (+941%) | a stage-2 leader dips to its 20 EMA and closes back above the 10 EMA and the prior high |
| Breakout + retest | supply-zone flip (Indian price-action practice, e.g. Apoorv Dubey); cup and handle (O'Neil); ascending triangle (Bulkowski) | a fresh breakout of a horizontal level (all-time high, 52-week high, flag and pole, ascending triangle, or cup-and-handle / base rim) after 20+ sessions under it, on 1.5x volume, a 4%+ move above it, a lighter-volume pullback that tests the level (within 3%) and holds it (no close 3%+ under), then a bounce over the prior day's high; stage-2 trend |
| CT breakout + retest | counter-trendline break (Indian price-action practice) | the same retest after a close through a falling line from the year's highest swing high through the lower swing highs after it; a reversal, so it needs only the 50-DMA |

**Verdict scale** (added 2026-11-06): GOOD is split by three checks that successful
traders use: the setup's 12-month success rate >= 40%, O'Neil's up/down volume ratio
(50 days) >= 1.2 (volume building up) and an RS rank >= 80. All three: BEST; two:
BETTER; else GOOD. An up/down ratio under 0.8 (distribution) caps a setup at OK.

**Micro caps** (below the top 500 by market cap) are scanned only when they trade Rs 25
crore+ a day (20-day average). They never enter the momentum core, the breadth or the RS
rank. They get the same verdict scale, judged on each setup's record on micro caps alone
(needs 15 trades in 12 months and 8 in 6), with a MICRO CAP caution: half size. The
micro-cap record is survivor-biased (today's liquid micro caps), so it flatters them.

**10-year test** (2017-06 to 2026-11, 1,968 NSE stocks, 0.30% costs, stop 5-10%, target 2R,
max 20 sessions; R per trade after costs):

| Setup | 2017-21 | 2022-24 | 2024-26 (weak) | last 12 months | all |
|---|---|---|---|---|---|
| 52-week breakout | +0.09R | +0.10R | +0.04R | +0.04R | +0.09R (1,048 trades) |
| Minervini VCP | +0.11R | +0.10R | -0.04R | +0.03R | +0.06R (2,435) |
| Qullamaggie flag | +0.10R | +0.06R | -0.16R | -0.06R | +0.02R (4,351) |
| Episodic pivot | +0.08R | +0.11R | +0.03R | -0.11R | +0.07R (662) |
| Kell crossback | +0.09R | +0.13R | -0.12R | -0.05R | +0.06R (4,113) |

The same breakout, **sold on a close below the 20-day EMA** instead of at the target (stop
unchanged, max 60 sessions): +0.09R, +0.25R, +0.10R, last 12 months +0.29R; all +0.17R
(1,020 trades), profit factor 1.34. It was the best exit in every period. The trailing
exit did not rescue the other setups in 2024-26.

Neither a market filter (Nifty above its 200-DMA with 50%+ breadth) nor a strict RS rank
>= 90 fixed the weak period: the few "healthy" days in 2024-26 were near the top.

**2026-11-04 retest: no time limit, trader-style exits** (same data, all five setups,
large/mid/small caps, R per trade after costs; win % in brackets):

| Exit | 2017-21 | 2022-Jun 24 | Jul 24-26 | all |
|---|---|---|---|---|
| 2R target or sell after 20 sessions (old) | +0.11R | +0.18R | -0.04R | +0.09R (45%) |
| 2R target, no time limit | +0.21R | +0.31R | -0.04R | +0.17R (40%) |
| close below the 20-day EMA (no target) | +0.19R | +0.28R | -0.05R | +0.15R (32%) |
| close below the 10-day EMA | +0.11R | +0.10R | -0.04R | +0.06R (34%) |
| **half at 2R, stop to cost, rest on a 20-EMA close (chosen)** | **+0.28R** | **+0.44R** | -0.06R | **+0.23R (40%)** |

The chosen exit is how Qullamaggie and Minervini sell: take part of the gain at the
target, then let the rest run on a moving average. It keeps your 10-20% target and
removes the calendar. Typical hold: 22-34 sessions; the target half fills in about 18.

**Follow the money: NSE delivery %.** NSE publishes the delivered share of each stock's
volume every day (the MTO file, free, back to 2016). Funds buy for delivery; intraday
traders square off. dp_trend = the 20-day average delivery % / the 100-day average.
All five setups, half-at-target exit:

| dp_trend on the signal day | 2017-21 | 2022-Jun 24 | Jul 24-26 | last 12m | all |
|---|---|---|---|---|---|
| any (no filter) | +0.28R | +0.44R | -0.06R | -0.09R | +0.23R (6,801) |
| >= 1.00 | +0.39R | +0.52R | -0.02R | -0.06R | +0.30R |
| **>= 1.05 (money IN)** | **+0.42R** | **+0.58R** | **+0.04R** | -0.08R | **+0.36R (1,906)** |
| >= 1.08 | +0.40R | +0.61R | +0.14R | +0.20R | +0.40R (1,329) |

Every step up in the threshold was better in every period, so the effect is not one
lucky setting. It helps breakouts, VCPs and crossbacks most; it does not help episodic
pivots (news days are full of intraday churn), so they are exempt. Price-only "money
flow" proxies (O'Neil up/down volume, volume surge) showed no consistent effect.

**Universe**: liquid micro caps (price >= Rs 100, turnover >= Rs 10 crore) lost on the
same rules (-0.01R overall, -0.20R in 2024-26; the most traded micro caps -0.65R), so
the scan stays on the top 500 by market cap (Large, Mid, Small), about 475 with history.

**Bulk/block deals**: NSE serves only the current day freely, so they cannot be tested.
They are shown as a note; an institution selling in one demotes GOOD to OK.

What this means:

11. **Stoploss 5-10%, target 10-20%** (2R). Setups outside the band are dropped.
11b. **Money flow**: money OUT (dp_trend < 1.00) drops the setup; flat (1.00-1.05) is OK
    at best; only money IN (>= 1.05) can be GOOD. Episodic pivots are exempt. The setup
    records behind the verdict count money-IN trades only.
11a. **The verdict follows each setup's live record across NSE** (recomputed every run):
    GOOD when its last 12 and 6 months are positive per trade (30 and 15 trades at least);
    OK (half size) when one is, when there are too few recent trades, or for breakouts
    (positive in every tested period); AVOID when both are negative.
    A GOOD setup drops to OK when results fall inside the hold or the Nifty is below its
    200-DMA; bad headlines make it AVOID.
12. **Risk about 1% of the swing money per trade** (0.5% on OK), at most 25% in one stock.
13. **Entry**: a stop-limit buy with trigger = "buy above" and limit = max, for the next
    session only.
14. **Exit, no time limit**: right after the fill, a GTT OCO with the stoploss and the
    target for **half** the shares. When the target fills, move the stop on the other half
    to your buy price; sell it at the next open after a close below the 20-day EMA.
15. **Holding time**: the row's Hold is the median of the setup's own trades (about 22-26
    sessions; the target half fills in about 18). There is no sell-by date.
16. Results date inside the typical hold: halve the size, or sell before the results.

Champion returns of several hundred percent came from concentrated, often leveraged,
discretionary trading, with a few huge winners ridden for months. The mechanical
versions above keep the entries and the risk control, and earn a small edge per trade.

## B2. Value buys (medium to long term)

16a. Screen: the 250 most traded stocks in Minervini's stage 2 (above the 150 and 200-day
     averages, the 200-day rising, within 25% of the 52-week high), with ROE >= 15%,
     debt/equity <= 100%, operating margin >= 10%, revenue and earnings growing, P/E at or
     below the sector median, and PEG <= 1.5 (O'Neil's CAN SLIM growth tests).
16b. A profit jump over 100% on revenue growth under 30% is dropped as a one-off, and so
     is a cyclical (oil, gas, metals, mining) at a P/E under 8: peak-cycle earnings.
16c. Stop 10-15% (under the 50-day average), target 2R (20-30%), hold 3-12 months, review
     on every quarterly result. **Not backtested**: free fundamentals have no history.

## C. Survival rules (the account as a whole)

17. **Start only with money you can watch fall 20-25%** without selling in panic. The
    tested worst drop was -20%, and the future can be worse.
18. **Account drawdown brake**: if your total equity is 10% below its peak, halve the
    swing risk to 0.5%. At 20% below, stop swing trades for a month. The core keeps
    following rules 1-10.
19. **At -30% from the peak** (worse than anything tested), stop everything and review.
    Something has changed.
20. **Idle cash goes to LIQUIDBEES** (about 6-7% a year), never into a savings account.
20a. **Never take a call marked AVOID.**
21. **Log every fill** in `/trade-journal` the same day, then check `journal stats` monthly
    against these numbers. A big gap from the backtest means you are not following the rules.
22. **Taxes**: the core holds about 2 months, so most gains are short-term (STCG 20%). Gains
    on holdings kept over 12 months are long-term (LTCG 12.5% above Rs 1.25 lakh a year).
    Budget for it.

## D. When to run what

| When | What |
|---|---|
| Every trading day after 18:00 IST | `/trade-setup`: top 5 swing and top 3 value (or the 18:30 mail from `alerts digest`) |
| Market hours | `tradingagents alerts watch --gaps`: buy triggers, stop/target hits, gap-ups by mail |
| Before 09:15 IST next morning | place the SL buy orders for swing setups; core BUYs at the open |
| Last trading day of the month, after 16:30 | core review: BUY / HOLD / SELL from `/trade-setups` |
| After every fill | `/trade-journal`: log it |
| Monthly | `tradingagents journal stats` and `tradingagents calls review`: are you, and the bot, on plan? |

## E. Getting better: the feedback loop

23. Every `/trade-setups` run logs its calls. `tradingagents calls review` replays them on
    the prices that followed, and shows the hit rate by verdict and strategy.
24. Tell the bot when a call was good or bad: `tradingagents calls feedback <ticker> "<why>"
    --good/--bad`.
25. Change a rule only when a group has 20 or more closed calls that disagree with the
    backtest, and re-test the change on the 10-year data before adopting it.

## Honest limits

- **Survivorship bias**: delisted stocks are missing from the data, so real results will be
  somewhat lower.
- **Momentum can lag the index for years**: 2017-2019 trailed the Nifty. The plan only works
  if you keep following it through those years.
- **Data**: the data is free and can lag (Yahoo). Missing sessions are filled from NSE's own
  bhavcopy; live alert prices can be a few minutes late. Always confirm prices in your broker.
- **Not advice**: past results are not a promise. This is software, not investment advice.
