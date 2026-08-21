"""Issue #170: a provider-wide failure stops the eligibility sweep.

Live run 32440540565 made eight consecutive judgment calls, each refused with
``RateLimitError`` — one provider outage amplified into a burst against the
provider that was refusing it. These scenarios reproduce that shape through
the real selector and prove the circuit breaker: the first provider-scope
failure terminates the sweep, candidate-scope failures still walk the queue,
and every fail-closed exit semantic is unchanged.

The SDK retry cap is proven at the client boundary: one logical request may
no longer become three HTTP attempts by inherited default.
"""

from __future__ import annotations

import json

import httpx
import openai
import pytest

from scripts.streams import select_eligible_signal
from src.editorial.source_eligibility import (
    SourceEligibilityError,
    judge_source_eligibility,
)
from src.strategy.business_config import EditorialRole
from src.utils import llm_client


MONDAY_ROLE = "never-blank-monday-documented-case"
WEDNESDAY_ROLE = "never-blank-wednesday-golden"

CANDIDATES = [
    {
        "SIGNAL_ID": f"sig-queue-{index}",
        "HEADLINE": f"A documented owner-led case number {index}",
        "CORE_FACT": "A small firm documented an operating decision.",
        "REAL_COMPANY_EXAMPLE": "Owner-led firm",
    }
    for index in range(1, 9)
]


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.RateLimitError(
        "Rate limit reached",
        response=httpx.Response(429, request=request),
        body=None,
    )


def _auth_error() -> openai.AuthenticationError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.AuthenticationError(
        "Invalid API key",
        response=httpx.Response(401, request=request),
        body=None,
    )


def _server_error() -> openai.InternalServerError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.InternalServerError(
        "Server error",
        response=httpx.Response(500, request=request),
        body=None,
    )


def _connection_error() -> openai.APIConnectionError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.APIConnectionError(request=request)


class ScriptedTransport:
    """Judgment transport scripted per SIGNAL_ID; records every request."""

    def __init__(self, script: dict) -> None:
        # script[signal_id] is an exception to raise, or (eligible, reason)
        self.script = script
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        signal_id = json.loads(request)["source_case"].get("SIGNAL_ID", "")
        self.requests.append(signal_id)
        action = self.script[signal_id]
        if isinstance(action, BaseException):
            raise action
        eligible, reason = action
        return json.dumps({"eligible": eligible, "reason": reason})


