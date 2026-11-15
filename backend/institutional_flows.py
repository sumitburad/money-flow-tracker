"""Permission-aware institutional flow collection (read-only, fail closed).

NSE explicitly prohibits unattended site collection in its website terms.
NSDL report portal does not offer a verified stable keyless API in this build.
Use authorized read-only Upstox analytics only when opt-in bearer token exists,
and keep its NSE_EQ|CASH participant trades separate from NSDL FINAL FPI flows.
Never publish raw broker data, positions or credentials to the public repo.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

NSE_OFFICIAL_REPORT = "https://www.nseindia.com/reports/fii-dii"
NSDL_FINAL_REPORT = "https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx"
CDSL_FINAL_REPORT = "https://www.cdslindia.com/Publications/FIIDailyData.aspx"
UPSTOX = "https://api.upstox.com/v2/market/"
MARKET_SEGMENT = "NSE_EQ|CASH"
MAX_BYTES = 300_000


def _nonnegative(value):
    if isinstance(value, bool):
        raise ValueError("not numeric")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1e16:
        raise ValueError("nonfinite or unsupported amount")
    return number


def parse_upstox_cash(raw, participant, run_day):
    """Documented Upstox INR amounts, not INR crore; release-time unknown."""
    if participant not in ("FPI", "DII") or not raw or len(raw) > MAX_BYTES:
        raise ValueError("participant invalid or response outside limit")
    response = json.loads(raw)
    if response.get("status") != "success" or not isinstance(response.get("data"), dict):
        raise ValueError("Upstox API status/schema invalid")
    records = response["data"].get(MARKET_SEGMENT)
    if not isinstance(records, list) or len(records) > 35:
        raise ValueError("Upstox NSE cash data missing/oversized")
    cutoff = date.fromisoformat(run_day)
    parsed = {}
    for row in records:
        try:
            ms = row["time_stamp"]
            if isinstance(ms, bool) or not isinstance(ms, int):
                raise ValueError("timestamp must be integer milliseconds")
            d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            observed = d.astimezone(timezone(timedelta(hours=5,minutes=30))).date()
            buy = _nonnegative(row["buy_amount"])
            sell = _nonnegative(row["sell_amount"])
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError("Upstox row schema, time or amount invalid")
        if observed > cutoff or observed.year < 2026 or observed.isoformat() in parsed:
            raise ValueError("future, unsupported or duplicate Upstox day")
        parsed[observed.isoformat()] = {
            "date": observed.isoformat(), "participant": participant,
            "direction": "net_buying" if buy > sell else
                         "net_selling" if buy < sell else "flat",
            "scope": "NSE_EQ|CASH ONLY",
            "currency_unit": "INR_NOT_CRORE",
            "not_final_fpi_investments": True,
            "source_provisional_status": "UNKNOWN",
            "source": UPSTOX + ("fii" if participant=="FPI" else "dii"),
            "published_at": None,
        }
    return list(parsed.values())


def collect_upstox_cash(run_day, *, token=None, http=requests):
    """Only when existing eligible developer's read-only analytics token exists.

    Never archive body or absolute amounts in a PUBLIC repository.
    """
    key = token if token is not None else os.getenv("UPSTOX_ANALYTICS_TOKEN", "")
    if not key:
        return {
            "status": "not_configured",
            "source": UPSTOX, "reason": "read-only analytics token not configured",
            "scope": "NSE_EQ|CASH", "nsdl_final": "not_available",
            "source_terms_approval_required": True,
        }
    from_date = (date.fromisoformat(run_day) - timedelta(days=28)).isoformat()
    pairs = {}
    for code, path in (("FPI","fii"),("DII","dii")):
        response = http.get(UPSTOX + path, params={
            "data_type": MARKET_SEGMENT, "interval": "1D", "from": from_date
        }, headers={"Authorization": "Bearer " + key,
                    "Accept": "application/json"}, timeout=12)
        response.raise_for_status()
        pairs[code] = parse_upstox_cash(response.content, code, run_day)
    by_part = {k: {r["date"]: r for r in rows} for k,rows in pairs.items()}
    latest = sorted(set(by_part["FPI"]) & set(by_part["DII"]))
    if not latest:
        raise ValueError("No paired Upstox cash dates")
    day = latest[-1]
    return {
        "status": "observed_readonly_provider_not_nsdl_reconciled",
        "observation_date": day,
        "source": UPSTOX + "fii",
        "independent_dii_source": UPSTOX + "dii",
        "scope": MARKET_SEGMENT, "units": "INR",
        "participant_directions": {
            "FPI": by_part["FPI"][day]["direction"],
            "DII": by_part["DII"][day]["direction"],
        },
        "nsdl_final": "not_available",
        "trading_authorization": False,
        "publication_timestamp": None,
        "numeric_broker_data_exported": False,
        "note": "Participant trading activity on NSE equity cash, not total FPI investment flows",
    }


def validate_official_download(raw, manifest, *, run_day):
    """Optional offline official-download intake, never autonomous NSE scraping.

    A URL/manifest alone cannot prove authentic origin, so reviewed flag stays
    false until a human verifies actual download, licensing, scope and release.
    """
    if not 2 <= len(raw) <= MAX_BYTES or not isinstance(manifest, dict):
        raise ValueError("missing official download or manifest")
    required = {"origin_url", "collected_at_utc", "observation_date",
                "data_scope", "raw_sha256", "provider"}
    if not required.issubset(manifest):
        raise ValueError("missing provenance fields")
    official = {
        "NSDL": NSDL_FINAL_REPORT,
        "NSE": NSE_OFFICIAL_REPORT,
        "CDSL": CDSL_FINAL_REPORT,
    }
    if manifest["provider"] not in official or manifest["origin_url"] != official[manifest["provider"]]:
        raise ValueError("unknown or mismatched official origin")
    if hashlib.sha256(raw).hexdigest() != manifest["raw_sha256"]:
        raise ValueError("official download hash mismatch")
    if date.fromisoformat(manifest["observation_date"]) > date.fromisoformat(run_day):
        raise ValueError("future source date")
    if manifest.get("reviewed_license_and_origin") is True and not manifest.get("operator_approval_id"):
        raise ValueError("positive approval needs independently reviewable identifier")
    return {
        "status": "quarantined_for_origin_and_license_review",
        "origin": manifest["origin_url"], "provider": manifest["provider"],
        "observation_date": manifest["observation_date"],
        "raw_sha256": manifest["raw_sha256"],
        "proof_of_authenticity": False,
        "promoted_to_market_signal": False,
    }


def institutional_status(run_day, *, token=None, http=requests):
    try:
        provider = collect_upstox_cash(run_day, token=token, http=http)
    except Exception as exc:
        provider = {"status": "unavailable",
                    "error": type(exc).__name__,
                    "source": UPSTOX, "nsdl_final": "not_available"}
    return {
        "nse_automated_scraping": "disabled_by_terms",
        "nse_report": NSE_OFFICIAL_REPORT,
        "nse_cash_via_authorized_broker": provider,
        "nsdl_final": {"status":"not_available",
                       "reason":"No verified, licensed and automatable NSDL final flow access",
                       "source":NSDL_FINAL_REPORT},
        "cdsl_final": {"status":"not_available",
                       "reason":"No verified structured access; separate source from NSE provisional cash",
                       "source":CDSL_FINAL_REPORT},
        "complete_verified_institutional_flows": False,
    }
