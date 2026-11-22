import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

from backend.exec_summary import (PROVIDERS, build_digest, build_executive_summary,
                                  check_summary, rules_summary)
from backend.feed_contract import validate_executive_summary, validate_feed
from backend.flow_windows import build_rotation, compute_flow_windows, load_config

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config()
NOW = datetime(2026, 11, 22, 13, 37, tzinfo=timezone.utc)


def bars(drift, volume_bump=1.3):
    index = pd.bdate_range(end="2026-11-20", periods=120)
    i = np.arange(120)
    frame = pd.DataFrame({"Close": 100 * (1 + drift) ** i * (1 + 0.001 * (-1.0) ** i),
                          "Volume": 1e6 * 1.04 ** i}, index=index)
    frame.iloc[-1, 1] *= volume_bump
    return frame


def make_feed():
    """The real published feed, with flow windows added: sectors inflow, bonds outflow."""
    feed = json.loads((ROOT / "data" / "feed" / "v1" / "latest.json").read_text(encoding="utf-8"))
    for item in feed["items"]:
        if item["group"] in ("global_sector", "india_sector"):
            frame = bars(0.004)
        elif item["group"] == "bond":
            frame = bars(-0.004)
        else:
            frame = bars(0.0)
        item["flow_windows"] = compute_flow_windows(frame, {"asset_type": "equity", "region": "US"}, NOW, CFG)
    feed["rotation"] = build_rotation(feed["items"], CFG)
    return feed


GOOD = {
    "headline": "Flow is inflow-led in equity sectors and outflow-led in bonds over the week.",
    "rotation_view": ("Money appears to be moving into Equity sectors and themes and out of Bonds and "
                      "credit over the week, while the month is less clear."),
    "drivers_view": "Recent Federal Reserve and European Central Bank releases are not confirmed as market drivers.",
    "watch": ["Week and month disagree in some groups."],
    "evidence_refs": ["sectors", "bonds"],
}


class Reply:
    def __init__(self, content=None, status=200):
        self.status_code = status
        self.headers = {"retry-after": "3"} if status == 429 else {}
        self.content = b"{}"
        self._body = {"choices": [{"message": {"content": content}}]}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code, response=self)

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "payload": json})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ai(answer):
    return Reply(json.dumps(answer))


ENV = {"GROQ_API_KEY": "gsk_test_secret_value_1234", "OPENROUTER_API_KEY": "sk-or-test-secret-5678"}


# ------------------------------------------------------------------- digest

def test_digest_is_categories_and_names_only():
    digest = build_digest(make_feed())
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            assert not isinstance(x, float), x       # no price, volume or percentage
    walk(digest)
    assert digest["overall"]["trend"] in ("improving", "weakening", "steady", "mixed", "not_available")
    assert "sectors" in digest["allowed_refs"] and "Equity sectors and themes" in digest["allowed_names"]
    sectors = next(g for g in digest["groups"] if g["ref"] == "sectors")
    assert sectors["week"] == "inflow_led" and sectors["inflow_week"]
    assert {"Federal Reserve", "European Central Bank"} <= set(digest["allowed_names"])


# ---------------------------------------------------------------- rule-based

def test_without_any_key_the_summary_is_rule_based_and_says_so():
    feed = make_feed()
    summary, health = build_executive_summary(feed, env={}, now=NOW)
    assert summary["method"] == "rules_only" and summary["provider"] is None and summary["model"] is None
    assert health["ai_configured"] is False and health["method"] == "rules_only"
    assert "Equity sectors and themes" in summary["rotation_view"]
    assert "Bonds and credit" in summary["rotation_view"]
    validate_executive_summary(summary)
    feed["executive_summary"] = summary
    assert validate_feed(feed)


