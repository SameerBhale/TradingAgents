from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.vendors import nse_results, upstox
from tradingagents.scanner import data as data_mod, multibagger as MB, strategies as S

_XBRL = """<xbrli:xbrl>
<xbrli:context id="OneD"><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="FourD"><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="OneI"><xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period></xbrli:context>
<in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2024-01-01</in-capmkt:DateOfStartOfReportingPeriod>
<in-capmkt:DateOfEndOfReportingPeriod contextRef="OneD">2024-03-31</in-capmkt:DateOfEndOfReportingPeriod>
<in-capmkt:DateOfStartOfReportingPeriod contextRef="FourD">2023-04-01</in-capmkt:DateOfStartOfReportingPeriod>
<in-capmkt:DateOfEndOfReportingPeriod contextRef="FourD">2024-03-31</in-capmkt:DateOfEndOfReportingPeriod>
<in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-5">600.00</in-capmkt:RevenueFromOperations>
<in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-5">2400.00</in-capmkt:RevenueFromOperations>
<in-capmkt:ProfitLossForPeriod contextRef="FourD" unitRef="INR" decimals="-5">300.00</in-capmkt:ProfitLossForPeriod>
<in-capmkt:CashFlowsFromUsedInOperatingActivities contextRef="FourD" unitRef="INR">250.00</in-capmkt:CashFlowsFromUsedInOperatingActivities>
<in-capmkt:Equity contextRef="OneI" unitRef="INR">1000.00</in-capmkt:Equity>
<in-capmkt:NatureOfReportStandaloneConsolidated contextRef="FourD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
</xbrli:xbrl>"""


@pytest.mark.unit
def test_xbrl_reads_the_full_year_not_the_quarter():
    r = nse_results.parse_xbrl(_XBRL)
    assert r["fy_end"] == "2024-03-31"
    assert r["revenue"] == 2400.0 and r["profit"] == 300.0 and r["ocf"] == 250.0
    assert r["equity"] == 1000.0 and r["basis"] == "Consolidated"


@pytest.mark.unit
def test_merge_adds_official_years_only_on_the_same_basis():
    yahoo = {"sales": {"2023-03-31": 100.0, "2024-03-31": 120.0, "2025-03-31": 150.0},
             "profit": {"2023-03-31": 10.0, "2024-03-31": 13.0, "2025-03-31": 17.0}}
    same = [{"fy_end": "2021-03-31", "revenue": 70.0, "profit": 6.0},
            {"fy_end": "2022-03-31", "revenue": 85.0, "profit": 8.0},
            {"fy_end": "2023-03-31", "revenue": 102.0, "profit": 10.0}]
    m = MB.merge_history(yahoo, same)
    assert m["sales"] == [70.0, 85.0, 100.0, 120.0, 150.0]   # Yahoo wins on the shared year
    assert m["source"].startswith("NSE filings from FY2021")
    other = [{"fy_end": "2022-03-31", "revenue": 40.0}, {"fy_end": "2023-03-31", "revenue": 50.0}]  # standalone
    m = MB.merge_history(yahoo, other)
    assert m["sales"] == [100.0, 120.0, 150.0] and "different basis" in m["source"]


@pytest.mark.unit
def test_corporate_action_jump_is_detected_and_skipped():
    c = np.r_[np.linspace(100, 120, 50), np.linspace(45, 50, 30)]   # a demerger-style drop
    o = c.copy()
    assert S.jumps(o, c).sum() == 1
    idx = pd.bdate_range("2025-01-01", periods=len(c))
    df = pd.DataFrame({"Open": o, "High": c, "Low": c, "Close": c, "Volume": 1e6}, index=idx)
    assert S.has_jump(df) and not S.has_jump(df.iloc[:50])


@pytest.mark.unit
def test_upstox_candles_become_an_ohlcv_frame():
    candles = [["2026-11-04T00:00:00+05:30", 1301.9, 1318.9, 1296.0, 1311.0, 19451679, 0],
               ["2026-11-03T00:00:00+05:30", 1287.9, 1307.9, 1282.0, 1307.9, 42319913, 0]]
    df = upstox._frame(candles)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index[0] == pd.Timestamp("2026-11-03") and df["Close"].iloc[-1] == 1311.0
    assert upstox.equity_key("INE002A01018") == "NSE_EQ|INE002A01018"


@pytest.mark.unit
def test_crosscheck_replaces_a_bar_that_disagrees_with_nse(monkeypatch):
    idx = pd.to_datetime(["2026-11-04", "2026-11-05"])
    good = pd.DataFrame({"Open": [10, 10], "High": [11, 11], "Low": [9, 9], "Close": [10, 10.05], "Volume": [1, 1]},
                        index=idx, dtype=float)
    bad = good.copy()
    bad.loc[idx[-1], "Close"] = 12.0
    monkeypatch.setattr(data_mod.nse_bhav, "equity_bars",
                        lambda d: {"AAA": (10, 11, 9, 10.0, 5), "BBB": (10, 11, 9, 10.0, 5)})
    frames = {"AAA.NS": good, "BBB.NS": bad}
    assert data_mod._crosscheck(frames, date(2026, 11, 5)) == 1
    assert frames["BBB.NS"].loc[idx[-1], "Close"] == 10.0 and frames["AAA.NS"].loc[idx[-1], "Close"] == 10.05
