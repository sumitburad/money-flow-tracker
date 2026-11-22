"""Reading a free AI model's answer, and saying plainly why when there is nothing usable.

The executive summary and the headline tagging both talk to the same kind of service, so what
they share lives here once:

* how much room a model is given. The free router on OpenRouter often picks a "thinking" model.
  Its thinking is counted inside the same limit as the visible answer, so a limit that is only a
  little bigger than the answer can be used up before the answer starts: the reply then says
  ``finish_reason: "length"`` and has no text. That was the cause of "AI response missing text";
* how long to wait for it;
* how to read the text out of the reply, and what to say when there is none;
* a short reason for any failure, with no secret in it, for the dashboard's data-quality box.
"""
from __future__ import annotations

import re
from collections import namedtuple

import requests

from backend.net import redact

# Room for the model's thinking AND its answer. The visible JSON is a few hundred words; the
# rest is room to think. (Groq's models run at their lowest thinking effort, so they keep the
# smaller limit each step passes in.)
OPENROUTER_ANSWER_TOKENS = 3500
# Seconds to connect, then to wait for the answer: a thinking model can need a minute.
AI_TIMEOUT = (10, 75)
# What to add on the one retry after an empty reply: ask for the least thinking. Only added on
# the retry, because the first attempt should not depend on every free model accepting it.
THINK_LESS = (("openrouter.ai", {"reasoning": {"effort": "low"}}),)

ModelReply = namedtuple("ModelReply", "text model finish")

_HTTP_MEANING = {
    400: "the model did not accept the request",
    401: "the key was not accepted",
    402: "no credit left",
    403: "the key is not allowed to do this",
    404: "no model was available",
    408: "the provider timed out",
    429: "busy, or the daily free limit is used up",
}


class AIReplyError(ValueError):
    """The model answered, but there was nothing usable to read.

    ``empty`` is True when no text came back at all, or the text was cut off by the length
    limit. That is worth exactly one more try that asks the model to think less."""

    def __init__(self, message, *, empty=False):
        super().__init__(message)
        self.empty = empty


def answer_tokens(url, default):
    """How many tokens the model may use (thinking plus answer) for this provider."""
    return OPENROUTER_ANSWER_TOKENS if "openrouter.ai" in str(url) else default


def think_less_fields(url):
    """Extra request fields that ask for less thinking, or None when the provider has none to add."""
    for host, fields in THINK_LESS:
        if host in str(url):
            return {key: (dict(value) if isinstance(value, dict) else value)
                    for key, value in fields.items()}
    return None


def _short(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:max(0, limit - 3)].rstrip() + "..."


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):       # some providers send the answer as a list of parts
        return "".join(part["text"] for part in content
                       if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def read_reply(body):
    """The text, the model that really answered and why it stopped, from a chat-completion reply.

    Raises ``AIReplyError`` with a plain reason when there is no text to use."""
    if not isinstance(body, dict):
        raise AIReplyError("the provider sent a reply that could not be read")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        problem = body.get("error")
        if isinstance(problem, dict) and isinstance(problem.get("message"), str):
            raise AIReplyError("the provider reported: " + _short(redact(problem["message"]), 90))
        raise AIReplyError("the provider returned no completion")
    choice = choices[0]
    model = body.get("model") if isinstance(body.get("model"), str) else None
    model = _short(redact(model), 60) if model else None
    finish = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = _text_of(message.get("content"))
    who = model or "the model"
    if not text.strip():
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise AIReplyError("%s declined to answer" % who)
        if finish == "length":
            raise AIReplyError("empty reply from %s: it used all its room thinking (finish: length)"
                               % who, empty=True)
        raise AIReplyError("empty reply from %s%s" % (who, " (finish: %s)" % finish if finish else ""),
                           empty=True)
    return ModelReply(text, model, finish)


def reply_from(response):
    """Check an HTTP response from a model and read its answer.

    Raises ``requests.HTTPError`` for an error status, ``AIReplyError`` when there is nothing usable."""
    response.raise_for_status()
    if len(response.content) > 200_000:
        raise AIReplyError("the provider sent an oversized reply")
    try:
        body = response.json()
    except ValueError:
        raise AIReplyError("the provider's reply was not JSON") from None
    return read_reply(body)


def unreadable(reply, problem="is not valid JSON"):
    """The error for a reply whose text could not be read as JSON.

    When the model was stopped by the length limit the JSON was simply cut off, which is worth
    one retry; any other broken text is not."""
    who = reply.model or "the model"
    if reply.finish == "length":
        return AIReplyError("reply from %s was cut off by the length limit" % who, empty=True)
    return AIReplyError("reply from %s %s" % (who, problem))


def failure_reason(exc, limit=140):
    """A short plain reason for a failed AI call. A key can never be in it (it is redacted)."""
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
        if code is None:
            found = re.search(r"\b([45]\d\d)\b", str(exc))
            code = int(found.group(1)) if found else None
        detail = ""
        try:
            error = response.json().get("error")
            detail = error.get("message") if isinstance(error, dict) else error
        except Exception:
            detail = ""
        text = "HTTP %s" % code if code else "HTTP error"
        meaning = _HTTP_MEANING.get(code) or ("provider error" if code and code >= 500 else "")
        if meaning:
            text += " (%s)" % meaning
        if isinstance(detail, str) and detail.strip():
            text += ": " + detail
    elif isinstance(exc, requests.Timeout):
        text = "no answer within %d seconds" % AI_TIMEOUT[1]
    elif isinstance(exc, requests.ConnectionError):
        text = "could not connect"
    elif isinstance(exc, ValueError):
        text = str(exc) or type(exc).__name__
    else:
        text = type(exc).__name__
    return _short(redact(text), limit)
