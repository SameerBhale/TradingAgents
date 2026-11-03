"""Calls log and review, allocation, value screen, the swing bands and the alerts."""

import json

import numpy as np
import pandas as pd
import pytest

from tradingagents import alerts, calls
from tradingagents.scanner import strategies as S


@pytest.mark.unit
def test_alerts_trigger_chase_value_and_positions():
    setups = {
        "swing": {"ideas": [
            {"symbol": "AAA.NS", "grade": "OK", "entry": 100.0, "max_entry": 103.0, "stop": 93.0, "target": 114.0,
             "strategy_label": "VCP", "verdict": "OK"},
            {"symbol": "BBB.NS", "grade": "GOOD", "entry": 50.0, "max_entry": 51.5, "stop": 47.0, "target": 56.0,
             "strategy_label": "Breakout", "verdict": "GOOD"},
            {"symbol": "CCC.NS", "grade": "AVOID", "entry": 10.0, "max_entry": 10.3, "stop": 9.0, "target": 12.0,
             "strategy_label": "Flag", "verdict": "AVOID"},
        ]},
        "value": {"picks": [{"symbol": "VVV.NS", "max_entry": 500.0, "stop": 450.0, "target": 600.0, "hold": "3-12m"}]},
    }
    quotes = {"AAA.NS": {"price": 101.0}, "BBB.NS": {"price": 53.0}, "CCC.NS": {"price": 10.1},
              "VVV.NS": {"price": 495.0}, "PPP.NS": {"price": 80.0}}
    keys = [a["key"] for a in alerts.check_alerts(
        setups, quotes, [{"symbol": "PPP.NS", "stop": 82.0, "target": 120.0, "entry_price": 90.0}])]
    assert keys == ["trig:AAA", "chase:BBB", "value:VVV", "stop:PPP"]  # AVOID ideas never alert


@pytest.mark.unit
def test_gap_alert_needs_gap_move_and_volume_pace():
    prev = {"G.NS": {"close": 100.0, "vol50": 1e6}}
    hit = alerts.gap_alerts({"G.NS": {"open": 105.0, "price": 108.0, "volume": 2e6}}, prev, 60)
    assert hit and hit[0]["key"] == "gap:G"
    assert not alerts.gap_alerts({"G.NS": {"open": 105.0, "price": 108.0, "volume": 2e5}}, prev, 60)
    assert not alerts.gap_alerts({"G.NS": {"open": 101.0, "price": 108.0, "volume": 2e6}}, prev, 60)


@pytest.mark.unit
def test_email_needs_gmail_settings(monkeypatch):
    monkeypatch.delenv("TA_GMAIL_USER", raising=False)
    monkeypatch.delenv("TA_GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="Gmail is not set up"):
        alerts.send_email("x", "y")
    assert "<table>" in alerts.md_to_html("| a | b |\n|---|---|\n| 1 | 2 |")


@pytest.mark.unit
def test_stop_band_keeps_stops_between_5_and_10_pct():
    row = pd.Series({"High": 100.0, "Low": 99.5, "atr": 0.5, "low5": 99.0, "low10": 98.0,
                     "high52_incl": 101.0, "Close": 100.0, "sma5": 100.5})
    row = pd.concat([row, pd.Series({"high10": 100.0, "ema20": 98.0})])
    for name in ("breakout", "vcp", "flag", "ep", "crossback"):
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
            {"rank": 1, "symbol": "AAA.NS", "grade": "GOOD", "entry": 100.0, "stop": 95.0, "target": 110.0,
             "exit_by": "2026-12-02"},
            {"rank": 2, "symbol": "BBB.NS", "grade": "OK", "entry": 200.0, "stop": 188.0, "target": 224.0,
             "exit_by": "2026-12-02"},
            {"rank": 3, "symbol": "CCC.NS", "grade": "AVOID", "entry": 50.0, "stop": 40.0, "target": 70.0,
             "exit_by": "2026-12-02"},
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
    assert "CCC.NS" not in syms  # AVOID is never sized
    a = r["rows"][0]
    assert a["qty"] == 200 and a["max_loss"] == 1000  # 1% of 1,00,000 / Rs 5 risk
    b = r["rows"][1]
    assert b["max_loss"] <= 500  # OK at half risk
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
    assert len(r["picks"]) <= 3
    for p in r["picks"]:
        assert 10.0 - 1e-6 <= p["risk_pct"] <= 15.0 + 1e-6
        assert p["target"] > p["entry"] > p["stop"]


@pytest.mark.unit
def test_live_status_words():
    i = {"entry": 100.0, "max_entry": 103.0, "stop": 93.0, "target": 114.0}
    assert alerts.swing_status(i, 98.0, 99.0).startswith("WAITING")
    assert alerts.swing_status(i, 101.0, 101.5).startswith("TRIGGERED: inside")
    assert alerts.swing_status(i, 105.0, 105.0).startswith("RAN PAST MAX")
    assert alerts.swing_status(i, 99.0, 101.0).startswith("TRIGGERED, then faded")
    assert alerts.swing_status(i, 92.0, 101.0) == "STOPLOSS HIT"
    assert alerts.swing_status(i, 115.0, 115.0) == "TARGET HIT"
    v = {"max_entry": 500.0, "stop": 450.0}
    assert alerts.value_status(v, 495.0) == "IN BUY ZONE"
    assert alerts.value_status(v, 520.0).startswith("ABOVE BUY ZONE")
