import json
import pytest
import requests
from backend import gemini
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


# ------------------------------------------- empty replies from "thinking" models

class Recorder:
    """Like Fake, but keeps everything that was sent, so a test can read the request fields."""

    def __init__(self, *steps):
        self.steps, self.sent = list(steps), []

    def post(self, url, headers, json, timeout):
        self.sent.append({"url": url, "headers": headers, "payload": json, "timeout": timeout})
        step = self.steps.pop(0)
        return step(json) if callable(step) else step


def said(content, *, finish="stop", model="vendor/thinking-model:free"):
    """A reply that names the model that really answered and why it stopped."""
    reply = Reply(text="placeholder")
    reply._outer = {"model": model, "choices": [{"finish_reason": finish,
                                                 "message": {"content": content, "reasoning": "thoughts"}}]}
    return reply


def used_up_its_room():
    """No text and finish "length": the thinking used the whole limit."""
    return said(None, finish="length")


def valid_answer(model="vendor/other-model:free"):
    def build(payload):
        sent = __import__("json").loads(payload["messages"][1]["content"])
        return said(json.dumps({"tags": [tag_for(h) for h in sent["headlines"]]}), model=model)
    return build


OPENROUTER_ENV = {"OPENROUTER_API_KEY": "k" * 12}
GROQ_ENV = {"GROQ_API_KEY": "g" * 12}


def test_openrouter_tagging_gets_room_to_think_and_time_to_answer_and_groq_keeps_its_limit():
    rec = Recorder(valid_answer())
    classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert rec.sent[0]["payload"]["max_tokens"] == 3500 and rec.sent[0]["timeout"] == (10, 75)
    assert "reasoning" not in rec.sent[0]["payload"]        # the first try does not depend on this
    rec = Recorder(valid_answer())
    classify_headlines([news()], UNIVERSE, env=GROQ_ENV, http=rec)
    assert rec.sent[0]["payload"]["max_tokens"] == 1800
    assert rec.sent[0]["payload"]["reasoning_effort"] == "low"


def test_an_empty_reply_is_tried_once_more_asking_the_model_to_think_less():
    rec = Recorder(used_up_its_room(), valid_answer())
    tagged, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert tagged[0]["classification"]["classifier"] == "validated_model_json"
    assert len(rec.sent) == 2 and "reasoning" not in rec.sent[0]["payload"]
    assert rec.sent[1]["payload"]["reasoning"] == {"effort": "low"}
    assert h["model_calls"] == 2 and h["empty_reply_retries"] == 1
    assert h["rejected_model_responses"] == 0 and h["failure_reasons"] == []
    assert h["models_seen"] == ["vendor/other-model:free"]


def test_a_reply_cut_off_inside_the_json_is_also_tried_once_more():
    cut = said('{"tags": [{"headline_id": "ab', finish="length")
    rec = Recorder(cut, valid_answer())
    _, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert h["model_classified"] == 1 and len(rec.sent) == 2 and h["empty_reply_retries"] == 1


