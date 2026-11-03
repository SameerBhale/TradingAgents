"""Auditor, calls log and review, allocation, value screen and the swing bands."""

import json

import numpy as np
import pandas as pd
import pytest

from tradingagents import calls
from tradingagents.scanner import audit, strategies as S


def _idea(**kw):
    base = {"risk_pct": 5.0, "reward_pct": 10.0, "rr": 2.0, "grade": "A", "verdict": "TAKE", "cap": "Large",
            "earnings_in_window": False, "earnings_date": None, "news_flag": "neutral", "quantity": 10}
    return {**base, **kw}


MARKET = {"filter_on": True, "nifty": 110, "nifty_sma200": 100}


@pytest.mark.unit
def test_auditor_correct_questionable_wrong():
    assert audit.audit_swing(_idea(), MARKET)["status"] == "CORRECT"
    assert audit.audit_swing(_idea(cap="Small"), MARKET)["status"] == "QUESTIONABLE"
    wrong = audit.audit_swing(_idea(risk_pct=12.0, reward_pct=24.0), MARKET)
    assert wrong["status"] == "WRONG" and len(wrong["wrong"]) == 2
    assert audit.audit_swing(_idea(grade="C", verdict="TAKE"), MARKET)["status"] == "WRONG"
    assert audit.audit_swing(_idea(earnings_in_window=True, earnings_date="2026-11-07"), MARKET)["status"] == "WRONG"


@pytest.mark.unit
def test_stop_band_keeps_stops_between_5_and_10_pct():
    row = pd.Series({"High": 100.0, "Low": 99.5, "atr": 0.5, "low5": 99.0, "low10": 98.0,
                     "high52_incl": 101.0, "Close": 100.0, "sma5": 100.5})
    for name in ("breakout", "pullback", "pivot"):
        s = S.setup_for(name, row)
        assert 5.0 - 1e-6 <= s.risk_pct <= 10.0 + 1e-6, (name, s.risk_pct)
        reward = (s.target / s.entry - 1) * 100
        assert 10.0 - 0.05 <= reward <= 20.0 + 0.05


def _bars(prices, start="2026-10-01"):
    idx = pd.bdate_range(start, periods=len(prices))
    p = np.asarray(prices, dtype=float)
    return pd.DataFrame({"Open": p, "High": p * 1.01, "Low": p * 0.99, "Close": p}, index=idx)


@pytest.mark.unit
def test_call_outcomes():
    call = {"as_of": "2026-10-01", "entry_type": "stop", "entry": 101.0, "stop": 96.0, "target": 111.0,
            "hold_sessions": 20}
    up = _bars([100, 102, 105, 108, 112, 115] + [115] * 20)
    assert calls.outcome(call, up)["status"] == "target"
    down = _bars([100, 102, 99, 95, 94] + [94] * 20)
    assert calls.outcome(call, down)["status"] == "stop"
    flat = _bars([100, 99, 99, 99] + [99] * 20)
    assert calls.outcome(call, flat)["status"] == "not triggered"


@pytest.mark.unit
def test_calls_record_dedupe_feedback_and_review(tmp_path):
    path = str(tmp_path / "calls.jsonl")
    setups = {
        "as_of": "2026-10-01",
        "swing": {"ideas": [{"symbol": "AAA.NS", "strategy": "breakout", "grade": "A", "cap": "Large",
                             "entry_type": "stop", "entry": 101.0, "stop": 96.0, "target": 111.0,
                             "hold_sessions": 20, "verdict": "TAKE", "audit": {"status": "CORRECT"}}]},
        "value": {"picks": []},
        "core": {"picks": [{"symbol": "BBB.NS", "action": "BUY", "cap": "Mid", "close": 50.0, "stop": 42.5,
                            "audit": {"status": "CORRECT"}}]},
    }
    assert calls.record(setups, path) == 2
    assert calls.record(setups, path) == 0  # same day, same calls: not logged twice
    calls.feedback("AAA", "entry was late", "bad", path=path)
    rep = calls.review({"AAA.NS": _bars([100, 102, 105, 108, 112] + [112] * 20),
                        "BBB.NS": _bars([50] * 30)}, path)
    assert rep["calls"] == 2
    assert rep["by_grade"]["A"]["win_rate"] == 100
    assert rep["feedback"][0]["feedback"][0]["note"] == "entry was late"


