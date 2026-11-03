"""The NSE breakout engine and scan, offline on synthetic bars."""

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.scanner import breakout as B, engine as E


def _frame(closes, highs=None, lows=None, opens=None, volumes=None, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "Open": opens if opens is not None else closes,
        "High": highs if highs is not None else closes * 1.005,
        "Low": lows if lows is not None else closes * 0.995,
        "Close": closes,
        "Volume": volumes if volumes is not None else np.full(len(closes), 1e6),
    }, index=idx)


def _breakout_series(n=320, spike_at=300):
    """A steady uptrend, a tight base, then a high-volume close over the 52-week high."""
    up = np.linspace(200, 300, spike_at - 25)
    base = np.full(25, 300.0) + np.sin(np.arange(25)) * 2
    after = np.linspace(312, 330, n - spike_at)
    closes = np.concatenate([up, base, after])
    vol = np.full(n, 1e6)
    vol[spike_at] = 3e6
    df = _frame(closes, volumes=vol)
    df.iloc[spike_at, df.columns.get_loc("High")] = closes[spike_at] * 1.002
    return df


RULES = replace(B.DEFAULT_RULES, min_turnover_cr=1.0, min_rs=None)


@pytest.mark.unit
def test_signal_fires_on_the_breakout_bar():
    df = _breakout_series()
    ind = E.indicators(df, RULES)
    mask = E.signal_mask(ind, RULES)
    assert mask.iloc[300]
    assert mask.sum() == 1


@pytest.mark.unit
def test_penny_and_illiquid_stocks_never_signal():
    df = _breakout_series()
    penny = df.copy()
    penny[["Open", "High", "Low", "Close"]] /= 10  # Rs 20-33: below the Rs 100 floor
    assert not E.signal_mask(E.indicators(penny, RULES), RULES).any()
    thin = replace(RULES, min_turnover_cr=10_000)
    assert not E.signal_mask(E.indicators(df, thin), thin).any()


@pytest.mark.unit
def test_market_filter_blocks_signals():
    df = _breakout_series()
    ind = E.indicators(df, RULES)
    market = pd.DataFrame({
        "nifty": 90.0, "nifty_sma50": 100.0, "nifty_sma200": 100.0,
        "nifty_ret126": 0.0, "breadth": 30.0,
    }, index=df.index)
    assert not E.signal_mask(ind, RULES, market).any()
    market["nifty"] = 110.0
    assert E.signal_mask(ind, RULES, market).iloc[300]


@pytest.mark.unit
def test_plan_levels_and_risk_cap():
    row = pd.Series({"High": 100.0, "Low": 97.0, "atr": 5.0})
    plan = E.plan_for(row, replace(RULES, max_risk_pct=6.0))
    assert plan.trigger == pytest.approx(100.1)
    # 2 x ATR = 10 below would risk ~10%: capped at 6%.
    assert plan.stop == pytest.approx(100.1 * 0.94, abs=0.01)
    assert plan.rr == pytest.approx(2.0, abs=0.01)


def _sim(bars, plan, rules=RULES):
    df = _frame([b[3] for b in bars], highs=[b[1] for b in bars], lows=[b[2] for b in bars],
                opens=[b[0] for b in bars])
    df["atr"] = 2.0
    return E.simulate(df, 0, plan, rules)


@pytest.mark.unit
def test_target_hit():
    plan = E.Plan(trigger=100.0, stop=95.0, target=110.0, risk_pct=5.0)
    bars = [(99, 99.5, 98, 99), (99.5, 101, 99, 100.5), (101, 111, 100.5, 110)] + [(110, 110, 110, 110)] * 20
    t = _sim(bars, plan)
    assert t["outcome"] == "target"
    assert t["r"] == pytest.approx((1.10 - 1 - 0.003) * 100 / 5, rel=1e-6)


@pytest.mark.unit
def test_no_fill_means_no_trade():
    plan = E.Plan(trigger=100.0, stop=95.0, target=110.0, risk_pct=5.0)
    bars = [(99, 99.5, 98, 99), (99, 99.9, 98, 99)] + [(99, 99, 99, 99)] * 20
    assert _sim(bars, plan) is None


@pytest.mark.unit
def test_gap_over_max_entry_is_skipped():
    plan = E.Plan(trigger=100.0, stop=95.0, target=110.0, risk_pct=5.0)
    bars = [(99, 99.5, 98, 99), (104, 106, 103.5, 105)] + [(105, 105, 105, 105)] * 20
    assert _sim(bars, plan) is None


