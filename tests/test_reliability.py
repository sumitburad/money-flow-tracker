"""FRED key path, secret safety, collection timestamps and the retry hint."""
import json
from datetime import date

import pytest

import backend.run_daily as engine
from backend.feed_contract import validate_feed


class Resp:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None, **kw):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


API_BODY = json.dumps({"observations": [
    {"date": "2026-11-13", "value": "."},
    {"date": "2026-11-12", "value": "4.10"},
    {"date": "2026-11-11", "value": "4.05"},
]}).encode()
CSV_BODY = b"observation_date,DGS2\n2026-11-11,4.05\n2026-11-12,4.10\n2026-11-13,.\n"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    return tmp_path


def test_fred_without_key_uses_public_csv(sandbox, monkeypatch):
    fake = FakeHttp(Resp(200, CSV_BODY))
    monkeypatch.setattr(engine, "HTTP", fake)
    record = engine.fetch_fred("DGS2", "2026-11-15")
    assert record["fetch_path"] == "fred_csv"
    assert record["latest"] == {"observation_date": "2026-11-12", "value": 4.1}
    assert "fredgraph.csv" in fake.calls[0][0]


def test_fred_with_key_uses_api_and_skips_missing_values(sandbox, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "abcdefghijklmnop1234567890abcdef")
    fake = FakeHttp(Resp(200, API_BODY))
    monkeypatch.setattr(engine, "HTTP", fake)
    record = engine.fetch_fred("DGS2", "2026-11-15")
    assert record["fetch_path"] == "fred_api"
    assert [r["observation_date"] for r in record["recent"]] == ["2026-11-11", "2026-11-12"]
    assert record["latest"]["value"] == 4.1
    assert fake.calls[0][1]["observation_end"] == "2026-11-15"
    # the key is sent to FRED but never stored in the returned record
    assert "abcdefghijklmnop1234567890abcdef" not in json.dumps(record)


def test_rejected_key_falls_back_to_csv_without_leaking_it(sandbox, monkeypatch):
    key = "abcdefghijklmnop1234567890abcdef"
    monkeypatch.setenv("FRED_API_KEY", key)
    fake = FakeHttp(Resp(400, b'{"error_message":"api_key is not registered"}'),
                    Resp(200, CSV_BODY))
    monkeypatch.setattr(engine, "HTTP", fake)
    record = engine.fetch_fred("DGS2", "2026-11-15")
    assert record["fetch_path"] == "fred_csv"
    assert len(fake.calls) == 2


def test_api_error_message_has_no_key(sandbox, monkeypatch):
    key = "abcdefghijklmnop1234567890abcdef"
    monkeypatch.setattr(engine, "HTTP", FakeHttp(Resp(403, b"{}")))
    with pytest.raises(Exception) as info:
        engine.fetch_fred_api("DGS2", "2026-11-15", key)
    assert key not in str(info.value)


def test_saved_json_never_contains_a_configured_secret(sandbox, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_12345")
    engine.save_json("out/test.json", {"note": "leak gsk_secret_value_12345 here"})
    saved = (sandbox / "out" / "test.json").read_text()
    assert "gsk_secret_value_12345" not in saved and "***" in saved


def test_official_source_problem_pattern():
    match = engine.OFFICIAL_SOURCE_PROBLEM.match
    for source in ("fred:DGS2", "fred_api", "macro:WALCL", "us_treasury_par_curve",
                   "us_treasury:UST_PAR_2Y", "cftc_tff"):
        assert match(source), source
    for source in ("macro_stale:DGS2", "price:sp500", "boj_assets", "news_classifier",
                   "institutional_flows", "breadth:sp500", "cftc_market:sp500"):
        assert not match(source), source


def test_assess_stamps_collection_time(monkeypatch):
    def unavailable(asset):
        raise ValueError("provider unavailable")
    monkeypatch.setattr(engine, "fetch_yfinance", unavailable)
    record = engine.assess({"id": "t", "name": "T", "group": "g", "region": "IN",
                            "currency": "INR", "symbol": "T", "asset_type": "equity"},
                           date(2026, 11, 15), {})
    assert record["collected_at_utc"].endswith("+00:00")


def _feed(extra=None):
    fam = {"state": "not_available", "evidence": "none", "source": None}
    item = {"id": "x", "item": "T", "group": "g", "symbol": "T", "region": "US",
            "currency": "USD", "label": "Neutral/Mixed", "tag": "Steady",
            "agreement": "Weak", "freshness": "current",
            "families": {name: dict(fam) for name in engine.FAMILIES}}
    item.update(extra or {})
    return {"schema_version": "1.0", "usage": "research_only_not_order_authorization",
            "items": [item], "macro": {}}


def test_contract_accepts_old_feed_without_collected_at():
    assert validate_feed(_feed())


def test_contract_accepts_timezone_aware_collected_at():
    assert validate_feed(_feed({"collected_at_utc": "2026-11-22T02:10:00+00:00"}))


@pytest.mark.parametrize("bad", ["yesterday", "2026-11-22T02:10:00", ""])
def test_contract_rejects_bad_collected_at(bad):
    with pytest.raises(ValueError, match="collected_at_utc"):
        validate_feed(_feed({"collected_at_utc": bad}))
