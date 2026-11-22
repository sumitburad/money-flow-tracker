import json
import pytest
import requests
from backend.news_classifier import (check_tag, classify_headlines, fallback_tag)

UNIVERSE = [{"name": "S&P 500"}]


def news(i=0):
    return {"headline_id": "abc" if i == 0 else "h%d" % i,
            "title": "Federal Reserve announces new banking policy",
            "publisher": "Federal Reserve", "url": "https://www.federalreserve.gov/"}


def tag_for(headline, **override):
    tag = {"headline_id": headline["headline_id"], "event_type": "central_bank",
           "region": ["US"], "affected": ["S&P 500"], "direction": "supportive",
           "horizon": "days", "novelty": "new", "confidence": "low",
           "one_line_reason": "Policy may affect United States equity exposure"}
    tag.update(override)
    return tag


class Reply:
    def __init__(self, tags=None, text=None, status=200, headers=None):
        body = text if text is not None else json.dumps({"tags": tags})
        self._outer = {"choices": [{"message": {"content": body}}]}
        self.content = b"{}"
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code)

    def json(self):
        return self._outer


class Fake:
    """Stands in for the internet. ``answer(url, payload)`` returns a Reply."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def post(self, url, headers, json, timeout):
        assert headers["Authorization"].startswith("Bearer ")
        assert json["messages"][0]["role"] == "system"
        sent = __import__("json").loads(json["messages"][1]["content"])
        self.calls.append((url, sent))
        return self.answer(url, sent)


def echo_valid(url, sent):
    return Reply([tag_for(h) for h in sent["headlines"]])


def test_schema_rejects_fabricated_names_and_numbers():
    tag = tag_for(news(), direction="unclear",
                  one_line_reason="Federal Reserve banking policy headline is unconfirmed")
    assert check_tag(tag, news(), ["S&P 500"]) == tag
    tag["affected"] = ["Invented Company"]
    with pytest.raises(ValueError, match="unknown"):
        check_tag(tag, news(), ["S&P 500"])
    tag["affected"] = []
    tag["one_line_reason"] = "Secret rate hiked 6.25 percent"
    with pytest.raises(ValueError, match="numerical"):
        check_tag(tag, news(), ["S&P 500"])


def test_without_api_key_rules_are_not_claimed_ai():
    tagged, h = classify_headlines([news()], UNIVERSE, env={})
    assert tagged[0]["classification"]["classifier"] == "deterministic_rules_NOT_AI"
    assert h["model_classified"] == 0 and h["no_ai_is_not_model_inference"]
    assert h["model_calls"] == 0


def test_valid_model_is_accepted_but_direction_remains_unconfirmed():
    http = Fake(echo_valid)
    tagged, h = classify_headlines([news()], UNIVERSE,
                                   env={"OPENROUTER_API_KEY": "sample-secret"}, http=http)
    assert tagged[0]["classification"]["direction"] == "unclear"
    assert tagged[0]["classification"]["classifier"] == "validated_model_json"
    assert tagged[0]["classification"]["model_provider"] == "openrouter"
    assert h["model_classified"] == 1 and h["model_calls"] == 1
    assert "sample-secret" not in str(tagged)


def test_headlines_are_tagged_in_batches_not_one_request_each():
    heads = [news(i) for i in range(30)]
    http = Fake(echo_valid)
    tagged, h = classify_headlines(heads, UNIVERSE, env={"OPENROUTER_API_KEY": "k" * 12}, http=http)
    assert len(http.calls) == 3                      # never more than three requests a run
    assert [len(sent["headlines"]) for _, sent in http.calls] == [5, 5, 5]
    assert h["model_calls"] == 3 and h["model_classified"] == 15 and h["rule_fallback"] == 15
    assert len(tagged) == 30                         # every headline is still published
    assert tagged[14]["classification"]["classifier"] == "validated_model_json"
    assert tagged[15]["classification"]["classifier"] == "deterministic_rules_NOT_AI"
    # the list of allowed names is sent once per request, not once per headline
    assert all(sent["allowed_affected_names"] == ["S&P 500"] for _, sent in http.calls)


def test_each_answer_is_checked_on_its_own():
    heads = [news(i) for i in range(3)]

    def answer(url, sent):
        a, b, c = sent["headlines"]
        return Reply([tag_for(a),
                      tag_for(b, one_line_reason="Rates rose 5 percent"),   # a number: rejected
                      tag_for(c, headline_id="someone-else")])              # wrong identity: rejected
    tagged, h = classify_headlines(heads, UNIVERSE, env={"OPENROUTER_API_KEY": "k" * 12},
                                   http=Fake(answer))
    kinds = [t["classification"]["classifier"] for t in tagged]
    assert kinds == ["validated_model_json", "deterministic_rules_NOT_AI", "deterministic_rules_NOT_AI"]
    assert h["model_classified"] == 1 and h["rule_fallback"] == 2
    assert h["rejected_model_responses"] == 2


def test_unusable_answers_fall_back_to_rules_and_never_raise():
    heads = [news(i) for i in range(2)]
    for reply in (Reply(text="not json at all"), Reply(status=500), Reply(tags=[])):
        tagged, h = classify_headlines(heads, UNIVERSE, env={"OPENROUTER_API_KEY": "k" * 12},
                                       http=Fake(lambda u, s, r=reply: r))
        assert [t["classification"]["classifier"] for t in tagged] == ["deterministic_rules_NOT_AI"] * 2
        assert h["model_classified"] == 0 and h["rejected_model_responses"] >= 1


def test_answer_with_text_around_the_json_or_a_bare_list_is_accepted():
    head = news()
    wrapped = Reply(text="Here you go:\n" + json.dumps({"tags": [tag_for(head)]}) + "\nDone.")
    bare = Reply(text=json.dumps([tag_for(head)]))
    single = Reply(text=json.dumps(tag_for(head)))      # one object instead of a list
    for reply in (wrapped, bare, single):
        tagged, h = classify_headlines([head], UNIVERSE, env={"OPENROUTER_API_KEY": "k" * 12},
                                       http=Fake(lambda u, s, r=reply: r))
        assert h["model_classified"] == 1, reply._outer


def test_busy_free_plan_is_asked_once_more_after_the_wait_and_no_more():
    waits = []
    replies = [Reply(status=429, headers={"Retry-After": "2"}), Reply(tags=None)]
    head = news()

    def answer(url, sent):
        r = replies.pop(0)
        return Reply([tag_for(head)]) if r.status_code != 429 else r
    http = Fake(answer)
    tagged, h = classify_headlines([head], UNIVERSE, env={"OPENROUTER_API_KEY": "k" * 12},
                                   http=http, sleep=waits.append)
    assert len(http.calls) == 2 and waits == [2.0] and h["model_classified"] == 1
    # still busy on the second try: give up quietly, no third request
    http = Fake(lambda u, s: Reply(status=429, headers={"Retry-After": "999"}))
    waits.clear()
    tagged, h = classify_headlines([head], UNIVERSE, env={"OPENROUTER_API_KEY": "k" * 12},
                                   http=http, sleep=waits.append)
    assert len(http.calls) == 2 and waits == [30.0]      # the wait is capped at 30 seconds
    assert h["model_classified"] == 0 and h["rule_fallback"] == 1


def test_second_provider_only_gets_what_the_first_rejected():
    heads = [news(i) for i in range(3)]

    def answer(url, sent):
        if "groq" in url:
            a, b, c = sent["headlines"]
            return Reply([tag_for(a), tag_for(b, event_type="made_up"), tag_for(c)])
        return echo_valid(url, sent)
    http = Fake(answer)
    tagged, h = classify_headlines(
        heads, UNIVERSE, env={"GROQ_API_KEY": "g" * 12, "OPENROUTER_API_KEY": "o" * 12}, http=http)
    assert [("groq" in u, len(s["headlines"])) for u, s in http.calls] == [(True, 3), (False, 1)]
    assert [t["classification"]["model_provider"] for t in tagged] == ["groq", "openrouter", "groq"]
    assert h["model_classified"] == 3 and h["providers_used"] == ["groq", "openrouter"]


def test_model_calls_are_spaced_out_for_the_free_token_limit():
    heads = [news(i) for i in range(12)]            # 12 headlines = three requests of five, five, two
    http = Fake(lambda u, s: Reply(text="not json"))
    waits = []
    classify_headlines(heads, UNIVERSE, http=http, env={"GROQ_API_KEY": "k" * 12},
                       pace_seconds=8, sleep=waits.append)
    assert waits == [8, 8]                          # nothing before the first call
    waits.clear()
    classify_headlines(heads, UNIVERSE, http=http, env={"GROQ_API_KEY": "k" * 12}, sleep=waits.append)
    assert waits == []                              # a stand-in connection is never slowed down


def test_rule_tag_marks_itself_as_not_ai():
    tag = fallback_tag(news(), ["S&P 500"])
    assert tag["classifier"] == "deterministic_rules_NOT_AI" and tag["human_review_required"]
