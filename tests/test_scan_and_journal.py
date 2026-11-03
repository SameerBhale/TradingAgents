"""The four strategies, the daily top-10 scan (offline) and the trade journal."""

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
    closes += [395, 388, 382, 379, 381, 392]  # dip toward the 20-DMA, then a reversal day
    df = _frame(closes)
    df.iloc[-1, df.columns.get_loc("High")] = 393.0
    return df


@pytest.mark.unit
def test_rsi2_signal_on_a_sharp_dip_in_an_uptrend():
    closes = list(np.linspace(200, 400, 295)) + [390, 375, 362]
    ind = S.indicators(_frame(closes))
    assert ind["rsi2"].iloc[-1] < 10
    assert bool(S.signals("rsi2", ind, None).iloc[-1])
    s = S.setup_for("rsi2", ind.iloc[-1])
    assert s.entry_type == "open" and s.exit_sma5 and s.stop < s.entry


@pytest.mark.unit
def test_pullback_signal_and_plan():
    ind = S.indicators(_uptrend_with_dip())
    assert bool(S.signals("pullback", ind, None).iloc[-1])
    s = S.setup_for("pullback", ind.iloc[-1])
    assert s.entry == pytest.approx(393.0 * 1.001, abs=0.01)
    assert s.risk_pct <= 6.0 + 1e-9
    assert s.target == pytest.approx(s.entry + 2 * (s.entry - s.stop), abs=0.02)


@pytest.mark.unit
def test_rsi2_exits_on_close_above_sma5():
    ind = S.indicators(_frame(list(np.linspace(200, 400, 295)) + [390, 375, 362, 366, 380, 395] + [395] * 10))
    i = 297
    s = S.setup_for("rsi2", ind.iloc[i])
    arrays = tuple(ind[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "sma5"))
    t = S.simulate(ind, i, s, arrays)
    assert t["outcome"] == "target" and t["days"] <= 3 and t["r"] > 0


@pytest.mark.unit
def test_grades():
    rec_good = {"6m": {"trades": 30, "expectancy_r": 0.1}, "12m": {"trades": 60, "expectancy_r": 0.05}}
    rec_bad = {"6m": {"trades": 30, "expectancy_r": -0.1}, "12m": {"trades": 60, "expectancy_r": 0.05}}
    assert D._grade("breakout", rec_bad) == "A"
    assert D._grade("pullback", rec_good) == "B"
    assert D._grade("pullback", rec_bad) == "C"


@pytest.mark.unit
def test_news_flags_use_whole_words():
    assert D._matches(D.NEGATIVE_WORDS, "shares listed and closed higher") == []
    assert D._matches(D.NEGATIVE_WORDS, "enforcement directorate raids office; profit falls") == [
        "enforcement directorate", "profit falls", "raids"]


@pytest.mark.unit
def test_run_daily_offline(monkeypatch):
    df = _uptrend_with_dip()
    nifty = _frame(np.linspace(100, 130, len(df)))
    sec = D.india.IndianSecurity("TESTCO", "Test Company Limited", "EQ", "EQUITY", "INE000000000", "2000-01-01")
    last = df.index[-1].date()

    class Status:
        last_completed_session = last

    monkeypatch.setattr(D, "_universe", lambda: {"TESTCO.NS": sec})
    monkeypatch.setattr(D.india, "market_status", lambda now=None: Status())
    monkeypatch.setattr(D.india, "cap_class", lambda s: "Mid")
    monkeypatch.setattr(D, "download_daily", lambda *a, **k: {"TESTCO.NS": df, "^NSEI": nifty})
    monkeypatch.setattr(D, "next_earnings_date", lambda s: None)
    monkeypatch.setattr(D, "_records", lambda inds, market, stamp: {
        n: {"all": {"trades": 0}, "12m": {"trades": 0}, "6m": {"trades": 0}} for n in S.STRATEGIES})
    r = D.run_daily(capital=500_000, risk_pct=1.0, top=10, with_news=False)
    assert r["as_of"] == str(last)
    assert len(r["ideas"]) == 1
    idea = r["ideas"][0]
    assert idea["symbol"] == "TESTCO.NS" and idea["cap"] == "Mid"
    assert idea["stop"] < idea["entry"] < idea["target"]
    assert idea["grade"] == "C" and idea["quantity"] > 0  # no positive record: half size
    assert idea["bull"] and idea["verdict"]


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
