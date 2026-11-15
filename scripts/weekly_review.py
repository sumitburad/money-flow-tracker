"""Independent weekly quality-review of stored, source-dated research snapshots.

No model, no downstream trading orders, no numeric conviction or asset ranks.
"""
from __future__ import annotations
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATES = ("Bullish", "Neutral/Mixed", "Bearish")


def generate_review(root: Path, asof: date) -> tuple[dict, str]:
    root = Path(root)
    days = [(asof - timedelta(days=n)).isoformat() for n in range(7)]
    daily = []
    warnings = []
    for day in sorted(days):
        path = root / "data" / "labels" / (day + ".json")
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items", [])
        if not isinstance(items, list):
            warnings.append("Malformed labels on " + day)
            continue
        daily.append((day, items))
    stability: dict[str, list[tuple[str, str]]] = {}
    for day, items in daily:
        for item in items:
            ident = item.get("id", item.get("item"))
            if not ident or item.get("label") not in STATES:
                continue
            stability.setdefault(ident, []).append((day, item["label"]))
    flips = {}
    for ident, observations in stability.items():
        recent = observations[-5:]
        changes = sum(recent[i][1] != recent[i - 1][1]
                      for i in range(1, len(recent)))
        if len(recent) >= 5 and changes > 2:
            flips[ident] = {"state": "unstable", "message":
               "More than two label transitions across five observations; review as Neutral/Mixed before use"}
    latest_labels = daily[-1][1] if daily else []
    total = Counter(x.get("label") for x in latest_labels)
    health = []
    for day in sorted(days):
        file = root / "data" / "health" / (day + ".json")
        if file.is_file():
            entry = json.loads(file.read_text(encoding="utf-8"))
            health.append({"date": day,
                           "status": entry.get("status", "unknown"),
                           "current": entry.get("price_proxies_current"),
                           "total": entry.get("items_configured"),
                           "missing": entry.get("missing", []),
                           "errors": entry.get("errors", [])})
    # Fixed reproducible review sample. This is a human-review QUEUE, not
    # evidence that a human or model has already checked the tags.
    review_sample = []
    latest_news = root / "data" / "news" / (asof.isoformat() + ".json")
    if not latest_news.exists():
        for d in sorted(days, reverse=True):
            candidate = root / "data" / "news" / (d + ".json")
            if candidate.exists():
                latest_news = candidate
                break
    if latest_news.is_file():
        raw_news = json.loads(latest_news.read_text(encoding="utf-8"))
        if isinstance(raw_news, list):
            review_sample = [{
                "headline_id": x.get("headline_id"),
                "title": x.get("title"), "source": x.get("url"),
                "classifier": x.get("classification", {}).get("classifier", "not_classified"),
                "human_review_status": "pending"
            } for x in raw_news[:20]]
        review = {
       "schema_version": "1.0",
       "run_day": asof.isoformat(),
       "coverage_start": min(days),
       "coverage_end": max(days),
       "label_days_found": len(daily),
       "health_days_found": len(health),
       "last_label_day": daily[-1][0] if daily else None,
       "latest_label_counts": {x: total[x] for x in STATES},
       "unstable_label_ids": flips,
       "health": health,
       "warnings": warnings,
       "research_only": True,
       "sample_news_for_human_review": review_sample,
       "news_review_completed": False,
       "no_predictive_claim": True,
    }
    lines = [
        "# Weekly Global Money-Flow Quality Review | " + asof.isoformat(),
        "",
        "Data: " + str(len(daily)) + " archived label dates and " +
        str(len(health)) + " health snapshots available in the seven-day window.",
        "",
        "This is a source-quality and rules-stability review, **not** a score, ranking, return claim or investment recommendation.",
        "",
        "## Most recent stored labels",
        "Latest archive: " + (review["last_label_day"] or "data unavailable"),
    ]
    for category in STATES:
        lines.append("- " + category + ": " + str(total[category]) + " tracked items")
    lines += ["", "## Source health"]
    if health:
        for row in health:
            lines.append("- " + row["date"] + ": " + row["status"] +
                ", current price proxies " + str(row["current"]) + "/" + str(row["total"]) +
                "; unavailable IDs: " + (", ".join(row["missing"]) or "none") +
                "; source warnings: " + str(len(row["errors"])))
    else:
        lines.append("- Health data unavailable")
    lines += ["", "## Label stability (review only)"]
    if flips:
        for ident in sorted(flips):
            lines.append("- " + ident + ": repeated transitions, do not treat as a stable directional label")
    else:
        lines.append("- No unstable IDs established from available snapshots; missing history is not proof of stability")
    lines += ["", "## Next maintenance actions",
      "- Review failed sources and source age; never silently impute missing observations",
      "- Verify 20 news headlines manually before treating model classifications as reliable",
      "- Preserve all historical label snapshots; do not backfill any label using future data",
      "- Re-check published free-source and AI-provider limits monthly",
      "", "Reading: the archive is descriptive and cannot establish predictive hit rates without several months of independently audited outcomes.",
      ""]
    return review, "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", default=None, help="YYYY-MM-DD; default current IST date")
    args = parser.parse_args()
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    asof = date.fromisoformat(args.asof) if args.asof else now_ist
    result, report = generate_review(ROOT, asof)
    d = asof.isoformat()
    for folder, content, name in (
        ("data/reviews/weekly", json.dumps(result, indent=2) + "\n", d + ".json"),
        ("docs/reviews", json.dumps(result, indent=2) + "\n", "latest.json"),
        ("frontend/reviews", json.dumps(result, indent=2) + "\n", "latest.json"),
        ("briefs/weekly", report, d + ".md"),
    ):
        path = ROOT / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"Weekly archive review ready: {len(result['health'])} health dates, {len(result['unstable_label_ids'])} unstable labels")


if __name__ == "__main__":
    main()
