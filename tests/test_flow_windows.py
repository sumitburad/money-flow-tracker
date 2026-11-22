import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from backend.feed_contract import (FLOW_SIGNALS, expected_flow_signal, validate_feed,
                                   validate_flow_windows, validate_rotation)
from backend.flow_windows import (bar_is_complete, build_rotation, completed_closes,
                                  compute_flow_windows, group_verdict, levels_trend,
                                  load_config, price_direction, typical_move)

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config()
SUNDAY_PM = datetime(2026, 11, 22, 13, 37, tzinfo=timezone.utc)
ASSET = {"id": "x", "asset_type": "equity", "region": "US"}


def make_bars(n=120, end="2026-11-20", drift=0.004, wiggle=0.001, vol_growth=1.04):
    index = pd.bdate_range(end=end, periods=n)
    i = np.arange(n)
    close = 100 * (1 + drift) ** i * (1 + wiggle * (-1.0) ** i)
    return pd.DataFrame({"Close": close, "Volume": 1e6 * vol_growth ** i}, index=index)


def bump_last_volume(bars, factor):
    bars.iloc[-1, bars.columns.get_loc("Volume")] *= factor
    return bars


def signals(block):
    return [block[n]["signal"] for n in ("day", "week", "month")]


# ------------------------------------------------------------------ the rule

@pytest.mark.parametrize("price,volume,expected", [
    ("up", "up", "inflow"), ("down", "up", "outflow"),
    ("up", "down", "inflow_fading"), ("down", "down", "outflow_fading"),
    ("flat", "up", "unclear"), ("up", "flat", "unclear"),
    ("not_available", "up", "not_available"), ("up", "not_available", "not_available"),
])
def test_signal_rule(price, volume, expected):
    assert expected_flow_signal(price, volume) == expected


def test_price_up_and_volume_up_is_inflow_in_all_three_windows():
    block = compute_flow_windows(bump_last_volume(make_bars(), 1.3), ASSET, SUNDAY_PM, CFG)
    assert block["status"] == "ok" and block["as_of"] == "2026-11-20"
    assert signals(block) == ["inflow", "inflow", "inflow"]
    assert block["trend"] == "steady"


def test_price_down_and_volume_up_is_outflow():
    bars = bump_last_volume(make_bars(drift=-0.004), 1.3)
    assert signals(compute_flow_windows(bars, ASSET, SUNDAY_PM, CFG))[1:] == ["outflow", "outflow"]


def test_rising_price_on_falling_volume_is_marked_fading():
    block = compute_flow_windows(make_bars(vol_growth=0.96), ASSET, SUNDAY_PM, CFG)
    assert block["week"]["signal"] == "inflow_fading" and block["month"]["signal"] == "inflow_fading"


def test_tiny_moves_are_flat_not_a_signal():
    bars = make_bars(drift=0.0, wiggle=0.01, vol_growth=1.0)
    bars["Close"] = 100 * (1 + 0.01 * (-1.0) ** np.arange(len(bars)))
    block = compute_flow_windows(bars, ASSET, SUNDAY_PM, CFG)
    assert block["month"]["price"] == "flat" and block["month"]["signal"] == "unclear"


def test_daily_volume_change_inside_the_band_is_flat():
    # Volume +4% a day gives about +4% on the day, so the 10% daily band calls it flat.
    block = compute_flow_windows(make_bars(), ASSET, SUNDAY_PM, CFG)
    assert block["day"]["volume"] == "flat" and block["day"]["signal"] == "unclear"
    assert block["week"]["volume"] == "up"


def test_no_volume_keeps_the_price_direction_but_gives_no_flow_signal():
    bars = make_bars()
    bars["Volume"] = 0.0
    block = compute_flow_windows(bars, ASSET, SUNDAY_PM, CFG)
    assert block["status"] == "ok"
    assert block["month"]["price"] == "up" and block["month"]["volume"] == "not_available"
    assert signals(block) == ["not_available"] * 3
    assert block["trend"] == "not_available"
    del bars["Volume"]
    assert compute_flow_windows(bars, ASSET, SUNDAY_PM, CFG)["week"]["signal"] == "not_available"


