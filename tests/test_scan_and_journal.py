"""The five strategies, the daily scan (offline) and the trade journal."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.journal import Journal
from tradingagents.scanner import daily as D, strategies as S


def _frame(closes, start="2024-01-01", vol=1e6):
    idx = pd.bdate_range(start, periods=len(closes))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c,
                         "Volume": np.full(len(c), vol)}, index=idx)


def _uptrend_with_dip(n=300):
    closes = list(np.linspace(200, 400, n - 6))
    closes += [399, 396, 394, 393, 395, 399]  # dip to the 20 EMA, then a reversal day
    df = _frame(closes)
    df.iloc[-1, df.columns.get_loc("High")] = 400.0
    return df


def _vcp_frame():
    """A stage-2 uptrend, then a base that tightens 20% -> 10% -> 4% on drying volume."""
    up = list(np.linspace(150, 400, 260))
    rng = np.random.default_rng(0)
    base = (list(400 - 40 * np.abs(np.sin(np.linspace(0, np.pi, 25))))       # ~10-20% deep
            + list(400 - 20 * np.abs(np.sin(np.linspace(0, np.pi, 15))))     # ~5-10%
            + list(398 + rng.uniform(-3, 3, 10)))                            # tight finish
    closes = up + base
    df = _frame(closes)
    df["Volume"] = np.r_[np.full(len(up), 2e6), np.linspace(2e6, 0.8e6, len(base))]
    return df


@pytest.mark.unit
def test_trend_template_and_vcp_signal():
    ind = S.indicators(_vcp_frame())
    assert bool(S.trend_template(ind).iloc[-1])
    r = ind.iloc[-1]
    assert r["c1"] > r["c2"] > r["c3"]
    assert bool(S.signals("vcp", ind, None).iloc[-1])
    s = S.setup_for("vcp", r)
    assert s.entry == pytest.approx(r["high10"] * 1.001, abs=0.01)
    assert 5.0 - 0.01 <= s.risk_pct <= 10.0 + 0.01


@pytest.mark.unit
def test_episodic_pivot_on_a_news_gap():
    closes = list(np.linspace(200, 300, 280))
    df = _frame(closes)
    df.loc[df.index[-1], ["Open", "High", "Low", "Close", "Volume"]] = [312.0, 326.0, 311.0, 324.0, 5e6]
    ind = S.indicators(df)
    assert bool(S.signals("ep", ind, None).iloc[-1])
    s = S.setup_for("ep", ind.iloc[-1])
    assert s.entry == pytest.approx(326.0 * 1.001, abs=0.01) and s.stop < 311.0


@pytest.mark.unit
def test_kell_crossback_on_a_dip_to_the_emas():
    ind = S.indicators(_uptrend_with_dip())
    assert bool(S.signals("crossback", ind, None).iloc[-1])
    s = S.setup_for("crossback", ind.iloc[-1])
    assert s.entry == pytest.approx(400.0 * 1.001, abs=0.01)
    assert s.target == pytest.approx(s.entry + 2 * (s.entry - s.stop), abs=0.02)


@pytest.mark.unit
def test_rs_rank_is_a_cross_sectional_percentile():
    strong = S.indicators(_frame(np.linspace(100, 300, 300)))
    weak = S.indicators(_frame(np.linspace(100, 120, 300)))
    S.add_rs_rank({"A": strong, "B": weak})
    assert strong["rs_rank"].iloc[-1] > weak["rs_rank"].iloc[-1]


@pytest.mark.unit
def test_verdict_grades():
    good = {"6m": {"trades": 30, "expectancy_r": 0.1}, "12m": {"trades": 60, "expectancy_r": 0.05}}
    mixed = {"6m": {"trades": 30, "expectancy_r": -0.1}, "12m": {"trades": 60, "expectancy_r": 0.05}}
    bad = {"6m": {"trades": 30, "expectancy_r": -0.1}, "12m": {"trades": 60, "expectancy_r": -0.05}}
    assert D._grade("vcp", good) == "GOOD"
    assert D._grade("vcp", mixed) == "OK"
    assert D._grade("flag", bad) == "AVOID"
    assert D._grade("breakout", bad) == "OK"  # held up in every tested period


@pytest.mark.unit
def test_news_flags_use_whole_words():
    assert D._matches(D.NEGATIVE_WORDS, "shares listed and closed higher") == []
    assert D._matches(D.NEGATIVE_WORDS, "enforcement directorate raids office; profit falls") == [
        "enforcement directorate", "profit falls", "raids"]


@pytest.mark.unit
def _md(stocks, nifty, etfs=None, secs=None):
    from tradingagents.scanner.data import MarketData

    last = nifty.index[-1].date()
    return MarketData(stocks, etfs or {}, nifty, last, last, secs or {})


def test_run_daily_offline(monkeypatch):
    df = _uptrend_with_dip()
    nifty = _frame(np.linspace(100, 130, len(df)))
    sec = D.india.IndianSecurity("TESTCO", "Test Company Limited", "EQ", "EQUITY", "INE000000000", "2000-01-01")
    last = df.index[-1].date()
    monkeypatch.setattr(D.india, "cap_class", lambda s: "Mid")
    monkeypatch.setattr(D, "next_earnings_date", lambda s: None)
    monkeypatch.setattr(D, "_records", lambda inds, market, stamp: {
        n: {"all": {"trades": 0}, "12m": {"trades": 0}, "6m": {"trades": 0}} for n in S.STRATEGIES})
    md = _md({"TESTCO.NS": df}, nifty, secs={"TESTCO.NS": sec})
    r = D.run_daily(capital=500_000, risk_pct=1.0, top=10, with_news=False, md=md)
    assert r["as_of"] == str(last)
    assert len(r["ideas"]) == 1
    idea = r["ideas"][0]
    assert idea["symbol"] == "TESTCO.NS" and idea["cap"] == "Mid"
    assert idea["stop"] < idea["entry"] < idea["target"]
    assert idea["strategy"] == "crossback"
    assert idea["grade"] == "AVOID" and idea["verdict"].startswith("AVOID")  # no record yet
    assert idea["bull"] and idea["verdict"] and idea["hold"]


def test_etf_ideas_are_labelled_etf(monkeypatch):
    df = _uptrend_with_dip()
    nifty = _frame(np.linspace(100, 130, len(df)))
    sec = D.india.IndianSecurity("TESTBEES", "Test Nifty ETF", "EQ", "ETF", "INF000000000", "2010-01-01")
    monkeypatch.setattr(D, "_records", lambda inds, market, stamp: {
        n: {"all": {"trades": 0}, "12m": {"trades": 0}, "6m": {"trades": 0}} for n in S.STRATEGIES})
    md = _md({}, nifty, etfs={"TESTBEES.NS": df}, secs={"TESTBEES.NS": sec})
    r = D.run_daily(top=10, with_news=False, md=md)
    assert r["ideas"] and r["ideas"][0]["cap"] == "ETF"
    assert r["ideas"][0]["earnings_date"] is None


def test_hold_text_from_record():
    rec = {"all": {"median_days": 13.0, "median_days_to_target": 8.0}}
    assert D.hold_text("breakout", rec, 20) == "typ. 13 sessions, winners hit target in ~8; max 20"
    assert D.hold_text("vcp", {"all": {"trades": 0}}, 20) == "up to 20 sessions"


def test_cash_etfs_are_not_trade_candidates():
    from tradingagents.scanner.data import etf_universe

    names = " ".join(s.name.lower() for s in etf_universe().values())
    assert "liquid" not in names and "1d rate" not in names
    assert "GOLDBEES.NS" in etf_universe() and "NIFTYBEES.NS" in etf_universe()


def _momentum_md(n_stocks=30, days=300, regime_up=True):
    stocks, secs = {}, {}
    for k in range(n_stocks):
        drift = 0.0005 + k * 0.00005  # higher k = stronger trend
        noise = np.random.default_rng(k).normal(0, 0.01, days)
        closes = 150 * np.exp(np.cumsum(drift + noise))
        df = _frame(closes, vol=1e6 + k)
        stocks[f"S{k:02d}.NS"] = df
        secs[f"S{k:02d}.NS"] = D.india.IndianSecurity(f"S{k:02d}", f"Stock {k}", "EQ", "EQUITY", "X", "2000-01-01")
    trend = np.linspace(100, 130, days) if regime_up else np.linspace(130, 100, days)
    return _md(stocks, _frame(trend), secs=secs)


def test_momentum_core_buys_top_20_with_stops():
    from tradingagents.scanner import momentum as M

    r = M.core_picks(_momentum_md(), core_capital=400_000)
    assert r["regime_on"]
    picks = r["picks"]
    assert len(picks) == M.TOP_N
    assert all(p["action"] == "BUY" for p in picks)
    assert [p["rank"] for p in picks] == sorted(p["rank"] for p in picks)
    for p in picks:
        assert p["stop"] == pytest.approx(p["entry"] * 0.85, abs=0.01)
        assert p["capital_needed"] <= 400_000 / 20 + 1


def test_momentum_core_holds_and_sells_against_the_journal():
    from tradingagents.scanner import momentum as M

    md = _momentum_md()
    ranked = M.ranking(md)
    weakest = ranked["symbol"].iloc[-1] if len(ranked) > M.KEEP_RANK else None
    best = ranked["symbol"].iloc[0]
    held = {best: 100.0}
    if weakest:
        held[weakest] = 100.0
    r = M.core_picks(md, 400_000, held)
    by = {p["symbol"]: p for p in r["picks"]}
    assert by[best]["action"] in ("HOLD", "SELL (stop hit)") and by[best]["entry"] == 100.0


def test_momentum_regime_off_waits():
    from tradingagents.scanner import momentum as M

    md = _momentum_md(regime_up=False)
    r = M.core_picks(md, 400_000, {"S29.NS": 100.0}, mode="safe")
    assert not r["regime_on"]
    assert all(p["action"] in ("WAIT", "SELL (regime off)") for p in r["picks"])
    assert any(s["symbol"] == "S29.NS" for s in r["sells"])
    half = M.core_picks(md, 400_000, mode="balanced")
    full = M.core_picks(md, 400_000, mode="aggressive")
    assert all(p["action"] == "BUY (half size)" for p in half["picks"])
    assert all(p["action"] == "BUY" for p in full["picks"])
    assert sum(p["capital_needed"] for p in half["picks"]) <= 200_000 + 20
    with pytest.raises(ValueError):
        M.core_picks(md, 400_000, mode="yolo")


def test_portfolio_replay_respects_slots_and_cash():
    from tradingagents.scanner import portfolio as P

    days = pd.bdate_range("2024-01-01", periods=40)
    rows = []
    for k in range(10):  # ten signals on the same day, each +10%
        rows.append({"symbol": f"S{k}", "strategy": "breakout", "signal_date": days[0], "entry_date": days[1],
                     "exit_date": days[10], "entry": 100.0, "exit": 110.0, "stop": 95.0, "ret_pct": 10.0, "r": 2.0})
    r = P.replay(pd.DataFrame(rows), P.Account(capital=100_000, max_positions=4))
    assert r["trades"] == 4
    assert r["final_equity"] > 100_000


@pytest.mark.unit
def test_journal_round_trip(tmp_path):
    path = str(tmp_path / "j.json")
    j = Journal.load(path)
    j.capital = 500_000
    a = j.add(symbol="GAIL.NS", entry_date="2026-10-20", entry_price=178.0, qty=200, stop=166.93, target=198.89)
    j.add(symbol="TCS.NS", entry_date="2026-10-21", entry_price=3000.0, qty=10, stop=2900.0)
    j.close(a.id, 195.5, "2026-11-02")
    j.save()

    j2 = Journal.load(path)
    t = j2.get(a.id)
    assert t.gross_pnl() == pytest.approx(3500.0)
    assert t.total_charges() == pytest.approx(101.66, abs=0.01)
    assert t.net_pnl() == pytest.approx(3398.34, abs=0.01)
    assert t.r_multiple() == pytest.approx(1.53, abs=0.01)
    s = j2.stats({"TCS.NS": 3100.0})
    assert s["closed_trades"] == 1 and s["open_trades"] == 1
    assert s["capital_deployed"] == pytest.approx(30_000.0)
    assert s["realized_pnl"] == pytest.approx(3398.34, abs=0.01)
    assert s["unrealized_pnl"] > 0
    assert s["capital_free"] == pytest.approx(500_000 + 3398.34 - 30_000, abs=0.01)


@pytest.mark.unit
def test_journal_partial_close_and_errors(tmp_path):
    j = Journal.load(str(tmp_path / "j.json"))
    t = j.add(symbol="INFY.NS", entry_date="2026-10-01", entry_price=1500.0, qty=100)
    j.close(t.id, 1600.0, "2026-10-10", charges=50.0, qty=40)
    assert t.qty == 40 and t.net_pnl() == pytest.approx(4000 - 50)
    rest = j.open_trades()[0]
    assert rest.qty == 60 and rest.entry_price == 1500.0
    with pytest.raises(ValueError):
        j.close(t.id, 1600.0, "2026-10-11")
    with pytest.raises(ValueError):
        j.add(symbol="X.NS", entry_date="2026-10-01", entry_price=0, qty=1)
    assert rest.holding_days(date(2026, 10, 11)) == 10
