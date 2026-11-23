"""Reading a free AI model's answer, and explaining plainly when there is nothing to read."""
import pytest
import requests

from backend import gemini
from backend.ai_reply import (AI_TIMEOUT, OPENROUTER_ANSWER_TOKENS, AIReplyError, answer_tokens,
                              failure_reason, read_reply, reply_from, think_less_fields,
                              unreadable)

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
GROQ = "https://api.groq.com/openai/v1/chat/completions"


def completion(content, *, finish="stop", model="vendor/thinking-model:free", **message):
    return {"model": model,
            "choices": [{"finish_reason": finish, "message": {"content": content, **message}}]}


class Response:
    def __init__(self, body=None, status=200, size=10, bad_json=False):
        self.status_code, self._body, self.content = status, body, b"x" * size
        self._bad_json = bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%s Error: for url: https://openrouter.ai/api" % self.status_code,
                                     response=self)

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._body


# ------------------------------------------------------------------ reading

def test_the_text_the_real_model_and_the_stop_reason_are_returned():
    reply = read_reply(completion('{"a": 1}'))
    assert (reply.text, reply.model, reply.finish) == ('{"a": 1}', "vendor/thinking-model:free", "stop")


def test_a_reply_without_model_or_stop_reason_is_still_read():
    reply = read_reply({"choices": [{"message": {"content": "hello"}}]})
    assert (reply.text, reply.model, reply.finish) == ("hello", None, None)


def test_an_answer_sent_as_a_list_of_parts_is_joined():
    parts = [{"type": "text", "text": '{"a":'}, {"type": "text", "text": " 1}"}, {"type": "image"}]
    assert read_reply(completion(parts)).text == '{"a": 1}'


def test_a_thinking_model_that_used_all_its_room_gets_a_plain_retryable_reason():
    # the reply seen from the free router: no text, finish "length", the thinking sitting elsewhere
    with pytest.raises(AIReplyError) as caught:
        read_reply(completion(None, finish="length", reasoning="long thoughts ..."))
    message = str(caught.value)
    assert caught.value.empty is True
    assert "vendor/thinking-model:free" in message and "room" in message and "finish: length" in message


@pytest.mark.parametrize("content", [None, "", "   \n", [], [{"type": "text", "text": " "}]])
def test_every_kind_of_empty_content_is_an_empty_reply(content):
    with pytest.raises(AIReplyError) as caught:
        read_reply(completion(content, finish="stop"))
    assert caught.value.empty is True and "empty reply" in str(caught.value)


def test_the_thinking_text_is_never_used_as_the_answer():
    with pytest.raises(AIReplyError):
        read_reply(completion(None, finish="length", reasoning='{"headline": "from the thoughts"}',
                              reasoning_content='{"headline": "also thoughts"}'))


def test_a_refusal_is_reported_and_is_not_retried():
    with pytest.raises(AIReplyError) as caught:
        read_reply(completion(None, refusal="I can't help with that"))
    assert caught.value.empty is False and "declined" in str(caught.value)


