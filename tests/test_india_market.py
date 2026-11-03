"""The India market: NSE/BSE symbol resolution, the IST session clock and holidays."""

from datetime import date, datetime

import pytest

from tradingagents.dataflows import india
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.symbols import normalize_symbol, safe_ticker_component
from tradingagents.default_config import _apply_market, _build_base_config

IST = india.IST


@pytest.fixture
def india_market():
    with run_config({"market": "india"}):
        yield


@pytest.mark.unit
def test_bundled_universe_lists_every_segment():
    universe = india.nse_universe()
    assert len(universe) > 3000
    assert {s.segment for s in universe.values()} == {"EQUITY", "SME", "ETF"}
    for symbol in ("RELIANCE", "TCS", "HDFCBANK", "INFY", "M&M", "BAJAJ-AUTO", "NIFTYBEES"):
        assert symbol in universe, symbol


@pytest.mark.unit
def test_every_bundled_symbol_is_path_safe():
    for sec in india.nse_universe().values():
        safe_ticker_component(sec.yahoo)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("RELIANCE", "RELIANCE.NS"),
        ("reliance", "RELIANCE.NS"),
        ("M&M", "M&M.NS"),
        ("BAJAJ-AUTO", "BAJAJ-AUTO.NS"),
        ("TCS.NS", "TCS.NS"),
        ("NSE:TCS", "TCS.NS"),
        ("INFY.NSE", "INFY.NS"),
        ("BSE:RELIANCE", "RELIANCE.BO"),
        ("RELIANCE.BSE", "RELIANCE.BO"),
        ("RELIANCE.BO", "RELIANCE.BO"),
        ("NIFTY", "^NSEI"),
        ("BANKNIFTY", "^NSEBANK"),
        ("SENSEX", "^BSESN"),
        ("BTCUSD", "BTC-USD"),
        ("XAUUSD", "GC=F"),
        ("USDINR", "USDINR=X"),
    ],
)
def test_india_market_resolves_indian_symbols(india_market, raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.unit
def test_us_market_leaves_bare_symbols_alone():
    with run_config({"market": "us"}):
        assert normalize_symbol("RELIANCE") == "RELIANCE"
        # Exchange-qualified forms and index names are unambiguous in any market.
        assert normalize_symbol("NSE:TCS") == "TCS.NS"
        assert normalize_symbol("NIFTY") == "^NSEI"


@pytest.mark.unit
def test_bse_scrip_codes_get_a_pointer_not_a_guess(india_market):
    assert normalize_symbol("500325") == "500325"
    assert "RELIANCE.BO" in india.bse_code_hint("500325")
    assert india.bse_code_hint("BSE:500325")
    assert india.bse_code_hint("RELIANCE") is None


@pytest.mark.unit
def test_unknown_bare_symbol_is_left_unchanged(india_market):
    assert normalize_symbol("AAPL") == "AAPL"


@pytest.mark.unit
def test_india_preset_sets_benchmark_vendors_and_news():
    config = _apply_market(_build_base_config() | {"market": "india"})
    assert config["benchmark_map"][""] == "^NSEI"
    assert config["benchmark_map"][".NS"] == "^NSEI"
    assert config["data_vendors"]["fundamental_data"] == "yfinance"
    assert config["data_vendors"]["core_stock_apis"] == "yfinance"
    assert any("RBI" in q for q in config["global_news_queries"])
    assert config["market_timezone"] == "Asia/Kolkata"


@pytest.mark.unit
def test_us_market_keeps_upstream_defaults():
    config = _apply_market(_build_base_config() | {"market": "us"})
    assert config["benchmark_map"][""] == "SPY"
    assert config["data_vendors"]["fundamental_data"] == "sec_edgar,yfinance"


@pytest.mark.unit
def test_unknown_market_is_refused():
    with pytest.raises(ValueError):
        _apply_market({"market": "mars"})


@pytest.mark.unit
@pytest.mark.parametrize(
    "clock, phase",
    [
        ("08:59", "closed"),
        ("09:00", "pre-open"),
        ("09:14", "pre-open"),
        ("09:15", "open"),
        ("15:29", "open"),
        ("15:30", "closing"),
        ("15:45", "post-close"),
        ("16:00", "closed"),
    ],
)
def test_session_phases_follow_ist(clock, phase):
    hh, mm = map(int, clock.split(":"))
    # Wednesday 4 November 2026, an ordinary trading day.
    status = india.market_status(datetime(2026, 11, 4, hh, mm, tzinfo=IST))
    assert status.phase == phase


@pytest.mark.unit
def test_status_from_another_time_zone_reads_ist():
    from datetime import timedelta, timezone

    new_york = timezone(timedelta(hours=-5))
    # 23:00 on Tuesday in New York is 09:30 Wednesday in India.
    status = india.market_status(datetime(2026, 11, 3, 23, 0, tzinfo=new_york))
    assert status.phase == "open"
    assert status.now.date() == date(2026, 11, 4)


@pytest.mark.unit
def test_holidays_and_weekends_are_not_trading_days():
    assert not india.is_trading_day(date(2026, 1, 26))  # Republic Day
    assert not india.is_trading_day(date(2026, 11, 10))  # Diwali Balipratipada
    assert not india.is_trading_day(date(2026, 11, 7))  # Saturday
    assert india.is_trading_day(date(2026, 11, 9))


@pytest.mark.unit
def test_next_open_skips_holidays():
    # Monday 9 Nov after the close: Tuesday 10 Nov is a holiday.
    status = india.market_status(datetime(2026, 11, 9, 17, 0, tzinfo=IST))
    assert status.next_open == datetime(2026, 11, 11, 9, 15, tzinfo=IST)
    assert status.last_completed_session == date(2026, 11, 9)


@pytest.mark.unit
def test_last_completed_session_before_settlement():
    status = india.market_status(datetime(2026, 11, 9, 12, 0, tzinfo=IST))
    assert status.last_completed_session == date(2026, 11, 6)


@pytest.mark.unit
def test_session_settles_at_four_pm_ist():
    day = date(2026, 11, 4)
    assert not india.session_settled(day, datetime(2026, 11, 4, 15, 59, tzinfo=IST))
    assert india.session_settled(day, datetime(2026, 11, 4, 16, 0, tzinfo=IST))


@pytest.mark.unit
def test_current_date_is_ist(monkeypatch, india_market):
    from tradingagents.dataflows import date_window

    monkeypatch.setattr(india, "today_ist", lambda: date(2026, 11, 4))
    assert date_window.get_current_date() == "2026-11-04"


@pytest.mark.unit
def test_instrument_context_carries_the_indian_market_note():
    from tradingagents.agents.context import build_instrument_context

    context = build_instrument_context("RELIANCE.NS")
    assert "National Stock Exchange of India" in context
    assert "09:15-15:30 IST" in context
    assert "INR" in context
    assert "India" not in build_instrument_context("AAPL")


@pytest.mark.unit
def test_search_finds_symbol_and_name_matches():
    assert india.search("RELIANCE")[0].symbol == "RELIANCE"
    assert any(s.symbol == "TCS" for s in india.search("Tata Consultancy"))


@pytest.mark.unit
def test_graph_entry_qualifies_bare_indian_symbols():
    from tradingagents.graph.trading_graph import _indian_listing

    with run_config({"market": "india"}):
        assert _indian_listing("RELIANCE", "stock") == "RELIANCE.NS"
        assert _indian_listing("BTC-USD", "crypto") == "BTC-USD"
    with run_config({"market": "us"}):
        assert _indian_listing("RELIANCE", "stock") == "RELIANCE"
