import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import backend.run_daily as engine
from backend.feed_contract import (FORBIDDEN, REGIME_VOTES, REGIME_WINDOWS, regime_label,
                                   regime_shift, validate_feed, validate_regime)
from backend.flow_windows import load_config as load_flow_config
from backend.regime import (build_regime, digest_regime, evaluate_check, load_config,
                            method_text, usable_close, window_return)

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config()
FLOW = load_flow_config()
NOW = datetime(2026, 11, 22, 13, 37, tzinfo=timezone.utc)     # a Sunday
END = "2026-11-20"                                            # the Friday before
CHECKS = {check["id"]: check for check in CFG["checks"]}
UNIVERSE = {a["id"] for a in yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())["assets"]}


# --------------------------------------------------------------- test data helpers

def series(first=0.0, last=0.0, scale=1.0, n=60, end=END):
    """35 flat days, then 15 days at ``first`` a day, then the last 5 days at ``last`` a day."""
    daily = np.array([0.0] * (n - 20) + [first * scale] * 15 + [last * scale] * 5)
    index = pd.bdate_range(end=end, periods=n)
    return pd.Series(100.0 * np.cumprod(1.0 + daily), index=index)


def flat(n=60, end=END):
    return series(0.0, 0.0, n=n, end=end)


def steady(drift, n=60, end=END):
    index = pd.bdate_range(end=end, periods=n)
    return pd.Series(100.0 * (1 + drift) ** np.arange(n), index=index)


def world(month, week, scale_small=2.0):
    """Closes for every member of every check, leaning the same way for every check.

    month and week are +1 (risk-on lean) or -1 (risk-off lean). The first 15 days of the
    series decide the month reading and the last 5 days the week reading.
    """
    out = {}
    for check in CFG["checks"]:
        if check["kind"] == "trend":
            sign = 1 if check["risk_on_when"] == "up" else -1
            for member in check["members"]:
                out[member] = series(0.01 * sign * month, 0.01 * sign * week)
        else:
            for member in check["b"]["members"]:
                out.setdefault(member, flat())
            for member in check["a"]["members"]:
                # the confident side moves further than the cautious side, in the same direction
                out[member] = series(0.01 * month, 0.01 * week, scale=scale_small)
    return out


def votes(block, window):
    return {c["id"]: c["windows"][window]["vote"] for c in block["checks"]}


def build(closes):
    return build_regime(closes, CFG, FLOW, NOW)


# --------------------------------------------------------------- the rule that sets the word

RULE = {"min_assessed_checks": 5, "agree_share": 0.6, "max_opposing": 1}


@pytest.mark.parametrize("on,off,neutral,expected", [
    (8, 0, 0, "risk_on"), (5, 1, 2, "risk_on"), (5, 0, 3, "risk_on"),
    (4, 0, 4, "mixed"),            # only half lean the same way
    (6, 2, 0, "mixed"),            # two checks disagree: too many
    (4, 4, 0, "mixed"),
    (0, 8, 0, "risk_off"), (1, 5, 2, "risk_off"), (2, 6, 0, "mixed"),
    (3, 1, 0, "not_enough_data"),  # only four checks have a vote
    (0, 0, 0, "not_enough_data"),
])
def test_label_rule(on, off, neutral, expected):
    tally = {"risk_on": on, "risk_off": off, "neutral": neutral, "not_available": 8 - on - off - neutral}
    assert regime_label(tally, RULE) == expected


def test_exactly_the_agree_share_counts():
    # 3 of 5 is exactly 60 percent, which meets "at least 60 percent"
    tally = {"risk_on": 3, "risk_off": 0, "neutral": 2, "not_available": 0}
    assert regime_label(tally, RULE) == "risk_on"


@pytest.mark.parametrize("month,week,expected", [
    ("risk_on", "risk_on", "steady"), ("risk_off", "risk_off", "steady"), ("mixed", "mixed", "steady"),
    ("risk_off", "risk_on", "improving"), ("mixed", "risk_on", "improving"),
    ("risk_on", "risk_off", "weakening"), ("risk_on", "mixed", "weakening"),
    ("not_enough_data", "risk_on", "not_available"), ("risk_on", "not_enough_data", "not_available"),
])
def test_shift_rule(month, week, expected):
    assert regime_shift(month, week) == expected


# --------------------------------------------------------------- trend checks