def test_risk_gauges_get_no_signal():
    block = compute_flow_windows(make_bars(), {"asset_type": "risk", "region": "US"}, SUNDAY_PM, CFG)
    assert block["status"] == "not_available"


def test_short_or_old_history_is_not_guessed():
    assert compute_flow_windows(make_bars(n=20), ASSET, SUNDAY_PM, CFG)["status"] == "not_available"
    old = compute_flow_windows(make_bars(end="2026-11-02"), ASSET, SUNDAY_PM, CFG)
    assert old["status"] == "not_available" and "too old" in old["reason"]


def test_output_contains_only_categories_no_numbers():
    block = compute_flow_windows(make_bars(), ASSET, SUNDAY_PM, CFG)
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        else:
            assert isinstance(x, str), x      # no price, volume or percentage anywhere
    walk(block)


# ------------------------------------------------------- unfinished sessions

def test_a_session_still_in_progress_is_never_used():
    now_asia_morning = datetime(2026, 11, 23, 2, 7, tzinfo=timezone.utc)
    japan = {"asset_type": "equity", "region": "JP"}
    crypto = {"asset_type": "crypto", "region": "GLOBAL"}
    india = {"asset_type": "equity", "region": "IN"}
    today = now_asia_morning.date()
    assert not bar_is_complete(today, japan, now_asia_morning, CFG)        # Tokyo is trading
    assert not bar_is_complete(today, crypto, now_asia_morning, CFG)       # trades round the clock
    assert bar_is_complete(today, india, datetime(2026, 11, 23, 13, 37, tzinfo=timezone.utc), CFG)
    assert not bar_is_complete(today, india, now_asia_morning, CFG)
    assert bar_is_complete(today, japan, datetime(2026, 11, 23, 13, 37, tzinfo=timezone.utc), CFG)
    assert bar_is_complete(today.replace(day=20), crypto, now_asia_morning, CFG)


def test_unfinished_newest_bar_is_dropped_before_comparing():
    now = datetime(2026, 11, 23, 2, 7, tzinfo=timezone.utc)
    bars = make_bars(end="2026-11-23")
    bars.iloc[-1, bars.columns.get_loc("Volume")] = 1.0     # a few hours of trading only
    crypto = {"asset_type": "crypto", "region": "GLOBAL"}
    block = compute_flow_windows(bars, crypto, now, CFG)
    assert block["as_of"] == "2026-11-20"          # Monday's unfinished bar was skipped
    assert block["day"]["volume"] == "flat"        # it would have read as a volume collapse


def test_session_market_override_in_universe_is_respected():
    asset = {"asset_type": "equity", "region": "CN", "session_market": "US"}
    now = datetime(2026, 11, 23, 13, 37, tzinfo=timezone.utc)
    assert not bar_is_complete(now.date(), asset, now, CFG)
    assert bar_is_complete(now.date(), {"asset_type": "equity", "region": "CN"}, now, CFG)


# ---------------------------------------------------------------- flow trend

@pytest.mark.parametrize("levels,expected", [
    ([-2, 0, 2], "improving"), ([2, 1, 0], "weakening"), ([2, 2, 2], "steady"),
    ([2, -1, 2], "mixed"), ([None, 1, 2], "improving"), ([None, None, 1], "not_available"),
    ([0, 0, 1], "improving"), ([1, 1, 0], "weakening"),
])
def test_levels_trend(levels, expected):
    assert levels_trend(levels) == expected


# ------------------------------------------------------------- rotation map