@pytest.mark.unit
def test_gap_through_stop_fills_at_the_open():
    plan = E.Plan(trigger=100.0, stop=95.0, target=110.0, risk_pct=5.0)
    bars = [(99, 99.5, 98, 99), (99.5, 101, 99, 100.5), (92, 93, 91, 92)] + [(92, 92, 92, 92)] * 20
    t = _sim(bars, plan)
    assert t["outcome"] == "stop"
    assert t["exit"] == 92
    assert t["r"] < -1


@pytest.mark.unit
def test_stop_and_target_same_bar_counts_as_stop():
    plan = E.Plan(trigger=100.0, stop=95.0, target=110.0, risk_pct=5.0)
    bars = [(99, 99.5, 98, 99), (99.5, 101, 99, 100.5), (100, 111, 94, 100)] + [(100, 100, 100, 100)] * 20
    assert _sim(bars, plan)["outcome"] == "stop"


@pytest.mark.unit
def test_time_exit_after_max_hold():
    plan = E.Plan(trigger=100.0, stop=95.0, target=110.0, risk_pct=5.0)
    bars = [(99, 99.5, 98, 99), (99.5, 101, 99, 100.5)] + [(102, 103, 101, 102)] * 25
    t = _sim(bars, plan, replace(RULES, max_hold=20))
    assert t["outcome"] == "time"
    assert t["days"] == 20


@pytest.mark.unit
def test_position_size_respects_risk_and_cash_caps():
    assert B._size(500_000, 1.0, 100.0, 95.0) == 1000  # Rs 5,000 risk / Rs 5 = 1,000, under 25% cash
    assert B._size(500_000, 1.0, 1000.0, 990.0) == 125  # risk allows 500, cash cap 25% = 125


@pytest.mark.unit
def test_inr_grouping():
    from cli.breakout import _inr

    assert _inr(12345678.9) == "Rs 1,23,45,678.90"
    assert _inr(999.5) == "Rs 999.50"
    assert _inr(100000) == "Rs 1,00,000.00"


@pytest.mark.unit
def test_run_scan_offline(monkeypatch):
    df = _breakout_series(n=301)  # the breakout is the last settled bar
    last = df.index[-1].date()
    nifty = _frame(np.linspace(100, 130, len(df)))
    sec = B.india.IndianSecurity("TESTCO", "Test Company Limited", "EQ", "EQUITY", "INE000000000", "2000-01-01")
    monkeypatch.setattr(B, "_universe", lambda: {"TESTCO.NS": sec})
    monkeypatch.setattr(B, "_settled_session", lambda now=None: last)
    monkeypatch.setattr(B, "download_daily", lambda *a, **k: {"TESTCO.NS": df, "^NSEI": nifty})
    monkeypatch.setattr(B, "next_earnings_date", lambda s: date(2099, 1, 1))
    result = B.run_scan(capital=500_000, risk_pct=1.0, rules=replace(RULES, min_rs=None))
    assert result.regime_ok
    assert len(result.picks) == 1
    p = result.picks[0]
    assert p.symbol == "TESTCO.NS"
    assert p.stop < p.entry < p.target
    assert p.rr == pytest.approx(2.0, abs=0.01)
    assert p.quantity > 0 and p.max_loss <= 5_000 + 1
    assert not p.earnings_in_window
    assert p.exit_by > p.signal_date


@pytest.mark.unit
def test_google_news_parses_rss(monkeypatch):
    from datetime import UTC, datetime
    from email.utils import format_datetime

    from tradingagents.dataflows.vendors import google_news

    now = format_datetime(datetime.now(UTC))
    rss = (
        "<rss><channel>"
        f"<item><title>Stock hits 52-week high</title><pubDate>{now}</pubDate>"
        "<source url='x'>Mint</source><link>http://a</link></item>"
        "<item><title>Old news</title><pubDate>Mon, 01 Jan 2001 00:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    ).encode()

    class Resp:
        content = rss

        def raise_for_status(self):
            pass

    monkeypatch.setattr(google_news.requests, "get", lambda *a, **k: Resp())
    items = google_news.headlines("Test", days=7)
    assert [i["title"] for i in items] == ["Stock hits 52-week high"]
    assert items[0]["source"] == "Mint"