def stocks_with(up, down, flats):
    ids = CHECKS["stocks"]["members"]
    closes = {}
    for i, member in enumerate(ids):
        if i < up:
            closes[member] = steady(0.004)
        elif i < up + down:
            closes[member] = steady(-0.004)
        elif i < up + down + flats:
            closes[member] = flat()
    return closes


@pytest.mark.parametrize("up,down,flats,expected", [
    (6, 0, 0, "risk_on"), (4, 2, 0, "risk_on"),
    (3, 3, 0, "neutral"),          # not a strict majority
    (3, 1, 2, "neutral"),          # three of six is not more than half
    (4, 0, 2, "risk_on"),
    (2, 4, 0, "risk_off"), (0, 6, 0, "risk_off"),
    (0, 0, 6, "neutral"),
])
def test_trend_check_needs_a_strict_majority(up, down, flats, expected):
    result = evaluate_check(CHECKS["stocks"], stocks_with(up, down, flats), CFG, FLOW)
    assert result["windows"]["week"]["vote"] == expected
    assert result["windows"]["month"]["vote"] == expected


def test_trend_reading_counts_markets_in_plain_words():
    result = evaluate_check(CHECKS["stocks"], stocks_with(4, 1, 1), CFG, FLOW)
    assert result["windows"]["week"]["reading"] == "4 of 6 stock markets up, 1 down, 1 flat"
    result = evaluate_check(CHECKS["stocks"], stocks_with(6, 0, 0), CFG, FLOW)
    assert result["windows"]["week"]["reading"] == "6 of 6 stock markets up, 0 down"


def test_a_falling_fear_gauge_is_risk_on_and_a_rising_one_is_risk_off():
    falling = {"vix": steady(-0.01), "indiavix": steady(-0.01)}
    rising = {"vix": steady(0.01), "indiavix": steady(0.01)}
    assert evaluate_check(CHECKS["fear"], falling, CFG, FLOW)["windows"]["week"]["vote"] == "risk_on"
    assert evaluate_check(CHECKS["fear"], rising, CFG, FLOW)["windows"]["week"]["vote"] == "risk_off"


def test_a_weaker_dollar_is_risk_on():
    weak = {"dollar": steady(-0.002), "dollar_etf": steady(-0.002)}
    strong = {"dollar": steady(0.002), "dollar_etf": steady(0.002)}
    assert evaluate_check(CHECKS["dollar"], weak, CFG, FLOW)["windows"]["month"]["vote"] == "risk_on"
    assert evaluate_check(CHECKS["dollar"], strong, CFG, FLOW)["windows"]["month"]["vote"] == "risk_off"


def test_two_dollar_measures_that_disagree_give_no_lean():
    mixed = {"dollar": steady(0.002), "dollar_etf": steady(-0.002)}
    assert evaluate_check(CHECKS["dollar"], mixed, CFG, FLOW)["windows"]["week"]["vote"] == "neutral"


def test_one_member_is_enough_when_the_config_says_so():
    result = evaluate_check(CHECKS["crypto"], {"bitcoin": steady(0.01)}, CFG, FLOW)
    assert result["windows"]["week"]["vote"] == "risk_on"
    assert result["windows"]["week"]["reading"] == "1 of 1 coins up, 0 down"


def test_too_few_stock_markets_gives_no_vote():
    three = evaluate_check(CHECKS["stocks"], stocks_with(3, 0, 0), CFG, FLOW)
    assert three["windows"]["week"] == {"vote": "not_available", "reading": "Not enough data"}
    four = evaluate_check(CHECKS["stocks"], stocks_with(4, 0, 0), CFG, FLOW)
    assert four["windows"]["week"]["vote"] == "risk_on"


# --------------------------------------------------------------- "A versus B" checks

def credit(a_drift, b_drift):
    return {"us_highyield": steady(a_drift), "us_treasury": steady(b_drift)}


def test_relative_check_follows_the_side_that_leads_by_enough():
    on = evaluate_check(CHECKS["credit"], credit(0.002, -0.001), CFG, FLOW)
    assert on["windows"]["week"]["vote"] == "risk_on"
    assert on["windows"]["week"]["reading"] == "Junk bonds did better than government bonds"
    off = evaluate_check(CHECKS["credit"], credit(-0.001, 0.002), CFG, FLOW)
    assert off["windows"]["month"]["vote"] == "risk_off"
    assert off["windows"]["month"]["reading"] == "Government bonds did better than junk bonds"