def test_rule_summary_handles_a_feed_with_no_flow_data():
    old = json.loads((ROOT / "data" / "feed" / "v1" / "latest.json").read_text(encoding="utf-8"))
    summary, _ = build_executive_summary(old, env=ENV, http=FakeHttp(), now=NOW)   # no AI call is possible
    assert summary["method"] == "rules_only" and "not available" in summary["headline"]
    validate_executive_summary(summary)


# ------------------------------------------------------------------------ AI

def test_a_clean_ai_answer_is_accepted_and_labelled_with_provider_and_model():
    feed = make_feed()
    http = FakeHttp(ai(GOOD))
    summary, health = build_executive_summary(feed, http=http, env=ENV, now=NOW)
    assert summary["method"] == "ai_validated" and summary["provider"] == "groq"
    assert summary["model"] == "openai/gpt-oss-120b"
    assert summary["human_review_required"] is True
    assert health["method"] == "ai_validated" and health["rejected_answers"] == 0
    validate_executive_summary(summary)
    sent = http.calls[0]
    assert sent["url"].startswith("https://api.groq.com/")
    assert sent["headers"]["Authorization"] == "Bearer " + ENV["GROQ_API_KEY"]
    user_facts = json.loads(sent["payload"]["messages"][1]["content"])
    assert "allowed_names" in user_facts and "groups" in user_facts


def test_the_model_can_be_changed_without_touching_code():
    http = FakeHttp(ai(GOOD))
    summary, _ = build_executive_summary(make_feed(), http=http,
                                         env={**ENV, "GROQ_SUMMARY_MODEL": "some/other-model"}, now=NOW)
    assert summary["model"] == "some/other-model" and http.calls[0]["payload"]["model"] == "some/other-model"


@pytest.mark.parametrize("field,value,reason", [
    ("headline", "Inflow rose 5% in sectors this week.", "number"),
    ("headline", "Investors should buy sector funds now.", "advice"),
    ("drivers_view", "Prices will rally after the Federal Reserve release.", "advice"),
    ("rotation_view", "Money moved around quietly this week.", "names no tracked"),
    ("rotation_view", "See https://example.com for Bonds and credit.", "link"),
    ("evidence_refs", ["not_a_real_id"], "known ids"),
    ("evidence_refs", [], "known ids"),
    ("watch", ["a", "b", "c", "d"], "short list"),
    ("headline", " ".join(["Bonds"] * 40), "too long"),
])
def test_bad_answers_are_rejected(field, value, reason):
    digest = build_digest(make_feed())
    bad = {**GOOD, field: value}
    with pytest.raises(ValueError, match=reason):
        check_summary(bad, digest)


def test_extra_or_missing_fields_are_rejected():
    digest = build_digest(make_feed())
    with pytest.raises(ValueError, match="missing or extra"):
        check_summary({**GOOD, "buy_list": ["x"]}, digest)
    missing = dict(GOOD)
    del missing["watch"]
    with pytest.raises(ValueError, match="missing or extra"):
        check_summary(missing, digest)


def test_names_that_contain_digits_are_fine_but_other_numbers_are_not():
    digest = build_digest(make_feed())
    ok = {**GOOD, "headline": "S&P 500 and Nifty 50 lag Equity sectors and themes this week."}
    assert check_summary(ok, digest)["headline"].startswith("S&P 500")
    with pytest.raises(ValueError, match="number"):
        check_summary({**GOOD, "headline": "Nifty 50 gained three points, about 2 percent."}, digest)


def test_rejected_first_provider_falls_through_to_the_second():
    http = FakeHttp(ai({**GOOD, "headline": "Inflow rose 5% this week."}), ai(GOOD))
    summary, health = build_executive_summary(make_feed(), http=http, env=ENV, now=NOW)
    assert summary["provider"] == "openrouter" and health["rejected_answers"] == 1
    assert [c["url"].split("/")[2] for c in http.calls] == ["api.groq.com", "openrouter.ai"]


