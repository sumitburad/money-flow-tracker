"""Day / week / month money-flow check: price up on rising volume = inflow.

The rule (set by the project owner):
  price UP   and volume UP   -> inflow          (money appears to be coming in)
  price DOWN and volume UP   -> outflow         (money appears to be leaving)
  price UP   and volume DOWN -> inflow_fading   (rise on thinning participation)
  price DOWN and volume DOWN -> outflow_fading  (fall on thinning participation)
  a flat price or flat volume -> unclear

It is repeated for three windows (day, week, month), then compared across them to
say whether the flow is improving or weakening, and rolled up into a rotation map
by asset class and sector.

Only categories leave this module. No price or volume number is published, because
the free price source (Yahoo) may not be redistributed and the project publishes no
scores. Volume is a participation proxy, never a measured net fund flow.
"""
from __future__ import annotations

import math
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from backend.feed_contract import FLOW_SIGNALS, FLOW_WINDOWS, expected_flow_signal

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "flow_windows.yaml"

# Ordered only so that two categories can be compared with each other (the same
# approach momentum_tag already uses). These numbers never leave this module.
SIGNAL_LEVEL = {"outflow": -2, "outflow_fading": -1, "unclear": 0,
                "inflow_fading": 1, "inflow": 2}
VERDICT_LEVEL = {"outflow_led": -1, "mixed": 0, "inflow_led": 1}

METHOD_TEXT = ("Inflow means the price rose while trading volume also rose; outflow means the "
               "price fell while volume rose. Price falling or rising on thinning volume is "
               "marked as fading. Volume is a participation proxy, not a measured fund flow.")


def load_config(path=None):
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def not_available(reason):
    return {"status": "not_available", "reason": reason}


def session_market(asset, cfg):
    """Which exchange clock decides when this item's daily bar is finished."""
    if asset.get("session_market"):
        return asset["session_market"]
    by_type = cfg.get("asset_type_session_market", {}).get(asset.get("asset_type"))
    if by_type:
        return by_type
    return cfg.get("region_session_market", {}).get(
        asset.get("region"), cfg.get("default_session_market", "US"))


def bar_is_complete(bar_date, asset, now, cfg):
    """True once the session dated bar_date has finished, so its volume is a full day.

    A day still in progress would look like a sudden volume collapse, so the newest
    bar is skipped until the market has closed. 24-hour markets never close, so a bar
    dated today (UTC) is always skipped for them.
    """
    today = now.date()
    if bar_date < today:
        return True
    if bar_date > today:
        return False
    after = cfg["session_complete_after_utc"].get(session_market(asset, cfg))
    if after is None:
        return False
    hours, minutes = after.split(":")
    return now.time() >= time(int(hours), int(minutes))


def _direction(change, band):
    if change is None or not math.isfinite(change):
        return "not_available"
    if abs(change) <= band:
        return "flat"
    return "up" if change > 0 else "down"


def _one_window(close, volume, sessions, sigma, cfg, name):
    price = "not_available"
    if len(close) >= sessions + 1:
        base = float(close.iloc[-1 - sessions])
        if base > 0:
            change = float(close.iloc[-1]) / base - 1.0
            band = cfg["price_flat_band"]["fraction_of_typical_move"] * sigma * math.sqrt(sessions)
            price = _direction(change, band)
    flow = "not_available"
    if volume is not None and len(volume) >= 2 * sessions:
        recent = volume.iloc[-sessions:]
        prior = volume.iloc[-2 * sessions:-sessions]
        usable = not (recent.isna().any() or prior.isna().any()
                      or (recent <= 0).any() or (prior <= 0).any())
        if usable:
            change = float(recent.mean()) / float(prior.mean()) - 1.0
            flow = _direction(change, cfg["volume_flat_band_pct"][name] / 100.0)
    return {"price": price, "volume": flow, "signal": expected_flow_signal(price, flow)}


def levels_trend(levels):
    """Is the picture improving or weakening from the longest window to the shortest?

    levels are ordered long -> short; None entries are skipped.
    """
    seq = [x for x in levels if x is not None]
    if len(seq) < 2:
        return "not_available"
    steps = [b - a for a, b in zip(seq, seq[1:])]
    if all(step == 0 for step in steps):
        return "steady"
    if all(step >= 0 for step in steps):
        return "improving"
    if all(step <= 0 for step in steps):
        return "weakening"
    return "mixed"