def test_a_small_gap_is_neutral():
    result = evaluate_check(CHECKS["credit"], credit(0.0004, 0.0), CFG, FLOW)
    assert result["windows"]["week"]["vote"] == "neutral"
    assert result["windows"]["week"]["reading"] == "Junk bonds and government bonds did about the same"


def test_the_minimum_gap_is_different_for_week_and_month():
    # about 1.0 points apart over 5 sessions (above 0.75) but about 4 points over 20 sessions
    result = evaluate_check(CHECKS["credit"], credit(0.002, 0.0), CFG, FLOW)
    assert result["windows"]["week"]["vote"] == "risk_on"
    assert result["windows"]["month"]["vote"] == "risk_on"
    # about 0.4 points over 5 sessions (below 0.75)
    result = evaluate_check(CHECKS["credit"], credit(0.0008, 0.0), CFG, FLOW)
    assert result["windows"]["week"]["vote"] == "neutral"


def test_a_side_with_no_data_gives_no_vote():
    result = evaluate_check(CHECKS["credit"], {"us_highyield": steady(0.01)}, CFG, FLOW)
    assert result["windows"]["week"] == {"vote": "not_available", "reading": "Not enough data"}


def test_a_group_is_averaged_and_needs_its_minimum_members():
    full = {m: steady(0.004) for m in CHECKS["cyclicals"]["a"]["members"]}
    full.update({m: flat() for m in CHECKS["cyclicals"]["b"]["members"]})
    assert evaluate_check(CHECKS["cyclicals"], full, CFG, FLOW)["windows"]["week"]["vote"] == "risk_on"
    two_of_three = dict(full)
    del two_of_three["us_materials"]
    assert evaluate_check(CHECKS["cyclicals"], two_of_three, CFG, FLOW)["windows"]["week"]["vote"] == "risk_on"
    one_of_three = dict(two_of_three)
    del one_of_three["us_industrials"]
    assert evaluate_check(CHECKS["cyclicals"], one_of_three, CFG, FLOW)["windows"]["week"]["vote"] == "not_available"


def test_a_group_average_is_not_dominated_by_one_member():
    # one growth sector falls hard, two rise: the average still leans the confident way
    members = CHECKS["cyclicals"]["a"]["members"]
    closes = {members[0]: steady(-0.002), members[1]: steady(0.006), members[2]: steady(0.006)}
    closes.update({m: flat() for m in CHECKS["cyclicals"]["b"]["members"]})
    assert evaluate_check(CHECKS["cyclicals"], closes, CFG, FLOW)["windows"]["month"]["vote"] == "risk_on"


def test_window_return():
    close = steady(0.01)
    assert window_return(close, 5) == pytest.approx(1.01 ** 5 - 1)
    assert window_return(close.iloc[:4], 5) is None
    assert window_return(pd.Series([0.0] * 10, index=pd.bdate_range(end=END, periods=10)), 5) is None


# --------------------------------------------------------------- the whole banner

def test_everything_leaning_confident_is_risk_on():
    block = build(world(+1, +1))
    assert block["label"] == "risk_on" and block["short_term_label"] == "risk_on"
    assert block["shift"] == "steady"
    assert set(votes(block, "month").values()) == {"risk_on"}
    assert block["windows"]["month"]["tally"] == {"risk_on": 8, "risk_off": 0, "neutral": 0, "not_available": 0}
    assert block["as_of"] == END
    validate_regime(block)


def test_everything_leaning_defensive_is_risk_off():
    block = build(world(-1, -1))
    assert block["label"] == "risk_off" and block["short_term_label"] == "risk_off"
    assert block["shift"] == "steady"
    validate_regime(block)


def test_a_weak_month_with_a_strong_last_week_is_improving():
    block = build(world(-1, +1))
    assert block["label"] == "risk_off"
    assert block["short_term_label"] == "risk_on"
    assert block["shift"] == "improving"
    validate_regime(block)


def test_a_strong_month_with_a_weak_last_week_is_weakening():
    block = build(world(+1, -1))
    assert block["label"] == "risk_on"
    assert block["short_term_label"] == "risk_off"
    assert block["shift"] == "weakening"
    validate_regime(block)


