"""Fail-closed API prohibition for ordinary tests (#172).

Ordinary unit/integration tests must never be able to make a real billed
OpenAI call merely because the developer's shell happens to export
``NB_OPENAI_API_KEY``. Before this guard, CI was safe only because the test
workflow happened not to pass the key — an accident of configuration, not a
guarantee.

The guard is one autouse fixture. A test may see real OpenAI credentials
only when TWO independent explicit conditions hold together:

1. the test carries ``@pytest.mark.live_api`` — the per-test authorization,
   greppable and reviewable at the test site; and
2. the pytest run carries the run-level authorization
   ``NB_ALLOW_LIVE_API_TESTS=1`` — exactly the string ``"1"``, nothing
   else. ``true``, ``yes``, ``11`` and every other truthy-looking value do
   not authorize anything: an ambiguous authorization is no authorization.

Either condition alone blocks: a marked test in an ordinary run is stripped
like any other test, and an authorized run strips every unmarked test. For
every blocked test the OpenAI key variables are removed and the shared
client cache is cleared, so an accidental real client construction fails
visibly at ``_get_client()`` (``EnvironmentError: NB_OPENAI_API_KEY is not
set``) before any transport — and a client cached by an authorized test can
never be reused past its authorization. Tests that inject fakes, patch the
client, or set their own sentinel key values are unaffected: test-level
setup runs after this fixture.

This module is loaded only by pytest; production execution is untouched.
"""

from __future__ import annotations

import os

import pytest

import src.utils.llm_client as llm_client


#: Every variable that could authenticate a billed OpenAI call. The bare
#: OPENAI_API_KEY is included because the SDK reads it as a default when no
#: explicit key is passed.
_OPENAI_KEY_VARS = ("NB_OPENAI_API_KEY", "OPENAI_API_KEY")

#: Run-level live authorization: exactly this variable, exactly "1".
_LIVE_OPT_IN_VAR = "NB_ALLOW_LIVE_API_TESTS"
_LIVE_OPT_IN_VALUE = "1"


def _run_authorizes_live_api() -> bool:
    """Strict run-level check: only the canonical value authorizes."""
    return os.environ.get(_LIVE_OPT_IN_VAR) == _LIVE_OPT_IN_VALUE


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_api: this test is deliberately allowed to see real OpenAI "
        "credentials and may make billed API calls — but only when the run "
        "itself is also authorized with NB_ALLOW_LIVE_API_TESTS=1. Either "
        "condition alone blocks; ordinary tests always have the key "
        "variables stripped and fail closed at client construction.",
    )


@pytest.fixture(autouse=True)
def _no_billed_openai_calls(request, monkeypatch):
    """Strip OpenAI credentials unless BOTH live authorizations hold."""

    if (
        request.node.get_closest_marker("live_api")
        and _run_authorizes_live_api()
    ):
        # Both independent authorizations present: the environment is left
        # exactly as the runner provided it.
        yield
        return

    for var in _OPENAI_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    # A client cached by an earlier authorized test must never be reusable
    # past its authorization: the cache is cleared for every blocked test.
    # monkeypatch restores the previous value afterwards.
    monkeypatch.setattr(llm_client, "_client", None)
    yield
