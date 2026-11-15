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
    raw=json.dumps([line("E-MINI S&P 500 STOCK INDEX","2026-11-03T00:00:00"),
                    line("S&P 500 STOCK INDEX","2026-11-03T00:00:00"),
                    line("E-MINI S&P 500 STOCK INDEX","2026-11-10T00:00:00")]).encode()
    assert "sp500" not in parse_cftc_tff(raw,"2026-11-15")


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