def compute_flow_windows(bars, asset, now, cfg):
    """Per-item day / week / month signal from the item's daily bars."""
    if asset.get("asset_type") in cfg.get("excluded_asset_types", []):
        return not_available("Risk gauge, not an investable money-flow candidate")
    try:
        frame = bars.dropna(subset=["Close"]).sort_index()
        close = frame["Close"].astype(float)
        volume = frame["Volume"].astype(float) if "Volume" in frame else None
    except Exception:
        return not_available("Price history could not be read")
    if len(close) and not bar_is_complete(close.index[-1].date(), asset, now, cfg):
        close = close.iloc[:-1]
        volume = volume.iloc[:-1] if volume is not None else None
    if len(close) < 25:
        return not_available("Fewer than 25 completed sessions of history")
    as_of = close.index[-1].date()
    age = max(0, int(np.busday_count(as_of, now.date())))
    if age > cfg["max_age_weekdays"]:
        return not_available("Last completed session " + as_of.isoformat() + " is too old")
    returns = close.pct_change().dropna().tail(cfg["price_flat_band"]["lookback_sessions"])
    sigma = float(returns.std(ddof=1)) if len(returns) >= 20 else 0.0
    if not math.isfinite(sigma):
        sigma = 0.0
    result = {"status": "ok", "as_of": as_of.isoformat()}
    for name in FLOW_WINDOWS:
        result[name] = _one_window(close, volume, cfg["windows"][name]["sessions"],
                                   sigma, cfg, name)
    result["trend"] = levels_trend(
        [SIGNAL_LEVEL.get(result[n]["signal"]) for n in ("month", "week", "day")])
    return result


# ----------------------------------------------------------------- rotation map

def _tally(members, window):
    counts = {name: 0 for name in sorted(FLOW_SIGNALS)}
    inflow, outflow = [], []
    for item in members:
        block = item.get("flow_windows") or {}
        if block.get("status") != "ok":
            counts["not_available"] += 1
            continue
        signal = block[window]["signal"]
        counts[signal] += 1
        if signal == "inflow":
            inflow.append(item["id"])
        elif signal == "outflow":
            outflow.append(item["id"])
    return counts, inflow, outflow


def group_verdict(counts, rotation_cfg):
    assessed = sum(v for k, v in counts.items() if k != "not_available")
    if assessed < rotation_cfg["min_assessed_members"]:
        return "not_enough_data"
    pos, neg = counts["inflow"], counts["outflow"]
    share = rotation_cfg["lead_share"]
    if pos > neg and pos / assessed >= share:
        return "inflow_led"
    if neg > pos and neg / assessed >= share:
        return "outflow_led"
    return "mixed"


def _group_block(members, cfg, verdicts=True):
    windows = {}
    for name in FLOW_WINDOWS:
        counts, inflow, outflow = _tally(members, name)
        windows[name] = {
            "verdict": group_verdict(counts, cfg["rotation"]) if verdicts else "not_applicable",
            "counts": counts, "inflow": inflow, "outflow": outflow}
    trend = levels_trend([VERDICT_LEVEL.get(windows[n]["verdict"])
                          for n in ("month", "week", "day")]) if verdicts else "not_available"
    return windows, trend


def build_rotation(items, cfg):
    """Roll the per-item signals up into asset-class and sector verdicts."""
    by_id = {item["id"]: item for item in items}
    buckets, moves, pooled = [], {n: {"into": [], "out_of": []} for n in FLOW_WINDOWS}, []
    for bucket in cfg["buckets"]:
        members = [by_id[m] for m in bucket["members"] if m in by_id]
        if not members:
            continue
        has_verdict = bucket.get("verdict", True) is not False
        windows, trend = _group_block(members, cfg, has_verdict)
        record = {"id": bucket["id"], "name": bucket["name"],
                  "members": [m["id"] for m in members],
                  "windows": windows, "trend": trend}
        if bucket.get("note"):
            record["note"] = bucket["note"]
        buckets.append(record)
        if has_verdict:
            pooled.extend(members)
            for name in FLOW_WINDOWS:
                verdict = windows[name]["verdict"]
                if verdict == "inflow_led":
                    moves[name]["into"].append(bucket["id"])
                elif verdict == "outflow_led":
                    moves[name]["out_of"].append(bucket["id"])
    windows, trend = _group_block(pooled, cfg, True)
    assessed = [i for i in pooled if (i.get("flow_windows") or {}).get("status") == "ok"
                and any(i["flow_windows"][n]["signal"] != "not_available" for n in FLOW_WINDOWS)]
    no_volume = [i["id"] for i in items
                 if (i.get("flow_windows") or {}).get("status") == "ok"
                 and all(i["flow_windows"][n]["signal"] == "not_available" for n in FLOW_WINDOWS)]
    return {
        "method": METHOD_TEXT,
        "windows": {n: {"label": cfg["windows"][n]["label"], "basis": cfg["windows"][n]["basis"]}
                    for n in FLOW_WINDOWS},
        "overall": {"windows": windows, "trend": trend},
        "buckets": buckets,
        "moves": moves,
        "coverage": {"items_with_signal": len(assessed),
                     "items_in_rotation": len(pooled),
                     "items_without_volume": no_volume},
    }
