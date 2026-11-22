"""Load official-source history (FRED, US Treasury, CFTC) into data/history/v1/.

* Official data only. No market price data of any kind is fetched or written.
* Output is plain CSV (opens in Excel) plus manifest.json that lists every series,
  where it came from, its date range and how it was fetched.
* Every row has ``available_from_estimate``: a conservative guess of the date the
  value became public, so a backtest never uses a number before the world had it.
  Values are the CURRENT vintage (later revisions are not tracked).
* Safe to run again and again: it rewrites files only when their content changed,
  and when one series fails it keeps the previous good file.

Run by the "Load official history" workflow (one click) and, in ``--mode update``,
by the daily refresh. Exit code: 0 all good, 3 partly good, 1 nothing fetched.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.advanced_sources import CFTC_MARKETS, CFTC_URL  # noqa: E402
from backend.net import HTTP, redact  # noqa: E402

OUT_DEFAULT = ROOT / "data" / "history" / "v1"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
DBNOMICS_URL = "https://api.db.nomics.world/v22/series/FRED/"
TREASURY_BASE = ("https://home.treasury.gov/resource-center/data-chart-center/"
                 "interest-rates/daily-treasury-rates.csv")
HEADERS = {"User-Agent": "money-flow-history/1.0 (research)"}
TIMEOUT = (6, 40)
MAX_BYTES = 12_000_000
CFTC_PAGE = 5000
CFTC_MAX_PAGES = 20
HISTORY_SCHEMA = "history-1.0"
AVAILABILITY_NOTE = ("available_from_estimate is a conservative publication-lag estimate, "
                     "not a true vintage date. Values are the current vintage; later "
                     "revisions are not tracked.")


# ----------------------------------------------------------------- small helpers
def add_business_days(day, count):
    """Move forward ``count`` Monday-Friday days. Holidays are ignored on purpose;
    the lag settings are padded so an estimate is never earlier than reality."""
    current = day
    while count > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count -= 1
    return current


def available_from(day, lag):
    if "business_days" in lag:
        return add_business_days(day, int(lag["business_days"]))
    return day + timedelta(days=int(lag.get("calendar_days", 0)))


def number_text(value):
    return repr(float(value))


def short_error(exc):
    return (type(exc).__name__ + ": " + redact(str(exc)))[:140]


def get_bytes(http, url, params=None):
    response = http.get(url, params=params, timeout=TIMEOUT, headers=HEADERS)
    if response.status_code != 200:
        raise RuntimeError("HTTP %s from %s" % (response.status_code, url.split("?")[0]))
    raw = response.content
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty or oversized response")
    return raw


def year_on_year(rows, start):
    """Percent change from the same month one year earlier, for each month on or after ``start``.

    ``rows`` are the monthly (date, index level) pairs, oldest first or not. A month whose
    year-earlier level is missing is skipped rather than guessed.
    """
    by_day = dict(rows)
    out = []
    for day in sorted(by_day):
        if day < start:
            continue
        try:
            earlier = by_day.get(day.replace(year=day.year - 1))
        except ValueError:            # 29 February has no twin a year earlier
            earlier = None
        value = by_day[day]
        if earlier is None or earlier <= 0 or value <= 0:
            continue
        out.append((day, round((value / earlier - 1.0) * 100.0, 4)))
    return out


def csv_text(header, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


# ---------------------------------------------------------------------- parsers
def parse_fred_csv(raw, series_id, start, end):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    date_col = "observation_date" if "observation_date" in fields else "DATE"
    if date_col not in fields or series_id not in fields:
        raise ValueError("unexpected FRED CSV headers")
    rows = {}
    for record in reader:
        try:
            day = date.fromisoformat(str(record[date_col])[:10])
            value = float(record[series_id])  # "." (missing) raises and is skipped
        except (ValueError, TypeError, KeyError):
            continue
        if math.isfinite(value) and start <= day <= end:
            rows[day] = value
    return sorted(rows.items())


def parse_fred_api(raw, start, end):
    observations = json.loads(raw).get("observations")
    if not isinstance(observations, list):
        raise ValueError("unexpected FRED API payload")
    rows = {}
    for record in observations:
        try:
            day = date.fromisoformat(str(record["date"])[:10])
            value = float(record["value"])
        except (ValueError, TypeError, KeyError):
            continue
        if math.isfinite(value) and start <= day <= end:
            rows[day] = value
    return sorted(rows.items())


def parse_dbnomics(raw, series_id, start, end):
    docs = json.loads(raw).get("series", {}).get("docs", [])
    if len(docs) != 1 or docs[0].get("series_code") != series_id:
        raise ValueError("DBnomics series identity mismatch")
    periods = docs[0].get("period_start_day") or docs[0].get("period") or []
    values = docs[0].get("value") or []
    if len(periods) != len(values):
        raise ValueError("DBnomics arrays differ in length")
    rows = {}
    for period, value in zip(periods, values):
        try:
            day = date.fromisoformat(str(period)[:10])
            number = float(value)
        except (ValueError, TypeError):
            continue
        if math.isfinite(number) and start <= day <= end:
            rows[day] = number
    return sorted(rows.items())


def parse_treasury_csv(raw, columns, start, end):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = [str(f).strip() for f in (reader.fieldnames or [])]
    missing = [c for c in ["Date", *columns] if c not in fields]
    if missing:
        raise ValueError("Treasury CSV lacks columns: " + ", ".join(missing))
    series = {sid: {} for sid in columns.values()}
    for record in reader:
        record = {str(k).strip(): v for k, v in record.items() if k}
        try:
            day = datetime.strptime(str(record["Date"]).strip(), "%m/%d/%Y").date()
        except (ValueError, TypeError):
            continue
        if not start <= day <= end:
            continue
        for column, sid in columns.items():
            try:
                value = float(record[column])
            except (KeyError, ValueError, TypeError):
                continue
            if math.isfinite(value) and 0 <= value <= 30:
                series[sid][day] = value
    return {sid: sorted(rows.items()) for sid, rows in series.items()}


def parse_cftc_rows(payload, start, end):
    """Returns (rows per universe id, every contract name seen with a count)."""
    matched, names = {}, {}
    for record in payload:
        if not isinstance(record, dict):
            continue
        try:
            day = date.fromisoformat(str(record["report_date_as_yyyy_mm_dd"])[:10])
            name = str(record["market_and_exchange_names"]).strip()
        except (KeyError, ValueError, TypeError):
            continue
        if not start <= day <= end or not name:
            continue
        seen = names.setdefault(name, {"rows": 0, "last_report_date": day.isoformat()})
        seen["rows"] += 1
        seen["last_report_date"] = max(seen["last_report_date"], day.isoformat())
        try:
            long_ = float(record["asset_mgr_positions_long"])
            short = float(record["asset_mgr_positions_short"])
            interest = float(record["open_interest_all"])
        except (KeyError, ValueError, TypeError):
            continue
        if not all(math.isfinite(x) and x >= 0 for x in (long_, short, interest)):
            continue
        title = name.upper()
        for universe_id, patterns in CFTC_MARKETS.items():
            if any(re.search(p, title) for p in patterns):
                matched.setdefault(universe_id, []).append(
                    (day, name, long_, short, interest))
    return matched, names


# ------------------------------------------------------------------- fetchers
def fetch_fred_history(http, series_id, start, end, api_key):
    """FRED API (free key) -> FRED public CSV -> DBnomics mirror. Returns (rows, transport)."""
    attempts = []
    if api_key:
        attempts.append(("fred_api", lambda: parse_fred_api(get_bytes(http, FRED_API_URL, {
            "series_id": series_id, "api_key": api_key, "file_type": "json",
            "observation_start": start.isoformat(), "observation_end": end.isoformat()}),
            start, end)))
    attempts.append(("fred_csv", lambda: parse_fred_csv(
        get_bytes(http, FRED_CSV_URL, {"id": series_id}), series_id, start, end)))
    attempts.append(("dbnomics_mirror", lambda: parse_dbnomics(
        get_bytes(http, DBNOMICS_URL + series_id, {"observations": "1"}),
        series_id, start, end)))
    errors = []
    for transport, attempt in attempts:
        try:
            rows = attempt()
            if rows:
                return rows, transport
            errors.append(transport + ": no rows in range")
        except Exception as exc:
            errors.append(transport + ": " + short_error(exc))
    raise RuntimeError("; ".join(errors))


def fetch_treasury_history(http, columns, start, end):
    """One small CSV per calendar year. All years must succeed, or the block fails."""
    combined = {sid: {} for sid in columns.values()}
    for year in range(start.year, end.year + 1):
        raw = get_bytes(http, "%s/%d/all" % (TREASURY_BASE, year), {
            "type": "daily_treasury_yield_curve",
            "field_tdr_date_value": str(year), "_format": "csv"})
        for sid, rows in parse_treasury_csv(raw, columns, start, end).items():
            combined[sid].update(dict(rows))
    return {sid: sorted(rows.items()) for sid, rows in combined.items() if rows}


def fetch_cftc_history(http, start, end):
    payload = []
    for page in range(CFTC_MAX_PAGES):
        raw = get_bytes(http, CFTC_URL, {
            "$select": ("market_and_exchange_names,report_date_as_yyyy_mm_dd,"
                        "asset_mgr_positions_long,asset_mgr_positions_short,"
                        "open_interest_all"),
            "$where": "report_date_as_yyyy_mm_dd >= '%sT00:00:00'" % start.isoformat(),
            "$order": "report_date_as_yyyy_mm_dd ASC,market_and_exchange_names ASC",
            "$limit": str(CFTC_PAGE), "$offset": str(page * CFTC_PAGE)})
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError("unexpected CFTC payload")
        payload.extend(rows)
        if len(rows) < CFTC_PAGE:
            break
    else:
        raise ValueError("CFTC history exceeded the page limit")
    return parse_cftc_rows(payload, start, end)


# --------------------------------------------------------------------- writing
class Writer:
    def __init__(self, out_dir, dry_run=False):
        self.out_dir, self.dry_run, self.changed = Path(out_dir), dry_run, 0

    def write(self, relative, text):
        """Write only when the content changed. Returns the SHA-256 of the content."""
        data = text.encode("utf-8")
        target = self.out_dir / relative
        if not self.dry_run:
            if not target.is_file() or target.read_bytes() != data:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                self.changed += 1
        return hashlib.sha256(data).hexdigest()


def series_entry(sid, title, provider, frequency, unit, lag, rows, transport,
                 source_url, relative, digest, now):
    return {"id": sid, "title": title, "provider": provider, "frequency": frequency,
            "unit": unit, "file": relative, "rows": len(rows),
            "first_observation": rows[0][0].isoformat(),
            "last_observation": rows[-1][0].isoformat(),
            "lag_rule": lag, "transport": transport,
            "mirror": transport == "dbnomics_mirror",
            "source_url": source_url, "sha256": digest,
            "fetched_at_utc": now.isoformat(), "status": "ok"}


def write_series(writer, folder, sid, rows, lag):
    body = [(d.isoformat(), number_text(v), available_from(d, lag).isoformat())
            for d, v in rows]
    relative = "%s/%s.csv" % (folder, sid)
    digest = writer.write(relative, csv_text(
        ["observation_date", "value", "available_from_estimate"], body))
    return relative, digest


def load_previous_manifest(out_dir):
    try:
        return json.loads((Path(out_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------------- run
def run(config, out_dir, http, today, api_key="", only=None, dry_run=False, now=None):
    now = now or datetime.now(timezone.utc)
    start = date.fromisoformat(str(config["start_date"]))
    only = set(only or ("fred", "treasury", "cftc"))
    writer = Writer(out_dir, dry_run)
    previous = {e["id"]: e for e in load_previous_manifest(out_dir).get("series", [])}
    entries, problems = {}, []

    def group_of(sid):
        if sid in config["fred"] or sid in (config.get("fred_yoy") or {}):
            return "fred"
        if sid in config["treasury_par"]["columns"].values():
            return "treasury"
        return "cftc" if sid.startswith("CFTC_TFF_") else None

    # Groups skipped by --only keep their entries, so a partial run never shortens the list.
    carried = set()
    for sid, entry in previous.items():
        if group_of(sid) not in (None, *only):
            entries[sid] = entry
            carried.add(sid)

    def fail(sid, title, message):
        problems.append({"series": sid, "error": message})
        earlier = previous.get(sid) or {}
        # Only a series that really has a good file on disk can be "kept". One that
        # never loaded stays "missing" no matter how many times it fails.
        if earlier.get("file") and (Path(out_dir) / earlier["file"]).is_file():
            old = dict(earlier)
            old.update(status="kept_previous", last_error=message,
                       last_attempt_utc=now.isoformat())
            entries[sid] = old
        else:
            entries[sid] = {"id": sid, "title": title, "status": "missing",
                            "last_error": message, "last_attempt_utc": now.isoformat()}

    if "fred" in only:
        for sid, meta in config["fred"].items():
            try:
                rows, transport = fetch_fred_history(http, sid, start, today, api_key)
                relative, digest = write_series(writer, "fred", sid, rows, meta["lag"])
                entries[sid] = series_entry(
                    sid, meta["title"], meta["provider"], meta["frequency"], meta["unit"],
                    meta["lag"], rows, transport,
                    "https://fred.stlouisfed.org/series/" + sid, relative, digest, now)
            except Exception as exc:
                fail(sid, meta["title"], short_error(exc))
        for sid, meta in (config.get("fred_yoy") or {}).items():
            try:
                # One extra year of the base index, only so the first month can be calculated.
                rows, transport = fetch_fred_history(
                    http, meta["base"], start - timedelta(days=400), today, api_key)
                changes = year_on_year(rows, start)
                if not changes:
                    raise ValueError("not enough %s history to calculate a yearly change" % meta["base"])
                relative, digest = write_series(writer, "fred", sid, changes, meta["lag"])
                entry = series_entry(
                    sid, meta["title"], meta["provider"], meta["frequency"], meta["unit"],
                    meta["lag"], changes, transport,
                    "https://fred.stlouisfed.org/series/" + meta["base"], relative, digest, now)
                entry.update(derived_from=meta["base"], method="year_on_year_percent",
                             formula="(index / index 12 months earlier - 1) x 100",
                             group=meta.get("group"), line_name=meta.get("line_name"))
                entries[sid] = entry
            except Exception as exc:
                fail(sid, meta["title"], short_error(exc))

    if "treasury" in only:
        block = config["treasury_par"]
        try:
            fetched = fetch_treasury_history(http, block["columns"], start, today)
            for sid in block["columns"].values():
                if sid not in fetched:
                    raise ValueError("no rows for " + sid)
            for column, sid in block["columns"].items():
                relative, digest = write_series(writer, "treasury", sid, fetched[sid], block["lag"])
                entries[sid] = series_entry(
                    sid, "US Treasury par yield, %s" % column, block["provider"],
                    block["frequency"], block["unit"], block["lag"], fetched[sid],
                    "us_treasury_csv", TREASURY_BASE + "/{year}/all", relative, digest, now)
        except Exception as exc:
            for column, sid in block["columns"].items():
                fail(sid, "US Treasury par yield, %s" % column, short_error(exc))

    if "cftc" in only:
        block = config["cftc"]
        try:
            matched, names = fetch_cftc_history(http, start, today)
            if not names:
                raise ValueError("CFTC returned no rows")
            for universe_id in CFTC_MARKETS:
                rows = sorted(matched.get(universe_id, []))
                sid = "CFTC_TFF_" + universe_id
                label = (block.get("names") or {}).get(universe_id, universe_id)
                if not rows:
                    # Data was fetched fine; the name pattern just matches no contract.
                    entries[sid] = {
                        "id": sid, "status": "no_matching_contract",
                        "title": "Asset-manager net futures position: " + label,
                        "note": "No contract name matched the pattern in CFTC_MARKETS; "
                                "see cftc/contracts_seen.json for the real names."}
                    continue
                body = [(d.isoformat(), name, number_text(l), number_text(s),
                         number_text(l - s), number_text(oi),
                         available_from(d, block["lag"]).isoformat())
                        for d, name, l, s, oi in rows]
                relative = "cftc/%s.csv" % universe_id
                digest = writer.write(relative, csv_text(
                    ["report_date", "contract", "asset_mgr_long", "asset_mgr_short",
                     "asset_mgr_net", "open_interest", "available_from_estimate"], body))
                entries[sid] = series_entry(
                    sid, "Asset-manager net futures position: " + label,
                    block["provider"], block["frequency"], "contracts", block["lag"],
                    [(r[0],) for r in rows], "cftc_socrata", CFTC_URL, relative, digest, now)
            listing = {name: info for name, info in sorted(names.items())}
            writer.write("cftc/contracts_seen.json", json.dumps({
                "note": "Every CFTC TFF contract name seen since the start date, with row "
                        "counts. Use it to correct the market name patterns in "
                        "backend/advanced_sources.py (CFTC_MARKETS).",
                "contracts": listing}, indent=2, ensure_ascii=False) + "\n")
        except Exception as exc:
            for universe_id in CFTC_MARKETS:
                label = (block.get("names") or {}).get(universe_id, universe_id)
                fail("CFTC_TFF_" + universe_id, "Asset-manager net futures position: " + label,
                     short_error(exc))

    ordered = [entries[k] for k in sorted(entries)]
    manifest = {
        "schema": HISTORY_SCHEMA,
        "usage": "research_only_not_order_authorization",
        "generated_at_utc": now.isoformat(),
        "start_date": start.isoformat(),
        "no_price_data": True,
        "availability_basis": AVAILABILITY_NOTE,
        "series": ordered,
        "problems": problems,
    }
    writer.write("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    good = sum(1 for e in ordered if e.get("status") == "ok" and e["id"] not in carried)
    code = 0 if not problems else (3 if good else 1)
    return {"manifest": manifest, "files_changed": writer.changed, "good": good,
            "problems": problems, "exit_code": code}


def summary_markdown(result):
    manifest = result["manifest"]
    lines = ["### Official history load", "",
             "- **Series loaded:** %d of %d" % (result["good"], len(manifest["series"])),
             "- **Files changed:** %d" % result["files_changed"],
             "- **Start date:** " + manifest["start_date"], "",
             "| Series | Rows | First | Last | Fetched via | Status |", "|---|---|---|---|---|---|"]
    for e in manifest["series"]:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            e["id"], e.get("rows", "-"), e.get("first_observation", "-"),
            e.get("last_observation", "-"), e.get("transport", "-"), e["status"]))
    if result["problems"]:
        lines += ["", "**Problems (the previous good file, if any, was kept):**"]
        lines += ["- `%s`: %s" % (p["series"], p["error"]) for p in result["problems"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=("backfill", "update"), default="backfill",
                        help="same work either way; 'update' is the quiet daily top-up")
    parser.add_argument("--config", default=str(ROOT / "config" / "history.yaml"))
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.add_argument("--only", default="fred,treasury,cftc")
    parser.add_argument("--start", default=None, help="override start date, YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.start:
        config["start_date"] = args.start
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    result = run(config, args.out, HTTP, datetime.now(timezone.utc).date(),
                 api_key=os.environ.get("FRED_API_KEY", "").strip(), only=only,
                 dry_run=args.dry_run)
    text = summary_markdown(result)
    print(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    if args.mode == "update" and result["good"]:
        return 0  # daily top-up: partial problems are shown in the manifest, not as a red cross
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
