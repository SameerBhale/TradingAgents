import numpy as np
import pandas as pd
import pytest

from tradingagents.scanner import multibagger as MB, strategies as S


def _uptrend(n=300, start=100.0, end=200.0):
    c = np.linspace(start, end, n)
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c,
                         "Volume": np.full(n, 1e6)}, index=idx)


GOOD_F = {"marketCap": 5_000 * MB.CR, "returnOnEquity": 0.25, "debtToEquity": 20.0, "operatingMargins": 0.18,
          "trailingPE": 30.0, "heldPercentInsiders": 0.55, "revenueGrowth": 0.2}
GOOD_H = {"sales": [100.0, 125.0, 160.0, 200.0], "profit": [10.0, 14.0, 20.0, 27.0],
          "ocf": [8.0, 11.0, 15.0], "fcf": [2.0, 4.0, 6.0]}


@pytest.mark.unit
def test_a_compounder_passes_every_check():
    res = MB.evaluate("ABC.NS", S.indicators(_uptrend()), GOOD_F, GOOD_H)
    assert res["passes"], res["fails"]
    assert res["sales_cagr_pct"] == pytest.approx(26.0, abs=0.5)
    assert res["profit_cagr_pct"] == pytest.approx(39.2, abs=0.5)
    assert res["peg"] == pytest.approx(30 / 39.2, abs=0.02)


@pytest.mark.unit
def test_a_one_off_year_or_a_falling_chart_fails():
    lumpy = {**GOOD_H, "sales": [100.0, 140.0, 130.0, 200.0]}  # a down year
    assert "sales did not grow every year" in MB.evaluate("X.NS", S.indicators(_uptrend()), GOOD_F, lumpy)["fails"]
    falling = MB.evaluate("X.NS", S.indicators(_uptrend(start=200, end=100)), GOOD_F, GOOD_H)
    assert any(f.startswith("chart") for f in falling["fails"])
    big = MB.evaluate("X.NS", S.indicators(_uptrend()), {**GOOD_F, "marketCap": 90_000 * MB.CR}, GOOD_H)
    assert any("market cap" in f for f in big["fails"])


@pytest.mark.unit
def test_the_list_adds_holds_and_removes(tmp_path, monkeypatch):
    path = str(tmp_path / "mb.json")
    df = _uptrend()
    nifty = _uptrend()
    sec = MB.india.IndianSecurity("ABC", "Abc Limited", "EQ", "EQUITY", "INE000000001", "2000-01-01")

    class MD:
        stocks = {"ABC.NS": df}
        micro = {}
        securities = {"ABC.NS": sec}
        last = df.index[-1].date()

    MD.nifty = nifty
    funds = {"ABC.NS": dict(GOOD_F)}
    monkeypatch.setattr(MB, "fundamentals_snapshot", lambda syms, stamp: {s: funds.get(s, {}) for s in syms})
    monkeypatch.setattr(MB, "annual_history", lambda syms, stamp: {s: GOOD_H for s in syms})
    monkeypatch.setattr(MB.india, "cap_class", lambda s: "Small")
    r = MB.update(MD, path=path)
    assert r["added"] == ["ABC.NS"] and r["rows"][0]["status"] == "NEW"
    r = MB.update(MD, path=path)
    assert r["added"] == [] and r["rows"][0]["status"] == "HOLD"
    funds["ABC.NS"]["returnOnEquity"] = 0.08  # the story breaks
    r = MB.update(MD, path=path)
    assert r["removed"] == ["ABC.NS"] and not r["rows"]
    assert "ROE fell" in MB.load_list(path)["removed"][-1]["reason"]