@pytest.mark.unit
def test_allocate_swing_and_core(tmp_path, monkeypatch):
    import cli.setups as cs

    saved = {
        "as_of": "2026-11-03",
        "swing": {"ideas": [
            {"rank": 1, "symbol": "AAA.NS", "grade": "A", "entry": 100.0, "stop": 95.0, "target": 110.0,
             "exit_by": "2026-12-02", "audit": {"status": "CORRECT"}},
            {"rank": 2, "symbol": "BBB.NS", "grade": "C", "entry": 200.0, "stop": 188.0, "target": 224.0,
             "exit_by": "2026-12-02", "audit": {"status": "QUESTIONABLE"}},
            {"rank": 3, "symbol": "CCC.NS", "grade": "A", "entry": 50.0, "stop": 40.0, "target": 70.0,
             "exit_by": "2026-12-02", "audit": {"status": "WRONG"}},
        ]},
        "core": {"invested_pct": 50, "picks": [
            {"rank": 1, "symbol": "M1.NS", "action": "BUY (half size)", "max_entry": 101.0, "close": 100.0,
             "review_on": "2026-11-30"}]},
        "value": {"picks": []},
    }
    (tmp_path / "setups-2026-11-03.json").write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(cs, "scans_dir", lambda: str(tmp_path))
    r = cs.allocate(100_000, "swing", None, 1.0)
    syms = [x["symbol"] for x in r["rows"]]
    assert "CCC.NS" not in syms  # the auditor said WRONG
    a = r["rows"][0]
    assert a["qty"] == 200 and a["max_loss"] == 1000  # 1% of 1,00,000 / Rs 5 risk
    b = r["rows"][1]
    assert b["max_loss"] <= 500  # grade C at half risk
    core = cs.allocate(100_000, "core", None, 1.0)
    assert core["rows"][0]["qty"] == int(100_000 * 0.5 // 101.0)


@pytest.mark.unit
def test_value_screen_scores_and_plans(monkeypatch):
    from tradingagents.scanner import value as V
    from tradingagents.scanner.data import MarketData

    idx = pd.bdate_range("2025-01-01", periods=300)
    stocks, secs, funds = {}, {}, {}
    for k, (pe, roe) in enumerate([(10, 0.25), (30, 0.30), (12, 0.08), (15, 0.20)]):
        c = np.linspace(100, 160, 300)
        stocks[f"V{k}.NS"] = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                                            "Volume": np.full(300, 2e6)}, index=idx)
        funds[f"V{k}.NS"] = {"trailingPE": pe, "returnOnEquity": roe, "debtToEquity": 20, "revenueGrowth": 0.2,
                             "earningsGrowth": 0.25, "operatingMargins": 0.18, "priceToBook": 2.0}
    nifty = stocks["V0.NS"].copy()
    md = MarketData(stocks, {}, nifty, idx[-1].date(), idx[-1].date(), secs)
    monkeypatch.setattr(V, "fundamentals_snapshot", lambda syms, stamp: {s: funds[s] for s in syms})
    monkeypatch.setattr(V.india, "industry", lambda s: "Test sector")
    monkeypatch.setattr(V.india, "cap_class", lambda s: "Mid")
    r = V.value_picks(md, top=5, with_news=False)
    syms = [p["symbol"] for p in r["picks"]]
    assert "V2.NS" not in syms  # ROE 8%: fails quality
    assert "V1.NS" not in syms  # PEG 30/25 = 1.2 passes, but P/E 30 is above the sector median
    for p in r["picks"]:
        assert 5.0 - 1e-6 <= p["risk_pct"] <= 10.0 + 1e-6
        assert p["target"] > p["entry"] > p["stop"]
