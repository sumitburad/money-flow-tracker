"""Shared test setup."""
import json

import pytest
import requests

from backend import free_models


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
