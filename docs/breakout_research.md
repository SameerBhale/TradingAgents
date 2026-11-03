# NSE breakout rule: how it was chosen, and its record

Data: daily bars of all 2,391 NSE mainboard stocks (EQ series), Nov 2021 to Nov 2026,
from Yahoo Finance (free, split/dividend adjusted). Every result is **after 0.30% round-trip
costs** (STT, exchange/SEBI fees, stamp duty, GST, slippage on delivery trades).

Method: rules were compared on **Jan 2022 to Jun 2024** (the "train" period). The
**Jul 2024 to Sep 2026** period (the "test" period) was used only to check them. Test
was a hard market for buying breakouts: the Nifty went sideways to down, with -8.4%
(Q4 2024) and -14.5% (Q1 2026) quarters, and often fewer than 40% of stocks were above
their 200-day average.

R = the trade's result in units of its initial risk (entry minus stop). +0.10R per trade
at 1% risk per trade is about +0.1% of capital per trade.

## 1. Breakouts beat random entries, but the loose rules lost money in the weak market

| Rule | Train exp. | Test exp. |
|---|---|---|
| Random entries on liquid uptrend days, same exits (baseline) | -0.03R | -0.26R |
| 20-day high breakout | +0.07R | -0.13R |
| 55-day high breakout | +0.05R | -0.10R |
| 52-week high breakout | +0.11R | -0.07R |

## 2. What did not help (rejected)

- A stricter "healthy market" filter (Nifty above its 200-DMA and breadth over 50/60%):
  better on train, **worse** on test. The few healthy windows in test were market tops.
- Trailing-stop exits: much better on train (+0.33R), worse on test (-0.15R).
- An adaptive filter that trades only while recent breakouts are working: inconsistent.
- Ranking by relative strength or volume surge: no consistent effect in either period.

## 3. What did help: tight bases and tight stops

In quintiles of the signal-day features, the widest bases and the widest stops were
the worst fifth in **both** periods. Capping the base at 12% and the risk at 6%:

| Rule | Period | Trades | Win rate | Exp. | Avg. trade | Profit factor |
|---|---|---|---|---|---|---|
| 52-wk, base <= 15%, risk <= 8% | train | 660 | 46% | +0.12R | +0.55% | 1.24 |
| | test | 416 | 40% | -0.05R | -0.49% | 0.90 |
| **52-wk, base <= 12%, risk <= 6% (chosen)** | **train** | **406** | **47%** | **+0.13R** | **+0.57%** | **1.25** |
| | **test** | **245** | **43%** | **+0.05R** | **+0.24%** | **1.10** |
| | last 12 months | 127 | 45% | +0.18R | +0.79% | 1.39 |

The chosen rule (`tradingagents/scanner/breakout.py`, `DEFAULT_RULES`):

- **Signal** (on the daily close): a new 52-week high; volume >= 1.5x the 50-day average;
  a base of at most 12% over the prior 20 sessions; close no more than 4% over the old
  high and in the top 40% of the day's range; close > 50-DMA > 200-DMA; 6-month return at
  least the Nifty's; price >= Rs 100; turnover >= Rs 10 crore a day; and the Nifty 50
  above its 50-DMA.
- **Entry**: a buy-stop 0.1% above the signal day's high, for the next session only; skip
  it if it opens more than 3% above the trigger.
- **Stop**: 2 x ATR(14) below the entry, or the signal day's low if that is lower, but never
  more than 6% below.
- **Target**: 2R. **Time exit**: the close of the 20th session.

## Caveats (read these)

- **Survivorship bias**: only stocks listed today were tested. Stocks that were delisted
  or suspended after collapsing are missing, so the real record is somewhat worse.
- **Some selection on test**: the 12% / 6% caps were picked from patterns that held in
  both periods, so the test period is not fully untouched for that last step.
- **Execution**: fills assume the buy-stop fills at the trigger (or the open on a gap)
  and the stop fills at the stop (or the open on a gap down). Thin stocks, circuit
  limits and results-day gaps can do worse.
- **It is a small edge**: about 45% of trades win. Expect losing streaks of 6 to 8
  trades. Risk 0.5 to 1% of capital per trade, never more.
- **Results risk is flagged, not filtered**: the scanner flags results dates inside the
  holding window, but the backtest could not test that filter (Yahoo has no free
  history of past results dates).
- Past results do not guarantee future returns. This is software, not investment advice.
