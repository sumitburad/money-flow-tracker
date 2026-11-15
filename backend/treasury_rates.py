"""Official U.S. Treasury daily par yield curve (NOT FRED H.15 DGS2/DGS10).

Uses one public, keyless yearly CSV per run, preserves original response bytes,
and reports observed dates distinct from collection timestamps. No invented
conversion to Fed H.15 yields or investment recommendation.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import math
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

SERIES = {"UST_PAR_2Y": "2 Yr", "UST_PAR_10Y": "10 Yr"}
BASE = ("https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/daily-treasury-rates.csv")


def fetch_us_treasury_par_curve(run_day: str, root: Path, *,
                               session=requests, clock=None):
    year = date.fromisoformat(run_day).year
    url = f"{BASE}/{year}/all"
    response = session.get(url, params={
        "type": "daily_treasury_yield_curve",
        "field_tdr_date_value": str(year),
        "_format": "csv",
    }, timeout=15, headers={
        "User-Agent": "GlobalMoneyFlowResearchMonitor/1.0",
        "Accept": "text/csv",
    })
    response.raise_for_status()
    final_url = getattr(response, "url", url)
    parsed = urlparse(final_url)
    if (parsed.scheme, parsed.hostname) != ("https", "home.treasury.gov"):
        raise ValueError("Unexpected US Treasury redirect host")
    raw = response.content
    if not 20 <= len(raw) <= 3_000_000:
        raise ValueError("Unexpected Treasury CSV payload size")
    rawfile = Path(root) / "data" / "raw" / run_day / f"US_TREASURY_PAR_{year}.csv.gz"
    rawfile.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(rawfile, "wb") as handle:
        handle.write(raw)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or not {"Date", *SERIES.values()}.issubset(
            {str(x).strip() for x in reader.fieldnames}):
        raise ValueError("Missing date or treasury par-yield columns")
    observations = {key: [] for key in SERIES}
    cutoff = date.fromisoformat(run_day)
    for row in reader:
        try:
            observed = datetime.strptime(str(row["Date"]).strip(), "%m/%d/%Y").date()
        except (ValueError, TypeError):
            continue
        if observed > cutoff:
            continue
        for key, column in SERIES.items():
            try:
                value = float(row[column])
            except (KeyError, ValueError, TypeError):
                continue
            if not math.isfinite(value) or not (0 <= value <= 30):
                continue
            observations[key].append({
                "observation_date": observed.isoformat(),
                "value": value,
            })
    collected_at = clock or datetime.now(timezone.utc)
    out = {}
    for sid in SERIES:
        values = sorted(observations[sid], key=lambda r: r["observation_date"])
        if not values:
            continue
        out[sid] = {
            "id": sid,
            "latest": values[-1],
            "recent": values[-20:],
            "fetched_at_utc": collected_at.isoformat(),
            "source": final_url,
            "source_provider": "U.S. Department of the Treasury",
            "methodology": "Daily Treasury par yield curve, not Federal Reserve H.15 yields",
            "unit": "percent_per_annum",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_file": str(rawfile.relative_to(root)),
            "mirror": False,
        }
    if not out:
        raise ValueError("No valid dated Treasury par yields")
    return out