def test_every_failure_ends_in_the_rule_summary_without_raising():
    http = FakeHttp(requests.ConnectionError("down"), Reply("not json at all"))
    summary, health = build_executive_summary(make_feed(), http=http, env=ENV, now=NOW)
    assert summary["method"] == "rules_only" and health["rejected_answers"] == 2
    assert health["ai_configured"] and health["providers_tried"] == ["groq", "openrouter"]
    http = FakeHttp(Reply(status=500), Reply(json.dumps({"headline": "x"})))
    summary, _ = build_executive_summary(make_feed(), http=http, env=ENV, now=NOW)
    assert summary["method"] == "rules_only"


def test_a_busy_provider_gets_one_polite_retry_then_succeeds():
    waits = []
    http = FakeHttp(Reply(status=429), ai(GOOD))
    summary, health = build_executive_summary(make_feed(), http=http, env=ENV, now=NOW, sleep=waits.append)
    assert summary["method"] == "ai_validated" and summary["provider"] == "groq"
    assert len(http.calls) == 2 and waits == [3.0]          # waited the 3 seconds the provider asked for
    assert health["rejected_answers"] == 0


def test_a_provider_that_stays_busy_falls_through_to_the_next_one():
    http = FakeHttp(Reply(status=429), Reply(status=429), ai(GOOD))
    summary, health = build_executive_summary(make_feed(), http=http, env=ENV, now=NOW, sleep=lambda s: None)
    assert summary["provider"] == "openrouter" and health["rejected_answers"] == 1


def test_json_wrapped_in_text_is_still_read_but_still_checked():
    wrapped = Reply("Here is the summary:\n```json\n" + json.dumps(GOOD) + "\n```")
    summary, _ = build_executive_summary(make_feed(), http=FakeHttp(wrapped), env=ENV, now=NOW)
    assert summary["method"] == "ai_validated"


def test_secrets_never_appear_in_the_published_summary_or_health():
    summary, health = build_executive_summary(
        make_feed(), http=FakeHttp(requests.ConnectionError("down"), ai(GOOD)), env=ENV, now=NOW)
    text = json.dumps([summary, health])
    assert ENV["GROQ_API_KEY"] not in text and ENV["OPENROUTER_API_KEY"] not in text


# ------------------------------------------------------------- feed contract

def test_feed_contract_checks_the_summary_block():
    feed = make_feed()
    summary, _ = build_executive_summary(feed, http=FakeHttp(ai(GOOD)), env=ENV, now=NOW)
    feed["executive_summary"] = summary
    assert validate_feed(feed)
    for change, match in (({"method": "made_by_ai"}, "method"),
                          ({"provider": None}, "provider and model"),
                          ({"human_review_required": False}, "human review"),
                          ({"headline": ""}, "headline")):
        bad = copy.deepcopy(feed)
        bad["executive_summary"].update(change)
        with pytest.raises(ValueError, match=match):
            validate_feed(bad)
    bad = copy.deepcopy(feed)
    bad["executive_summary"].update(method="rules_only")        # still names a model
    with pytest.raises(ValueError, match="must not claim a model"):
        validate_feed(bad)


def test_both_providers_use_secret_names_the_run_protects():
    from backend.net import SECRET_ENV_NAMES
    assert all(secret in SECRET_ENV_NAMES for _, _, secret, *_ in PROVIDERS)


def test_rule_headline_reads_naturally_when_all_windows_agree_and_when_they_differ():
    digest = build_digest(make_feed())
    digest["overall"] = {"day": "mixed", "week": "mixed", "month": "mixed", "trend": "steady"}
    assert "mixed in all three windows" in rules_summary(digest)["headline"]
    digest["overall"] = {"day": "outflow_led", "week": "mixed", "month": "inflow_led", "trend": "weakening"}
    text = rules_summary(digest)["headline"]
    assert "inflow-led over the month" in text and "outflow-led on the latest day" in text
    assert "the picture is weakening" in text
