"""Deterministic fallback tests; no live calls or made-up market data."""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.macro_fallback import fetch_dbnomics_fed_yield


class Response:
    def __init__(self, content):
        self.content = content
    def raise_for_status(self):
        pass


class Session:
    def __init__(self, content):
        self.content = content
        self.calls = []
    def get(self, url, params, timeout, headers):
        self.calls.append((url, params, timeout))
        return Response(self.content)


def sample(series="RIFLGFCY02_N.B"):
    return json.dumps({"series": {"docs": [{
        "series_code": series,
        "period": ["2026-11-04", "2026-11-05", "2026-11-09"],
        "value": [4.5, 4.6, 4.55],
    }]}}).encode("utf-8")


def test_yield_mapping_provenance_and_replay(tmp_path):
    session = Session(sample())
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    result = fetch_dbnomics_fed_yield("DGS2", "2026-11-15", tmp_path,
                                       session=session, clock=now)
    assert result["latest"] == {"observation_date": "2026-11-09", "value": 4.55}
    assert result["source_provider"] == "Federal Reserve H.15 via DBnomics"
    assert result["mirror"] is True
    assert session.calls[0][0].endswith("/FED/H15/RIFLGFCY02_N.B")
    with gzip.open(tmp_path / result["raw_file"], "rb") as stream:
        assert stream.read() == session.content
    assert result["fetched_at_utc"] == now.isoformat()


def test_no_unverified_series_mapping(tmp_path):
    with pytest.raises(ValueError, match="No verified"):
        fetch_dbnomics_fed_yield("WALCL", "2026-11-15", tmp_path)


def test_unexpected_series_and_future_data_rejected(tmp_path):
    with pytest.raises(ValueError, match="identity"):
        fetch_dbnomics_fed_yield("DGS2", "2026-11-15", tmp_path,
                                   session=Session(sample("not-the-same-series")))
    future = json.dumps({"series": {"docs": [{"series_code": "RIFLGFCY02_N.B",
       "period": ["2026-11-16"], "value": [4.6]}]}}).encode()
    with pytest.raises(ValueError, match="valid dated"):
        fetch_dbnomics_fed_yield("DGS2", "2026-11-15", tmp_path,
                                   session=Session(future))


def test_corrupt_or_unbounded_values_rejected(tmp_path):
    invalid = json.dumps({"series": {"docs": [{"series_code": "RIFLGFCY02_N.B",
       "period": ["2026-11-13"], "value": [1000]}]}}).encode()
    with pytest.raises(ValueError, match="valid dated"):
        fetch_dbnomics_fed_yield("DGS2", "2026-11-15", tmp_path,
                                   session=Session(invalid))
