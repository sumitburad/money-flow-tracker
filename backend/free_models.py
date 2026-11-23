"""Free OpenRouter models chosen from OpenRouter's own model list.

Why this exists. OpenRouter's "free router" (``openrouter/free``) picks a free model at random. In
the first live runs (22 Nov 2026) it kept picking "thinking" models, for example NVIDIA's Nemotron
family. Those spend their whole answer allowance on hidden thinking and send back a blank reply
(``finish_reason: "length"``), so neither the AI summary nor the headline tags could be used.

What this does. Once per run it reads the list of models this account may use, keeps the free ones,
and puts up to three of them into the request: the first is asked, the others are automatic backups
(OpenRouter's ``models`` list). Only ``:free`` models are ever named, because OpenRouter bills a
backup at its own price and a paid backup would not be free.

Two kinds of model. Models that answer directly come first. A model that lists a ``reasoning``
setting "thinks" before it answers. The first version skipped every one of them, and five live runs
(22 to 23 Nov 2026) showed that every free model on this account lists that setting. So the list was
always empty, the random router did all the work, and the AI summary was written by AI in 1 run of 5.
Now thinking models fill the places that direct ones leave free. The ones that worked in the live
runs are asked first, the ones that kept sending blank answers are never named, and the request asks
them to think briefly (``reasoning: {"effort": "low"}``) and gives them more room.

Nothing in this file can stop a refresh. Any problem means "no choice made": the request goes to the
free router exactly as before, and ``summary()`` says in plain words what happened.

Model facts used, all from OpenRouter's public model list:
* ``pricing`` (both prices zero), ``architecture.output_modalities`` (text only),
* ``supported_parameters`` (a model that lists ``reasoning`` thinks),
* ``context_length`` and ``top_provider.max_completion_tokens`` (room for our prompt and answer),
* the size in the model's name, when it states one (small models fail our answer checks).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from backend.ai_reply import failure_reason

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "ai_models.yaml"
ROUTER = "openrouter/free"
BASE = "https://openrouter.ai"
# This account's own models first (it respects the account's privacy settings), then everyone's.
LIST_PATHS = ("/api/v1/models/user", "/api/v1/models")
LIST_TIMEOUT = (10, 30)
MAX_LIST_BYTES = 8_000_000
MAX_EXTRA_PAGES = 2
EFFORTS = ("minimal", "low", "medium", "high")
OUTCOMES = ("accepted", "rejected", "empty")
MAX_SEEN = 16               # models listed in the health report
MAX_RESULT_MODELS = 8       # models whose results are counted in the health report

DEFAULTS = {
    "enabled": True, "max_models": 3, "min_context_tokens": 32000, "min_answer_tokens": 3500,
    "min_billions": 20.0, "prefer": [], "avoid": [],
    "use_thinking_models": True, "thinking_effort": "low", "thinking_answer_tokens": 6000,
    "prefer_thinking": [],
}
# "27b", "70b", "1t", "1.2b": a size standing alone between separators (so "a3b" and "e2b" do not count).
SIZE = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)([bt])(?![a-z0-9])")
WORDS = {
    "paid": "paid models",
    "not_text": "models that do not answer in text",
    "avoided": "models on the avoid list",
    "no_parameter_list": "models with no list of settings",
    "thinks": "free models that think (skipped on purpose)",
    "short_context": "free models that read too little at once",
    "short_answer": "free models that cannot send a long enough answer",
    "too_small": "free models whose name says they are small",
    "size_unknown": "free models with an unknown size that are not on a preferred list",
}
# The same reasons as one short phrase for the model list on the dashboard.
SHORT = {
    "not_text": "not text-only", "avoided": "on the avoid list", "no_parameter_list": "no settings listed",
    "thinks": "thinks (switched off in the settings)", "short_context": "reads too little at once",
    "short_answer": "answer room too small", "too_small": "too small", "size_unknown": "size unknown",
}


def _why(exc):
    """A short plain reason a list could not be read (never a key: see failure_reason)."""
    if isinstance(exc, requests.Timeout):
        return "no answer within %d seconds" % LIST_TIMEOUT[1]
    if isinstance(exc, json.JSONDecodeError):
        return "the list was not valid JSON"
    return failure_reason(exc, 70)


def load_config(path=None):
    """The settings, with safe defaults for anything missing or wrong. Never raises."""
    try:
        data = yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        section = data.get("openrouter") or {}
        if not isinstance(section, dict):
            section = {}
    except (OSError, ValueError, yaml.YAMLError):
        section = {}
    cfg = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = section.get(key, default)
        if isinstance(default, bool):
            cfg[key] = bool(value) if isinstance(value, bool) else default
        elif isinstance(default, (int, float)):
            usable = isinstance(value, (int, float)) and not isinstance(value, bool)
            cfg[key] = (float(value) if isinstance(default, float) else int(value)) if usable else default
        elif isinstance(default, str):
            text = value.strip().lower() if isinstance(value, str) else ""
            cfg[key] = text if text in EFFORTS else default
        else:
            cfg[key] = [str(x).strip().lower() for x in value if str(x).strip()] \
                if isinstance(value, list) else []
    cfg["max_models"] = min(max(int(cfg["max_models"]), 1), 3)
    cfg["thinking_answer_tokens"] = min(max(int(cfg["thinking_answer_tokens"]), 3500), 16000)
    return cfg


def stated_billions(model_id):
    """The size a model's name states, in billions ("gemma-4-31b-it" -> 31.0), else None."""
    name = str(model_id).split("/", 1)[-1].split(":", 1)[0].lower()
    found = SIZE.search(name)
    if not found:
        return None
    return float(found.group(1)) * (1000.0 if found.group(2) == "t" else 1.0)


