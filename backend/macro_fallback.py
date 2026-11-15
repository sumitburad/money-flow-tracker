"""Official Federal Reserve H.15 yield series, keyless DBnomics mirror fallback.

Each response is archived verbatim before parsing; DBnomics is not rebranded
as a direct FRED observation. Only explicitly verified same-definition series
are mapped (U.S. nominal 2Y and 10Y Treasury constant-maturity yields).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import requests

SERIES = {
    "DGS2": ("FED", "H15", "RIFLGFCY02_N.B"),
    "DGS10": ("FED", "H15", "RIFLGFCY10_N.B"),
}
BASE = "https://api.db.nomics.world/v22/series"


def fetch_dbnomics_fed_yield(series_id: str, run_day: str, root: Path,
                              session=requests, clock=None) -> dict:
    if series_id not in SERIES:
        raise ValueError("No verified like-for-like DBnomics mapping: " + series_id)
    provider, dataset, code = SERIES[series_id]
    url = f"{BASE}/{provider}/{dataset}/{code}"
    response = session.get(url, params={"observations": "1"},
                           timeout=12,
                           headers={"User-Agent": "global-money-flow-monitor/1.0 public-research",
                                    "Accept": "application/json"})
    response.raise_for_status()
    raw = response.content
    if not 20 <= len(raw) <= 3_000_000:
        raise ValueError("Unexpected DBnomics response size")
    payload = json.loads(raw)
    container = payload.get("series", {})
    docs = container.get("docs", [])
    if len(docs) != 1 or docs[0].get("series_code") != code:
        raise ValueError("Unexpected DBnomics source series identity")
    item = docs[0]
    periods, values = item.get("period"), item.get("value")
    if not isinstance(periods, list) or not isinstance(values, list) or len(periods) != len(values):
        raise ValueError("Malformed observation array")
    observations = []
    for raw_day, raw_value in zip(periods, values):
        if not isinstance(raw_day, str):
            continue
        try:
            obs_date = date.fromisoformat(raw_day[:10])
            numeric = float(raw_value)
        except (ValueError, TypeError, OverflowError):
            continue
        if not math.isfinite(numeric) or not (0 <= numeric <= 30):
            continue
        if obs_date > date.fromisoformat(run_day):
            continue
        observations.append({"observation_date": obs_date.isoformat(), "value": numeric})
    if not observations:
        raise ValueError("DBnomics contains no valid dated yield observations")
    observations.sort(key=lambda v: v["observation_date"])
    file = Path(root) / "data" / "raw" / run_day / f"DBN_{series_id}.json.gz"
    file.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(file, "wb") as dest:
        dest.write(raw)
    fetch_time = clock or datetime.now(timezone.utc)
    return {
        "id": series_id,
        "latest": observations[-1],
        "recent": observations[-20:],
        "fetched_at_utc": fetch_time.isoformat(),
        "source": url,
        "source_provider": "Federal Reserve H.15 via DBnomics",
        "mirror": True,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_file": str(file.relative_to(root)),
    }
