"""Versioned, read-only feed contract; safe for downstream research clients."""
import json
from datetime import date, datetime, timezone
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

# Calendar of coming events: dates only, never a forecast of the result.
CALENDAR_BASES = {"fred_release_calendar", "built_in_list"}
CALENDAR_CATEGORIES = {"inflation", "growth", "central_bank"}
CALENDAR_IMPORTANCE = {"high", "medium"}
CALENDAR_SOURCE_STATUS = {"ok", "unavailable", "not_configured", "needs_update"}

# Risk-on / risk-off banner: a checklist of market groups. Words and counts of checks only;
# never a number derived from prices, and never a score.
REGIME_WINDOWS = ("week", "month")
REGIME_VOTES = {"risk_on", "risk_off", "neutral", "not_available"}
REGIME_LABELS = {"risk_on", "risk_off", "mixed", "not_enough_data"}
REGIME_KINDS = {"trend", "relative"}
REGIME_LEVEL = {"risk_off": -1, "mixed": 0, "risk_on": 1}

# Market and company news: headline, publisher, link and time only. No article text.
NEWS_STATUS = {"ok", "partial", "unavailable", "disabled"}
NEWS_MAX_STORIES = 60
NEWS_MAX_TITLE = 300


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


def _day(value, where):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(where + " must be a date (YYYY-MM-DD)")


def _text(record, key, where):
    if not isinstance(record.get(key), str) or not record[key].strip():
        raise ValueError(where + " needs text for " + key)


def _https(value, where):
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ValueError(where + " must be an https link")


def validate_calendar(block):
    """Optional top-level block: dates of coming releases and Fed meetings."""
    if not isinstance(block, dict):
        raise ValueError("calendar must be an object")
    as_of = _day(block.get("as_of"), "calendar as_of")
    if not isinstance(block.get("events"), list):
        raise ValueError("calendar events must be a list")
    for event in block["events"]:
        if not isinstance(event, dict):
            raise ValueError("calendar event must be an object")
        for key in ("id", "name", "why"):
            _text(event, key, "calendar event")
        if event.get("category") not in CALENDAR_CATEGORIES:
            raise ValueError("calendar event has an unknown category")
        if event.get("importance") not in CALENDAR_IMPORTANCE:
            raise ValueError("calendar event has an unknown importance")
        if event.get("basis") not in CALENDAR_BASES:
            raise ValueError("calendar event must say where its date comes from")
        day = _day(event.get("date"), "calendar event date")
        days_away = event.get("days_away")
        if (not isinstance(days_away, int) or isinstance(days_away, bool)
                or days_away < 0 or days_away != (day - as_of).days):
            raise ValueError("calendar days_away must match the date")
        _https(event.get("source_url"), "calendar event source_url")
    if not isinstance(block.get("sources"), list):
        raise ValueError("calendar sources must be a list")
    for source in block["sources"]:
        if not isinstance(source, dict) or source.get("status") not in CALENDAR_SOURCE_STATUS:
            raise ValueError("calendar source needs a known status")
        _text(source, "id", "calendar source")
        _https(source.get("url"), "calendar source url")
    _text(block, "notice", "calendar")


def _aware(value, where):
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        raise ValueError(where + " must be a timestamp")
    if stamp.tzinfo is None:
        raise ValueError(where + " must include a timezone")
    return stamp


def validate_market_news(block):
    """Optional top-level block: market and company headlines, as published, with links."""
    if not isinstance(block, dict):
        raise ValueError("market_news must be an object")
    if block.get("status") not in NEWS_STATUS:
        raise ValueError("market_news has an unknown status")
    _aware(block.get("as_of_utc"), "market_news as_of_utc")
    source = block.get("source")
    if not isinstance(source, dict):
        raise ValueError("market_news must name its source")
    _text(source, "id", "market_news source")
    _text(source, "name", "market_news source")
    _https(source.get("url"), "market_news source url")
    queries = block.get("queries")
    if (not isinstance(queries, dict) or not _whole(queries.get("asked"))
            or not _whole(queries.get("answered")) or queries["answered"] > queries["asked"]):
        raise ValueError("market_news queries must be whole numbers")
    themes = block.get("themes")
    if not isinstance(themes, list):
        raise ValueError("market_news themes must be a list")
    theme_ids = set()
    for theme in themes:
        if not isinstance(theme, dict):
            raise ValueError("market_news theme must be an object")
        _text(theme, "id", "market_news theme")
        _text(theme, "name", "market_news theme")
        theme_ids.add(theme["id"])
    watchlist = block.get("watchlist")
    if not isinstance(watchlist, list) or any(not isinstance(n, str) or not n for n in watchlist):
        raise ValueError("market_news watchlist must be a list of names")
    stories = block.get("stories")
    if not isinstance(stories, list) or len(stories) > NEWS_MAX_STORIES:
        raise ValueError("market_news stories must be a short list")
    if block["status"] in ("unavailable", "disabled") and stories:
        raise ValueError("market_news cannot carry headlines when the source gave none")
    seen = set()
    for story in stories:
        if not isinstance(story, dict):
            raise ValueError("market_news story must be an object")
        for key in ("id", "title", "publisher"):
            _text(story, key, "market_news story")
        if len(story["title"]) > NEWS_MAX_TITLE:
            raise ValueError("market_news headline is too long")
        if story["id"] in seen:
            raise ValueError("duplicate market_news story")
        seen.add(story["id"])
        _https(story.get("url"), "market_news story url")
        _aware(story.get("seen_at_utc"), "market_news story seen_at_utc")
        for key in ("topics", "companies"):
            if not isinstance(story.get(key), list) or any(
                    not isinstance(x, str) or not x for x in story[key]):
                raise ValueError("market_news story " + key + " must be a list of names")
        if any(topic not in theme_ids for topic in story["topics"]):
            raise ValueError("market_news story has an unknown topic")
        if any(name not in watchlist for name in story["companies"]):
            raise ValueError("market_news story names a company that is not on the watchlist")
    _text(block, "notice", "market_news")


