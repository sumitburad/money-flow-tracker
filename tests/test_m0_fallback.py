import gzip
from backend.m0_fallback import parse_m0_csv,fetch_m0_fred_series
import pytest


def test_fred_identity_and_unit_required():
    good=b"# FRED source series: WALCL\n# Unit: USD billions\nobservation_date,value\n2026-11-11,6760.0\n"
    assert parse_m0_csv(good,"WALCL","2026-11-15")[0]["value"]==6760
    with pytest.raises(ValueError,match="identity"):
        parse_m0_csv(good.replace(b"WALCL",b"OTHER"),"WALCL","2026-11-15")
    with pytest.raises(ValueError,match="unit"):
        parse_m0_csv(good.replace(b"USD billions",b"USD unknown"),"WALCL","2026-11-15")


def test_future_rows_not_promoted():
    raw=b"# FRED source series: WTREGEN\n# Unit: USD billions\ndate,value\n2026-11-16,100.0\n"
    with pytest.raises(ValueError,match="missing dated"):
        parse_m0_csv(raw,"WTREGEN","2026-11-15")


def test_archives_secondary_source_without_pretending_direct_fred(tmp_path):
    data=b"# FRED source series: WALCL\n# Unit: USD billions\ndate,value\n2026-11-11,6760\n"
    class R:
        content=data
        def raise_for_status(self): pass
    class H:
        def get(self,url,timeout,headers):
            assert url=="https://m0.com/data/fed-balance-sheet"
            return R()
    entry=fetch_m0_fred_series("WALCL",tmp_path,"2026-11-15",http=H())
    assert entry["not_official_primary"] is True
    assert entry["original_series"].endswith("/WALCL")
    with gzip.open(tmp_path/entry["raw_file"],"rb") as stream:assert stream.read()==data