def test_a_provider_error_inside_an_ok_reply_is_reported_without_any_secret(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-very-secret-value")
    body = {"error": {"message": "Upstream failed for key sk-or-very-secret-value", "code": 502}}
    with pytest.raises(AIReplyError) as caught:
        read_reply(body)
    assert "Upstream failed" in str(caught.value) and "sk-or-very-secret-value" not in str(caught.value)
    assert caught.value.empty is False


@pytest.mark.parametrize("body", [None, [], "text", {}, {"choices": []}, {"choices": ["x"]}])
def test_an_unreadable_reply_is_an_error_not_a_crash(body):
    with pytest.raises(AIReplyError):
        read_reply(body)


def test_a_model_name_cannot_flood_the_status_file():
    reply = read_reply(completion("ok", model="m" * 500))
    assert len(reply.model) <= 60


# ---------------------------------------------------------- whole responses

def test_a_good_response_is_read_after_the_status_check():
    assert reply_from(Response(completion("fine"))).text == "fine"


def test_an_error_status_is_raised_before_anything_is_read():
    with pytest.raises(requests.HTTPError):
        reply_from(Response(completion("fine"), status=500))


def test_an_oversized_or_non_json_response_is_refused_in_plain_words():
    with pytest.raises(AIReplyError, match="oversized"):
        reply_from(Response(completion("fine"), size=300_000))
    with pytest.raises(AIReplyError, match="not JSON"):
        reply_from(Response(bad_json=True))


def test_a_cut_off_answer_is_told_apart_from_one_that_is_just_not_json():
    reply = read_reply(completion('{"headline": "Flow is', finish="length"))
    cut = unreadable(reply)
    assert cut.empty is True and "cut off" in str(cut) and "vendor/thinking-model:free" in str(cut)
    plain = unreadable(read_reply(completion("Sorry, no.", finish="stop")))
    assert plain.empty is False and "not valid JSON" in str(plain)


# ------------------------------------------------------- budget and retry

def test_openrouter_gets_room_for_thinking_and_other_providers_keep_their_limit():
    assert answer_tokens(OPENROUTER, 1500) == OPENROUTER_ANSWER_TOKENS == 3500
    assert answer_tokens(GROQ, 1500) == 1500 and answer_tokens(GROQ, 1800) == 1800


def test_only_openrouter_has_a_think_less_retry_and_each_call_gets_its_own_copy():
    fields = think_less_fields(OPENROUTER)
    assert fields == {"reasoning": {"effort": "low"}}
    fields["reasoning"]["effort"] = "high"
    assert think_less_fields(OPENROUTER) == {"reasoning": {"effort": "low"}}
    assert think_less_fields(GROQ) is None       # Groq already runs at its lowest effort


def test_the_wait_for_an_answer_is_long_enough_for_a_thinking_model():
    connect, read = AI_TIMEOUT
    assert connect <= 15 and 60 <= read <= 120


# -------------------------------------------------------- failure reasons

def http_error(status, message=None):
    body = {"error": {"message": message}} if message else {}
    return requests.HTTPError("x", response=Response(body, status=status))


def test_http_errors_say_the_status_what_it_means_and_what_the_provider_said():
    text = failure_reason(http_error(429, "Rate limit exceeded: free-models-per-day"))
    assert text.startswith("HTTP 429 (busy, or the daily free limit is used up)")
    assert "free-models-per-day" in text
    assert failure_reason(http_error(402)).startswith("HTTP 402 (no credit left)")
    assert failure_reason(http_error(401)).startswith("HTTP 401 (the key was not accepted)")
    assert "provider error" in failure_reason(http_error(503))


def test_the_status_is_found_in_the_message_when_there_is_no_response_object():
    assert failure_reason(requests.HTTPError("HTTP 500")).startswith("HTTP 500")
    assert failure_reason(requests.HTTPError("429 Client Error: Too Many Requests")).startswith("HTTP 429")
    assert failure_reason(requests.HTTPError("odd")) == "HTTP error"


def test_other_failures_get_short_plain_words():
    assert failure_reason(requests.ReadTimeout("slow")) == "no answer within 75 seconds"
    assert failure_reason(requests.ConnectionError("down")) == "could not connect"
    assert failure_reason(AIReplyError("empty reply from m")) == "empty reply from m"
    assert failure_reason(KeyError("secret-detail")) == "KeyError"
    assert failure_reason(ValueError()) == "ValueError"


def test_a_reason_is_cut_short_and_never_holds_a_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-very-secret-value")
    leaky = http_error(400, "bad request near sk-or-very-secret-value " + "x" * 400)
    text = failure_reason(leaky)
    assert len(text) <= 140 and "sk-or-very-secret-value" not in text
    assert failure_reason(ValueError("token=abcdef123456 was rejected")).count("abcdef123456") == 0


# ------------------------------------------------- the model that sent a bad reply (23 Nov 2026)

def test_an_error_names_the_model_that_really_answered_so_it_can_be_counted():
    with pytest.raises(AIReplyError) as caught:
        read_reply(completion(None, finish="length", model="vendor/slow-one:free"))
    assert caught.value.model == "vendor/slow-one:free" and caught.value.empty is True
    with pytest.raises(AIReplyError) as caught:
        read_reply(completion("", finish="stop", model="vendor/blank-one:free"))
    assert caught.value.model == "vendor/blank-one:free"
    with pytest.raises(AIReplyError) as caught:
        read_reply(completion(None, refusal="No.", model="vendor/refuser:free"))
    assert caught.value.model == "vendor/refuser:free" and caught.value.empty is False


def test_an_error_without_a_model_in_the_reply_has_no_model():
    with pytest.raises(AIReplyError) as caught:
        read_reply({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]})
    assert caught.value.model is None
    with pytest.raises(AIReplyError) as caught:
        read_reply({"choices": []})
    assert caught.value.model is None and AIReplyError("plain").model is None


def test_an_unreadable_text_carries_the_model_too():
    reply = read_reply(completion("Sorry, no.", finish="stop", model="vendor/chatty:free"))
    assert unreadable(reply).model == "vendor/chatty:free"
    cut = read_reply(completion("{\"a\": ", finish="length", model="vendor/cut:free"))
    assert unreadable(cut).model == "vendor/cut:free" and unreadable(cut).empty is True


# ------------------------------------------------------------ Google Gemini

def test_gemini_gets_room_for_its_brief_thinking_and_no_openrouter_retry_fields():
    assert answer_tokens(gemini.URL, 1500) == gemini.ANSWER_TOKENS == 4000
    assert answer_tokens(gemini.URL, 1800) == 4000
    assert think_less_fields(gemini.URL) is None          # its effort is already low on the first try


def test_a_look_alike_address_does_not_get_gemini_room():
    assert answer_tokens("https://generativelanguage.googleapis.com.evil.example/x", 1500) == 1500
    assert answer_tokens("https://evil.example/?u=generativelanguage.googleapis.com", 1500) == 1500


def test_an_error_that_google_sends_inside_a_list_is_read():
    body = [{"error": {"code": 429, "message": "Quota exceeded for this model today",
                       "status": "RESOURCE_EXHAUSTED"}}]
    text = failure_reason(requests.HTTPError("x", response=Response(body, status=429)))
    assert text.startswith("HTTP 429 (busy, or the daily free limit is used up)")
    assert "Quota exceeded for this model today" in text


@pytest.mark.parametrize("body", [[], [None], ["text"], [{"nothing": 1}], [[]]])
def test_a_list_shaped_error_without_a_message_still_gives_the_status(body):
    text = failure_reason(requests.HTTPError("x", response=Response(body, status=403)))
    assert text == "HTTP 403 (the key is not allowed to do this)"


def test_a_google_key_in_an_error_message_is_hidden_even_when_it_is_not_in_the_environment():
    key = "AIza" + "Sy" + "Q" * 33                        # built in pieces so no scanner takes it for real
    body = [{"error": {"message": "API key not valid. Key " + key}}]
    text = failure_reason(requests.HTTPError("x", response=Response(body, status=400)))
    assert key not in text and "AIza" not in text and "***" in text
