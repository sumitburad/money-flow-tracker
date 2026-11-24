"""The rules the private algo app applies to this repo's public feed, written down independently.

Source: the handover from the algo-trader project (23 Nov 2026). The algo app reads
https://raw.githubusercontent.com/sumitburad/money-flow-tracker/main/data/feed/v1/latest.json and ignores
the whole feed if any rule below fails. ``validate_feed`` in backend/feed_contract.py checks much of the same;
these rules are kept here on purpose as a second, separate statement, so that changing one without the
other is noticed. Adding new fields to the feed is fine. Changing or removing anything below needs notice
to the algo side first.

Nothing from the algo side is ever stored in this repo (no positions, account data, strategies, tokens or
prices), and nothing here reads it.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FEED_FILES = ["data/feed/v1/latest.json", "docs/feed/v1/latest.json", "frontend/feed/v1/latest.json"]

FAMILIES = {"money_flow", "price_trend", "breadth", "positioning", "macro_liquidity", "news"}
STATES = {"supportive", "neutral", "opposing", "not_available"}
LABELS = {"Bullish", "Neutral/Mixed", "Bearish"}
BAD_KEYS = {"smart_money_score", "current_price", "raw_ohlcv", "account", "positions", "token", "api_key"}
TEXT_FIELDS = ("id", "item", "group", "symbol", "region", "currency", "label", "freshness")
USAGE = "research_only_not_order_authorization"
MAX_AGE = timedelta(hours=120)


def non_empty(value):
    return isinstance(value, str) and value.strip() != ""


def keys_anywhere(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from keys_anywhere(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from keys_anywhere(value)


def problems(feed, now=None):
    """Every rule the algo app applies that ``feed`` breaks. With ``now`` the age rules are applied too."""
    found = []
    if feed.get("schema_version") != "1.0":
        found.append("schema_version is not '1.0'")
    if feed.get("usage") != USAGE:
        found.append("usage is not the exact required text")
    raw = feed.get("generated_at_utc")
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            found.append("generated_at_utc has no timezone")
        elif now is not None:
            if now - stamp > MAX_AGE:
                found.append("generated_at_utc is older than 120 hours")
            if stamp > now + timedelta(minutes=1):
                found.append("generated_at_utc is in the future")
    except ValueError:
        found.append("generated_at_utc is not an ISO time")
    items = feed.get("items")
    if not isinstance(items, list) or not items:
        return found + ["items is not a non-empty list"]
    seen = set()
    for number, item in enumerate(items):
        if not isinstance(item, dict):
            found.append("item %d is not an object" % number)
            continue
        where = "item %s" % item.get("id", number)
        for field in TEXT_FIELDS:
            if not non_empty(item.get(field)):
                found.append("%s: %s is not a non-empty string" % (where, field))
        if item.get("id") in seen:
            found.append("%s: duplicate id" % where)
        seen.add(item.get("id"))
        if item.get("label") not in LABELS:
            found.append("%s: label is not one of the three allowed words" % where)
        families = item.get("families")
        if not isinstance(families, dict) or set(families) != FAMILIES:
            found.append("%s: families do not have exactly the six keys" % where)
            families = families if isinstance(families, dict) else {}
        for name, family in families.items():
            state = family.get("state") if isinstance(family, dict) else None
            if state not in STATES:
                found.append("%s: %s has an unknown state" % (where, name))
            if state in ("supportive", "opposing"):
                source = family.get("source")
                if not (isinstance(source, str) and source.startswith("https://")):
                    found.append("%s: %s is %s but its source is not https" % (where, name, state))
                observed = family.get("observed_at")
                try:
                    datetime.fromisoformat(str(observed)[:10])
                except ValueError:
                    found.append("%s: %s is %s but has no observed_at date" % (where, name, state))
        money = families.get("money_flow")
        if isinstance(money, dict) and money.get("state") == "not_available" and item.get("label") != "Neutral/Mixed":
            found.append("%s: money_flow is not_available but the label is not Neutral/Mixed" % where)
        bad = sorted({k for k in keys_anywhere(item) if k.lower() in BAD_KEYS})
        if bad:
            found.append("%s: forbidden keys: %s" % (where, ", ".join(bad)))
    if not isinstance(feed.get("macro"), dict):
        found.append("macro is not an object")
    for block in ("regime", "calendar"):                 # kept for the algo app's planned Health block
        if not isinstance(feed.get(block), dict) or not feed.get(block):
            found.append("%s is missing or empty" % block)
    return found


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FEED_FILES)
def test_the_published_feed_passes_every_rule_the_algo_app_applies(name):
    feed = load(name)
    stamp = datetime.fromisoformat(feed["generated_at_utc"])
    assert problems(feed, now=stamp) == []                        # age is judged at the time it was built


def test_the_three_published_copies_are_the_same_feed():
    assert load(FEED_FILES[0]) == load(FEED_FILES[1]) == load(FEED_FILES[2])


def test_the_status_file_for_the_algo_health_block_is_there():
    status = load("docs/status.json")
    assert isinstance(status, dict) and status.get("status") in ("ok", "degraded", "failed")


def test_a_feed_with_the_news_block_still_passes():
    """Whatever the news block holds, it is a new top-level field and none of the rules above look at it."""
    feed = load(FEED_FILES[0])
    for state in ("ok", "partial", "unavailable", "disabled"):
        feed["market_news"] = {"status": state, "stories": []}
        assert problems(feed, now=datetime.fromisoformat(feed["generated_at_utc"])) == []


# ---- the checker itself: each rule must be able to fail (otherwise the tests above prove nothing)

def mutate(feed, how):
    out = copy.deepcopy(feed)
    how(out)
    return out


FIRST = lambda f: f["items"][0]
MUTATIONS = {
    "schema_version": lambda f: f.update(schema_version="1.1"),
    "usage": lambda f: f.update(usage="research_only"),
    "no_timezone": lambda f: f.update(generated_at_utc="2026-11-24T01:11:50"),
    "not_a_time": lambda f: f.update(generated_at_utc="yesterday"),
    "empty_items": lambda f: f.update(items=[]),
    "empty_text_field": lambda f: FIRST(f).update(freshness=""),
    "number_for_text": lambda f: FIRST(f).update(symbol=5),
    "duplicate_id": lambda f: f["items"][1].update(id=FIRST(f)["id"]),
    "label": lambda f: FIRST(f).update(label="Neutral"),
    "missing_family": lambda f: FIRST(f)["families"].pop("news"),
    "extra_family": lambda f: FIRST(f)["families"].update(extra={"state": "neutral"}),
    "state": lambda f: FIRST(f)["families"]["breadth"].update(state="maybe"),
    "supportive_without_https": lambda f: FIRST(f)["families"]["price_trend"].update(
        state="supportive", source="http://example.org/x", observed_at="2026-11-23"),
    "opposing_without_date": lambda f: FIRST(f)["families"]["price_trend"].update(
        state="opposing", source="https://example.org/x", observed_at=""),
    "money_flow_missing_but_bullish": lambda f: (FIRST(f)["families"]["money_flow"].update(state="not_available"),
                                                 FIRST(f).update(label="Bullish")),
    "forbidden_key": lambda f: FIRST(f).update(current_price=1.0),
    "forbidden_key_deep": lambda f: FIRST(f)["families"]["breadth"].update(raw_ohlcv=[1]),
    "macro": lambda f: f.update(macro=[]),
    "regime_missing": lambda f: f.pop("regime"),
    "calendar_empty": lambda f: f.update(calendar={}),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_rule_can_fail(name):
    feed = load(FEED_FILES[0])
    stamp = datetime.fromisoformat(feed["generated_at_utc"])
    assert problems(mutate(feed, MUTATIONS[name]), now=stamp), name


def test_the_age_rules_apply_when_a_clock_is_given():
    feed = load(FEED_FILES[0])
    stamp = datetime.fromisoformat(feed["generated_at_utc"])
    assert problems(feed, now=stamp + timedelta(hours=119)) == []
    assert problems(feed, now=stamp + timedelta(hours=121)) == ["generated_at_utc is older than 120 hours"]
    assert problems(feed, now=stamp - timedelta(hours=2)) == ["generated_at_utc is in the future"]
