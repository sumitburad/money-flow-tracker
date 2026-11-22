"""Explicitly third-party, licensed-public M0.com CSV mirrors of FRED series.

FRED series identity and observation dates are verified; M0.com is *not*
misrepresented as a government issuer. M0's published data page permits
scheduled public CSV retrieval. Unit conversion is explicitly declared by M0.
"""
from __future__ import annotations
import csv
import hashlib
import io
import math
import gzip
import re
from datetime import date, datetime, timezone
from pathlib import Path
import requests  # noqa: F401

from backend.net import HTTP

SERIES = {
    "WALCL": ("fed-balance-sheet", "weekly"),
    "WTREGEN": ("treasury-general-account", "weekly"),
    "RRPONTSYD": ("reverse-repo", "daily"),
    "M2SL": ("m2", "monthly"),
}
BASE = "https://m0.com/data/"
SIZE_LIMIT=1_500_000


def parse_m0_csv(raw, series_id, run_day):
    """No accepted metadata => no source identity, no usable observation."""
    if series_id not in SERIES or not 30 < len(raw) <= SIZE_LIMIT:
        raise ValueError("unknown series or invalid response size")
    text=raw.decode("utf-8-sig")
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    header = "\n".join(lines[:15]).lower()
    # Provenance is mandatory, not inferred from the URL or a value.
    if series_id.lower() not in header:
        raise ValueError("CSV omits original FRED series identity")
    if not ("billion" in header or "usd b" in header or "usd_b" in header):
        raise ValueError("CSV unit billions USD not verified")
    data_lines=[line for line in lines if not line.startswith("#")]
    reader=csv.DictReader(io.StringIO("\n".join(data_lines)))
    columns=reader.fieldnames or []
    lower={x.strip().lower():x for x in columns}
    date_col=next((v for k,v in lower.items() if k in
                  ("date","observation_date","time_period","period")),None)
    value_col=next((v for k,v in lower.items() if k in
                    ("value","value_billions","value_usd_billions","value_billion_usd",
                     "usd_billions","value_b","billions_usd")),None)
    if not date_col or not value_col:
        raise ValueError("M0 data schema not recognized")
    cutoff=date.fromisoformat(run_day)
    rows={}
    for row in reader:
        try:
            obs=date.fromisoformat(row[date_col][:10])
            amount=float(row[value_col].replace(",",""))
            if not math.isfinite(amount) or not (0 <= amount < 100_000):
                continue
            if obs<=cutoff:
                rows[obs.isoformat()]=amount
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    if not rows:
        raise ValueError("M0 file missing dated numeric values")
    return [{"observation_date": d, "value": n} for d,n in sorted(rows.items())[-20:]]


def fetch_m0_fred_series(series_id,root,run_day,*,http=HTTP):
    if series_id not in SERIES:
        raise ValueError("unmapped FRED series")
    slug,frequency=SERIES[series_id]
    url=BASE+slug
    response=http.get(url,timeout=12,
           headers={"User-Agent":"global-money-flow-research/2.1",
                    "Accept":"text/csv"})
    response.raise_for_status()
    raw=response.content
    rows=parse_m0_csv(raw,series_id,run_day)
    out=Path(root)/"data"/"raw"/run_day/("M0_SECONDARY_"+series_id+".csv.gz")
    out.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(out,"wb") as stream: stream.write(raw)
    return {"id":series_id,"latest":rows[-1],"recent":rows,
            "source":url,"original_series":"https://fred.stlouisfed.org/series/"+series_id,
            "source_provider":"M0.com secondary public mirror of FRED, normalized by M0",
            "mirror":True,"frequency":frequency,"unit":"billions_usd",
            "not_official_primary":True,
            "raw_file":str(out.relative_to(root)),
            "raw_sha256":hashlib.sha256(raw).hexdigest(),
            "fetched_at_utc":datetime.now(timezone.utc).isoformat()}