def test_a_split_picture_is_mixed():
    closes = world(+1, +1)
    for member in ("sp500", "nasdaq100", "nifty50", "europe", "japan", "em",
                   "vix", "indiavix", "dollar", "dollar_etf", "bitcoin", "ethereum"):
        closes[member] = world(-1, -1)[member]
    block = build(closes)
    assert block["label"] == "mixed"
    validate_regime(block)


def test_one_check_disagreeing_still_allows_risk_on_but_two_do_not():
    closes = world(+1, +1)
    closes["bitcoin"] = closes["ethereum"] = world(-1, -1)["bitcoin"]
    one = build(closes)
    assert one["windows"]["week"]["tally"]["risk_off"] == 1
    assert one["short_term_label"] == "risk_on"
    closes["vix"] = closes["indiavix"] = world(-1, -1)["vix"]
    two = build(closes)
    assert two["windows"]["week"]["tally"]["risk_off"] == 2
    assert two["short_term_label"] == "mixed"


def test_too_few_checks_with_data_is_not_enough_data():
    full = world(+1, +1)
    closes = {m: full[m] for check in CFG["checks"] if check["kind"] == "trend"
              for m in check["members"]}
    block = build(closes)
    assert block["windows"]["month"]["tally"]["not_available"] == 4      # the four A-vs-B checks
    assert block["label"] == "not_enough_data" and block["short_term_label"] == "not_enough_data"
    assert block["shift"] == "not_available"
    validate_regime(block)


def test_no_data_at_all_still_gives_a_valid_block():
    block = build({})
    assert block["as_of"] is None
    assert block["label"] == block["short_term_label"] == "not_enough_data"
    validate_regime(block)
    assert all(v == "not_available" for v in votes(block, "week").values())


def test_old_or_short_history_is_ignored():
    old = {m: s.set_axis(pd.bdate_range(end="2026-11-10", periods=len(s))) for m, s in world(+1, +1).items()}
    assert build(old)["label"] == "not_enough_data"
    short = {m: s.iloc[-20:] for m, s in world(+1, +1).items()}
    assert build(short)["label"] == "not_enough_data"
    assert usable_close(world(+1, +1)["sp500"], NOW, FLOW) is not None
    assert usable_close(None, NOW, FLOW) is None


def test_as_of_is_the_newest_session_used():
    closes = world(+1, +1)
    closes["bitcoin"] = series(0.01, 0.01, end="2026-11-19")
    assert build(closes)["as_of"] == END


def test_the_published_block_holds_words_and_counts_only():
    block = build(world(+1, +1))
    floats, forbidden = [], []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in FORBIDDEN:
                    forbidden.append(key)
                walk(value, path + [key])
        elif isinstance(node, list):
            for value in node:
                walk(value, path)
        elif isinstance(node, float):
            floats.append(path)

    walk(block, [])
    assert not forbidden
    assert floats == [["rule", "agree_share"]]
    text = json.dumps(block)
    assert "score" not in text.lower() and "rank" not in text.lower()


def test_building_does_not_change_the_inputs():
    closes = world(+1, +1)
    before = {k: v.copy() for k, v in closes.items()}
    build(closes)
    assert all(closes[k].equals(before[k]) for k in closes)


def test_method_text_follows_the_config():
    text = method_text(CFG)
    assert text.startswith("8 simple checks")
    assert "60%" in text and "no more than 1" in text
    changed = copy.deepcopy(CFG)
    changed["rule"]["agree_share"] = 0.75
    changed["rule"]["max_opposing"] = 2
    assert "75%" in method_text(changed) and "no more than 2" in method_text(changed)


def test_digest_is_a_few_words_and_counts():
    assert digest_regime(None) is None
    digest = digest_regime(build(world(-1, +1)))
    assert digest == {"month": "risk_off", "week": "risk_on", "shift": "improving",
                      "agreeing": {"week": {"risk_on": 8, "risk_off": 0},
                                   "month": {"risk_on": 0, "risk_off": 8}}}


# --------------------------------------------------------------- the contract refuses a wrong block

def good():
    return build(world(+1, +1))


def test_contract_rejects_a_label_the_rule_does_not_give():
    block = good()
    block["windows"]["month"]["label"] = "risk_off"
    block["label"] = "risk_off"
    block["shift"] = regime_shift("risk_off", block["short_term_label"])
    with pytest.raises(ValueError, match="rule"):
        validate_regime(block)


