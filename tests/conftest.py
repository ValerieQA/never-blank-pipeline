"""Fail-closed API prohibition for ordinary tests (#172).

Ordinary unit/integration tests must never be able to make a real billed
OpenAI call merely because the developer's shell happens to export
``NB_OPENAI_API_KEY``. Before this guard, CI was safe only because the test
workflow happened not to pass the key — an accident of configuration, not a
guarantee.

The guard is one autouse fixture: for every test not explicitly marked
``live_api``, the OpenAI key variables are stripped and the shared client
cache is cleared. With no key, an accidental real client construction fails
visibly at ``_get_client()`` (``EnvironmentError: NB_OPENAI_API_KEY is not
set``) before any transport — and nothing anywhere in the process can
authenticate a billed call. Tests that inject fakes, patch the client, or
set their own sentinel key values are unaffected: test-level setup runs
after this fixture.

Deliberate live tests opt in with ``@pytest.mark.live_api`` — a greppable,
reviewable authorization. This module is loaded only by pytest; production
execution is untouched.
"""

from __future__ import annotations

import pytest

import src.utils.llm_client as llm_client


#: Every variable that could authenticate a billed OpenAI call. The bare
#: OPENAI_API_KEY is included because the SDK reads it as a default when no
#: explicit key is passed.
_OPENAI_KEY_VARS = ("NB_OPENAI_API_KEY", "OPENAI_API_KEY")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_api: this test is deliberately allowed to see real OpenAI "
        "credentials and may make billed API calls. Ordinary tests have the "
        "key variables stripped and fail closed at client construction.",
    )


@pytest.fixture(autouse=True)
def _no_billed_openai_calls(request, monkeypatch):
    """Strip OpenAI credentials for every test that has not opted in."""

    if request.node.get_closest_marker("live_api"):
        # Deliberate opt-in: the environment is left exactly as the runner
        # provided it. The marker is the authorization.
        yield
        return

    for var in _OPENAI_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    # A client cached by an earlier opt-in test must never be reusable past
    # its authorization: the cache is cleared for every ordinary test.
    # monkeypatch restores the previous value afterwards.
    monkeypatch.setattr(llm_client, "_client", None)
    yield
