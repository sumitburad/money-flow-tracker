"""Risk-on / risk-off banner: a plain checklist of market groups, not a score.

Each check looks at a group of markets over the last week and the last month and votes
risk_on, risk_off or neutral:

  trend checks    - did most of the group go up (or down)? A strict majority is needed.
  relative checks - did the confident side (e.g. junk bonds) beat the cautious side
                    (e.g. government bonds) by more than a minimum gap?

The votes are counted, and one fixed rule (``feed_contract.regime_label``) turns the
counts into a word: risk_on, risk_off, mixed or not_enough_data. The month gives the
headline, the week gives the short-term reading, and the two are compared to say whether
the tone is improving, weakening or steady.

Only words and counts of checks leave this module. No price, return or gap number is
published (the free price source may not be redistributed), no score is produced, and no
model takes part: the label follows only the rules in ``config/regime.yaml``.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import yaml

from backend.feed_contract import (REGIME_VOTES, REGIME_WINDOWS, regime_label,
                                   regime_shift)
from backend.flow_windows import price_direction, typical_move

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "regime.yaml"

MIN_SESSIONS = 25     # same history rule as the money-flow check

NOTICE_TEXT = ("A plain checklist of market groups, for research. It describes how markets "
               "behaved over the last week and month. It does not predict what comes next "
               "and it is not investment advice. No model chooses this label.")


def load_config(path=None):
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def method_text(cfg):
    rule = cfg["rule"]
    share = int(round(rule["agree_share"] * 100))
    return (str(len(cfg["checks"])) + " simple checks look at groups of markets over the last week "
            "and the last month. Each check votes risk-on (investors look comfortable owning "
            "riskier things), risk-off (investors look defensive) or neutral. The banner says "
            "risk-on or risk-off only when at least " + str(share) + "% of the checks that have data "
            "lean the same way and no more than " + str(rule["max_opposing"]) +
            " leans the other way; otherwise it says mixed.")


def window_return(close, sessions):
    """Change over the last ``sessions`` sessions as a fraction, or None when it cannot be known."""
    if len(close) < sessions + 1:
        return None
    base = float(close.iloc[-1 - sessions])
    if not base > 0:
        return None
    value = float(close.iloc[-1]) / base - 1.0
    return value if math.isfinite(value) else None


def usable_close(close, now, flow_cfg):
    """The close series if it is long enough and recent enough to be trusted, else None."""
    if close is None or len(close) < MIN_SESSIONS:
        return None
    as_of = close.index[-1].date()
    age = max(0, int(np.busday_count(as_of, now.date())))
    if age > flow_cfg["max_age_weekdays"]:
        return None
    return close


# ------------------------------------------------------------------ the checks

def _trend_vote(check, usable, sessions, flow_cfg):
    up = down = flat = 0
    for member in check["members"]:
        close = usable.get(member)
        if close is None:
            continue
        direction = price_direction(close, sessions, typical_move(close, flow_cfg), flow_cfg)
        if direction == "up":
            up += 1
        elif direction == "down":
            down += 1
        elif direction == "flat":
            flat += 1
    assessed = up + down + flat
    if assessed < check.get("min_members", 1):
        return "not_available", "Not enough data"
    leaning_on, leaning_off = (up, down) if check["risk_on_when"] == "up" else (down, up)
    if leaning_on * 2 > assessed:
        vote = "risk_on"
    elif leaning_off * 2 > assessed:
        vote = "risk_off"
    else:
        vote = "neutral"
    reading = str(up) + " of " + str(assessed) + " " + check["noun"] + " up, " + str(down) + " down"
    if flat:
        reading += ", " + str(flat) + " flat"
    return vote, reading


def _basket_change(members, usable, sessions):
    changes = []
    for member in members:
        close = usable.get(member)
        change = window_return(close, sessions) if close is not None else None
        if change is not None:
            changes.append(change)
    return (sum(changes) / len(changes)) if changes else None, len(changes)


def _mid(name):
    """A name inside a sentence: 'Government bonds' -> 'government bonds', but 'US dollar' stays."""
    return name[0].lower() + name[1:] if len(name) > 1 and name[1].islower() else name


def _relative_vote(check, usable, sessions, min_gap_pct):
    side_a, count_a = _basket_change(check["a"]["members"], usable, sessions)
    side_b, count_b = _basket_change(check["b"]["members"], usable, sessions)
    need = check.get("min_members_each_side", 1)
    if side_a is None or side_b is None or count_a < need or count_b < need:
        return "not_available", "Not enough data"
    gap_points = (side_a - side_b) * 100.0
    name_a, name_b = check["a"]["name"], check["b"]["name"]
    if abs(gap_points) < min_gap_pct:
        return "neutral", name_a + " and " + _mid(name_b) + " did about the same"
    if gap_points > 0:
        return "risk_on", name_a + " did better than " + _mid(name_b)
    return "risk_off", name_b + " did better than " + _mid(name_a)


def evaluate_check(check, usable, cfg, flow_cfg):
    windows = {}
    for name in REGIME_WINDOWS:
        spec = cfg["windows"][name]
        if check["kind"] == "trend":
            vote, reading = _trend_vote(check, usable, spec["sessions"], flow_cfg)
        else:
            vote, reading = _relative_vote(check, usable, spec["sessions"], spec["min_gap_pct"])
        windows[name] = {"vote": vote, "reading": reading}
    return {"id": check["id"], "name": check["name"], "kind": check["kind"],
            "question": check["question"], "windows": windows}


def _members_of(check):
    if check["kind"] == "trend":
        return list(check["members"])
    return list(check["a"]["members"]) + list(check["b"]["members"])


def build_regime(closes, cfg, flow_cfg, now):
    """Run every check and roll the votes up into the banner block of the feed."""
    usable = {}
    for ident, close in (closes or {}).items():
        trusted = usable_close(close, now, flow_cfg)
        if trusted is not None:
            usable[ident] = trusted
    checks = [evaluate_check(check, usable, cfg, flow_cfg) for check in cfg["checks"]]
    windows = {}
    for name in REGIME_WINDOWS:
        tally = {vote: 0 for vote in sorted(REGIME_VOTES)}
        for check in checks:
            tally[check["windows"][name]["vote"]] += 1
        windows[name] = {"title": cfg["windows"][name]["label"],
                         "label": regime_label(tally, cfg["rule"]), "tally": tally}
    label, short_term = windows["month"]["label"], windows["week"]["label"]
    dates = [usable[m].index[-1].date() for check in cfg["checks"]
             for m in _members_of(check) if m in usable]
    return {
        "as_of": max(dates).isoformat() if dates else None,
        "label": label,
        "short_term_label": short_term,
        "shift": regime_shift(label, short_term),
        "windows": windows,
        "checks": checks,
        "rule": {key: cfg["rule"][key]
                 for key in ("min_assessed_checks", "agree_share", "max_opposing")},
        "method": method_text(cfg),
        "notice": NOTICE_TEXT,
    }


def digest_regime(block):
    """A few plain words about the banner, for the executive summary's input."""
    if not block:
        return None
    return {"month": block["label"], "week": block["short_term_label"], "shift": block["shift"],
            "agreeing": {name: {"risk_on": block["windows"][name]["tally"]["risk_on"],
                                "risk_off": block["windows"][name]["tally"]["risk_off"]}
                         for name in REGIME_WINDOWS}}


