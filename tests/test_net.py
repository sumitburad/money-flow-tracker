"""Retry, circuit-breaker and secret-safety behaviour of backend.net."""
import pytest
import requests

from backend.net import (HostCircuitOpen, RetryingHttp, redact, scrub_secrets)


class FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}


def make(outcomes, **kwargs):
    """Build a client whose fetcher plays back ``outcomes`` in order."""
    calls = []
    queue = list(outcomes)

    def fetcher(url, **kw):
        calls.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    pauses = []
    client = RetryingHttp(sleep=pauses.append, fetcher=fetcher, jitter=False, **kwargs)
    return client, calls, pauses


def test_success_first_try_makes_one_call():
    client, calls, pauses = make([FakeResponse(200)])
    assert client.get("https://example.org/a").status_code == 200
    assert len(calls) == 1 and pauses == []


def test_retries_timeout_then_succeeds_with_growing_pauses():
    client, calls, pauses = make([requests.Timeout("slow"), requests.ConnectionError("drop"),
                                  FakeResponse(200)])
    assert client.get("https://example.org/a").status_code == 200
    assert len(calls) == 3
    assert pauses == [1.5, 3.0]


def test_retries_temporary_server_errors_and_honours_retry_after():
    client, calls, pauses = make([FakeResponse(503, {"Retry-After": "7"}), FakeResponse(200)])
    assert client.get("https://example.org/a").status_code == 200
    assert pauses == [7.0]


def test_client_errors_are_not_retried():
    client, calls, _ = make([FakeResponse(404)])
    assert client.get("https://example.org/a").status_code == 404
    assert len(calls) == 1


def test_final_server_error_is_returned_to_caller():
    client, calls, _ = make([FakeResponse(500)] * 3)
    assert client.get("https://example.org/a").status_code == 500
    assert len(calls) == 3


def test_exhausted_network_errors_raise_the_original_error_type():
    client, calls, _ = make([requests.Timeout("slow")] * 3)
    with pytest.raises(requests.Timeout):
        client.get("https://example.org/a")
    assert len(calls) == 3


def test_breaker_skips_host_after_two_complete_failures():
    client, calls, _ = make([requests.Timeout("x")] * 6)
    for _ in range(2):
        with pytest.raises(requests.Timeout):
            client.get("https://flaky.example/a")
    before = len(calls)
    with pytest.raises(HostCircuitOpen):
        client.get("https://flaky.example/b")
    assert len(calls) == before  # no network attempt was made
    # a different host is unaffected
    client2, calls2, _ = make([FakeResponse(200)])
    assert client2.get("https://other.example/a").status_code == 200


def test_breaker_error_is_a_connection_error_so_fallbacks_catch_it():
    assert issubclass(HostCircuitOpen, requests.ConnectionError)


def test_success_resets_failure_count():
    client, calls, _ = make([requests.Timeout("x")] * 3 + [FakeResponse(200)]
                            + [requests.Timeout("x")] * 3)
    with pytest.raises(requests.Timeout):
        client.get("https://h.example/a")
    assert client.get("https://h.example/a").status_code == 200
    with pytest.raises(requests.Timeout):
        client.get("https://h.example/a")
    # only one failure since the last success, so the breaker is still closed
    assert client._failed_calls["h.example"] == 1


def test_redact_hides_keys_in_urls():
    text = "HTTPSConnectionPool: url: /fred/series/observations?series_id=DGS2&api_key=abcd1234abcd1234&file_type=json"
    cleaned = redact(text)
    assert "abcd1234abcd1234" not in cleaned
    assert "api_key=***" in cleaned and "series_id=DGS2" in cleaned


def test_secret_values_never_survive(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "supersecretvalue123")
    assert "supersecretvalue123" not in redact("oops supersecretvalue123 leaked")
    assert scrub_secrets('{"x": "supersecretvalue123"}') == '{"x": "***"}'


def test_the_gemini_key_is_one_of_the_values_that_never_survive(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-value-12345")
    assert "gemini-key-value-12345" not in redact("oops gemini-key-value-12345 leaked")
    assert scrub_secrets("x gemini-key-value-12345") == "x ***"


def test_anything_shaped_like_a_google_key_is_hidden_even_when_it_is_not_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key = "AIza" + "Sy" + "R" * 33                          # built in pieces so no scanner takes it for real
    assert scrub_secrets("seen " + key + " here") == "seen *** here"
    assert key not in redact("GET /v1/models?key=" + key) and key not in redact("bad key " + key)
    assert key not in scrub_secrets('{"error": "' + key + '"}')
    # ordinary words and short look-alikes are left alone
    assert scrub_secrets("AIza is a prefix") == "AIza is a prefix"
    assert scrub_secrets("AIza" + "x" * 10) == "AIza" + "x" * 10


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "abc")
    assert scrub_secrets("abc def") == "abc def"


def test_raised_errors_carry_no_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k3y-k3y-k3y-k3y")
    boom = requests.ConnectionError("failed for url ...&api_key=k3y-k3y-k3y-k3y&x=1")
    client, _, _ = make([boom] * 3)
    with pytest.raises(requests.ConnectionError) as info:
        client.get("https://api.example/x", params={"api_key": "k3y-k3y-k3y-k3y"})
    assert "k3y-k3y-k3y-k3y" not in str(info.value)


def test_retry_after_is_kept_between_one_and_thirty_seconds():
    from backend.net import retry_after_seconds

    class Busy:
        def __init__(self, headers):
            self.headers = headers
    assert retry_after_seconds(Busy({"Retry-After": "7"})) == 7.0
    assert retry_after_seconds(Busy({"retry-after": "0"})) == 1.0
    assert retry_after_seconds(Busy({"Retry-After": "900"})) == 30.0
    assert retry_after_seconds(Busy({"Retry-After": "soon"})) == 15.0      # not a number: default
    assert retry_after_seconds(Busy({})) == 15.0
    assert retry_after_seconds(object()) == 15.0


def test_post_is_repeated_once_after_a_busy_answer_and_never_twice():
    from backend.net import post_with_one_429_retry

    class Answer:
        def __init__(self, code):
            self.status_code, self.headers = code, {"Retry-After": "3"}

    class Http:
        def __init__(self, codes):
            self.codes, self.posts = list(codes), 0

        def post(self, url, **kwargs):
            self.posts += 1
            return Answer(self.codes.pop(0))
    waits = []
    http = Http([429, 200])
    assert post_with_one_429_retry(http, "https://x.example", sleep=waits.append).status_code == 200
    assert http.posts == 2 and waits == [3.0]
    http = Http([429, 429, 200])
    assert post_with_one_429_retry(http, "https://x.example", sleep=waits.append).status_code == 429
    assert http.posts == 2                                  # gave up after the one retry
    http = Http([200])
    post_with_one_429_retry(http, "https://x.example", sleep=waits.append)
    assert http.posts == 1
