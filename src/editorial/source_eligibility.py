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
from dataclasses import dataclass
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

#: Mechanics only. What a candidate is judged against — the stream's selection
#: requirements — arrives in the request as ``eligibility_criteria``, from the
#: stream's human-readable document where one governs the role (#254 D1/D8).
#: No product meaning belongs in this text: until #254 it framed the question
#: as source class and company size, which was the superseded narrow contract.
_INSTRUCTIONS = """You judge ONE candidate signal against the selection \
requirements in `eligibility_criteria`, and nothing else.

Rules:
- Judge only from the material shown. Never manufacture, assume or infer facts \
the material does not establish.
- A requirement the material does not establish is not satisfied. If any \
requirement is not satisfied, the answer is ineligible.
- The reason must name the requirement that decided the answer and what the \
material establishes, in one or two sentences.

Return ONLY one valid JSON object:
{"eligible": true|false, "reason": "string"}
"""


@dataclass(frozen=True)
class ProviderFailureDiagnostic:
    """Sanitized, normalized account of one provider-scoped failure (#188).

    Built by explicit field extraction only — never from ``str(exc)``, never
    from response headers wholesale, never from request payloads, and never
    from the provider's human-readable ``error.message``: provider prose is
    arbitrary text that can echo secret-shaped material (authentication
    errors quote API-key fragments), so it is not extracted at all. The
    structured fields below are the complete set this record will ever
    carry. Missing fields stay ``None``: absence is the honest answer, and
    extraction must survive SDK-version differences in which attributes
    exist.

    Live run 32607277008 is why this exists: the audit said only
    ``RateLimitError`` while the provider had actually answered
    ``429 insufficient_quota / credit_balance_exhausted`` — exhausted
    credits, not throttling. Two conditions with opposite operator
    responses (wait vs. pay) were indistinguishable in the evidence.
    """

    provider: str
    normalized_reason: str
    http_status: int | None = None
    provider_error_type: str | None = None
    provider_error_code: str | None = None
    request_id: str | None = None
    #: Reserved for a future allowlist/redaction contract. Persisted as
    #: ``None`` in Release 1: no such contract exists, raw provider prose is
    #: not evidence, and the operational wording derives from
    #: ``normalized_reason``. Kept as a typed field so the audit shape is
    #: stable when a contract is ever defined.
    sanitized_message: str | None = None

    def as_audit_dict(self) -> dict:
        """The exact shape persisted into the selection audit artifact."""
        return {
            "provider": self.provider,
            "normalized_reason": self.normalized_reason,
            "http_status": self.http_status,
            "provider_error_type": self.provider_error_type,
            "provider_error_code": self.provider_error_code,
            "request_id": self.request_id,
            "sanitized_message": self.sanitized_message,
        }


#: normalized_reason values. Fixed vocabulary: the audit is evidence, and
#: evidence vocabularies do not drift silently.
PROVIDER_FAILURE_REASONS = (
    "rate_limit",
    "insufficient_quota",
    "authentication",
    "connection",
    "provider_internal",
    "unknown_provider_failure",
)

#: Structured markers that a 429 is exhausted quota/billing, not throttling.
#: Matched against the provider's structured ``error.type``/``error.code``
#: fields only — never against the human-readable message.
_QUOTA_MARKERS = frozenset({"insufficient_quota", "credit_balance_exhausted"})


def _provider_error_fields(exc: BaseException) -> tuple[str | None, str | None]:
    """(type, code) from the structured error body, defensively.

    ``error.message`` is deliberately not read: provider prose is arbitrary
    text and may quote secret-shaped material, so it never enters this
    module's data flow at all.
    """
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None, None

    def _text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    return _text(error.get("type")), _text(error.get("code"))


def _provider_diagnostic(exc: BaseException) -> "ProviderFailureDiagnostic | None":
    """Normalize a provider-scoped SDK exception; None for candidate scope.

    Classification is isinstance-anchored on exactly the #170 provider set,
    then refined by the provider's STRUCTURED type/code where one exists —
    a RateLimitError whose body says ``insufficient_quota`` or
    ``credit_balance_exhausted`` is exhausted quota, not throttling.
    """
    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a hard dependency
        return None

    if not _provider_scope(exc):
        return None

    error_type, error_code = _provider_error_fields(exc)
    if isinstance(exc, openai.RateLimitError):
        if error_type in _QUOTA_MARKERS or error_code in _QUOTA_MARKERS:
            reason = "insufficient_quota"
        else:
            reason = "rate_limit"
    elif isinstance(exc, openai.AuthenticationError):
        reason = "authentication"
    elif isinstance(exc, openai.APIConnectionError):
        reason = "connection"
    elif isinstance(exc, openai.InternalServerError):
        reason = "provider_internal"
    else:  # pragma: no cover - _provider_scope admits only the four above
        # "unknown_provider_failure" is RESERVED: with today's #170 provider
        # set every provider-scoped class maps to a named reason, so this
        # branch is unreachable. It exists so a future provider class added
        # to _provider_scope degrades to a safe named value instead of an
        # invented one. Do not widen the #170 scope to make it reachable.
        reason = "unknown_provider_failure"

    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    return ProviderFailureDiagnostic(
        provider="openai",
        normalized_reason=reason,
        http_status=status if isinstance(status, int) else None,
        provider_error_type=error_type,
        provider_error_code=error_code,
        request_id=request_id if isinstance(request_id, str) else None,
        sanitized_message=None,  # R1: provider prose is never persisted
    )


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

    ``diagnostic`` (#188) carries the sanitized normalized account of a
    provider-scoped failure; ``None`` for candidate scope. Semantics live in
    the typed fields, never encoded into the message string.

    Either way the judgment failed closed: no scope ever yields a verdict.
    """

    def __init__(
        self,
        message: str,
        *,
        scope: str = "candidate",
        diagnostic: "ProviderFailureDiagnostic | None" = None,
    ) -> None:
        super().__init__(message)
        self.scope = scope
        self.diagnostic = diagnostic


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
        diagnostic = _provider_diagnostic(exc)
        raise SourceEligibilityError(
            f"eligibility transport failed ({type(exc).__name__}"
            + (f": {diagnostic.normalized_reason}" if diagnostic else "")
            + ")",
            scope="provider" if diagnostic is not None else "candidate",
            diagnostic=diagnostic,
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
