"""Issue #172: ordinary tests cannot make billed OpenAI calls.

The guard in ``tests/conftest.py`` strips the OpenAI key variables for every
test not marked ``live_api``. These scenarios prove the four contracts: a
present developer key is invisible to ordinary tests and the real API path
fails closed before any transport; injected fakes work unchanged; the
``live_api`` marker is a working deliberate opt-in; and the guard exists
only inside pytest — plain production execution is untouched.

The end-to-end proofs spawn real ``python -m pytest`` subprocesses with the
key exported, running inner tests gated behind ``NB_GUARD_INNER`` so they
never execute in the outer session. No proof makes a real API call — key
*visibility* is the entire assertion.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import src.utils.llm_client as llm_client


_SENTINEL_KEY = "sk-fake-guard-proof-never-billed"
_INNER_GATE = "NB_GUARD_INNER"


def _run_inner(test_name: str, extra_env: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, _INNER_GATE: "1", **extra_env}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"{__file__}::{test_name}"],
        capture_output=True, text=True, env=env,
    )


# ===========================================================================
# Inner tests — run only inside the subprocess proofs
# ===========================================================================


@pytest.mark.skipif(os.environ.get(_INNER_GATE) != "1", reason="subprocess-only")
def test_inner_ordinary_test_cannot_see_the_key():
    # the runner exported a key; the guard must have stripped it
    for var in ("NB_OPENAI_API_KEY", "OPENAI_API_KEY"):
        assert os.environ.get(var) is None
    # and the real API path fails closed before any transport
    with pytest.raises(EnvironmentError, match="NB_OPENAI_API_KEY"):
        llm_client._get_client()


@pytest.mark.skipif(os.environ.get(_INNER_GATE) != "1", reason="subprocess-only")
@pytest.mark.live_api
def test_inner_live_api_test_sees_the_key_it_was_authorized_for():
    # both authorizations present: the exported key is visible, untouched
    assert os.environ.get("NB_OPENAI_API_KEY") == _SENTINEL_KEY
    # no call is made — visibility is the entire assertion


@pytest.mark.skipif(os.environ.get(_INNER_GATE) != "1", reason="subprocess-only")
@pytest.mark.live_api
def test_inner_marked_test_is_still_blocked():
    # the marker alone is one authorization of two: the run-level
    # authorization is absent or invalid, so the key must be stripped
    assert os.environ.get("NB_OPENAI_API_KEY") is None
    assert os.environ.get("OPENAI_API_KEY") is None
    with pytest.raises(EnvironmentError, match="NB_OPENAI_API_KEY"):
        llm_client._get_client()


# ===========================================================================
# 1. Ordinary test + developer key present → blocked before transport
# ===========================================================================


def test_a_present_developer_key_is_invisible_to_ordinary_tests():
    result = _run_inner(
        "test_inner_ordinary_test_cannot_see_the_key",
        {"NB_OPENAI_API_KEY": _SENTINEL_KEY, "OPENAI_API_KEY": _SENTINEL_KEY},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_this_very_test_runs_stripped():
    # the guard applies to the whole suite, this file included: whatever the
    # developer machine exports, an ordinary test cannot see it
    assert os.environ.get("NB_OPENAI_API_KEY") is None
    assert os.environ.get("OPENAI_API_KEY") is None
    with pytest.raises(EnvironmentError, match="NB_OPENAI_API_KEY"):
        llm_client._get_client()


def test_a_cached_client_cannot_outlive_its_authorization():
    # conftest resets the shared client cache for every ordinary test, so a
    # client cached under live_api can never be silently reused here
    assert llm_client._client is None


# ===========================================================================
# 2. Fakes and test-owned sentinels work unchanged
# ===========================================================================


def test_fake_transports_are_unaffected_by_the_guard():
    class FakeTransport:
        def complete(self, *, instructions: str, request: str) -> str:
            return json.dumps({"eligible": False, "reason": "Documented check."})

    from src.editorial.source_eligibility import judge_source_eligibility
    from src.strategy.business_config import EditorialRole

    role = EditorialRole(
        role_id="guard-proof", intent="i", structure=("s",), forbidden=("f",),
        eligibility_criteria=("Eligible: documented case.",),
    )
    verdict = judge_source_eligibility(
        {"SIGNAL_ID": "sig-guard", "HEADLINE": "h", "CORE_FACT": "f"},
        role, FakeTransport(),
    )
    assert verdict.eligible is False


def test_a_test_may_still_set_its_own_sentinel_key(monkeypatch):
    # the existing suite pattern: fixture strips first, the test then sets
    # its own value and patches the client class — unchanged by the guard
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("NB_OPENAI_API_KEY", "test-key-never-used")
    llm_client._get_client()
    assert captured["api_key"] == "test-key-never-used"


# ===========================================================================
# 3. The live opt-in needs BOTH the marker and the run-level authorization
# ===========================================================================

_AMBIENT = {"NB_OPENAI_API_KEY": _SENTINEL_KEY, "OPENAI_API_KEY": _SENTINEL_KEY}


def test_marker_plus_run_authorization_grants_key_visibility():
    # 2×2 cell: marker YES + run authorization YES → visible
    result = _run_inner(
        "test_inner_live_api_test_sees_the_key_it_was_authorized_for",
        {**_AMBIENT, "NB_ALLOW_LIVE_API_TESTS": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_marker_without_run_authorization_is_blocked():
    # 2×2 cell: marker YES + run authorization NO → blocked
    result = _run_inner("test_inner_marked_test_is_still_blocked", _AMBIENT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_run_authorization_without_marker_is_blocked():
    # 2×2 cell: marker NO + run authorization YES → blocked
    result = _run_inner(
        "test_inner_ordinary_test_cannot_see_the_key",
        {**_AMBIENT, "NB_ALLOW_LIVE_API_TESTS": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_neither_marker_nor_run_authorization_is_blocked():
    # 2×2 cell: marker NO + run authorization NO → blocked
    result = _run_inner("test_inner_ordinary_test_cannot_see_the_key", _AMBIENT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


@pytest.mark.parametrize(
    "value", ["true", "yes", "on", "1 ", " 1", "01", "11", "0", "TRUE", "enable"],
    ids=["true", "yes", "on", "trailing-space", "leading-space", "zero-padded",
         "eleven", "zero", "upper-true", "enable"],
)
def test_run_authorization_rejects_every_non_canonical_value(value):
    # strict: only the exact string "1" authorizes — a marked test under any
    # other value stays blocked, with real-looking credentials exported
    result = _run_inner(
        "test_inner_marked_test_is_still_blocked",
        {**_AMBIENT, "NB_ALLOW_LIVE_API_TESTS": value},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_the_run_authorization_check_is_strict_in_process():
    from tests import conftest as guard

    assert guard._LIVE_OPT_IN_VALUE == "1"
    for value in ("true", "yes", "0", "11", " 1", ""):
        os.environ["NB_ALLOW_LIVE_API_TESTS"] = value
        try:
            assert guard._run_authorizes_live_api() is False
        finally:
            del os.environ["NB_ALLOW_LIVE_API_TESTS"]
    os.environ["NB_ALLOW_LIVE_API_TESTS"] = "1"
    try:
        assert guard._run_authorizes_live_api() is True
    finally:
        del os.environ["NB_ALLOW_LIVE_API_TESTS"]


def test_the_marker_is_registered_not_ad_hoc():
    # an unregistered marker would be a typo-prone convention; the guard
    # registers it so --strict-markers builds reject misspellings
    text = (os.path.dirname(__file__) and open(
        os.path.join(os.path.dirname(__file__), "conftest.py")).read())
    assert 'markers' in text and "live_api" in text


# ===========================================================================
# 4. The guard exists only inside pytest
# ===========================================================================


def test_production_execution_outside_pytest_is_untouched():
    code = (
        "import os\n"
        f"os.environ['NB_OPENAI_API_KEY'] = {_SENTINEL_KEY!r}\n"
        "import src.utils.llm_client as llm_client\n"
        "assert os.environ.get('NB_OPENAI_API_KEY') == "
        f"{_SENTINEL_KEY!r}\n"
        "print('env-intact')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={**os.environ},
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "env-intact" in result.stdout


def test_no_production_module_imports_the_guard():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for base in ("src", "scripts"):
        for dirpath, _, files in os.walk(os.path.join(root, base)):
            for name in files:
                if name.endswith(".py"):
                    text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                    assert "conftest" not in text, os.path.join(dirpath, name)