def regime_label(tally, rule):
    """The one rule that turns the checks' votes into a banner word.

    risk_on / risk_off need a clear majority of the checks that have a vote and at most
    ``max_opposing`` checks leaning the other way; anything else is "mixed".
    """
    on, off, neutral = tally["risk_on"], tally["risk_off"], tally["neutral"]
    assessed = on + off + neutral
    if assessed < rule["min_assessed_checks"]:
        return "not_enough_data"
    need = rule["agree_share"] * assessed - 1e-9
    if on >= need and off <= rule["max_opposing"]:
        return "risk_on"
    if off >= need and on <= rule["max_opposing"]:
        return "risk_off"
    return "mixed"


def regime_shift(month_label, week_label):
    """Is the last week more or less risk-on than the month as a whole?"""
    longer, shorter = REGIME_LEVEL.get(month_label), REGIME_LEVEL.get(week_label)
    if longer is None or shorter is None:
        return "not_available"
    if shorter == longer:
        return "steady"
    return "improving" if shorter > longer else "weakening"


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_regime(block):
    """Optional top-level block: the risk-on / risk-off banner and the checks behind it."""
    if not isinstance(block, dict):
        raise ValueError("regime must be an object")
    for key in ("label", "short_term_label"):
        if block.get(key) not in REGIME_LABELS:
            raise ValueError("regime has an unknown " + key)
    if block.get("shift") not in FLOW_TRENDS:
        raise ValueError("regime has an unknown shift")
    if block.get("as_of") is None:
        if not (block["label"] == block["short_term_label"] == "not_enough_data"):
            raise ValueError("regime needs a date unless it says there is not enough data")
    else:
        _day(block["as_of"], "regime as_of")
    rule = block.get("rule")
    if (not isinstance(rule, dict) or not _whole(rule.get("min_assessed_checks"))
            or not _whole(rule.get("max_opposing"))
            or isinstance(rule.get("agree_share"), bool)
            or not isinstance(rule.get("agree_share"), (int, float))
            or not 0 < rule["agree_share"] <= 1):
        raise ValueError("regime must publish the rule that produced the label")
    checks = block.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("regime needs its checks")
    seen = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("regime check must be an object")
        for key in ("id", "name", "question"):
            _text(check, key, "regime check")
        if check["id"] in seen:
            raise ValueError("duplicate regime check")
        seen.add(check["id"])
        if check.get("kind") not in REGIME_KINDS:
            raise ValueError("regime check has an unknown kind")
        windows = check.get("windows")
        if not isinstance(windows, dict) or set(windows) != set(REGIME_WINDOWS):
            raise ValueError("regime check needs a week and a month")
        for record in windows.values():
            if not isinstance(record, dict) or record.get("vote") not in REGIME_VOTES:
                raise ValueError("regime check has an unknown vote")
            _text(record, "reading", "regime check")
    windows = block.get("windows")
    if not isinstance(windows, dict) or set(windows) != set(REGIME_WINDOWS):
        raise ValueError("regime needs a week and a month")
    for name, record in windows.items():
        if not isinstance(record, dict) or record.get("label") not in REGIME_LABELS:
            raise ValueError("regime window has an unknown label")
        _text(record, "title", "regime window")
        tally = record.get("tally")
        if (not isinstance(tally, dict) or set(tally) != REGIME_VOTES
                or not all(_whole(v) for v in tally.values())):
            raise ValueError("regime tally must count every kind of vote")
        # The tally has to be what the checks actually voted, and the label has to be
        # exactly what the published rule gives for that tally: nothing else may set it.
        recount = {vote: 0 for vote in REGIME_VOTES}
        for check in checks:
            recount[check["windows"][name]["vote"]] += 1
        if recount != tally:
            raise ValueError("regime tally does not match the checks")
        if record["label"] != regime_label(tally, rule):
            raise ValueError("regime label does not follow the published rule")
    if block["label"] != windows["month"]["label"] or (
            block["short_term_label"] != windows["week"]["label"]):
        raise ValueError("regime headline must match its month and week labels")
    if block["shift"] != regime_shift(block["label"], block["short_term_label"]):
        raise ValueError("regime shift does not follow the labels")
    for key in ("method", "notice"):
        _text(block, key, "regime")


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
    if "calendar" in feed:
        validate_calendar(feed["calendar"])
    if "regime" in feed:
        validate_regime(feed["regime"])
    if "market_news" in feed:
        validate_market_news(feed["market_news"])
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
