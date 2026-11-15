import gzip
from datetime import datetime, timezone
import pytest

from backend.treasury_rates import fetch_us_treasury_par_curve


class Response:
    def __init__(self, raw):
        self.content = raw
        self.url = ("https://home.treasury.gov/resource-center/data-chart-center/"
                    "interest-rates/daily-treasury-rates.csv/2026/all")
    def raise_for_status(self):
        return None


class Session:
    def __init__(self, body):
        self.body = body
        self.calls = 0
    def get(self, url, params, timeout, headers):
        self.calls += 1
        assert params["_format"] == "csv"
        assert params["type"] == "daily_treasury_yield_curve"
        return Response(self.body)


def test_verified_treasury_dates_and_raw_file(tmp_path):
    csv = b"Date,2 Yr,10 Yr\n11/09/2026,4.56,4.88\n11/13/2026,4.88,5.15\n"
    session = Session(csv)
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    result = fetch_us_treasury_par_curve("2026-11-15", tmp_path,
                                         session=session, clock=now)
    assert session.calls == 1
    assert result["UST_PAR_2Y"]["latest"] == {"observation_date": "2026-11-13", "value": 4.88}
    assert result["UST_PAR_10Y"]["latest"]["value"] == 5.15
    assert "not Federal Reserve" in result["UST_PAR_10Y"]["methodology"]
    assert result["UST_PAR_2Y"]["unit"] == "percent_per_annum"
    with gzip.open(tmp_path / result["UST_PAR_2Y"]["raw_file"], "rb") as handle:
        assert handle.read() == csv


def test_future_rows_rejected_and_invalid_schema(tmp_path):
    future = b"Date,2 Yr,10 Yr\n11/16/2026,4.88,5.15\n"
    with pytest.raises(ValueError, match="No valid"):
        fetch_us_treasury_par_curve("2026-11-15", tmp_path,
                                    session=Session(future))
    with pytest.raises(ValueError, match="columns"):
        fetch_us_treasury_par_curve("2026-11-15", tmp_path,
                                    session=Session(b"Date,ForeignKey\n11/13/2026,2\n"))


def test_treasury_missing_column_value_never_fabricated(tmp_path):
    partial = b"Date,2 Yr,10 Yr\n11/13/2026,4.88,N/A\n"
    result = fetch_us_treasury_par_curve("2026-11-15", tmp_path,
                                         session=Session(partial))
    assert set(result) == {"UST_PAR_2Y"}
