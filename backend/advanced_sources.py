"""Independent, read-only official-public market evidence adapters.

CFTC: official COT public reporting API, Tuesday positions released later.
ECB: keyless official SDMX CSV. DBnomics: clearly attributed mirror of
named FRED/ECB/BOJ sources. No prohibited NSE website automation.
All collectors are bounded; failed sources are never fabricated.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from backend.net import HTTP

CFTC_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/ILM/W.U2.C.T000000.Z5.Z01"
DBN_BASE = "https://api.db.nomics.world/v22/series/FRED"
FRED_MIRRORS = {
    "WALCL": ("weekly", "millions_usd", "Fed total assets"),
    "WTREGEN": ("weekly", "millions_usd", "US Treasury General Account"),
    "RRPONTSYD": ("daily", "billions_usd", "Fed overnight reverse repos"),
    "M2SL": ("monthly", "billions_usd", "US M2"),
    "DEXINUS": ("daily", "inr_per_usd", "Federal Reserve dollar/INR reference"),
    "ECBASSETSW": ("weekly", "millions_eur", "Eurosystem total assets (FRED mirror)"),
    "JPNASSETS": ("monthly", "hundred_million_yen", "BOJ total assets (FRED mirror)"),
}
CFTC_MARKETS = {
    "sp500": (r"E-MINI S&P 500|S&P 500 STOCK INDEX",),
    "nasdaq100": (r"NASDAQ.100|NASDAQ 100",),
    "us_treasury": (r"10.YEAR U.S. TREASURY|10 YEAR U.S. TREASURY",),
    "dollar": (r"U.S. DOLLAR INDEX|USD INDEX",),
}
MAX_PUBLIC_BYTES = 4_000_000


def archive(root, run_day, stem, raw):
    if not raw or len(raw) > MAX_PUBLIC_BYTES:
        raise ValueError("empty or oversized source response")
    path = Path(root) / "data" / "raw" / run_day / (stem + ".gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fp:
        fp.write(raw)
    return str(path.relative_to(root)), hashlib.sha256(raw).hexdigest()


def _bounded_json(raw):
    if not 2 <= len(raw) <= MAX_PUBLIC_BYTES:
        raise ValueError("unexpected JSON size")
    return json.loads(raw)


def _finite(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError("boolean not a number")
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1e15 or positive and number < 0:
        raise ValueError("out-of-range number")
    return number


def _iso_day(s):
    return date.fromisoformat(str(s)[:10]).isoformat()


def fetch_fred_mirror(series_id, root, run_day, *, http=HTTP):
    """One known FRED series only, no guessed mappings or synthetic observations."""
    if series_id not in FRED_MIRRORS:
        raise ValueError("unverified FRED mirror series")
    url = DBN_BASE + "/" + series_id
    resp = http.get(url, params={"observations": "1"}, timeout=12,
                    headers={"User-Agent": "global-money-flow-research/2.0"})
    resp.raise_for_status()
    raw = resp.content
    payload = _bounded_json(raw)
    docs = payload.get("series", {}).get("docs", [])
    if not isinstance(docs, list) or len(docs) != 1:
        raise ValueError("FRED mirror series missing or ambiguous")
    doc = docs[0]
    if doc.get("series_code") != series_id:
        raise ValueError("FRED series identity mismatch")
    periods, values = doc.get("period"), doc.get("value")
    if not isinstance(periods, list) or not isinstance(values, list) or len(periods) != len(values):
        raise ValueError("FRED mirror observations malformed")
    pairs = {}
    cutoff = date.fromisoformat(run_day)
    for p, v in zip(periods, values):
        try:
            observed = date.fromisoformat(str(p)[:10])
            numerical = _finite(v)
        except (TypeError, ValueError, OverflowError):
            continue
        if observed <= cutoff:
            pairs[observed.isoformat()] = numerical
    if not pairs:
        raise ValueError("FRED mirror without dated numeric data")
    rows = [{"observation_date": day, "value": value}
            for day, value in sorted(pairs.items())[-20:]]
    rawfile, digest = archive(root, run_day, "DBN_FRED_" + series_id, raw)
    frequency, unit, description = FRED_MIRRORS[series_id]
    return {
        "id": series_id, "latest": rows[-1], "recent": rows,
        "source": url,
        "original_series": "https://fred.stlouisfed.org/series/" + series_id,
        "source_provider": "FRED mirror on DBnomics; see original source credits",
        "mirror": True, "frequency": frequency, "unit": unit,
        "description": description, "raw_sha256": digest, "raw_file": rawfile,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _ecb_day(period):
    value = str(period).strip()
    if re.fullmatch(r"\d{4}-W\d{2}", value):
        year, week = int(value[:4]), int(value[-2:])
        return date.fromisocalendar(year, week, 5)
    return date.fromisoformat(value[:10])


def parse_ecb_ilm(raw, run_day):
    """Verify exact consolidated Eurosystem total-assets series, weekly EUR millions."""
    if not raw or len(raw) > MAX_PUBLIC_BYTES:
        raise ValueError("ECB response outside limit")
    table = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = set(table.fieldnames or [])
    if not {"TIME_PERIOD", "OBS_VALUE"}.issubset(fields):
        raise ValueError("unexpected ECB SDMX CSV headers")
    cutoff = date.fromisoformat(run_day)
    observations = {}
    for row in table:
        key = row.get("KEY") or row.get("SERIES_KEY") or ""
        if key and "ILM.W.U2.C.T000000.Z5.Z01" not in key:
            raise ValueError("ECB data does not match requested series")
        try:
            observed = _ecb_day(row["TIME_PERIOD"])
            val = _finite(row["OBS_VALUE"], positive=True)
        except (ValueError, OverflowError, TypeError):
            continue
        if observed <= cutoff:
            observations[observed.isoformat()] = val
    if not observations:
        raise ValueError("ECB no valid dated observations")
    return [{"observation_date": day, "value": v}
            for day, v in sorted(observations.items())[-20:]]


def fetch_ecb_assets(root, run_day, *, http=HTTP):
    resp = http.get(ECB_URL, params={"format": "csvdata", "lastNObservations": "20"},
                    headers={"Accept": "text/csv",
                             "User-Agent": "global-money-flow-research/2.0"},
                    timeout=15)
    resp.raise_for_status()
    raw = resp.content
    observations = parse_ecb_ilm(raw, run_day)
    file, digest = archive(root, run_day, "ECB_ILM_TOTAL_ASSETS", raw)
    return {
        "id": "ECB_ILM_TOTAL_ASSETS", "latest": observations[-1],
        "recent": observations, "source": ECB_URL,
        "source_provider": "European Central Bank (direct official SDMX)",
        "unit": "millions_eur", "frequency": "weekly",
        "description": "Consolidated Eurosystem weekly total assets",
        "mirror": False, "raw_sha256": digest, "raw_file": file,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat()
    }


def parse_cftc_tff(raw, run_day):
    """Returns latest and previous CFTC *weekly* TFF financial futures rows.

    Tuesday reporting date is not release time. Conservatively wait >=3
    calendar days before displaying a new report.
    """
    data = _bounded_json(raw)
    if not isinstance(data, list) or len(data) > 2000:
        raise ValueError("unexpected CFTC API response shape")
    cutoff = date.fromisoformat(run_day) - timedelta(days=3)
    eligible = defaultdict(list)
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("non-object CFTC record")
        try:
            day = date.fromisoformat(str(row["report_date_as_yyyy_mm_dd"])[:10])
            title = str(row["market_and_exchange_names"]).upper().strip()
            long = _finite(row["asset_mgr_positions_long"], positive=True)
            short = _finite(row["asset_mgr_positions_short"], positive=True)
            oi = _finite(row["open_interest_all"], positive=True)
        except (ValueError, KeyError, TypeError):
            continue
        if day > cutoff or day.year < 2020 or not title or not oi:
            continue
        for universe_id, patterns in CFTC_MARKETS.items():
            if any(re.search(p, title) for p in patterns):
                eligible[universe_id].append({
                    "observation_date": day.isoformat(),
                    "net_asset_manager_contracts": long - short,
                    "long": long, "short": short, "oi": oi,
                    "cftc_contract": title,
                })
    result = {}
    for asset_id, records in eligible.items():
        by_date = {}
        for record in records:
            if record["observation_date"] in by_date:
                # Multiple distinct contracts cannot safely be added without
                # clearing/contract specification checks.
                by_date[record["observation_date"]] = None
            else:
                by_date[record["observation_date"]] = record
        valid = [v for key,v in sorted(by_date.items()) if v is not None]
        if len(valid) < 2:
            continue
        prev, latest = valid[-2:]
        gap = (date.fromisoformat(latest["observation_date"]) -
               date.fromisoformat(prev["observation_date"])).days
        if gap > 21:
            continue
        diff = latest["net_asset_manager_contracts"] - prev["net_asset_manager_contracts"]
        direction = ("supportive" if diff > 0 else
                     "opposing" if diff < 0 else "neutral")
        result[asset_id] = {
            "state": direction, "observation_date": latest["observation_date"],
            "market": latest["cftc_contract"],
            "evidence": "CFTC TFF weekly asset-manager net futures position " +
                        ("increased" if diff > 0 else "decreased" if diff < 0 else "was unchanged") +
                        "; positions do not reveal why traders hold them",
            "contract_basis": "futures_only", "classification": "asset_manager",
            "source": CFTC_URL,
            "report_date_not_release_date": True,
        }
    return result


def fetch_cftc(root, run_day, *, http=HTTP):
    cutoff = date.fromisoformat(run_day)
    from_date = (cutoff - timedelta(days=60)).isoformat()
    resp = http.get(CFTC_URL, params={
        "$select": ("market_and_exchange_names,report_date_as_yyyy_mm_dd,"
                    "asset_mgr_positions_long,asset_mgr_positions_short,open_interest_all"),
        "$where": "report_date_as_yyyy_mm_dd >= '" + from_date + "T00:00:00'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "2000",
    }, timeout=18, headers={"User-Agent": "global-money-flow-research/2.0"})
    resp.raise_for_status()
    rows = parse_cftc_tff(resp.content, run_day)
    rawfile, digest = archive(root, run_day, "CFTC_TFF_FUTURES_ONLY", resp.content)
    return {"entries": rows, "source": CFTC_URL,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "raw_sha256": digest, "raw_file": rawfile, "type": "TFF_FUTURES_ONLY",
            "note": "CFTC weekly holdings, not cash investment flows"}


def breadth_from_equal_weight(asset_id, run_day, *, download=None):
    """Independent US ETF breadth proxy, never constituent-wide participation."""
    pairs = {
        "sp500": ("RSP", "SPY"),
        "nasdaq100": ("QQEW", "QQQ"),
    }
    if asset_id not in pairs:
        return None
    a, b = pairs[asset_id]
    if download is None:
        import yfinance as yf
        download = yf.download
    values = {}
    days = {}
    for sym in (a, b):
        df = download(sym, period="6mo", interval="1d",
                      auto_adjust=False, progress=False, threads=False,
                      timeout=12)
        if df is None or df.empty:
            raise ValueError("equal-weight ETF quote unavailable")
        if getattr(df.columns, "nlevels", 1) > 1:
            df.columns = df.columns.get_level_values(0)
        c = df["Close"].dropna()
        if len(c) < 23:
            raise ValueError("equal-weight comparison requires 22 observations")
        latest_date = c.index[-1].date()
        days[sym] = latest_date
        values[sym] = float(c.iloc[-1] / c.iloc[-21])
    if days[a] != days[b] or date.fromisoformat(run_day) < days[a]:
        raise ValueError("unmatched ETF observation sessions")
    if (date.fromisoformat(run_day) - days[a]).days > 5:
        raise ValueError("stale equal-weight ETF pair")
    diff = values[a] - values[b]
    state = "supportive" if diff > 0.002 else "opposing" if diff < -0.002 else "neutral"
    return {
        "state": state, "observation_date": days[a].isoformat(),
        "method": "relative_equal_weight_vs_cap_weight_etf_proxy",
        "proxy_only": True,
        "source": "https://finance.yahoo.com/quote/" + a + "/",
        "reference": "https://finance.yahoo.com/quote/" + b + "/",
        "evidence": ("Equal-weight ETF outperformed cap-weight ETF over 20 sessions"
                     if state=="supportive" else "Equal-weight ETF lagged cap-weight ETF over 20 sessions"
                     if state=="opposing" else "Equal-weight and cap-weight ETF performance broadly matched") +
                    "; NOT constituent breadth or direct flows"
    }
