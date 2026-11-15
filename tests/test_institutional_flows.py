import hashlib
import json
from datetime import datetime,timezone
import pytest
from backend.institutional_flows import (
    collect_upstox_cash,parse_upstox_cash, validate_official_download,
    institutional_status, NSDL_FINAL_REPORT
)


def timestamp(day):
    d=datetime.fromisoformat(day+"T12:00:00+05:30")
    return int(d.timestamp()*1000)


def test_no_token_does_not_scrape_nse():
    class H:
        def get(self,*a,**k): raise AssertionError("must not fetch without key")
    x=collect_upstox_cash("2026-11-15",token="",http=H())
    assert x["status"]=="not_configured"
    assert institutional_status("2026-11-15",token="",http=H())["complete_verified_institutional_flows"] is False


def test_cash_is_separate_from_nsdl_final_and_numbers_stay_private():
    raw=json.dumps({"status":"success","data":{"NSE_EQ|CASH":[{
      "time_stamp":timestamp("2026-11-13"),"buy_amount":250000000,
      "sell_amount":210000000}]}}).encode()
    row=parse_upstox_cash(raw,"FPI","2026-11-15")[0]
    assert row["direction"]=="net_buying"
    assert row["currency_unit"]=="INR_NOT_CRORE"
    assert "buy_amount" not in row and "net_amount" not in row
    assert row["not_final_fpi_investments"]


def test_hash_and_explicit_manifest_review_are_required():
    raw=b"Date,Net\n2026-11-13,100\n"
    m={"provider":"NSDL","origin_url":NSDL_FINAL_REPORT,
       "observation_date":"2026-11-13","data_scope":"equity",
       "collected_at_utc":"2026-11-15T09:00:00Z","raw_sha256":hashlib.sha256(raw).hexdigest()}
    record=validate_official_download(raw,m,run_day="2026-11-15")
    assert record["proof_of_authenticity"] is False
    m["raw_sha256"]="0"*64
    with pytest.raises(ValueError,match="hash"):
        validate_official_download(raw,m,run_day="2026-11-15")


def test_reject_future_or_duplicate_cash_dates():
    future=json.dumps({"status":"success","data":{"NSE_EQ|CASH":[{
       "time_stamp":timestamp("2026-11-16"),"buy_amount":10,"sell_amount":4}]}}).encode()
    with pytest.raises(ValueError,match="future"):
        parse_upstox_cash(future,"FPI","2026-11-15")
