"""Shared test setup.

The autouse fixture below enforces the invariant that no test makes a real model
call. It is not decoration: wiring analysis into the run pipeline immediately
made the pipeline tests spend real rate limit, and the only symptom was the suite
taking 104 seconds instead of half of one. A test that quietly costs money is
worse than a failing test, because nothing draws your attention to it.

Any test that legitimately needs a client asks for `fake_llm`, which replaces the
factory with a canned response.
"""

from __future__ import annotations

import pytest

from core import llm


@pytest.fixture(autouse=True)
def no_real_model_calls(monkeypatch):
    """Make a real client impossible to obtain by accident."""
    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "A test tried to build a real LLM client. Stub it, or use the "
            "fake_llm fixture. Tests must never make a model call."
        )

    monkeypatch.setattr(llm, "get_client", refuse)
    monkeypatch.setattr(llm, "ClaudeCliClient", refuse)
    monkeypatch.setattr(llm, "AnthropicApiClient", refuse)


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a FakeLLMClient as the result of get_client(), and return it."""
    def _install(text: str = "", data: dict | None = None) -> llm.FakeLLMClient:
        client = llm.FakeLLMClient(text=text, data=data)
        monkeypatch.setattr(llm, "get_client", lambda *a, **k: client)
        return client
    return _install