def _select(tmp_path, role, transport, signals=CANDIDATES, max_candidates=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    active = tmp_path / "signals_active.jsonl"
    active.write_text("\n".join(json.dumps(s) for s in signals) + "\n")
    published = tmp_path / "published_signal_ids.txt"
    published.write_text("")
    audit_path = tmp_path / "audit.json"
    argv = [
        "--editorial-role", role,
        "--active-path", str(active),
        "--published-path", str(published),
        "--audit-out", str(audit_path),
    ]
    if max_candidates is not None:
        argv += ["--max-candidates", str(max_candidates)]
    code = select_eligible_signal.main(argv, transport=transport)
    return code, json.loads(audit_path.read_text()), published


# ===========================================================================
# 1. The live failure shape: first 429 ends the sweep
# ===========================================================================


@pytest.mark.parametrize("role", [MONDAY_ROLE, WEDNESDAY_ROLE])
def test_first_provider_rate_limit_stops_the_sweep_for_both_streams(tmp_path, role):
    transport = ScriptedTransport({"sig-queue-1": _rate_limit_error()})

    code, audit, published = _select(tmp_path, role, transport)

    # exactly one model call — candidates 2..8 were never attempted
    assert transport.requests == ["sig-queue-1"]
    # visible infrastructure failure, exact existing exit semantics
    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["outcome"] == "eligibility_failure"
    assert audit["selected_signal_id"] is None
    # the audit is truthful: stopped after 1 of 8, 7 never evaluated
    assert audit["evaluated"] == 1
    assert audit["remaining"] == 7
    assert [d["disposition"] for d in audit["dispositions"]] == [
        "provider_unavailable"
    ]
    assert "RateLimitError" in audit["dispositions"][0]["detail"]
    # nothing consumed
    assert published.read_text() == ""


@pytest.mark.parametrize(
    "exc_factory", [_auth_error, _server_error, _connection_error],
    ids=["authentication", "internal_server", "connection"],
)
def test_every_provider_wide_condition_trips_the_breaker(tmp_path, exc_factory):
    transport = ScriptedTransport({"sig-queue-1": exc_factory()})

    code, audit, _ = _select(tmp_path, MONDAY_ROLE, transport)

    assert transport.requests == ["sig-queue-1"]
    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["dispositions"][0]["disposition"] == "provider_unavailable"


# ===========================================================================
# 2. Candidate-scope failures still walk the queue
# ===========================================================================


def test_a_candidate_scope_failure_continues_to_the_next_candidate(tmp_path):
    transport = ScriptedTransport({
        "sig-queue-1": RuntimeError("judgment transport failed"),
        "sig-queue-2": (True, "Documented owner-led case."),
    })

    code, audit, _ = _select(tmp_path, MONDAY_ROLE, transport)

    # the failure did not stop the sweep, and the eligible candidate won
    assert transport.requests == ["sig-queue-1", "sig-queue-2"]
    assert code == 0
    assert audit["selected_signal_id"] == "sig-queue-2"
    dispositions = {d["signal_id"]: d["disposition"] for d in audit["dispositions"]}
    assert dispositions["sig-queue-1"] == "judgment_failed"
    assert dispositions["sig-queue-2"] == "eligible"


def test_malformed_judgment_output_is_candidate_scope(tmp_path):
    class MalformedTransport:
        def __init__(self):
            self.requests = []

        def complete(self, *, instructions, request):
            self.requests.append(json.loads(request)["source_case"]["SIGNAL_ID"])
            if len(self.requests) == 1:
                return "not json at all"
            return json.dumps({"eligible": True, "reason": "Documented case."})

    transport = MalformedTransport()
    code, audit, _ = _select(tmp_path, MONDAY_ROLE, transport)

    assert len(transport.requests) == 2
    assert code == 0
    assert audit["selected_signal_id"] == "sig-queue-2"


# ===========================================================================
# 3. Fail-closed semantics are exact
# ===========================================================================


def test_provider_failure_can_never_become_a_clean_empty_queue(tmp_path):
    # ineligible, ineligible, provider stop — an all-ineligible reading would
    # be a lie about the five candidates never evaluated
    transport = ScriptedTransport({
        "sig-queue-1": (False, "Not in the allowed class."),
        "sig-queue-2": (False, "Not in the allowed class."),
        "sig-queue-3": _rate_limit_error(),
    })

    code, audit, _ = _select(tmp_path, MONDAY_ROLE, transport)

    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert code != select_eligible_signal.NO_ELIGIBLE
    assert audit["outcome"] == "eligibility_failure"
    assert audit["evaluated"] == 3
    assert audit["remaining"] == 5


def test_provider_stop_on_a_truncated_queue_is_failure_not_truncation(tmp_path):
    # 8 candidates, bound of 3, provider stop on the first: the outcome must
    # be the infrastructure failure, not the softer search_truncated
    transport = ScriptedTransport({"sig-queue-1": _rate_limit_error()})

    code, audit, _ = _select(
        tmp_path, MONDAY_ROLE, transport, max_candidates=3
    )

    assert audit["truncated"] is True
    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["outcome"] == "eligibility_failure"


def test_existing_exit_semantics_are_unchanged(tmp_path):
    # 0: selected
    ok = ScriptedTransport({"sig-queue-1": (True, "Documented case.")})
    code, _, _ = _select(tmp_path / "a", MONDAY_ROLE, ok)
    assert code == 0
    # 3: complete all-ineligible search
    all_no = ScriptedTransport({
        s["SIGNAL_ID"]: (False, "Outside the class.") for s in CANDIDATES
    })
    code, audit, _ = _select(tmp_path / "b", MONDAY_ROLE, all_no)
    assert code == select_eligible_signal.NO_ELIGIBLE
    assert audit["outcome"] == "no_eligible_complete"
    # 5: truncated search with no failures
    code, audit, _ = _select(
        tmp_path / "c", MONDAY_ROLE,
        ScriptedTransport({
            s["SIGNAL_ID"]: (False, "Outside the class.") for s in CANDIDATES[:3]
        }),
        max_candidates=3,
    )
    assert code == select_eligible_signal.SEARCH_TRUNCATED
    assert audit["outcome"] == "search_truncated"


# ===========================================================================
# 4. Scope classification at the judgment boundary
# ===========================================================================


def _role_with_criteria() -> EditorialRole:
    return EditorialRole(
        role_id="role-under-test", intent="i", structure=("s",),
        forbidden=("f",), eligibility_criteria=("Eligible: documented case.",),
    )


class RaisingTransport:
    def __init__(self, exc):
        self.exc = exc

    def complete(self, *, instructions, request):
        raise self.exc


@pytest.mark.parametrize(
    "exc_factory", [_rate_limit_error, _auth_error, _server_error, _connection_error],
    ids=["rate_limit", "authentication", "internal_server", "connection"],
)
def test_provider_exceptions_classify_as_provider_scope(exc_factory):
    with pytest.raises(SourceEligibilityError) as info:
        judge_source_eligibility(
            CANDIDATES[0], _role_with_criteria(), RaisingTransport(exc_factory())
        )
    assert info.value.scope == "provider"


def test_ordinary_transport_failures_stay_candidate_scope():
    with pytest.raises(SourceEligibilityError) as info:
        judge_source_eligibility(
            CANDIDATES[0], _role_with_criteria(),
            RaisingTransport(RuntimeError("judgment transport failed")),
        )
    assert info.value.scope == "candidate"


def test_contract_violations_stay_candidate_scope():
    class WrongShape:
        def complete(self, *, instructions, request):
            return json.dumps({"eligible": True, "reason": "ok", "extra": 1})

    with pytest.raises(SourceEligibilityError) as info:
        judge_source_eligibility(CANDIDATES[0], _role_with_criteria(), WrongShape())
    assert info.value.scope == "candidate"


# ===========================================================================
# 5. The SDK retry cap is explicit, not inherited
# ===========================================================================


def test_llm_client_caps_sdk_retries_by_default(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setenv("NB_OPENAI_API_KEY", "test-key-never-used")
    monkeypatch.delenv("NB_OPENAI_MAX_RETRIES", raising=False)

    llm_client._get_client()

    assert captured["max_retries"] == 1
    monkeypatch.setattr(llm_client, "_client", None)


def test_retry_cap_is_configurable_and_deterministic(monkeypatch):
    monkeypatch.setenv("NB_OPENAI_MAX_RETRIES", "0")
    assert llm_client.max_retries() == 0
    monkeypatch.delenv("NB_OPENAI_MAX_RETRIES", raising=False)
    assert llm_client.max_retries() == 1


def test_image_pipeline_clients_share_the_same_cap():
    from pathlib import Path

    source = Path("src/publishing/image_pipeline.py").read_text()
    constructions = source.count("OpenAI(")
    capped = source.count("max_retries=max_retries()")
    assert constructions == capped == 2