def test_contract_rejects_a_tally_that_does_not_match_the_checks():
    block = good()
    block["windows"]["week"]["tally"]["risk_on"] -= 1
    block["windows"]["week"]["tally"]["neutral"] += 1
    with pytest.raises(ValueError, match="tally"):
        validate_regime(block)


def test_contract_rejects_a_changed_vote_without_a_matching_tally():
    block = good()
    block["checks"][0]["windows"]["week"]["vote"] = "risk_off"
    with pytest.raises(ValueError, match="tally"):
        validate_regime(block)


@pytest.mark.parametrize("edit,message", [
    (lambda b: b["checks"][0]["windows"]["week"].update(vote="bullish"), "vote"),
    (lambda b: b.update(label="bullish"), "label"),
    (lambda b: b.update(short_term_label="up"), "short_term_label"),
    (lambda b: b.update(shift="sideways"), "shift"),
    (lambda b: b.update(shift="weakening"), "shift"),
    (lambda b: b.update(as_of=None), "date"),
    (lambda b: b.update(as_of="22 Nov"), "date"),
    (lambda b: b.pop("rule"), "rule"),
    (lambda b: b["rule"].update(agree_share=True), "rule"),
    (lambda b: b["rule"].update(agree_share=0), "rule"),
    (lambda b: b.pop("checks"), "checks"),
    (lambda b: b["checks"][0].update(kind="mystery"), "kind"),
    (lambda b: b["checks"][0]["windows"].pop("month"), "week and a month"),
    (lambda b: b["checks"][0]["windows"]["week"].update(reading=""), "reading"),
    (lambda b: b["checks"].append(copy.deepcopy(b["checks"][0])), "duplicate"),
    (lambda b: b["windows"].pop("week"), "week and a month"),
    (lambda b: b["windows"]["week"].update(tally={"risk_on": 8}), "tally"),
    (lambda b: b["windows"]["week"]["tally"].update(risk_on=-1), "tally"),
    (lambda b: b["windows"]["week"]["tally"].update(risk_on=8.0), "tally"),
    (lambda b: b.update(label="mixed"), "headline"),
    (lambda b: b.update(method=""), "method"),
    (lambda b: b.pop("notice"), "notice"),
])
def test_contract_rejects_a_malformed_block(edit, message):
    block = good()
    edit(block)
    with pytest.raises(ValueError, match=message):
        validate_regime(block)


def minimal_feed(**extra):
    fam = {"state": "not_available", "evidence": "none", "source": None}
    item = {"id": "x", "item": "T", "group": "g", "symbol": "T", "region": "US",
            "currency": "USD", "label": "Neutral/Mixed", "tag": "Steady",
            "agreement": "Weak", "freshness": "current",
            "families": {name: dict(fam) for name in engine.FAMILIES}}
    feed = {"schema_version": "1.0", "usage": "research_only_not_order_authorization",
            "items": [item], "macro": {}}
    feed.update(extra)
    return feed


def test_a_feed_with_the_banner_validates_and_an_old_feed_still_does():
    assert validate_feed(minimal_feed())
    assert validate_feed(minimal_feed(regime=good()))


def test_a_banner_with_a_score_is_refused_by_the_feed_check():
    block = good()
    block["score"] = 70
    with pytest.raises(ValueError, match="forbidden"):
        validate_feed(minimal_feed(regime=block))


def test_a_broken_banner_is_refused_by_the_feed_check():
    block = good()
    block["windows"]["month"]["label"] = "mixed"
    with pytest.raises(ValueError):
        validate_feed(minimal_feed(regime=block))


# --------------------------------------------------------------- the settings file

def test_settings_are_consistent():
    ids = [c["id"] for c in CFG["checks"]]
    assert len(ids) == len(set(ids))
    assert set(CFG["windows"]) == set(REGIME_WINDOWS)
    assert CFG["rule"]["min_assessed_checks"] <= len(ids)
    assert 0 < CFG["rule"]["agree_share"] <= 1
    for name, spec in CFG["windows"].items():
        assert spec["sessions"] > 0 and spec["min_gap_pct"] > 0 and spec["label"]
    for check in CFG["checks"]:
        assert check["name"] and check["question"]
        if check["kind"] == "trend":
            assert check["risk_on_when"] in ("up", "down")
            assert check["noun"] and 1 <= check["min_members"] <= len(check["members"])
            members = check["members"]
        else:
            assert check["kind"] == "relative"
            a, b = check["a"], check["b"]
            assert a["name"] and b["name"] and a["members"] and b["members"]
            assert not set(a["members"]) & set(b["members"])
            assert 1 <= check["min_members_each_side"] <= min(len(a["members"]), len(b["members"]))
            members = a["members"] + b["members"]
        missing = set(members) - UNIVERSE
        assert not missing, check["id"] + " uses unknown items: " + ", ".join(sorted(missing))