def _is_free(model):
    prices = model.get("pricing")
    if not isinstance(prices, dict):
        return False
    try:
        return float(prices["prompt"]) == 0 and float(prices["completion"]) == 0
    except (KeyError, TypeError, ValueError):
        return False


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def preference(model_id, prefer):
    """Position of the first preferred word found in the name; later than any word = len(prefer)."""
    name = str(model_id).lower()
    for position, word in enumerate(prefer):
        if word in name:
            return position
    return len(prefer)


def is_thinker(model):
    """True when OpenRouter lists a reasoning setting for this model, which means it thinks first."""
    params = model.get("supported_parameters")
    return isinstance(params, list) and bool({str(p).lower() for p in params}
                                             & {"reasoning", "include_reasoning"})


def why_not(model, cfg):
    """None if this model can be used, else a short code saying why not (see WORDS)."""
    model_id = str(model.get("id", ""))
    if not model_id or model_id.startswith("openrouter/") or not model_id.endswith(":free") \
            or not _is_free(model):
        return "paid"
    arch = model.get("architecture") if isinstance(model.get("architecture"), dict) else {}
    outputs, inputs = arch.get("output_modalities"), arch.get("input_modalities")
    if (isinstance(outputs, list) and (not outputs or any(str(o).lower() != "text" for o in outputs))) or \
            (isinstance(inputs, list) and "text" not in [str(i).lower() for i in inputs]):
        return "not_text"
    if any(word in model_id.lower() for word in cfg["avoid"]):
        return "avoided"
    if not isinstance(model.get("supported_parameters"), list):
        return "no_parameter_list"
    if is_thinker(model) and not cfg["use_thinking_models"]:
        return "thinks"
    top = model.get("top_provider") if isinstance(model.get("top_provider"), dict) else {}
    context = _number(model.get("context_length")) or _number(top.get("context_length")) or 0
    if context < cfg["min_context_tokens"]:
        return "short_context"
    longest = _number(top.get("max_completion_tokens"))
    if longest is not None and longest < cfg["min_answer_tokens"]:
        return "short_answer"
    size = stated_billions(model_id)
    if size is not None and size < cfg["min_billions"]:
        return "too_small"
    known = cfg["prefer"] + cfg["prefer_thinking"]
    if size is None and preference(model_id, known) >= len(known):
        return "size_unknown"
    return None


