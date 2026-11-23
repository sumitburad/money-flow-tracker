"""Choosing free OpenRouter models (backend/free_models.py): direct answerers first, thinking models after.

Nothing here touches the internet: the model list is faked."""
import copy
import json
from pathlib import Path

import pytest
import requests

from backend import free_models as fm
from backend.free_models import (FreePool, ROUTER, load_config, pick, shape_request,
                                 stated_billions, why_not)

ROOT = Path(__file__).resolve().parent.parent
KEY = "sk-or-test-secret-5678"
CFG = {**fm.DEFAULTS, "prefer": ["gemma-4", "llama-3.3-70b", "mistral-small", "qwen3-next"],
       "avoid": ["guard", "safety", "embed"]}
CFG_NO_THINK = {**CFG, "use_thinking_models": False}      # the first version's rule: skip every thinker
THINKS = ["max_tokens", "reasoning", "include_reasoning"]


def model(model_id="google/gemma-4-31b-it:free", **changes):
    """A model as OpenRouter lists it: free, text only, no thinking, plenty of room."""
    row = {"id": model_id, "context_length": 131072,
           "pricing": {"prompt": "0", "completion": "0", "request": "0"},
           "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
           "supported_parameters": ["max_tokens", "temperature", "response_format"],
           "top_provider": {"context_length": 131072, "max_completion_tokens": 8192}}
    row.update(changes)
    return row


# ------------------------------------------------------------------ what qualifies

def test_a_free_model_that_answers_directly_qualifies():
    assert why_not(model(), CFG) is None