def test_only_one_think_less_retry_is_allowed_in_a_whole_run():
    heads = [news(i) for i in range(10)]                    # two batches of five
    rec = Recorder(used_up_its_room(), used_up_its_room(), used_up_its_room())
    tagged, h = classify_headlines(heads, UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert len(rec.sent) == 3 and h["model_calls"] == 3     # batch one twice, batch two once
    assert h["empty_reply_retries"] == 1 and h["rejected_model_responses"] == 2
    assert h["model_classified"] == 0 and h["rule_fallback"] == 10
    [reason] = h["failure_reasons"]
    assert reason.startswith("openrouter: empty reply from vendor/thinking-model:free")
    assert "finish: length" in reason and reason.endswith("(x2)")


def test_groq_is_not_retried_after_an_empty_reply():
    rec = Recorder(used_up_its_room())
    _, h = classify_headlines([news()], UNIVERSE, env=GROQ_ENV, http=rec)
    assert len(rec.sent) == 1 and h["empty_reply_retries"] == 0
    assert h["failure_reasons"][0].startswith("groq: empty reply")


def test_a_reply_that_is_simply_not_json_is_not_retried_and_says_so():
    rec = Recorder(said("Sorry, I cannot do that."), valid_answer())
    _, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert len(rec.sent) == 1 and h["empty_reply_retries"] == 0 and h["model_classified"] == 0
    assert h["failure_reasons"] == ["openrouter: reply from vendor/thinking-model:free is not valid JSON"]


def test_a_reply_with_json_but_no_tag_list_says_so():
    rec = Recorder(said("42"))                          # valid JSON, but a number is not a list of tags
    _, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert h["failure_reasons"] == ["openrouter: reply from vendor/thinking-model:free has no tag list"]


def test_http_failures_are_listed_in_plain_words_with_how_often_they_happened():
    heads = [news(i) for i in range(10)]
    rec = Recorder(Reply(status=402), Reply(status=402))
    _, h = classify_headlines(heads, UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert h["failure_reasons"] == ["openrouter: HTTP 402 (no credit left) (x2)"]
    assert h["rejected_model_responses"] == 2 and h["model_classified"] == 0


def test_each_refused_tag_is_counted_under_its_own_reason():
    heads = [news(i) for i in range(4)]

    def answer(payload):
        a, b, c, _d = __import__("json").loads(payload["messages"][1]["content"])["headlines"]
        return said(json.dumps({"tags": [tag_for(a),
                                         tag_for(b, one_line_reason="Rates rose 5 percent"),
                                         tag_for(c, headline_id="someone-else")]}))
    tagged, h = classify_headlines(heads, UNIVERSE, env=OPENROUTER_ENV, http=Recorder(answer))
    assert h["model_classified"] == 1 and h["rejected_model_responses"] == 3
    # a tag with the wrong id is, in effect, a headline the model left out: the third and the fourth
    assert sorted(h["failure_reasons"]) == [
        "openrouter: a tag failed the checks (free-form rationale must have no numerical assertions)",
        "openrouter: the model left a headline out (x2)"]


def test_no_more_than_four_reasons_are_kept_and_a_key_the_provider_echoes_is_never_published(monkeypatch):
    class ErrorReply(Reply):
        def __init__(self, message):
            super().__init__(status=400)
            self._outer = {"error": {"message": message}}

        def raise_for_status(self):
            raise requests.HTTPError("400 Client Error", response=self)

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-very-secret-value")
    heads = [news(i) for i in range(15)]
    rec = Recorder(*[ErrorReply("different problem %d with sk-or-very-secret-value" % n) for n in range(3)])
    _, h = classify_headlines(heads, UNIVERSE, env={"OPENROUTER_API_KEY": "sk-or-very-secret-value"}, http=rec)
    assert len(h["failure_reasons"]) == 3 and all("HTTP 400" in r for r in h["failure_reasons"])
    assert "sk-or-very-secret-value" not in json.dumps(h) and "***" in h["failure_reasons"][0]


def test_without_a_key_there_are_no_reasons_and_no_retries():
    _, h = classify_headlines([news()], UNIVERSE, env={})
    assert h["failure_reasons"] == [] and h["empty_reply_retries"] == 0 and h["models_seen"] == []


# ------------------------------------------------------------------- free models that answer directly

GEMMA, LLAMA = "google/gemma-4-31b-it:free", "meta-llama/llama-3.3-70b-instruct:free"
THINKER = "nvidia/nemotron-3.5-lightning:free"


class PoolRecorder(Recorder):
    """Recorder that can also answer OpenRouter's model-list request."""

    def __init__(self, listing, *steps):
        super().__init__(*steps)
        self.listing, self.list_calls = listing, []

    def get(self, url, headers=None, timeout=None, **kw):
        self.list_calls.append(url)
        if isinstance(self.listing, Exception):
            raise self.listing
        return self.listing


def test_tagging_names_free_models_and_a_retry_starts_with_the_next_one(model_list):
    rec = PoolRecorder(model_list(GEMMA, LLAMA, thinkers=[THINKER]), used_up_its_room(), valid_answer(model=LLAMA))
    tagged, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    first, second = rec.sent[0]["payload"], rec.sent[1]["payload"]
    assert first["model"] == GEMMA and first["models"] == [LLAMA] and "reasoning" not in first
    assert second["model"] == LLAMA and second["models"] == [GEMMA] and second["reasoning"] == {"effort": "low"}
    assert THINKER not in json.dumps([first, second])
    assert tagged[0]["classification"]["classifier"] == "validated_model_json"
    assert h["free_pool"] == [GEMMA, LLAMA] and "pool_note" not in h and h["empty_reply_retries"] == 1


def test_the_model_list_is_read_once_for_all_batches(model_list):
    heads = [news(i) for i in range(10)]                    # two batches of five
    rec = PoolRecorder(model_list(GEMMA, LLAMA), valid_answer(model=GEMMA), valid_answer(model=GEMMA))
    _, h = classify_headlines(heads, UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert len(rec.sent) == 2 and len(rec.list_calls) == 1 and h["model_classified"] == 10
    assert [s["payload"]["model"] for s in rec.sent] == [GEMMA, GEMMA]


def test_when_the_model_list_cannot_be_read_the_free_router_is_used_and_the_reason_is_kept():
    rec = PoolRecorder(requests.ConnectionError("down"), valid_answer())
    _, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    sent = rec.sent[0]["payload"]
    assert sent["model"] == "openrouter/free" and "models" not in sent
    assert h["free_pool"] == [] and h["pool_note"].startswith("No free model could be chosen")
    assert h["model_classified"] == 1


def test_a_model_named_in_the_environment_is_never_replaced_for_tagging(model_list):
    env = {**OPENROUTER_ENV, "OPENROUTER_CLASSIFIER_MODEL": "vendor/my-pick-70b:free"}
    rec = PoolRecorder(model_list(GEMMA), valid_answer())
    classify_headlines([news()], UNIVERSE, env=env, http=rec)
    sent = rec.sent[0]["payload"]
    assert sent["model"] == "vendor/my-pick-70b:free" and "models" not in sent and rec.list_calls == []


def test_groq_tagging_is_not_changed_and_never_reads_the_model_list(model_list):
    rec = PoolRecorder(model_list(GEMMA), valid_answer())
    _, h = classify_headlines([news()], UNIVERSE, env=GROQ_ENV, http=rec)
    assert rec.sent[0]["payload"]["model"] == "openai/gpt-oss-20b" and rec.list_calls == []
    assert "free_pool" not in h


# ------------------------------------------------------------------- thinking models (23 Nov 2026)

DEEP_THINKER = "vendor/deep-think-120b:free"


def test_a_thinking_model_fills_the_place_the_direct_ones_leave_for_tagging(model_list):
    rec = PoolRecorder(model_list(GEMMA, thinkers=[DEEP_THINKER]), valid_answer(model=DEEP_THINKER))
    tagged, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    sent = rec.sent[0]["payload"]
    assert sent["model"] == GEMMA and sent["models"] == [DEEP_THINKER]
    assert sent["reasoning"] == {"effort": "low"} and sent["max_tokens"] == 6000
    assert tagged[0]["classification"]["classifier"] == "validated_model_json"
    assert h["free_pool"] == [GEMMA, DEEP_THINKER] and h["pool_thinking"] == [DEEP_THINKER]
    assert h["model_results"] == [{"model": "vendor/deep-think-120b", "accepted": 1, "rejected": 0, "empty": 0}]


def test_a_tag_that_fails_the_checks_is_counted_against_the_model_that_wrote_it(model_list):
    def bad(payload):
        sent = json.loads(payload["messages"][1]["content"])
        return said(json.dumps({"tags": [tag_for(h, event_type="made_up") for h in sent["headlines"]]}),
                    model=GEMMA)
    rec = PoolRecorder(model_list(GEMMA, LLAMA), bad)
    _, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert h["model_classified"] == 0 and h["rule_fallback"] == 1
    assert h["model_results"] == [{"model": "google/gemma-4-31b-it", "accepted": 0, "rejected": 1, "empty": 0}]


def test_an_empty_reply_is_counted_against_the_model_that_sent_it(model_list):
    rec = PoolRecorder(model_list(GEMMA, LLAMA), used_up_its_room(), valid_answer(model=LLAMA))
    _, h = classify_headlines([news()], UNIVERSE, env=OPENROUTER_ENV, http=rec)
    assert h["model_results"] == [
        {"model": "vendor/thinking-model", "accepted": 0, "rejected": 0, "empty": 1},
        {"model": "meta-llama/llama-3.3-70b-instruct", "accepted": 1, "rejected": 0, "empty": 0}]


# ------------------------------------------------------------------- Google Gemini (23 Nov 2026)

# Built from pieces, so a scanner reading this file never mistakes the test value for a real key.
GEMINI_KEY = "AIza" + "Sy" + "T" * 33
GEMINI_ENV = {"GEMINI_API_KEY": GEMINI_KEY}
GEMINI_HOST = "generativelanguage.googleapis.com"


def host(call):
    return call["url"].split("/")[2]


class Refused(Reply):
    """An HTTP error that carries its response, as the real library's errors do."""

    def __init__(self, status, body=None):
        super().__init__(status=status)
        self._outer = body if body is not None else {"error": {"message": "refused"}}

    def raise_for_status(self):
        raise requests.HTTPError("%d Client Error" % self.status_code, response=self)


def test_gemini_tags_headlines_at_its_own_address_with_adjusted_request_fields():
    rec = Recorder(valid_answer(model="gemini-flash-latest"))
    tagged, h = classify_headlines([news()], UNIVERSE, env=GEMINI_ENV, http=rec)
    sent = rec.sent[0]
    assert sent["url"] == gemini.URL and GEMINI_KEY not in sent["url"]
    assert sent["headers"]["Authorization"] == "Bearer " + GEMINI_KEY
    body = sent["payload"]
    assert body["model"] == "gemini-flash-latest" and body["max_tokens"] == 4000
    assert body["reasoning_effort"] == "low" and sent["timeout"] == (10, 75)
    assert not {"response_format", "temperature", "reasoning", "models"} & set(body)
    assert GEMINI_KEY not in json.dumps(body)
    tag = tagged[0]["classification"]
    assert tag["classifier"] == "validated_model_json" and tag["model_provider"] == "gemini"
    assert tag["model_name"] == "gemini-flash-latest"
    assert h["providers_used"] == ["gemini"] and h["model_classified"] == 1 and "free_pool" not in h
    assert h["model_results"] == [{"model": "gemini-flash-latest", "accepted": 1, "rejected": 0, "empty": 0}]
    assert GEMINI_KEY not in json.dumps([tagged, h])


def test_gemini_is_asked_after_groq_and_only_for_what_groq_did_not_tag():
    heads = [news(i) for i in range(3)]

    def answer(url, sent):
        if "groq" in url:
            a, b, c = sent["headlines"]
            return Reply([tag_for(a), tag_for(b, event_type="made_up"), tag_for(c)])
        return echo_valid(url, sent)
    http = Fake(answer)
    tagged, h = classify_headlines(heads, UNIVERSE, env={"GROQ_API_KEY": "g" * 12, **GEMINI_ENV,
                                                         "OPENROUTER_API_KEY": "o" * 12}, http=http)
    assert [(GEMINI_HOST in u, "groq" in u, len(s["headlines"])) for u, s in http.calls] == [
        (False, True, 3), (True, False, 1)]                  # OpenRouter is never needed
    assert [t["classification"]["model_provider"] for t in tagged] == ["groq", "gemini", "groq"]
    assert h["providers_used"] == ["groq", "gemini"] and h["model_classified"] == 3


def test_when_every_gemini_model_fails_the_headlines_go_on_to_openrouter(model_list):
    names = gemini.models("")
    rec = PoolRecorder(model_list(GEMMA), *[Reply(status=500)] * len(names), valid_answer(model=GEMMA))
    tagged, h = classify_headlines([news()], UNIVERSE, env={**GEMINI_ENV, **OPENROUTER_ENV}, http=rec)
    assert [host(c) for c in rec.sent] == [GEMINI_HOST] * len(names) + ["openrouter.ai"]
    assert [c["payload"]["model"] for c in rec.sent[:len(names)]] == names
    assert tagged[0]["classification"]["model_provider"] == "openrouter"
    assert any(reason.startswith("gemini: HTTP 500") for reason in h["failure_reasons"])
    assert GEMINI_KEY not in json.dumps([tagged, h])


def test_a_refused_gemini_key_rules_out_every_gemini_model_for_the_rest_of_the_run(model_list):
    heads = [news(i) for i in range(10)]                    # two batches of five
    rec = PoolRecorder(model_list(GEMMA), Refused(403), valid_answer(model=GEMMA), valid_answer(model=GEMMA))
    _, h = classify_headlines(heads, UNIVERSE, env={**GEMINI_ENV, **OPENROUTER_ENV}, http=rec)
    assert [host(c) for c in rec.sent] == [GEMINI_HOST, "openrouter.ai", "openrouter.ai"]
    assert h["model_classified"] == 10 and h["rule_fallback"] == 0
    assert h["failure_reasons"] == ["gemini: HTTP 403 (the key is not allowed to do this): refused"]   # once, not three times


def test_a_gemini_model_that_is_not_found_is_skipped_but_the_next_gemini_model_is_still_asked():
    names = gemini.models("")
    heads = [news(i) for i in range(10)]
    rec = Recorder(Refused(404), valid_answer(model=names[1]), valid_answer(model=names[1]))
    _, h = classify_headlines(heads, UNIVERSE, env=GEMINI_ENV, http=rec)
    assert [c["payload"]["model"] for c in rec.sent] == [names[0], names[1], names[1]]
    assert h["model_classified"] == 10 and h["providers_used"] == ["gemini"]


def test_a_gemini_model_named_in_the_environment_replaces_the_list():
    rec = Recorder(valid_answer(model="gemini-9-pro"))
    classify_headlines([news()], UNIVERSE, env={**GEMINI_ENV, "GEMINI_CLASSIFIER_MODEL": "gemini-9-pro"}, http=rec)
    assert [c["payload"]["model"] for c in rec.sent] == ["gemini-9-pro"]


def test_gemini_is_skipped_when_the_settings_switch_it_off(tmp_path, monkeypatch):
    off = tmp_path / "off.yaml"
    off.write_text("gemini:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(gemini, "CONFIG_PATH", off)
    rec = Recorder()
    _, h = classify_headlines([news()], UNIVERSE, env=GEMINI_ENV, http=rec)
    assert rec.sent == [] and h["model_configured"] is False and h["rule_fallback"] == 1


def test_a_blank_gemini_key_counts_as_no_key():
    rec = Recorder()
    _, h = classify_headlines([news()], UNIVERSE, env={"GEMINI_API_KEY": "   "}, http=rec)
    assert rec.sent == [] and h["model_configured"] is False


def test_a_google_key_inside_an_error_body_is_never_published():
    leaky = [{"error": {"message": "API key not valid: " + GEMINI_KEY, "status": "INVALID_ARGUMENT"}}]
    rec = Recorder(*[Refused(400, leaky) for _ in range(len(gemini.models("")))])
    _, h = classify_headlines([news()], UNIVERSE, env=GEMINI_ENV, http=rec)
    text = json.dumps(h)
    assert GEMINI_KEY not in text and "AIza" not in text
    assert h["failure_reasons"] and h["failure_reasons"][0].startswith("gemini: HTTP 400") and "***" in text
