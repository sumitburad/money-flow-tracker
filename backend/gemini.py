"""Google Gemini as one more free AI for the executive summary and the headline tagger.

Why. The free OpenRouter models are shared by many people and change often, so on some runs none
of them sends a usable answer. A free key from Google AI Studio gives a steadier second source.

How. Google offers an OpenAI-compatible address, so the same kind of request is used. The key is
saved in GitHub as the secret ``GEMINI_API_KEY``. Without it Gemini is simply skipped. The key is sent
in the ``Authorization`` header to ``generativelanguage.googleapis.com`` only (the address is fixed
in this file), never in a web address and never anywhere else.

Which model. ``config/ai_models.yaml`` (section ``gemini``) lists model names in the order to try. The
next name is used only when the one before it fails: a wrong name, or its free daily allowance used
up (every model has its own allowance). ``GEMINI_SUMMARY_MODEL`` and ``GEMINI_CLASSIFIER_MODEL`` can
name one model instead.

What is sent. The same public categories, names and headlines as every other AI step. On the free
plan Google may use what it receives to improve its products, so nothing private is ever put in it.

Nothing in this file can stop a refresh: any problem means the next AI in the list is asked.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "ai_models.yaml"
HOST = "generativelanguage.googleapis.com"
URL = "https://%s/v1beta/openai/chat/completions" % HOST
SECRET = "GEMINI_API_KEY"
# "-latest" follows Google's newest Flash model, so a renamed model does not break the program. The
# other two are fixed names for the same job, tried only if the first one fails.
DEFAULT_MODELS = ("gemini-flash-latest", "gemini-3.5-flash", "gemini-2.5-flash")
MAX_MODELS = 3
# Room for Gemini's brief thinking AND its answer (both count toward one limit).
ANSWER_TOKENS = 4000
# How much Gemini may think. "low" is accepted by every Gemini model that can think.
EFFORT = "low"
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{1,60}")


def is_gemini(url):
    """True only when the web address really belongs to Google's Gemini host (not a look-alike)."""
    try:
        return (urlparse(str(url)).hostname or "").lower() == HOST
    except ValueError:
        return False


def _valid(names):
    clean = []
    for name in names if isinstance(names, (list, tuple)) else []:
        text = str(name).strip().lower()
        if _NAME.fullmatch(text) and text not in clean:
            clean.append(text)
    return clean[:MAX_MODELS]


def load_config(path=None):
    """{"enabled": bool, "models": [names]} with safe defaults for anything missing or wrong."""
    try:
        data = yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        section = data.get("gemini") if isinstance(data, dict) else None
        if not isinstance(section, dict):
            section = {}
    except (OSError, ValueError, yaml.YAMLError):
        section = {}
    enabled = section.get("enabled", True)
    return {"enabled": enabled if isinstance(enabled, bool) else True,
            "models": _valid(section.get("models")) or list(DEFAULT_MODELS)}


def models(override="", path=None):
    """The Gemini model names to try, in order. A name given in the environment replaces the list.

    Returns [] when Gemini is switched off in the settings file."""
    cfg = load_config(path)
    if not cfg["enabled"]:
        return []
    named = _valid([str(override or "")])
    return named or cfg["models"]


def key_refused(exc):
    """True when Google turned the key itself away (HTTP 401 or 403), so another model cannot help."""
    return getattr(getattr(exc, "response", None), "status_code", None) in (401, 403)


def fit_request(body, url):
    """Adjust a chat request for Gemini; any other address gets ``body`` back unchanged.

    * ``response_format`` is left out: the prompt already asks for a single JSON object and the
      answer readers accept JSON wrapped in text or a code fence, so a setting Google might not accept
      for every model cannot cause a failure.
    * ``temperature`` is left out: Google advises keeping the newer models at their own default.
    * ``reasoning_effort`` is set to ``low`` so thinking does not use up the answer's room.
    * Fields that only OpenRouter understands (``models``, ``reasoning``) are dropped.
    """
    if not is_gemini(url):
        return body
    fitted = {key: value for key, value in body.items()
              if key not in ("response_format", "temperature", "models", "reasoning")}
    fitted.setdefault("reasoning_effort", EFFORT)
    return fitted
