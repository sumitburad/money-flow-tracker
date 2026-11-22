"""Official history loader: files, availability dates, failure handling, secrecy."""
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("backfill", ROOT / "scripts" / "backfill_official.py")
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 2, 0, tzinfo=timezone.utc)
CONFIG = yaml.safe_load((ROOT / "config" / "history.yaml").read_text())


class Resp:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content


def fred_csv(series_id):
    return ("observation_date,%s\n2021-11-19,9.9\n2021-11-22,1.5\n2021-11-23,1.6\n"
            "2021-11-24,.\n2026-11-12,4.1\n2026-11-30,7.7\n" % series_id).encode()


TREASURY_ROWS = "Date,1 Mo,3 Mo,2 Yr,10 Yr,30 Yr\n%s\n"
CFTC_ROWS = [
    {"market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
     "report_date_as_yyyy_mm_dd": "2026-11-10T00:00:00.000", "asset_mgr_positions_long": "300",
     "asset_mgr_positions_short": "100", "open_interest_all": "1000"},
    {"market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
     "report_date_as_yyyy_mm_dd": "2026-11-17T00:00:00.000", "asset_mgr_positions_long": "320",
     "asset_mgr_positions_short": "90", "open_interest_all": "1010"},
    {"market_and_exchange_names": "USD INDEX - ICE FUTURES U.S.",
     "report_date_as_yyyy_mm_dd": "2026-11-17T00:00:00.000", "asset_mgr_positions_long": "50",
     "asset_mgr_positions_short": "20", "open_interest_all": "400"},
    {"market_and_exchange_names": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
     "report_date_as_yyyy_mm_dd": "2026-11-17T00:00:00.000", "asset_mgr_positions_long": "500",
     "asset_mgr_positions_short": "700", "open_interest_all": "3000"},
]


class Router:
    """Plays the part of every public website. ``fail`` lists hosts that must break."""

    def __init__(self, fail=(), dbnomics=None):
        self.fail, self.calls, self.dbnomics = set(fail), [], dbnomics

    def get(self, url, params=None, timeout=None, headers=None, **kw):
        params = params or {}
        self.calls.append((url, dict(params)))
        for host in self.fail:
            if host in url and not (host == "fred.stlouisfed.org" and "api.stlouisfed" in url):
                return Resp(503, b"")
        if url == backfill.FRED_API_URL:
            body = json.dumps({"observations": [
                {"date": "2021-11-22", "value": "1.5"}, {"date": "2026-11-12", "value": "4.1"}]})
            return Resp(200, body.encode())
        if url == backfill.FRED_CSV_URL:
            return Resp(200, fred_csv(params["id"]))
        if url.startswith(backfill.DBNOMICS_URL):
            sid = url.rsplit("/", 1)[1]
            return Resp(200, json.dumps({"series": {"docs": [{
                "series_code": sid, "period_start_day": ["2021-11-22", "2026-11-12"],
                "value": [1.5, "NA"]}]}}).encode())
        if url.startswith(backfill.TREASURY_BASE):
            year = int(params["field_tdr_date_value"])
            day = "11/22/2021" if year == 2021 else "01/04/%d" % year
            return Resp(200, (TREASURY_ROWS % ("%s,5.0,0.05,0.55,1.54,1.88" % day)).encode())
        if url == backfill.CFTC_URL:
            return Resp(200, json.dumps(CFTC_ROWS).encode())
        return Resp(404, b"")


def go(tmp_path, http=None, key="", only=None, now=NOW):
    return backfill.run(CONFIG, tmp_path, http or Router(), TODAY, api_key=key,
                        only=only, now=now)


def test_config_is_valid_and_has_no_price_series():
    assert CONFIG["start_date"] == "2021-11-22"
    names = " ".join(CONFIG["fred"]).upper()
    assert all(bad not in names for bad in ("SP500", "NASDAQ", "VIX", "DJIA", "WILL"))
    for meta in CONFIG["fred"].values():
        assert set(meta["lag"]) <= {"business_days", "calendar_days"}


def test_business_day_lag_skips_weekends():
    friday = date(2026, 11, 20)
    assert backfill.add_business_days(friday, 1) == date(2026, 11, 23)
    assert backfill.add_business_days(friday, 2) == date(2026, 11, 24)
    assert backfill.available_from(date(2026, 11, 18), {"calendar_days": 3}) == date(2026, 11, 21)


def test_fred_csv_range_and_missing_values():
    rows = backfill.parse_fred_csv(fred_csv("DGS2"), "DGS2", date(2021, 11, 22), TODAY)
    assert rows == [(date(2021, 11, 22), 1.5), (date(2021, 11, 23), 1.6), (date(2026, 11, 12), 4.1)]


def test_full_run_writes_csv_files_with_availability_dates(tmp_path):
    result = go(tmp_path)
    assert result["problems"] == [] and result["exit_code"] == 0
    lines = (tmp_path / "fred" / "DGS10.csv").read_text().splitlines()
    assert lines[0] == "observation_date,value,available_from_estimate"
    # 2021-11-22 is a Monday: two business days later is Wednesday the 24th
    assert lines[1] == "2021-11-22,1.5,2021-11-24"
    treasury = (tmp_path / "treasury" / "UST_PAR_2Y.csv").read_text().splitlines()
    assert treasury[1] == "2021-11-22,0.55,2021-11-23"
    assert (tmp_path / "treasury" / "UST_PAR_30Y.csv").is_file()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["no_price_data"] is True and manifest["start_date"] == "2021-11-22"
    by_id = {e["id"]: e for e in manifest["series"]}
    assert by_id["DGS10"]["first_observation"] == "2021-11-22"
    assert by_id["DGS10"]["transport"] == "fred_csv"
    assert "available_from_estimate" in manifest["availability_basis"]


