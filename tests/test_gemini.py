"""Google Gemini as another free AI (backend/gemini.py). Nothing here touches the internet."""
import re
from pathlib import Path

import pytest
import yaml

from backend import gemini
from backend.net import SECRET_ENV_NAMES

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

BODY = {"model": "gemini-x", "temperature": 0.2, "max_tokens": 4000,
        "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": "x"}],
        "models": ["a/b:free"], "reasoning": {"effort": "low"}}


@pytest.mark.parametrize("url", [
    gemini.URL, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "HTTPS://GenerativeLanguage.GoogleAPIs.com/x"])
def test_the_real_gemini_host_is_recognised(url):
    assert gemini.is_gemini(url)


@pytest.mark.parametrize("url", [
    "https://generativelanguage.googleapis.com.evil.example/v1",          # look-alike host
    "https://evil.example/generativelanguage.googleapis.com",             # name hidden in the path
    "https://evil.example/?next=generativelanguage.googleapis.com",       # name hidden in the query
    "https://notgenerativelanguage.googleapis.com/",
    "https://api.groq.com/openai/v1/chat/completions", "http://[::1", "", None])
def test_look_alike_addresses_are_not_gemini(url):
    assert not gemini.is_gemini(url)


def test_the_address_is_fixed_and_the_key_name_is_one_the_run_protects():
    assert gemini.URL == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert gemini.URL.startswith("https://") and gemini.is_gemini(gemini.URL)
    assert gemini.SECRET == "GEMINI_API_KEY" and gemini.SECRET in SECRET_ENV_NAMES


def test_a_missing_or_broken_settings_file_gives_the_safe_defaults(tmp_path):
    defaults = {"enabled": True, "models": list(gemini.DEFAULT_MODELS)}
    assert gemini.load_config(tmp_path / "nope.yaml") == defaults
    broken = tmp_path / "b.yaml"
    broken.write_text("gemini: [not: valid", encoding="utf-8")
    assert gemini.load_config(broken) == defaults
    wrong = tmp_path / "w.yaml"
    wrong.write_text("gemini:\n  enabled: 'sure'\n  models: gemini-x\n", encoding="utf-8")
    assert gemini.load_config(wrong) == defaults
    other = tmp_path / "o.yaml"
    other.write_text("openrouter:\n  enabled: false\n", encoding="utf-8")       # no gemini section at all
    assert gemini.load_config(other) == defaults


def test_model_names_are_checked_deduplicated_and_capped(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("gemini:\n  models: [Gemini-A, gemini-a, 'bad name', '../x', gemini-b, gemini-c, gemini-d]\n",
                    encoding="utf-8")
    assert gemini.load_config(path)["models"] == ["gemini-a", "gemini-b", "gemini-c"]


def test_the_switch_turns_gemini_off_even_when_a_name_is_given(tmp_path):
    path = tmp_path / "off.yaml"
    path.write_text("gemini:\n  enabled: false\n", encoding="utf-8")
    assert gemini.models("gemini-9", path) == [] and gemini.models("", path) == []


def test_a_name_in_the_environment_replaces_the_list_but_a_bad_one_does_not(tmp_path):
    path = tmp_path / "ok.yaml"
    path.write_text("gemini:\n  models: [gemini-a, gemini-b]\n", encoding="utf-8")
    assert gemini.models("gemini-9-pro", path) == ["gemini-9-pro"]
    assert gemini.models("  Gemini-9-Pro ", path) == ["gemini-9-pro"]
    assert gemini.models("", path) == ["gemini-a", "gemini-b"]
    assert gemini.models("not a name!", path) == ["gemini-a", "gemini-b"]
    assert gemini.models(None, path) == ["gemini-a", "gemini-b"]


def test_the_real_settings_file_lists_valid_gemini_models():
    cfg = gemini.load_config()
    assert cfg["enabled"] is True and 1 <= len(cfg["models"]) <= gemini.MAX_MODELS
    assert cfg["models"][0] == "gemini-flash-latest"
    assert gemini.models("") == cfg["models"]


def test_a_gemini_request_leaves_out_what_google_may_not_accept():
    before = dict(BODY)
    out = gemini.fit_request(BODY, gemini.URL)
    assert out == {"model": "gemini-x", "max_tokens": 4000, "messages": BODY["messages"],
                   "reasoning_effort": "low"}
    assert BODY == before                                          # the input is never changed


def test_a_request_that_already_sets_the_effort_keeps_it():
    out = gemini.fit_request({**BODY, "reasoning_effort": "medium"}, gemini.URL)
    assert out["reasoning_effort"] == "medium"


@pytest.mark.parametrize("url", ["https://api.groq.com/openai/v1/chat/completions",
                                 "https://openrouter.ai/api/v1/chat/completions",
                                 "https://generativelanguage.googleapis.com.evil.example/v1", "", None])
def test_every_other_address_gets_its_request_back_unchanged(url):
    assert gemini.fit_request(BODY, url) is BODY


# ------------------------------------------------------------ where the key may travel

def daily_steps():
    return yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))["jobs"]["refresh"]["steps"]


def test_the_daily_workflow_gives_the_gemini_secret_to_the_collect_step_and_nothing_else():
    steps = daily_steps()
    collect = [s for s in steps if str(s.get("name", "")).startswith("Collect official data")]
    assert len(collect) == 1
    assert collect[0]["env"]["GEMINI_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"
    holders = [s.get("name") for s in steps if "GEMINI_API_KEY" in str(s.get("env", {}))
               or "GEMINI_API_KEY" in str(s.get("run", ""))]
    assert holders == [collect[0]["name"]]


def test_no_workflow_puts_a_secret_in_a_command_line():
    for path in WORKFLOWS:
        for job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values():
            for step in job["steps"]:
                assert "secrets." not in str(step.get("run", "")), (path.name, step.get("name"))


def test_every_secret_a_workflow_reads_is_one_the_program_hides_in_its_logs():
    used = set()
    for path in WORKFLOWS:
        used |= set(re.findall(r"secrets\.([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")))
    used.discard("GITHUB_TOKEN")
    assert "GEMINI_API_KEY" in used and used <= set(SECRET_ENV_NAMES)


def test_the_only_place_the_program_sends_the_gemini_key_is_the_fixed_google_address():
    """The key goes into a header for requests to gemini.URL; no other file builds a Google address."""
    offenders = []
    for path in sorted((ROOT / "backend").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name != "gemini.py" and "generativelanguage" in text:
            offenders.append(path.name)
        assert not re.search(r"[?&]key=.*GEMINI|GEMINI.*[?&]key=", text), path.name     # never in a web address
    assert offenders == []