def plan(models, cfg):
    """What to use and why. Pure: no network.

    Returns {"chosen": ids in the order to ask, "thinking": the chosen ids that think first,
    "counts": how many models were seen and skipped, "seen": a short line per free model,
    "caps": the longest answer each chosen model allows, when it says}."""
    counts = {"free_seen": 0}
    direct, thinking, skipped = [], [], []
    for model in models:
        if not isinstance(model, dict):
            continue
        reason = why_not(model, cfg)
        if reason == "paid":
            continue
        counts["free_seen"] += 1
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            skipped.append({"id": str(model.get("id"))[:60], "result": SHORT.get(reason, reason)})
            continue
        (thinking if is_thinker(model) else direct).append(model)
    size_of = lambda m: -(stated_billions(m["id"]) or 0.0)
    direct.sort(key=lambda m: (preference(m["id"], cfg["prefer"]), size_of(m), m["id"]))
    thinker_words = cfg["prefer_thinking"] + cfg["prefer"]
    thinking.sort(key=lambda m: (preference(m["id"], thinker_words), size_of(m), m["id"]))
    # Models that answer directly first; thinking models fill the places that are left.
    chosen_rows = direct[:cfg["max_models"]]
    if cfg["use_thinking_models"]:
        chosen_rows += thinking[:max(cfg["max_models"] - len(chosen_rows), 0)]
    chosen = [m["id"] for m in chosen_rows]
    seen = []
    for position, row in enumerate(chosen_rows):
        label = "asked first" if position == 0 else "backup"
        seen.append({"id": row["id"][:60], "result": label + (", thinks briefly" if is_thinker(row) else "")})
    for row in direct + thinking:
        if row["id"] not in chosen:
            seen.append({"id": row["id"][:60], "result": "spare" + (", thinks" if is_thinker(row) else "")})
    seen.extend(skipped)
    counts["usable"] = len(direct) + len(thinking)
    top = lambda m: m.get("top_provider") if isinstance(m.get("top_provider"), dict) else {}
    return {"chosen": chosen, "counts": counts, "seen": seen[:MAX_SEEN],
            "thinking": [m["id"] for m in chosen_rows if is_thinker(m)],
            "caps": {m["id"]: _number(top(m).get("max_completion_tokens")) for m in chosen_rows}}


def pick(models, cfg):
    """(ordered ids to use, counts of what was seen). Pure: no network."""
    result = plan(models, cfg)
    return result["chosen"], result["counts"]


