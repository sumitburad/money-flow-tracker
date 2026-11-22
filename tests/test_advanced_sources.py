import json
from datetime import date
from backend.advanced_sources import (parse_cftc_tff, parse_ecb_ilm,
  fetch_fred_mirror, breadth_from_equal_weight)


def test_cftc_auditable_weekly_and_future_guard():
    def line(dt,long,short):
        return {"market_and_exchange_names":"E-MINI S&P 500 STOCK INDEX",
          "report_date_as_yyyy_mm_dd":dt, "asset_mgr_positions_long":str(long),
          "asset_mgr_positions_short":str(short), "open_interest_all":"1000"}
    raw = json.dumps([line("2026-11-03T00:00:00.000",400,300),
                      line("2026-11-10T00:00:00.000",500,350),
                      line("2026-11-13T00:00:00.000",900,50)]).encode()
    x=parse_cftc_tff(raw,"2026-11-15")
    assert x["sp500"]["state"]=="supportive"
    assert x["sp500"]["observation_date"]=="2026-11-10"
    assert x["sp500"]["report_date_not_release_date"]


def test_cftc_multiple_contracts_same_day_quarantined():
    def line(name,date):
        return {"market_and_exchange_names":name,
                "report_date_as_yyyy_mm_dd":date,
                "asset_mgr_positions_long":"100",
                "asset_mgr_positions_short":"90","open_interest_all":"1000"}
    # the old and the new name of one contract on the same day cannot be added together safely
    raw=json.dumps([line("E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE","2026-11-03T00:00:00"),
                    line("E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE","2026-11-03T00:00:00"),
                    line("E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE","2026-11-10T00:00:00")]).encode()
    assert "sp500" not in parse_cftc_tff(raw,"2026-11-15")


# Real contract names from data/history/v1/cftc/contracts_seen.json (what the exchange published
# between November 2021 and November 2026), each with the market it must match, or None for the
# look-alikes that must never be picked. The exchange renamed the main contracts in February 2022.
REAL_CONTRACTS = {
    "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE": "sp500",
    "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE": "sp500",
    "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE": "nasdaq100",
    "NASDAQ-100 STOCK INDEX (MINI) - CHICAGO MERCANTILE EXCHANGE": "nasdaq100",
    "UST 10Y NOTE - CHICAGO BOARD OF TRADE": "us_treasury",
    "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE": "us_treasury",
    "USD INDEX - ICE FUTURES U.S.": "dollar",
    "U.S. DOLLAR INDEX - ICE FUTURES U.S.": "dollar",
    "MICRO E-MINI S&P 500 INDEX - CHICAGO MERCANTILE EXCHANGE": None,
    "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE": None,
    "S&P 500 ANNUAL DIVIDEND INDEX - CHICAGO MERCANTILE EXCHANGE": None,
    "S&P 500 QUARTERLY DIVIDEND IND - CHICAGO MERCANTILE EXCHANGE": None,
    "ADJUSTED INT RATE S&P 500 TOTL - CHICAGO MERCANTILE EXCHANGE": None,
    "E-MINI S&P INDUSTRIAL INDEX - CHICAGO MERCANTILE EXCHANGE": None,
    "E-MINI S&P 400 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE": None,
    "MICRO E-MINI NASDAQ-100 INDEX - CHICAGO MERCANTILE EXCHANGE": None,
    "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE": None,
    "ULTRA UST 10Y - CHICAGO BOARD OF TRADE": None,
    "ULTRA U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE": None,
    "UST 2Y NOTE - CHICAGO BOARD OF TRADE": None,
    "UST 5Y NOTE - CHICAGO BOARD OF TRADE": None,
    "UST BOND - CHICAGO BOARD OF TRADE": None,
    "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": None,
}


def test_each_market_matches_one_real_contract_and_no_look_alike():
    import re
    from backend.advanced_sources import CFTC_MARKETS
    for name, expected in REAL_CONTRACTS.items():
        matched = [market for market, patterns in CFTC_MARKETS.items()
                   if any(re.search(p, name.upper().strip()) for p in patterns)]
        assert matched == ([expected] if expected else []), name


def test_the_daily_reading_finds_all_four_markets_among_the_real_contract_names():
    def line(name, day, long, short):
        return {"market_and_exchange_names": name, "report_date_as_yyyy_mm_dd": day,
                "asset_mgr_positions_long": str(long), "asset_mgr_positions_short": str(short),
                "open_interest_all": "5000"}
    current = [n for n in REAL_CONTRACTS if n not in (
        "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
        "NASDAQ-100 STOCK INDEX (MINI) - CHICAGO MERCANTILE EXCHANGE",
        "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
        "U.S. DOLLAR INDEX - ICE FUTURES U.S.")]          # the pre-2022 names are not published now
    rows = []
    for name in current:
        rows.append(line(name, "2026-11-03T00:00:00.000", 400, 300))
        rows.append(line(name, "2026-11-10T00:00:00.000", 450, 300))   # net position up by 50 everywhere
    found = parse_cftc_tff(json.dumps(rows).encode(), "2026-11-15")
    assert set(found) == {"sp500", "nasdaq100", "us_treasury", "dollar"}
    assert found["sp500"]["market"] == "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"
    assert found["nasdaq100"]["market"] == "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE"
    assert found["us_treasury"]["market"] == "UST 10Y NOTE - CHICAGO BOARD OF TRADE"
    assert found["dollar"]["market"] == "USD INDEX - ICE FUTURES U.S."
    assert all(entry["state"] == "supportive" for entry in found.values())


def test_a_market_with_no_matching_contract_is_reported_not_silent():
    from backend.advanced_sources import cftc_gaps
    shown = {"sp500", "nasdaq100", "us_treasury", "dollar", "gold"}
    assert cftc_gaps({"dollar": {}}, shown) == ["sp500", "nasdaq100", "us_treasury"]
    assert cftc_gaps({"sp500": {}, "nasdaq100": {}, "us_treasury": {}, "dollar": {}}, shown) == []
    assert cftc_gaps(None, {"sp500"}) == ["sp500"]
    assert cftc_gaps({}, {"gold"}) == []          # markets this dashboard does not show are not reported


def test_ecb_exact_series_and_weekly_date():
    raw=("KEY,TIME_PERIOD,OBS_VALUE\n"
         "ILM.W.U2.C.T000000.Z5.Z01,2026-W44,6135000\n"
         "ILM.W.U2.C.T000000.Z5.Z01,2026-W45,6137000\n").encode()
    x=parse_ecb_ilm(raw,"2026-11-15")
    assert len(x)==2 and x[-1]["value"]==6137000
    import pytest
    with pytest.raises(ValueError,match="match requested"):
        parse_ecb_ilm(b"KEY,TIME_PERIOD,OBS_VALUE\nother,2026-W45,123\n","2026-11-15")


def test_reject_wrong_fred_mirror_series(tmp_path):
    import pytest
    class R:
        content=json.dumps({"series":{"docs":[{"series_code":"WRONG",
           "period":["2026-11-10"],"value":[100]}]}}).encode()
        def raise_for_status(self): pass
    class H:
        def get(self,*args,**kwargs): return R()
    with pytest.raises(ValueError,match="identity"):
        fetch_fred_mirror("WALCL",tmp_path,"2026-11-15",http=H())
    with pytest.raises(ValueError,match="unverified"):
        fetch_fred_mirror("IND_RBI_LIQUIDITY",tmp_path,"2026-11-15",http=H())
