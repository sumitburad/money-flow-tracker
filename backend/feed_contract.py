"""Versioned, read-only feed contract; safe for downstream research clients."""
import json
from datetime import datetime, timezone
from pathlib import Path

FAMILIES = ("money_flow", "price_trend", "breadth", "positioning",
            "macro_liquidity", "news")
STATES = {"supportive", "neutral", "opposing", "not_available"}
LABELS = {"Bullish", "Neutral/Mixed", "Bearish"}
FORBIDDEN = {"score", "smart_money_score", "rank", "conviction", "confidence_score",
             "current_price", "raw_ohlcv", "api_key", "access_token", "secret"}


def validate_feed(feed):
    if feed.get("schema_version") != "1.0":
        raise ValueError("unsupported schema version")
    if feed.get("usage") != "research_only_not_order_authorization":
        raise ValueError("feed cannot authorize orders")
    if not isinstance(feed.get("items"), list) or not feed["items"]:
        raise ValueError("no tracked instruments")
    if not isinstance(feed.get("macro"), dict):
        raise ValueError("no macro object")
    ids = set()
    for item in feed["items"]:
        for field in ("id", "item", "group", "symbol", "region", "currency",
                      "label", "tag", "agreement", "families", "freshness"):
            if field not in item:
                raise ValueError("missing required field: " + field)
        if item["id"] in ids:
            raise ValueError("duplicate instrument id")
        ids.add(item["id"])
        if item["label"] not in LABELS:
            raise ValueError("invalid label")
        if item["agreement"] not in ("Strong", "Moderate", "Weak"):
            raise ValueError("invalid evidence agreement")
        if set(item["families"]) != set(FAMILIES):
            raise ValueError("missing evidence family")
        flow = item["families"]["money_flow"]["state"]
        if flow == "not_available" and item["label"] != "Neutral/Mixed":
            raise ValueError("missing money flow cannot produce bullish/bearish")
        for name, family in item["families"].items():
            if family["state"] not in STATES:
                raise ValueError("invalid evidence state for " + name)
            if family["state"] in ("supportive", "opposing") and (
                    not family.get("source") or not family.get("observed_at")):
                raise ValueError("directional evidence lacks citation and date")
    def scan(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in FORBIDDEN:
                    raise ValueError("forbidden feed field: " + key)
                scan(value)
        elif isinstance(obj, list):
            for value in obj:
                scan(value)
    scan(feed)
    return True


def load_feed(path, max_age_hours=None):
    feed = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_feed(feed)
    if max_age_hours is not None:
        timestamp = datetime.fromisoformat(feed["generated_at_utc"])
        if timestamp.tzinfo is None:
            raise ValueError("naive timestamp")
        if (datetime.now(timezone.utc) - timestamp).total_seconds() > max_age_hours * 3600:
            raise ValueError("feed too old for downstream research")
    return feed