def test_the_longest_window_fits_inside_the_history_rule():
    assert max(s["sessions"] for s in CFG["windows"].values()) < 25


def test_votes_are_the_ones_the_contract_knows():
    assert set(votes(build(world(+1, +1)), "week").values()) <= REGIME_VOTES


# --------------------------------------------------------------- hand-off from the item check

def bars_for(end, n=300):
    index = pd.bdate_range(end=end, periods=n)
    i = np.arange(n)
    return pd.DataFrame({"Close": 100 * 1.002 ** i, "Volume": 1e6 * 1.001 ** i}, index=index)


ASSET = {"id": "x", "name": "X", "group": "equity_market", "region": "US", "currency": "USD",
         "symbol": "X", "asset_type": "equity"}


def test_a_fresh_item_hands_its_closes_to_the_banner(monkeypatch):
    monkeypatch.setattr(engine, "fetch_yfinance", lambda asset: (bars_for(END), END, "https://example.org/"))
    sink = {}
    record = engine.assess(ASSET, date(2026, 11, 22), {}, flow_cfg=FLOW, now=NOW, closes_sink=sink)
    assert record["freshness"] == "current"
    assert list(sink) == ["x"]
    assert sink["x"].index[-1].date().isoformat() == END
    assert not np.isnan(sink["x"].to_numpy()).any()


def test_a_stale_item_hands_over_nothing(monkeypatch):
    monkeypatch.setattr(engine, "fetch_yfinance",
                        lambda asset: (bars_for("2026-11-02"), "2026-11-02", "https://example.org/"))
    sink = {}
    record = engine.assess(ASSET, date(2026, 11, 22), {}, flow_cfg=FLOW, now=NOW, closes_sink=sink)
    assert record["freshness"] == "stale"
    assert sink == {}


def test_a_session_still_running_is_left_out_of_the_handed_over_closes(monkeypatch):
    monkeypatch.setattr(engine, "fetch_yfinance",
                        lambda asset: (bars_for("2026-11-20"), "2026-11-20", "https://example.org/"))
    during_session = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)     # US still trading
    sink = {}
    engine.assess(ASSET, date(2026, 11, 20), {}, flow_cfg=FLOW, now=during_session, closes_sink=sink)
    assert sink["x"].index[-1].date().isoformat() == "2026-11-19"


def test_the_item_check_works_without_a_sink_and_survives_a_failing_one(monkeypatch):
    monkeypatch.setattr(engine, "fetch_yfinance", lambda asset: (bars_for(END), END, "https://example.org/"))
    plain = engine.assess(ASSET, date(2026, 11, 22), {}, flow_cfg=FLOW, now=NOW)
    assert plain["freshness"] == "current"

    def boom(*args, **kwargs):
        raise RuntimeError("no")
    monkeypatch.setattr(engine, "completed_closes", boom)
    sink = {}
    record = engine.assess(ASSET, date(2026, 11, 22), {}, flow_cfg=FLOW, now=NOW, closes_sink=sink)
    assert record["freshness"] == "current" and record["flow_windows"]["status"] == "ok"
    assert sink == {}


def test_the_hand_over_changes_nothing_in_the_published_item(monkeypatch):
    monkeypatch.setattr(engine, "fetch_yfinance", lambda asset: (bars_for(END), END, "https://example.org/"))
    with_sink = engine.assess(ASSET, date(2026, 11, 22), {}, flow_cfg=FLOW, now=NOW, closes_sink={})
    without = engine.assess(ASSET, date(2026, 11, 22), {}, flow_cfg=FLOW, now=NOW)
    for record in (with_sink, without):
        record.pop("collected_at_utc")
    assert with_sink == without


def test_the_second_name_in_a_reading_is_lower_case_unless_it_is_an_acronym():
    from backend.regime import _mid
    assert _mid("Government bonds") == "government bonds"
    assert _mid("Gold") == "gold"
    assert _mid("US dollar") == "US dollar"
    assert _mid("A") == "A"