def item(ident, day, week, month):
    def window(signal):
        price, volume = {"inflow": ("up", "up"), "outflow": ("down", "up"),
                         "inflow_fading": ("up", "down"), "outflow_fading": ("down", "down"),
                         "unclear": ("flat", "up"), "not_available": ("up", "not_available")}[signal]
        return {"price": price, "volume": volume, "signal": signal}
    return {"id": ident, "flow_windows": {"status": "ok", "as_of": "2026-11-20",
            "day": window(day), "week": window(week), "month": window(month), "trend": "steady"}}


def test_group_verdicts():
    counts = {k: 0 for k in FLOW_SIGNALS}
    rule = CFG["rotation"]
    assert group_verdict({**counts, "inflow": 1}, rule) == "not_enough_data"
    assert group_verdict({**counts, "inflow": 4, "outflow": 1, "unclear": 3}, rule) == "inflow_led"
    assert group_verdict({**counts, "inflow": 3, "outflow": 1, "unclear": 4}, rule) == "mixed"   # 3 of 8 is below the 40% lead share
    assert group_verdict({**counts, "outflow": 3, "inflow": 1}, rule) == "outflow_led"
    assert group_verdict({**counts, "inflow": 2, "outflow": 2}, rule) == "mixed"
    assert group_verdict({**counts, "inflow": 1, "unclear": 9}, rule) == "mixed"


def test_rotation_names_where_money_is_moving_and_if_it_is_building():
    cfg = copy.deepcopy(CFG)
    cfg["buckets"] = [
        {"id": "tech", "name": "Tech", "members": ["a", "b", "c"]},
        {"id": "bonds", "name": "Bonds", "members": ["d", "e"]},
        {"id": "fx", "name": "Currencies", "verdict": False, "members": ["f", "g"]},
    ]
    items = [item("a", "inflow", "inflow", "inflow_fading"), item("b", "inflow", "inflow", "outflow_fading"),
             item("c", "unclear", "inflow", "unclear"),
             item("d", "outflow", "outflow", "outflow"), item("e", "outflow", "unclear", "outflow"),
             item("f", "inflow", "inflow", "inflow"), item("g", "outflow", "outflow", "outflow")]
    rotation = build_rotation(items, cfg)
    by_id = {b["id"]: b for b in rotation["buckets"]}
    assert by_id["tech"]["windows"]["week"]["verdict"] == "inflow_led"
    assert by_id["tech"]["windows"]["month"]["verdict"] == "mixed"
    assert by_id["tech"]["trend"] == "improving"            # month mixed -> week inflow-led
    assert by_id["bonds"]["windows"]["month"]["verdict"] == "outflow_led"
    assert by_id["fx"]["windows"]["week"]["verdict"] == "not_applicable" and by_id["fx"]["trend"] == "not_available"
    assert by_id["tech"]["windows"]["week"]["inflow"] == ["a", "b", "c"]
    assert rotation["moves"]["week"] == {"into": ["tech"], "out_of": ["bonds"]}
    assert rotation["moves"]["month"]["out_of"] == ["bonds"]
    pooled = rotation["overall"]["windows"]["week"]["counts"]
    assert pooled["inflow"] == 3 and pooled["outflow"] == 1 and sum(pooled.values()) == 5  # currencies not pooled
    validate_rotation(rotation)


def test_items_without_volume_are_reported_not_counted():
    cfg = copy.deepcopy(CFG)
    cfg["buckets"] = [{"id": "fx", "name": "Currencies", "members": ["f", "g", "h"]}]
    items = [item("f", "not_available", "not_available", "not_available"),
             item("g", "inflow", "inflow", "inflow"), item("h", "inflow", "inflow", "inflow")]
    rotation = build_rotation(items, cfg)
    assert rotation["coverage"]["items_without_volume"] == ["f"]
    assert rotation["buckets"][0]["windows"]["day"]["counts"]["not_available"] == 1


# ---------------------------------------------------- configuration and feed