REGIME_WORDS = {"risk_on": "risk-on", "risk_off": "risk-off", "mixed": "mixed",
                "not_enough_data": "not enough data"}


def regime_sentence(block):
    """One plain sentence about the banner, for the briefs and posts (descriptive, no advice)."""
    if not block:
        return ""
    month, week = block["label"], block["short_term_label"]
    if month == "not_enough_data" and week == "not_enough_data":
        return "Risk tone: not enough market data to read it today."
    sentence = ("Risk tone, from a checklist of market groups: " + REGIME_WORDS[month] +
                " over the last month and " + REGIME_WORDS[week] + " over the last week")
    if block["shift"] in ("improving", "weakening"):
        sentence += " (the short-term picture is " + block["shift"] + ")"
    return sentence + "."


def health_of(block):
    """What the data-quality box needs: did the banner have enough data to speak?"""
    if not block:
        return {"status": "not_available"}
    return {"status": "not_enough_data" if "not_enough_data" in (
                block["label"], block["short_term_label"]) else "ok",
            "label": block["label"], "short_term_label": block["short_term_label"],
            "checks_with_data": {name: sum(block["windows"][name]["tally"][v]
                                           for v in ("risk_on", "risk_off", "neutral"))
                                 for name in REGIME_WINDOWS},
            "checks_total": len(block["checks"])}

