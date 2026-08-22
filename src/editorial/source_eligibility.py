"""Is this source case in the class a role is allowed to start from? (#142)

An editorial role may declare eligibility criteria for its source material.
This boundary applies them to one candidate signal and returns a strict typed
verdict — nothing more. It deliberately answers only the source-class
question: whether the evidence is sufficient, whether the mechanism holds,
whether the interpretation is justified, and whether anything may publish all
remain the canonical research, evidence-assessment, Decision Lens and
editorial-acceptance stages' questions.

Generic by construction. The criteria come from the configured role; this
module carries them to the judgment and validates what comes back. It knows
nothing about company sizes, sectors, weekdays or any business's policy, and a
different business's roles bring entirely different criteria through the same
code.

Fail-closed posture: a malformed verdict, a transport failure, or an uncertain
answer never becomes an eligible candidate. The judgment classifies the source
material it is shown; it is instructed never to manufacture facts about the
case, and uncertainty is ineligibility.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.strategy.business_config import EditorialRole


_MAX_REASON = 600

#: The signal fields shown to the judgment — identity and descriptive material
#: only. Scores, routing metadata and pipeline bookkeeping are withheld: the
#: question is what the source case *is*, not how the pipeline rated it.
_SOURCE_FIELDS = (
    "SIGNAL_ID",
    "HEADLINE",
    "CORE_FACT",
    "REAL_COMPANY_EXAMPLE",
    "SOURCE_NAME",
    "SOURCE_URL",
    "SOURCE_DATE",
    "raw_summary",
    "WHY_THIS_CASE_IS_INTERESTING",
    "BUSINESS_RESPONSES_OBSERVED",
    "OUTCOME_IF_KNOWN",
)

_INSTRUCTIONS = """You judge ONE thing: whether the source case shown to you \
belongs to the allowed source class described by the criteria. You do not judge \
whether it would make a good article, whether its evidence is sufficient, or \
what it might teach anyone — later stages own those questions.

Rules:
- Judge only from the material shown. Never manufacture, assume or infer facts \
about the company's size, stage, ownership or history that the material does \
not establish.
- If the material does not establish eligibility, the answer is ineligible. \
Uncertainty is ineligibility.
- The reason must state what the material establishes (or fails to establish), \
in one or two sentences.

Return ONLY one valid JSON object:
{"eligible": true|false, "reason": "string"}
"""


class SourceEligibilityError(RuntimeError):
    """The eligibility judgment could not produce a trustworthy verdict.

    ``scope`` says how far the failure reaches (#170):

    - ``"candidate"`` — this one judgment failed (malformed output, contract
      violation, missing identity). The next candidate is unaffected and a
      caller walking a queue may continue.
    - ``"provider"`` — the model provider refused or could not be reached
      (rate limit, authentication, connection, provider outage). Every
      subsequent call is expected to fail identically, and each attempt makes
      a rate limit worse; a caller walking a queue must stop.

    Either way the judgment failed closed: no scope ever yields a verdict.
    """

    def __init__(self, message: str, *, scope: str = "candidate") -> None:
        super().__init__(message)
        self.scope = scope


#: Provider-wide SDK conditions. A failure of one of these types on one
#: candidate predicts the same failure on every candidate after it.
def _provider_scope(exc: BaseException) -> bool:
    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a hard dependency
        return False
    return isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.AuthenticationError,
            openai.APIConnectionError,  # includes APITimeoutError
            openai.InternalServerError,
        ),
    )


class SourceEligibilityTransport(Protocol):
    """Narrow injectable boundary to the judgment model."""

    def complete(self, *, instructions: str, request: str) -> str: ...


class SourceEligibilityVerdict(BaseModel):
    """Strict typed answer to the source-class question, and only that."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: str = Field(min_length=1, max_length=200)
    role_id: str = Field(min_length=1, max_length=120)
    eligible: bool
    reason: str = Field(min_length=1, max_length=_MAX_REASON)


class LlmChatSourceEligibilityTransport:
    """Production transport backed by the repository LLM client."""

    def complete(self, *, instructions: str, request: str) -> str:
        from src.utils.llm_client import chat, model_enrich

        return chat(
            system=instructions, user=request, json_mode=True, model=model_enrich()
        )


def judge_source_eligibility(
    signal: dict,
    role: EditorialRole,
    transport: SourceEligibilityTransport,
) -> SourceEligibilityVerdict:
    """Apply a role's declared criteria to one candidate signal.

    Raises ``SourceEligibilityError`` when the role declares no criteria (the
    caller has no business asking), and on any transport failure or malformed
    output — never silently converting a failed judgment into a verdict.
    """

    if not role.eligibility_criteria:
        raise SourceEligibilityError(
            f"role {role.role_id!r} declares no eligibility criteria"
        )
    signal_id = str(signal.get("SIGNAL_ID", "") or "").strip()
    if not signal_id:
        raise SourceEligibilityError("candidate signal has no SIGNAL_ID")

    request = json.dumps(
        {
            "eligibility_criteria": list(role.eligibility_criteria),
            "source_case": {
                key: signal[key]
                for key in _SOURCE_FIELDS
                if str(signal.get(key, "") or "").strip()
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        raw = transport.complete(instructions=_INSTRUCTIONS, request=request)
    except Exception as exc:  # noqa: BLE001 — boundary normalizes transport errors
        raise SourceEligibilityError(
            f"eligibility transport failed ({type(exc).__name__})",
            scope="provider" if _provider_scope(exc) else "candidate",
        ) from exc

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SourceEligibilityError("eligibility output is not valid JSON") from exc
    if not isinstance(data, dict):
        raise SourceEligibilityError("eligibility output is not a JSON object")
    unknown = sorted(set(data) - {"eligible", "reason"})
    if unknown:
        raise SourceEligibilityError(
            "eligibility output contains unknown fields: " + ", ".join(unknown)
        )
    if not isinstance(data.get("eligible"), bool):
        raise SourceEligibilityError("eligibility output must state eligible as a boolean")

    try:
        return SourceEligibilityVerdict(
            signal_id=signal_id,
            role_id=role.role_id,
            eligible=data["eligible"],
            reason=str(data.get("reason", "")).strip()[:_MAX_REASON] or "",
        )
    except ValidationError as exc:
        raise SourceEligibilityError(
            "eligibility output does not satisfy the verdict contract"
        ) from exc