def test_every_investable_universe_item_is_in_exactly_one_bucket():
    universe = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))["assets"]
    ids = {a["id"] for a in universe}
    listed = [m for b in CFG["buckets"] for m in b["members"]]
    assert len(listed) == len(set(listed)), "an item is in two buckets"
    assert set(listed) <= ids, "bucket names an item that is not in the universe"
    investable = {a["id"] for a in universe if a["asset_type"] not in CFG["excluded_asset_types"]}
    assert investable == set(listed), "an investable item is missing from the rotation map"
    assert {b["id"] for b in CFG["buckets"]} and set(CFG["windows"]) == {"day", "week", "month"}


def test_feed_contract_accepts_the_new_blocks_and_rejects_inconsistent_ones():
    feed = json.loads((ROOT / "data" / "feed" / "v1" / "latest.json").read_text(encoding="utf-8"))
    bars = bump_last_volume(make_bars(), 1.3)
    for entry in feed["items"]:
        entry["flow_windows"] = compute_flow_windows(bars, ASSET, SUNDAY_PM, CFG)
    feed["rotation"] = build_rotation(feed["items"], CFG)
    assert validate_feed(feed)
    bad = copy.deepcopy(feed)
    bad["items"][0]["flow_windows"]["day"]["signal"] = "outflow"
    with pytest.raises(ValueError, match="does not follow"):
        validate_feed(bad)
    bad = copy.deepcopy(feed)
    bad["rotation"]["moves"]["day"]["into"] = ["no_such_bucket"]
    with pytest.raises(ValueError, match="known buckets"):
        validate_feed(bad)
    with pytest.raises(ValueError):
        validate_flow_windows({"status": "ok", "as_of": "2026-11-20"})
    old = json.loads((ROOT / "data" / "feed" / "v1" / "latest.json").read_text(encoding="utf-8"))
    assert validate_feed(old)       # an older snapshot without the new blocks still passes


# ------------------------------------------------- helpers shared with the risk-tone banner

def test_completed_closes_drops_a_session_that_is_still_running():
    bars = make_bars(end="2026-11-20")
    during = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)      # US market still trading
    after = datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc)
    assert completed_closes(bars, ASSET, during, CFG).index[-1].date().isoformat() == "2026-11-19"
    assert completed_closes(bars, ASSET, after, CFG).index[-1].date().isoformat() == "2026-11-20"
    assert completed_closes(bars, ASSET, SUNDAY_PM, CFG).index[-1].date().isoformat() == "2026-11-20"


def test_completed_closes_ignores_gaps_and_unreadable_frames():
    bars = make_bars()
    bars.iloc[10, bars.columns.get_loc("Close")] = np.nan
    assert completed_closes(bars, ASSET, SUNDAY_PM, CFG).notna().all()
    assert len(completed_closes(bars, ASSET, SUNDAY_PM, CFG)) == len(bars) - 1
    assert completed_closes(pd.DataFrame({"Open": [1.0]}), ASSET, SUNDAY_PM, CFG) is None
    assert completed_closes(None, ASSET, SUNDAY_PM, CFG) is None


def test_price_direction_matches_the_flow_check():
    close = make_bars(drift=0.004)["Close"]
    sigma = typical_move(close, CFG)
    assert price_direction(close, 5, sigma, CFG) == "up"
    assert price_direction(make_bars(drift=-0.004)["Close"], 20, sigma, CFG) == "down"
    block = compute_flow_windows(make_bars(drift=0.004), ASSET, SUNDAY_PM, CFG)
    assert block["week"]["price"] == price_direction(close, 5, sigma, CFG)
    assert price_direction(close.iloc[:4], 5, sigma, CFG) == "not_available"


def test_typical_move_is_zero_when_history_is_too_short_or_constant():
    assert typical_move(make_bars(n=15)["Close"], CFG) == 0.0
    constant = pd.Series([100.0] * 60, index=pd.bdate_range(end="2026-11-20", periods=60))
    assert typical_move(constant, CFG) == 0.0
    assert price_direction(constant, 5, 0.0, CFG) == "flat"