def _rows(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("the model list had an unexpected shape")
    return data


class FreePool:
    """The free models for this run. Read once, shared by every AI step."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.tried = False
        self.ids = []
        self.thinking = []          # the chosen models that think before they answer
        self.think = None           # {"effort", "room"} asked of thinking models, else None
        self.counts = {}
        self.seen = []
        self.note = ""
        self.source = ""
        self.outcomes = {}          # model -> {"accepted", "rejected", "empty"} for this run

    # -- reading the list -------------------------------------------------------------
    def _read(self, getter, path, key):
        headers = {"Authorization": "Bearer " + key, "User-Agent": "global-money-flow-research/2.0"}
        url, rows, pages = BASE + path, [], 0
        while True:
            response = getter(url, headers=headers, timeout=LIST_TIMEOUT)
            response.raise_for_status()
            raw = response.content
            if len(raw) > MAX_LIST_BYTES:
                raise ValueError("the model list was unexpectedly large")
            payload = json.loads(raw)
            rows.extend(_rows(payload))
            following = payload.get("next") if isinstance(payload, dict) else None
            # Follow OpenRouter's own "next page" link only, and only on OpenRouter's own site.
            if isinstance(following, str) and following.startswith("/api/v1/models") \
                    and pages < MAX_EXTRA_PAGES:
                url, pages = BASE + following, pages + 1
                continue
            return rows

    def ensure(self, http, key, cfg=None):
        """Read the list once. Never raises; ``self.note`` says what went wrong, if anything."""
        if self.tried:
            return
        self.tried = True
        cfg = cfg or load_config()
        if not cfg["enabled"]:
            self.note = "Model choice is switched off in config/ai_models.yaml, so the free router was used."
            return
        getter = getattr(http, "get", None)
        if getter is None or not key:
            return
        problems = []
        for path in LIST_PATHS:
            label = "your account's model list" if path.endswith("/user") else "OpenRouter's public model list"
            try:
                result = plan(self._read(getter, path, key), cfg)
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                problems.append("%s could not be read (%s)" % (label, _why(exc)))
                continue
            self.counts, self.seen = result["counts"], result["seen"]
            if result["chosen"]:
                self.ids, self.source = result["chosen"], label
                self.thinking = [i for i in self.ids if i in result["thinking"]]
                if self.thinking:
                    limits = [result["caps"][i] for i in self.thinking if result["caps"].get(i)]
                    self.think = {"effort": cfg["thinking_effort"],
                                  "room": int(min([cfg["thinking_answer_tokens"]] + limits))}
                return
            problems.append("%s had no free model that %s" % (
                label, "could be used" if cfg["use_thinking_models"] else "answers directly"))
            break          # read fine: another list would only name models this account may not use
        self.note = ("No free model could be chosen, so the free router was used: "
                     + "; ".join(problems) + ".")

    # -- using it -------------------------------------------------------------------------
    def choose(self, attempt=0):
        """The chosen models in the order to try. Each retry starts one model further on."""
        if not self.ids:
            return []
        start = int(attempt) % len(self.ids)
        return self.ids[start:] + self.ids[:start]

    def record(self, model, outcome):
        """Count what a model did in this run: accepted, rejected or empty. Never raises."""
        try:
            if outcome not in OUTCOMES or not isinstance(model, str) or not model.strip():
                return
            name = re.sub(r":free$", "", model.strip())[:60]
            row = self.outcomes.get(name)
            if row is None:
                if len(self.outcomes) >= MAX_RESULT_MODELS:
                    return
                row = self.outcomes[name] = {key: 0 for key in OUTCOMES}
            row[outcome] += 1
        except Exception:      # a diagnostic must never stop a refresh
            return

    def active(self):
        """True when there is something to report: the list was tried, or a model answered."""
        return self.tried or bool(self.outcomes)

    def summary(self):
        """Plain facts for the status file (no secrets, nothing long)."""
        out = {}
        if self.tried:
            out["free_pool"] = list(self.ids)
            if self.thinking:
                out["pool_thinking"] = list(self.thinking)
            if self.note:
                out["pool_note"] = self.note[:300]
            if self.counts:
                out["pool_counts"] = {WORDS.get(k, k): v for k, v in self.counts.items()
                                      if k not in ("usable", "free_seen")}
                out["pool_counts"]["free models seen"] = self.counts.get("free_seen", 0)
            if self.seen:
                out["pool_seen"] = [dict(row) for row in self.seen[:MAX_SEEN]]
        if self.outcomes:
            # A list of rows, not a table keyed by name: a model's name is outside text and must never
            # become a field name in the published data (the feed refuses a few field names).
            out["model_results"] = [{"model": name, **row} for name, row in self.outcomes.items()]
        return out


POOL = FreePool()


def _is_openrouter(url):
    """True only when the web address really belongs to openrouter.ai (not a look-alike)."""
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return False
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


def shape_request(body, *, url, model, attempt, http, key, pool=None):
    """For the free router only: name specific free models instead. Otherwise returns ``body`` unchanged.

    When a thinking model is among the named ones, the request also asks for brief thinking and
    allows more room for it. A model named by the person in an environment variable is never replaced."""
    if not _is_openrouter(url) or model != ROUTER:
        return body
    pool = pool or POOL
    pool.ensure(http, key)
    chosen = pool.choose(attempt)
    if not chosen:
        return body
    shaped = {**body, "model": chosen[0]}
    if len(chosen) > 1:
        shaped["models"] = chosen[1:]
    if pool.think and any(name in pool.thinking for name in chosen):
        shaped.setdefault("reasoning", {"effort": pool.think["effort"]})
        shaped["max_tokens"] = max(int(shaped.get("max_tokens") or 0), pool.think["room"])
    return shaped
