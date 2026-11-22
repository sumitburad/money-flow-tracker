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

# Day / week / month money-flow signal ("price up on rising volume" = inflow).
# Categories only; no price or volume numbers are ever part of the feed.
FLOW_WINDOWS = ("day", "week", "month")
FLOW_DIRECTIONS = {"up", "down", "flat", "not_available"}
FLOW_SIGNALS = {"inflow", "inflow_fading", "outflow", "outflow_fading",
                "unclear", "not_available"}
FLOW_TRENDS = {"improving", "weakening", "steady", "mixed", "not_available"}
FLOW_VERDICTS = {"inflow_led", "outflow_led", "mixed", "not_enough_data",
                 "not_applicable"}
SUMMARY_METHODS = {"ai_validated", "rules_only"}


def expected_flow_signal(price, volume):
    """The one rule that turns a price direction and a volume direction into a signal."""
    if price == "not_available" or volume == "not_available":
        return "not_available"
    if price == "flat" or volume == "flat":
        return "unclear"
    return {("up", "up"): "inflow", ("up", "down"): "inflow_fading",
            ("down", "up"): "outflow", ("down", "down"): "outflow_fading"}[(price, volume)]


def validate_flow_windows(block, where="item"):
    """Optional per-item block. Older snapshots do not have it."""
    if not isinstance(block, dict):
        raise ValueError(where + ": flow_windows must be an object")
    if block.get("status") == "not_available":
        if not isinstance(block.get("reason"), str) or not block["reason"]:
            raise ValueError(where + ": flow_windows needs a reason")
        return
    if block.get("status") != "ok":
        raise ValueError(where + ": invalid flow_windows status")
    try:
        datetime.fromisoformat(str(block.get("as_of")))
    except ValueError:
        raise ValueError(where + ": flow_windows as_of must be a date")
    for name in FLOW_WINDOWS:
        record = block.get(name)
        if not isinstance(record, dict):
            raise ValueError(where + ": flow window missing: " + name)
        price, volume, signal = (record.get("price"), record.get("volume"),
                                 record.get("signal"))
        if price not in FLOW_DIRECTIONS or volume not in FLOW_DIRECTIONS:
            raise ValueError(where + ": invalid flow direction in " + name)
        if signal not in FLOW_SIGNALS or signal != expected_flow_signal(price, volume):
            raise ValueError(where + ": flow signal does not follow price and volume")
    if block.get("trend") not in FLOW_TRENDS:
        raise ValueError(where + ": invalid flow trend")


def _check_counts(counts, where):
    if not isinstance(counts, dict) or set(counts) != FLOW_SIGNALS or any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values()):
        raise ValueError(where + ": counts must list every signal with a whole number")


def _check_window_verdicts(windows, where):
    if not isinstance(windows, dict) or set(windows) != set(FLOW_WINDOWS):
        raise ValueError(where + ": needs day, week and month")
    for name, record in windows.items():
        if not isinstance(record, dict) or record.get("verdict") not in FLOW_VERDICTS:
            raise ValueError(where + ": invalid verdict in " + name)
        _check_counts(record.get("counts"), where + " " + name)
        for key in ("inflow", "outflow"):
            if not isinstance(record.get(key), list) or any(
                    not isinstance(x, str) for x in record[key]):
                raise ValueError(where + ": " + key + " must be a list of ids")


def validate_rotation(rotation):
    """Optional top-level block: money-flow verdicts by asset class and sector."""
    if not isinstance(rotation, dict):
        raise ValueError("rotation must be an object")
    overall = rotation.get("overall")
    if not isinstance(overall, dict) or overall.get("trend") not in FLOW_TRENDS:
        raise ValueError("rotation overall needs a trend")
    _check_window_verdicts(overall.get("windows"), "rotation overall")
    buckets = rotation.get("buckets")
    if not isinstance(buckets, list):
        raise ValueError("rotation buckets must be a list")
    seen = set()
    for bucket in buckets:
        if not isinstance(bucket, dict) or not bucket.get("id") or not bucket.get("name"):
            raise ValueError("rotation bucket needs an id and a name")
        if bucket["id"] in seen:
            raise ValueError("duplicate rotation bucket")
        seen.add(bucket["id"])
        if bucket.get("trend") not in FLOW_TRENDS:
            raise ValueError("invalid rotation bucket trend")
        _check_window_verdicts(bucket.get("windows"), "bucket " + bucket["id"])
    moves = rotation.get("moves")
    if not isinstance(moves, dict) or set(moves) != set(FLOW_WINDOWS):
        raise ValueError("rotation moves need day, week and month")
    for name, record in moves.items():
        for key in ("into", "out_of"):
            if not isinstance(record.get(key), list) or any(
                    x not in seen for x in record[key]):
                raise ValueError("rotation moves must name known buckets")


def validate_executive_summary(summary):
    """Optional top-level block: AI-written (validated) or rule-based summary."""
    if not isinstance(summary, dict):
        raise ValueError("executive_summary must be an object")
    if summary.get("method") not in SUMMARY_METHODS:
        raise ValueError("executive_summary method must say whether AI was used")
    for key in ("headline", "rotation_view", "drivers_view", "notice"):
        if not isinstance(summary.get(key), str) or not summary[key].strip():
            raise ValueError("executive_summary needs text for " + key)
    watch = summary.get("watch")
    if not isinstance(watch, list) or len(watch) > 5 or any(
            not isinstance(x, str) or not x.strip() for x in watch):
        raise ValueError("executive_summary watch must be a short list of sentences")
    if summary.get("human_review_required") is not True:
        raise ValueError("executive_summary must require human review")
    if summary["method"] == "ai_validated" and not (
            summary.get("provider") and summary.get("model")):
        raise ValueError("AI summary must name its provider and model")
    if summary["method"] == "rules_only" and (
            summary.get("provider") or summary.get("model")):
        raise ValueError("rule-based summary must not claim a model")


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
        # Optional, additive (older snapshots do not have it): when this item's
        # evidence was collected. Must be a timestamp that states its timezone.
        if "collected_at_utc" in item:
            try:
                stamp = datetime.fromisoformat(str(item["collected_at_utc"]))
            except ValueError:
                raise ValueError("invalid collected_at_utc")
            if stamp.tzinfo is None:
                raise ValueError("collected_at_utc must include a timezone")
        if "flow_windows" in item:
            validate_flow_windows(item["flow_windows"], item["id"])
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
    if "rotation" in feed:
        validate_rotation(feed["rotation"])
    if "executive_summary" in feed:
        validate_executive_summary(feed["executive_summary"])
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