@pytest.mark.parametrize("changes,expected", [
    ({"id": "openai/gpt-5"}, "paid"),                                           # no ":free"
    ({"id": "vendor/some-70b:free", "pricing": {"prompt": "0.0000001", "completion": "0"}}, "paid"),
    ({"pricing": None}, "paid"),
    ({"pricing": {"prompt": "0"}}, "paid"),                                     # a price is missing: not proven free
    ({"id": "openrouter/free"}, "paid"),                                        # the router itself
    ({"id": "openrouter/auto:free"}, "paid"),
    ({"architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}}, "not_text"),
    ({"architecture": {"input_modalities": ["text"], "output_modalities": ["text", "image"]}}, "not_text"),
    ({"architecture": {"input_modalities": ["image"], "output_modalities": ["text"]}}, "not_text"),
    ({"id": "nvidia/nemotron-guard-70b:free"}, "avoided"),
    ({"supported_parameters": None}, "no_parameter_list"),
    ({"context_length": 8192, "top_provider": {"context_length": 8192, "max_completion_tokens": None}}, "short_context"),
    ({"top_provider": {"context_length": 131072, "max_completion_tokens": 2048}}, "short_answer"),
    ({"id": "vendor/tiny-4b-instruct:free"}, "too_small"),
    ({"id": "vendor/mystery-model:free"}, "size_unknown"),
])
def test_why_a_model_is_not_used(changes, expected):
    assert why_not(model(**changes), CFG) == expected


def test_an_unlisted_answer_limit_or_context_in_the_provider_block_is_fine():
    row = model(context_length=None, top_provider={"context_length": 65536, "max_completion_tokens": None})
    assert why_not(row, CFG) is None


def test_an_unknown_size_is_allowed_when_the_name_is_on_the_preferred_list():
    assert why_not(model("google/gemma-4-flash:free"), CFG) is None          # "gemma-4" is preferred


@pytest.mark.parametrize("params", [THINKS, ["max_tokens", "include_reasoning"], ["Reasoning"]])
def test_a_thinking_model_is_skipped_only_when_the_settings_switch_thinking_models_off(params):
    row = model(supported_parameters=params)                  # case does not matter
    assert why_not(row, CFG_NO_THINK) == "thinks"
    assert why_not(row, CFG) is None                          # the default: thinking models may be used
    assert fm.is_thinker(row) and not fm.is_thinker(model())


def test_a_thinking_model_is_skipped_even_when_it_is_the_most_preferred_name_if_switched_off():
    row = model("google/gemma-4-31b-it:free", supported_parameters=["reasoning"])
    assert why_not(row, CFG_NO_THINK) == "thinks"


@pytest.mark.parametrize("name,billions", [
    ("google/gemma-4-31b-it:free", 31.0), ("meta-llama/llama-3.3-70b-instruct:free", 70.0),
    ("qwen/qwen3-next-80b-a3b-instruct:free", 80.0), ("inclusionai/ling-2.6-1t:free", 1000.0),
    ("liquid/lfm-2.5-1.2b-instruct:free", 1.2), ("qwen/qwen3-4b:free", 4.0),
    ("google/gemma-3n-e2b-it:free", None), ("dots-studio/dots3-note-preview:free", None),
])
def test_the_size_stated_in_a_name(name, billions):
    assert stated_billions(name) == billions


# ------------------------------------------------------------------ the order

def test_preferred_names_come_first_in_the_order_of_the_list():
    rows = [model("vendor/other-30b:free"), model("qwen/qwen3-next-80b-a3b-instruct:free"),
            model("meta-llama/llama-3.3-70b-instruct:free"), model("google/gemma-4-31b-it:free"),
            model("vendor/other-120b:free")]
    chosen, counts = pick(rows, {**CFG, "max_models": 3})
    assert chosen == ["google/gemma-4-31b-it:free", "meta-llama/llama-3.3-70b-instruct:free",
                      "qwen/qwen3-next-80b-a3b-instruct:free"]
    assert counts["usable"] == 5
    # with room for every model, the ones that are not on the list come last, biggest first
    everything, _ = pick(rows, {**CFG, "max_models": 3, "prefer": ["gemma-4", "llama-3.3-70b", "qwen3-next"]})
    assert everything == chosen
    wide = {**CFG, "prefer": ["gemma-4", "llama-3.3-70b", "qwen3-next"]}
    ordered = sorted([r for r in rows if why_not(r, wide) is None],
                     key=lambda r: (fm.preference(r["id"], wide["prefer"]), -(stated_billions(r["id"]) or 0), r["id"]))
    assert [r["id"] for r in ordered][-2:] == ["vendor/other-120b:free", "vendor/other-30b:free"]


def test_models_not_on_the_preferred_list_follow_biggest_first_and_the_number_is_capped():
    rows = [model("vendor/a-30b:free"), model("vendor/b-120b:free"), model("vendor/c-70b:free"),
            model("vendor/d-24b:free")]
    chosen, _ = pick(rows, {**CFG, "prefer": [], "max_models": 3})
    assert chosen == ["vendor/b-120b:free", "vendor/c-70b:free", "vendor/a-30b:free"]
    chosen, _ = pick(rows, {**CFG, "prefer": [], "max_models": 1})
    assert chosen == ["vendor/b-120b:free"]


ROWS_WITH_THINKERS = [
    model("openai/gpt-5"), model("vendor/paid-70b", pricing={"prompt": "1", "completion": "1"}),
    model("nvidia/nemotron-3-nano-30b-a3b:free", supported_parameters=["reasoning"]),
    model("nvidia/nemotron-3.5-lightning:free", supported_parameters=["reasoning"]),
    model("liquid/lfm-1.2b:free"), model("google/gemma-4-31b-it:free"), "not a model", None]


def test_the_counts_say_what_was_skipped_and_do_not_count_paid_models():
    chosen, counts = pick(ROWS_WITH_THINKERS, CFG_NO_THINK)
    assert chosen == ["google/gemma-4-31b-it:free"]
    assert counts == {"free_seen": 4, "thinks": 2, "too_small": 1, "usable": 1}


def test_with_thinking_models_allowed_they_fill_the_places_the_direct_ones_leave():
    chosen, counts = pick(ROWS_WITH_THINKERS, CFG)
    # the direct model first, then the thinker whose name states a usable size; "lightning" states none
    assert chosen == ["google/gemma-4-31b-it:free", "nvidia/nemotron-3-nano-30b-a3b:free"]
    assert counts == {"free_seen": 4, "too_small": 1, "size_unknown": 1, "usable": 2}


def test_nothing_usable_gives_an_empty_choice():
    chosen, counts = pick([model(supported_parameters=["reasoning"])], CFG_NO_THINK)
    assert chosen == [] and counts["thinks"] == 1 and counts["usable"] == 0
    chosen, counts = pick([model("vendor/tiny-4b:free")], CFG)
    assert chosen == [] and counts["too_small"] == 1 and counts["usable"] == 0


# ------------------------------------------------------------------ the settings file

def test_the_real_settings_file_is_valid():
    cfg = load_config()
    assert cfg["enabled"] is True and 1 <= cfg["max_models"] <= 3
    assert cfg["prefer"] and cfg["avoid"] and all(w == w.lower() for w in cfg["prefer"] + cfg["avoid"])
    assert cfg["min_billions"] >= 10 and cfg["min_answer_tokens"] >= 2000


def test_a_missing_or_broken_settings_file_gives_the_safe_defaults(tmp_path):
    assert load_config(tmp_path / "nope.yaml") == fm.DEFAULTS | {"max_models": 3}
    broken = tmp_path / "broken.yaml"
    broken.write_text("openrouter: [this is: not: valid", encoding="utf-8")
    assert load_config(broken)["enabled"] is True
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text("openrouter:\n  enabled: 'maybe'\n  max_models: 'lots'\n  min_billions: true\n"
                     "  prefer: 'gemma'\n  avoid: [Guard, '', 7]\n", encoding="utf-8")
    cfg = load_config(wrong)
    assert cfg["enabled"] is True and cfg["max_models"] == 3 and cfg["min_billions"] == 20.0
    assert cfg["prefer"] == [] and cfg["avoid"] == ["guard", "7"]


def test_the_number_of_backups_is_kept_between_one_and_three(tmp_path):
    for written, expected in ((0, 1), (2, 2), (9, 3), (-4, 1)):
        path = tmp_path / ("m%d.yaml" % written)
        path.write_text("openrouter:\n  max_models: %d\n" % written, encoding="utf-8")
        assert load_config(path)["max_models"] == expected


# ------------------------------------------------------------------ reading the list

class ListReply:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code = status
        self.content = raw if raw is not None else json.dumps(payload).encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code, response=self)

    def json(self):
        return json.loads(self.content)


class ListHttp:
    """Answers model-list requests by address and records what was asked."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        reply = self.routes[url]
        if isinstance(reply, Exception):
            raise reply
        return reply


ACCOUNT = fm.BASE + "/api/v1/models/user"
PUBLIC = fm.BASE + "/api/v1/models"
LIST = {"data": [model("google/gemma-4-31b-it:free"), model("meta-llama/llama-3.3-70b-instruct:free"),
                 model("nvidia/nemotron-3.5-lightning:free", supported_parameters=["reasoning"])]}


def read(routes, cfg=None):
    http = ListHttp(routes)
    pool = FreePool()
    pool.ensure(http, KEY, cfg or CFG)
    return pool, http


def test_the_accounts_own_list_is_read_first_with_the_key_in_the_header_only():
    pool, http = read({ACCOUNT: ListReply(LIST)})
    assert pool.ids == ["google/gemma-4-31b-it:free", "meta-llama/llama-3.3-70b-instruct:free"]
    assert [c["url"] for c in http.calls] == [ACCOUNT]
    assert http.calls[0]["headers"]["Authorization"] == "Bearer " + KEY
    assert KEY not in http.calls[0]["url"] and http.calls[0]["timeout"] == fm.LIST_TIMEOUT
    assert pool.note == "" and pool.source == "your account's model list"


def test_the_list_is_read_only_once_per_run():
    http = ListHttp({ACCOUNT: ListReply(LIST)})
    pool = FreePool()
    pool.ensure(http, KEY, CFG)
    pool.ensure(http, KEY, CFG)
    pool.ensure(ListHttp({}), KEY, CFG)
    assert len(http.calls) == 1


def test_when_the_accounts_list_cannot_be_read_the_public_list_is_used():
    pool, http = read({ACCOUNT: ListReply({"error": {"message": "no"}}, status=401), PUBLIC: ListReply(LIST)})
    assert [c["url"] for c in http.calls] == [ACCOUNT, PUBLIC]
    assert pool.ids and pool.source == "OpenRouter's public model list" and pool.note == ""


def test_when_the_accounts_list_is_fine_but_has_no_usable_model_the_public_list_is_not_used():
    thinkers = {"data": [model("nvidia/nemotron-3.5-lightning:free", supported_parameters=["reasoning"])]}
    pool, http = read({ACCOUNT: ListReply(thinkers), PUBLIC: ListReply(LIST)}, CFG_NO_THINK)
    assert [c["url"] for c in http.calls] == [ACCOUNT]          # the public list would name models this account may not use
    assert pool.ids == [] and "no free model that answers directly" in pool.note
    summary = pool.summary()
    assert summary["free_pool"] == [] and summary["pool_counts"]["free models seen"] == 1
    assert summary["pool_counts"]["free models that think (skipped on purpose)"] == 1


def test_when_thinking_models_are_allowed_but_none_can_be_used_the_note_says_so():
    tiny = {"data": [model("vendor/tiny-4b:free", supported_parameters=THINKS)]}
    pool, http = read({ACCOUNT: ListReply(tiny), PUBLIC: ListReply(LIST)})
    assert [c["url"] for c in http.calls] == [ACCOUNT]
    assert pool.ids == [] and "had no free model that could be used" in pool.note


def test_when_neither_list_can_be_read_the_note_says_why_in_plain_words():
    pool, _ = read({ACCOUNT: ListReply(status=404, raw=b"{}"), PUBLIC: requests.ConnectTimeout("x")})
    assert pool.ids == []
    assert pool.note.startswith("No free model could be chosen, so the free router was used:")
    assert "your account's model list could not be read (HTTP 404" in pool.note
    assert "OpenRouter's public model list could not be read (no answer within 30 seconds)" in pool.note


@pytest.mark.parametrize("reply,words", [
    (ListReply(raw=b"<html>oops</html>"), "not valid JSON"),
    (ListReply({"models": []}), "unexpected shape"),
    (ListReply({"data": "none"}), "unexpected shape"),
    (ListReply(raw=b"x" * (fm.MAX_LIST_BYTES + 1)), "unexpectedly large"),
])
def test_an_unexpected_list_is_explained_not_trusted(reply, words):
    pool, _ = read({ACCOUNT: reply, PUBLIC: reply})
    assert pool.ids == [] and words in pool.note


def test_a_key_that_ends_up_in_an_error_is_removed_from_the_note(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    leaky = ValueError("bad list for " + KEY)
    pool, _ = read({ACCOUNT: leaky, PUBLIC: leaky})
    assert KEY not in pool.note and "***" in pool.note


def test_only_openrouters_own_next_page_links_are_followed_and_at_most_two():
    page = lambda names, nxt: ListReply({"data": [model(n) for n in names], "next": nxt})
    routes = {
        ACCOUNT: page(["google/gemma-4-31b-it:free"], "/api/v1/models/user?offset=2"),
        fm.BASE + "/api/v1/models/user?offset=2": page(["meta-llama/llama-3.3-70b-instruct:free"], "/api/v1/models?offset=9"),
        fm.BASE + "/api/v1/models?offset=9": page(["mistralai/mistral-small-3.2-24b-instruct:free"], "/api/v1/models?offset=10"),
        fm.BASE + "/api/v1/models?offset=10": page(["qwen/qwen3-next-80b-a3b-instruct:free"], "/api/v1/models?offset=11"),
    }
    pool, http = read(routes)
    assert len(http.calls) == 3                    # the first page and two more; the fourth link is not followed
    assert pool.ids == ["google/gemma-4-31b-it:free", "meta-llama/llama-3.3-70b-instruct:free",
                        "mistralai/mistral-small-3.2-24b-instruct:free"]


@pytest.mark.parametrize("link", ["https://evil.example/api/v1/models?offset=2", "//evil.example/api/v1/models",
                                  "/somewhere/else", 7, None, ""])
def test_a_next_link_that_does_not_stay_on_openrouters_model_list_is_ignored(link):
    pool, http = read({ACCOUNT: ListReply({"data": [model()], "next": link})})
    assert len(http.calls) == 1 and pool.ids == ["google/gemma-4-31b-it:free"]


def test_the_switch_turns_the_choice_off_without_any_request():
    http = ListHttp({})
    pool = FreePool()
    pool.ensure(http, KEY, {**CFG, "enabled": False})
    assert http.calls == [] and pool.ids == [] and "switched off" in pool.note


def test_without_a_way_to_ask_or_without_a_key_nothing_happens_and_nothing_is_said():
    pool = FreePool()
    pool.ensure(object(), KEY, CFG)
    assert pool.tried and pool.ids == [] and pool.note == ""
    pool = FreePool()
    http = ListHttp({})
    pool.ensure(http, "", CFG)
    assert http.calls == [] and pool.note == ""


def test_each_retry_starts_one_model_further_on():
    pool, _ = read({ACCOUNT: ListReply(LIST)})
    a, b = pool.ids
    assert pool.choose(0) == [a, b] and pool.choose(1) == [b, a] and pool.choose(2) == [a, b]
    assert FreePool().choose(3) == []


# ------------------------------------------------------------------ changing a request

def pool_of(*ids):
    pool = FreePool()
    pool.tried, pool.ids = True, list(ids)
    return pool


BODY = {"model": ROUTER, "temperature": 0, "max_tokens": 3500, "messages": [{"role": "user", "content": "x"}]}
URL = "https://openrouter.ai/api/v1/chat/completions"


def shaped(body=BODY, *, url=URL, model_name=ROUTER, attempt=0, pool=None):
    return shape_request(body, url=url, model=model_name, attempt=attempt, http=object(), key=KEY, pool=pool)


def test_the_free_router_is_replaced_by_named_free_models_with_the_rest_as_backups():
    out = shaped(pool=pool_of("a/x-70b:free", "b/y-70b:free", "c/z-70b:free"))
    assert out["model"] == "a/x-70b:free" and out["models"] == ["b/y-70b:free", "c/z-70b:free"]
    assert out["max_tokens"] == 3500 and out["messages"] == BODY["messages"]
    assert all(m.endswith(":free") for m in [out["model"], *out["models"]])      # never a paid backup


def test_a_retry_starts_with_a_different_model_and_the_input_is_never_changed():
    pool = pool_of("a/x-70b:free", "b/y-70b:free")
    before = copy.deepcopy(BODY)
    assert shaped(pool=pool, attempt=1)["model"] == "b/y-70b:free"
    assert BODY == before


def test_one_model_means_no_backup_list():
    out = shaped(pool=pool_of("a/x-70b:free"))
    assert out["model"] == "a/x-70b:free" and "models" not in out


def test_the_body_is_returned_unchanged_when_there_is_no_choice():
    assert shaped(pool=pool_of()) is BODY


def test_other_providers_and_models_the_person_named_are_left_alone():
    pool = pool_of("a/x-70b:free")
    groq = {**BODY, "model": "openai/gpt-oss-120b"}
    assert shaped(groq, url="https://api.groq.com/openai/v1/chat/completions", model_name="openai/gpt-oss-120b",
                  pool=pool) is groq
    named = {**BODY, "model": "meta-llama/llama-3.3-70b-instruct:free"}
    assert shaped(named, model_name="meta-llama/llama-3.3-70b-instruct:free", pool=pool) is named


@pytest.mark.parametrize("url", [
    "https://openrouter.ai.evil.example/api/v1/chat/completions",      # look-alike host
    "https://evil.example/openrouter.ai/api/v1/chat/completions",      # name hidden in the path
    "https://evil.example/?next=openrouter.ai",                         # name hidden in the query
    "https://notopenrouter.ai/api/v1/chat/completions",
    "http://[::1",                                                      # not even a valid address
    "", None])
def test_only_the_real_openrouter_host_gets_its_request_changed(url):
    pool = pool_of("a/x-70b:free", "b/y-70b:free")
    assert shaped(url=url, pool=pool) is BODY


def test_openrouters_own_hosts_are_recognised():
    pool = pool_of("a/x-70b:free")
    for url in ("https://openrouter.ai/api/v1/chat/completions", "https://api.openrouter.ai/v1/chat/completions"):
        assert shaped(url=url, pool=pool)["model"] == "a/x-70b:free"


def test_summary_is_small_and_plain():
    pool, _ = read({ACCOUNT: ListReply(LIST)})
    out = pool.summary()
    assert out["free_pool"] == pool.ids and "pool_note" not in out
    assert out["pool_counts"]["free models seen"] == 3
    assert KEY not in json.dumps(out)


# ------------------------------------------------------------------ thinking models (23 Nov 2026)

LIVE_IDS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free", "particle-ai/particle-1:free", "google/gemma-4-26b-a4b-it:free",
    "dots-studio/dots-3-note-preview:free", "baidu/ernie-5.5-flash-preview:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3.5-lightning:free", "liquid/lfm-3-1.7b:free", "recursive/flint-v1.0:free",
]


def live_list():
    """The free models seen in the live runs of 22 and 23 Nov 2026: every one lists a "reasoning" setting."""
    return [model(i, supported_parameters=THINKS) for i in LIVE_IDS]


def test_the_real_settings_choose_the_models_that_worked_in_the_live_runs():
    result = fm.plan(live_list(), load_config())
    assert result["chosen"] == ["nvidia/nemotron-3-ultra-550b-a55b:free", "particle-ai/particle-1:free",
                                "google/gemma-4-26b-a4b-it:free"]
    assert result["thinking"] == result["chosen"]
    why = {row["id"]: row["result"] for row in result["seen"]}
    assert why["nvidia/nemotron-3.5-super-vl:free"] == "on the avoid list"
    assert why["nvidia/nemotron-3.5-lightning:free"] == "on the avoid list"
    assert why["liquid/lfm-3-1.7b:free"] == "too small"
    assert why["recursive/flint-v1.0:free"] == "size unknown"
    assert why["dots-studio/dots-3-note-preview:free"] == "spare, thinks"
    assert why["nvidia/nemotron-3-ultra-550b-a55b:free"] == "asked first, thinks briefly"
    assert why["particle-ai/particle-1:free"] == "backup, thinks briefly"
    assert result["counts"]["free_seen"] == 10 and result["counts"]["usable"] == 6


def test_with_thinking_switched_off_the_same_live_list_leaves_nothing_to_choose():
    result = fm.plan(live_list(), {**load_config(), "use_thinking_models": False})
    assert result["chosen"] == []
    # the two avoid-list models are named first; the other eight all think
    assert result["counts"]["avoided"] == 2 and result["counts"]["thinks"] == 8


def test_the_real_settings_file_knows_the_live_run_results():
    cfg = load_config()
    assert cfg["use_thinking_models"] is True and cfg["thinking_effort"] in fm.EFFORTS
    assert 3500 <= cfg["thinking_answer_tokens"] <= 16000
    assert cfg["prefer_thinking"][:2] == ["nemotron-3-ultra", "particle-1"]
    assert "nemotron-3.5-super-vl" in cfg["avoid"] and "nemotron-3.5-lightning" in cfg["avoid"]


def test_models_that_think_are_ordered_by_the_thinking_list_then_biggest_first():
    cfg = {**CFG, "prefer_thinking": ["alpha", "beta"], "max_models": 3}
    rows = [model(i, supported_parameters=THINKS) for i in
            ("v/zeta-30b:free", "v/beta-24b:free", "v/yotta-120b:free", "v/alpha-70b:free")]
    chosen, _ = pick(rows, cfg)
    assert chosen == ["v/alpha-70b:free", "v/beta-24b:free", "v/yotta-120b:free"]
    chosen, _ = pick(rows, {**cfg, "max_models": 1})
    assert chosen == ["v/alpha-70b:free"]


def test_direct_models_keep_their_places_and_thinkers_only_fill_what_is_left():
    rows = [model("v/direct-70b:free"), model("v/think-a-120b:free", supported_parameters=THINKS),
            model("v/think-b-80b:free", supported_parameters=THINKS)]
    result = fm.plan(rows, {**CFG, "prefer": [], "max_models": 3})
    assert result["chosen"] == ["v/direct-70b:free", "v/think-a-120b:free", "v/think-b-80b:free"]
    assert result["thinking"] == ["v/think-a-120b:free", "v/think-b-80b:free"]
    one = fm.plan(rows, {**CFG, "prefer": [], "max_models": 1})
    assert one["chosen"] == ["v/direct-70b:free"] and one["thinking"] == []     # a direct model is never pushed out


def test_a_name_on_the_thinking_prefer_list_may_have_an_unknown_size():
    row = model("v/particle-1:free", supported_parameters=THINKS)
    assert why_not(row, CFG) == "size_unknown"
    assert why_not(row, {**CFG, "prefer_thinking": ["particle-1"]}) is None


def test_the_seen_list_is_short_and_says_what_each_model_is():
    rows = [model("v/a-%db:free" % n) for n in range(30, 50)] + [model("v/tiny-4b:free")]
    result = fm.plan(rows, {**CFG, "prefer": []})
    assert len(result["seen"]) == fm.MAX_SEEN and result["counts"]["free_seen"] == 21
    assert [r["result"] for r in result["seen"][:4]] == ["asked first", "backup", "backup", "spare"]


def test_the_longest_answer_each_chosen_model_allows_is_reported():
    rows = [model("v/a-70b:free", supported_parameters=THINKS,
                  top_provider={"context_length": 131072, "max_completion_tokens": 4096}),
            model("v/b-60b:free", supported_parameters=THINKS,
                  top_provider={"context_length": 131072, "max_completion_tokens": None})]
    assert fm.plan(rows, CFG)["caps"] == {"v/a-70b:free": 4096, "v/b-60b:free": None}


def test_the_room_for_thinking_models_is_the_setting_but_never_more_than_a_model_allows():
    cfg = {**CFG, "prefer": []}
    big = [model("v/a-70b:free", supported_parameters=THINKS), model("v/b-60b:free", supported_parameters=THINKS)]
    pool, _ = read({ACCOUNT: ListReply({"data": big})}, cfg)
    assert pool.thinking == ["v/a-70b:free", "v/b-60b:free"] and pool.think == {"effort": "low", "room": 6000}
    small = [model("v/a-70b:free", supported_parameters=THINKS,
                   top_provider={"context_length": 131072, "max_completion_tokens": 4096}), big[1]]
    pool, _ = read({ACCOUNT: ListReply({"data": small})}, cfg)
    assert pool.think["room"] == 4096
    pool, _ = read({ACCOUNT: ListReply({"data": [model("v/a-70b:free")]})}, cfg)
    assert pool.thinking == [] and pool.think is None          # only direct models: nothing extra is asked


def test_the_summary_lists_the_models_seen_and_the_thinkers_chosen():
    pool, _ = read({ACCOUNT: ListReply({"data": live_list()})}, load_config())
    out = pool.summary()
    assert out["free_pool"] == pool.ids and out["pool_thinking"] == pool.ids
    assert len(out["pool_seen"]) == 10
    assert out["pool_seen"][0] == {"id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                                   "result": "asked first, thinks briefly"}
    assert KEY not in json.dumps(out)


def test_the_settings_for_thinking_models_are_checked_and_kept_in_range(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text("openrouter:\n  use_thinking_models: 'yes'\n  thinking_effort: Ludicrous\n"
                    "  thinking_answer_tokens: 99999999\n  prefer_thinking: [Particle-1, '']\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["use_thinking_models"] is True and cfg["thinking_effort"] == "low"
    assert cfg["thinking_answer_tokens"] == 16000 and cfg["prefer_thinking"] == ["particle-1"]
    path.write_text("openrouter:\n  use_thinking_models: false\n  thinking_effort: HIGH\n"
                    "  thinking_answer_tokens: 10\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["use_thinking_models"] is False and cfg["thinking_effort"] == "high"
    assert cfg["thinking_answer_tokens"] == 3500


# ------------------------------------------------------------------ changing a request for thinking models

def pool_with_thinkers(*ids, thinking=(), room=6000):
    pool = pool_of(*ids)
    pool.thinking = list(thinking)
    pool.think = {"effort": "low", "room": room} if thinking else None
    return pool


def test_thinking_models_get_a_brief_thinking_request_and_more_room():
    pool = pool_with_thinkers("a/x-70b:free", "b/y-70b:free", thinking=["a/x-70b:free"])
    before = copy.deepcopy(BODY)
    out = shaped(pool=pool)
    assert out["reasoning"] == {"effort": "low"} and out["max_tokens"] == 6000
    assert out["model"] == "a/x-70b:free" and out["models"] == ["b/y-70b:free"]
    assert BODY == before                                       # the input is never changed


def test_a_retry_that_already_asks_for_less_thinking_keeps_its_own_setting():
    body = {**BODY, "reasoning": {"effort": "minimal"}}
    out = shaped(body, pool=pool_with_thinkers("a/x-70b:free", thinking=["a/x-70b:free"]))
    assert out["reasoning"] == {"effort": "minimal"}


def test_only_direct_models_means_no_extra_thinking_fields():
    out = shaped(pool=pool_with_thinkers("a/x-70b:free", "b/y-70b:free"))
    assert "reasoning" not in out and out["max_tokens"] == 3500


def test_a_room_smaller_than_the_request_already_has_never_lowers_it():
    out = shaped(pool=pool_with_thinkers("a/x-70b:free", thinking=["a/x-70b:free"], room=3000))
    assert out["max_tokens"] == 3500


def test_a_retry_that_rotates_to_a_direct_model_first_still_carries_the_thinking_fields():
    pool = pool_with_thinkers("a/direct-70b:free", "b/think-70b:free", thinking=["b/think-70b:free"])
    out = shaped(pool=pool, attempt=1)                          # the thinker is now asked first
    assert out["model"] == "b/think-70b:free" and out["reasoning"] == {"effort": "low"}
    out = shaped(pool=pool, attempt=0)                          # the thinker is a backup, so the fields stay
    assert out["model"] == "a/direct-70b:free" and out["reasoning"] == {"effort": "low"}


# ------------------------------------------------------------------ what each model did

def test_what_each_model_did_is_counted_and_reported():
    pool = FreePool()
    pool.record("nvidia/nemotron-3-ultra-550b-a55b:free", "accepted")
    pool.record("nvidia/nemotron-3-ultra-550b-a55b", "accepted")        # the ":free" ending does not matter
    pool.record("particle-ai/particle-1:free", "empty")
    pool.record("particle-ai/particle-1:free", "rejected")
    assert pool.active() and not pool.tried
    out = pool.summary()
    assert out["model_results"] == [
        {"model": "nvidia/nemotron-3-ultra-550b-a55b", "accepted": 2, "rejected": 0, "empty": 0},
        {"model": "particle-ai/particle-1", "accepted": 0, "rejected": 1, "empty": 1}]
    assert "free_pool" not in out            # the list was never read, so there is nothing to say about it


@pytest.mark.parametrize("model_id,outcome", [(None, "accepted"), ("", "accepted"), ("  ", "accepted"),
                                              (7, "accepted"), ("m/x", "good"), ("m/x", None)])
def test_junk_is_ignored_when_counting(model_id, outcome):
    pool = FreePool()
    pool.record(model_id, outcome)
    assert pool.outcomes == {} and not pool.active()


def test_only_a_few_models_are_counted():
    pool = FreePool()
    for number in range(20):
        pool.record("m/model-%d" % number, "accepted")
    assert len(pool.outcomes) == fm.MAX_RESULT_MODELS
    pool.record("m/model-0", "empty")                           # a model already counted still counts
    assert pool.outcomes["m/model-0"]["empty"] == 1


def test_reset_forgets_everything_including_results():
    pool, _ = read({ACCOUNT: ListReply(LIST)})
    pool.record("m/x", "accepted")
    pool.reset()
    assert (not pool.tried and pool.ids == [] and pool.seen == [] and pool.outcomes == {}
            and pool.thinking == [] and pool.think is None and pool.summary() == {})


def test_a_model_called_by_a_forbidden_field_name_cannot_break_the_published_feed():
    """Model names come from outside. They are values in the published data, never field names."""
    from backend.feed_contract import FORBIDDEN
    pool = FreePool()
    for word in sorted(FORBIDDEN):
        pool.record(word, "accepted")
    out = pool.summary()
    assert all(isinstance(row, dict) and set(row) == {"model", "accepted", "rejected", "empty"}
               for row in out["model_results"])

    def keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                yield key
                yield from keys(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from keys(value)
    assert not {k.lower() for k in keys(out)} & FORBIDDEN