def test_rows_outside_the_range_never_appear(tmp_path):
    go(tmp_path)
    text = (tmp_path / "fred" / "DGS10.csv").read_text()
    assert "2021-11-19" not in text and "2026-11-30" not in text


def test_cftc_net_positions_and_unmatched_markets(tmp_path):
    result = go(tmp_path)
    lines = (tmp_path / "cftc" / "sp500.csv").read_text().splitlines()
    assert lines[0].startswith("report_date,contract,asset_mgr_long")
    assert lines[1].split(",")[0:2] == ["2026-11-10", "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"]
    assert lines[1].split(",")[4] == "200.0"            # 300 - 100
    assert lines[1].split(",")[6] == "2026-11-14"       # Tuesday + 4 days, conservative
    by_id = {e["id"]: e for e in result["manifest"]["series"]}
    assert by_id["CFTC_TFF_us_treasury"]["status"] == "no_matching_contract"
    seen = json.loads((tmp_path / "cftc" / "contracts_seen.json").read_text())["contracts"]
    assert "UST 10Y NOTE - CHICAGO BOARD OF TRADE" in seen


def test_cftc_cards_use_plain_market_names(tmp_path):
    manifest = go(tmp_path)["manifest"]
    titles = {e["id"]: e["title"] for e in manifest["series"]}
    assert titles["CFTC_TFF_sp500"] == "Asset-manager net futures position: S&P 500"
    assert titles["CFTC_TFF_nasdaq100"] == "Asset-manager net futures position: Nasdaq-100"
    assert "us_treasury" not in " ".join(titles.values())


def test_second_identical_run_changes_no_files(tmp_path):
    go(tmp_path)
    assert go(tmp_path)["files_changed"] == 0


def test_failed_series_keeps_previous_good_file(tmp_path):
    go(tmp_path)
    before = (tmp_path / "fred" / "DGS10.csv").read_text()
    broken = Router(fail=["stlouisfed.org", "db.nomics.world"])
    result = go(tmp_path, http=broken, only=["fred"])
    assert result["exit_code"] == 1 and result["good"] == 0
    assert (tmp_path / "fred" / "DGS10.csv").read_text() == before
    by_id = {e["id"]: e for e in result["manifest"]["series"]}
    assert by_id["DGS10"]["status"] == "kept_previous"
    assert by_id["DGS10"]["last_error"]
    assert by_id["DGS10"]["rows"] == 3


def test_series_that_never_loaded_stays_missing_on_repeat_failures(tmp_path):
    broken = Router(fail=["stlouisfed.org", "db.nomics.world"])
    for _ in range(2):
        result = go(tmp_path, http=broken, only=["fred"])
        by_id = {e["id"]: e for e in result["manifest"]["series"]}
        assert by_id["DGS10"]["status"] == "missing"
        assert "file" not in by_id["DGS10"]
    assert not (tmp_path / "fred" / "DGS10.csv").exists()


def test_kept_previous_needs_the_old_file_to_still_exist(tmp_path):
    go(tmp_path)
    (tmp_path / "fred" / "DGS10.csv").unlink()
    result = go(tmp_path, http=Router(fail=["stlouisfed.org", "db.nomics.world"]), only=["fred"])
    by_id = {e["id"]: e for e in result["manifest"]["series"]}
    assert by_id["DGS10"]["status"] == "missing"
    assert by_id["DGS2"]["status"] == "kept_previous"


def test_running_one_group_keeps_the_other_groups_in_the_manifest(tmp_path):
    go(tmp_path)
    result = go(tmp_path, only=["fred"])
    ids = {e["id"] for e in result["manifest"]["series"]}
    assert {"DGS10", "UST_PAR_10Y", "CFTC_TFF_sp500", "CFTC_TFF_nasdaq100"} <= ids


def test_partial_failure_is_reported_with_exit_code_3(tmp_path):
    result = go(tmp_path, http=Router(fail=["home.treasury.gov"]))
    assert result["exit_code"] == 3
    assert any(p["series"] == "UST_PAR_10Y" for p in result["problems"])
    assert (tmp_path / "fred" / "DGS10.csv").is_file()


def test_falls_back_to_dbnomics_when_fred_is_down(tmp_path):
    result = go(tmp_path, http=Router(fail=["fred.stlouisfed.org"]), only=["fred"])
    by_id = {e["id"]: e for e in result["manifest"]["series"]}
    assert by_id["DGS10"]["transport"] == "dbnomics_mirror" and by_id["DGS10"]["mirror"] is True
    assert (tmp_path / "fred" / "DGS10.csv").read_text().splitlines()[1].startswith("2021-11-22,1.5,")


def test_api_key_is_used_but_never_saved(tmp_path):
    key = "abcdefghijklmnop1234567890abcdef"
    router = Router()
    result = go(tmp_path, http=router, key=key, only=["fred"])
    assert result["manifest"]["series"][0]["transport"] == "fred_api"
    assert any(call[1].get("api_key") == key for call in router.calls)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key not in path.read_text()


def test_dry_run_writes_nothing(tmp_path):
    backfill.run(CONFIG, tmp_path, Router(), TODAY, only=["fred"], dry_run=True, now=NOW)
    assert list(tmp_path.rglob("*")) == []


def test_outputs_have_no_price_columns(tmp_path):
    go(tmp_path)
    for path in tmp_path.rglob("*.csv"):
        header = path.read_text().splitlines()[0].lower()
        for banned in ("open,", "high", "low", "close", "volume", "ohlc"):
            assert banned not in header, (path.name, header)


def test_summary_text_is_readable(tmp_path):
    text = backfill.summary_markdown(go(tmp_path))
    assert "Series loaded" in text and "| DGS10 |" in text
