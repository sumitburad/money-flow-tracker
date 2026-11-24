"""Shared test setup."""
import json
from pathlib import Path

import pytest
import requests

from backend import free_models
from backend.feed_contract import FAMILIES


@pytest.fixture(autouse=True)
def fresh_model_choice():
    """The free-model choice is read once per run and kept; every test starts without one."""
    free_models.POOL.reset()
    yield
    free_models.POOL.reset()


class ModelList:
    """What OpenRouter's model-list request returns, for tests: free, text-only models.

    ``ids`` answer directly; ``thinkers`` list a "reasoning" setting, which means they think."""

    def __init__(self, *ids, thinkers=(), status=200):
        def row(model_id, thinks):
            return {"id": model_id, "context_length": 131072,
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    "supported_parameters": ["max_tokens"] + (["reasoning", "include_reasoning"] if thinks else []),
                    "top_provider": {"context_length": 131072, "max_completion_tokens": 8192}}
        self.status_code = status
        self.content = json.dumps({"data": [row(i, False) for i in ids]
                                   + [row(i, True) for i in thinkers]}).encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code, response=self)


@pytest.fixture
def model_list():
    return ModelList


@pytest.fixture
def published_tree():
    """Writes, into any folder, the files one healthy run leaves for publication.

    Returns the feed it wrote (a dict). ``feed_extra`` adds or replaces top-level feed fields."""

    def build(folder, day="2026-11-23", stamp="2026-11-23T16:10:42+05:30", **feed_extra):
        folder = Path(folder)
        blank = {"state": "not_available", "evidence": "none", "source": None}
        item = {"id": "x", "item": "T", "group": "g", "symbol": "T", "region": "US",
                "currency": "USD", "label": "Neutral/Mixed", "tag": "Steady",
                "agreement": "Weak", "freshness": "current",
                "families": {name: dict(blank) for name in FAMILIES}}
        feed = {"schema_version": "1.0", "usage": "research_only_not_order_authorization",
                "generated_at_utc": "2026-11-23T10:40:42+00:00", "as_of_ist": stamp,
                "run_date_ist": day, "items": [item], "macro": {}}
        feed.update(feed_extra)
        status = {"as_of_ist": stamp, "run_slot": "primary", "status": "degraded"}

        def put(relative, value):
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + "\n" if isinstance(value, dict) else value,
                            encoding="utf-8")

        for relative in ("data/feed/v1/latest.json", "docs/feed/v1/latest.json",
                         "frontend/feed/v1/latest.json", "data/feed/v1/daily/%s.json" % day):
            put(relative, feed)
        for relative in ("docs/status.json", "frontend/status.json", "data/health/%s.json" % day):
            put(relative, status)
        for base in ("data/history/v1", "docs/history/v1", "frontend/history/v1"):
            put(base + "/manifest.json", {"series": 1})
            put(base + "/fred/DGS2.csv", "observation_date,DGS2\n2026-11-12,4.10\n")
        return feed

    return build
