"""Release 1 LinkedIn composition traceability and acceptance (Issue #93 / Story #14).

The canonical Release 1 LinkedIn artifact is the Platform Composer ``medium``
body (product-owner decision: 120–220-word target). This module proves,
deterministically and fail-closed, that the artifact the orchestrator is about
to package for LinkedIn is channel-native and traceable:

- it is not the Wix article copied or shortened verbatim (no identical body,
  no shared sentence-length phrase, distinct opening);
- it stays within the accepted Release 1 length tolerance of the 120–220-word
  target contract;
- it passes platform output validation under the correct ``linkedin``
  identity;
- it is recorded in a strict immutable run-scoped composition record carrying
  the exact run/signal identity, the accepted source-article digest, the
  configuration identity and strategy version, the composition-rule version,
  and the canonical LinkedIn body.

There is no LinkedIn revision loop and no generalized editorial engine here
(Story #13 owns article editorial quality; this boundary only proves correct
LinkedIn-specific composition of already accepted content). A LinkedIn
artifact either passes and continues toward packaging, or the run fails
closed — never a silent fallback to another platform body.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.content.output_guard import (
    repeated_cross_platform_phrases,
    validate_platform_output,
)
from src.editorial.platform_composer import (
    LINKEDIN_COMPOSITION_RULES_VERSION,
    _WORD_RANGE,
)
from src.strategy.execution_context import ConfigurationIdentity


LINKEDIN_COMPOSITION_SCHEMA_VERSION = "1.0"

# The accepted Release 1 tolerance around the 120–220-word target: the same
# 0.6×low / 1.4×high band the Platform Composer has always treated as the
# acceptable envelope. Outside it the composition fails closed.
_LINKEDIN_WORDS = _WORD_RANGE["medium"]
LINKEDIN_MIN_WORDS = int(_LINKEDIN_WORDS[0] * 0.6)
LINKEDIN_MAX_WORDS = int(_LINKEDIN_WORDS[1] * 1.4)


class LinkedInCompositionError(RuntimeError):
    """The LinkedIn composition cannot be accepted — the run stops fail-closed."""


class LinkedInCompositionStatus(str, Enum):
    ACCEPTED = "accepted"


class _CompositionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LinkedInCompositionRecord(_CompositionModel):
    """Strict immutable traceability record for one accepted LinkedIn composition."""

    schema_version: str = LINKEDIN_COMPOSITION_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    source_article_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    configuration_identity: ConfigurationIdentity
    strategy_id: str = Field(min_length=1, max_length=200)
    strategy_version: str = Field(min_length=1, max_length=80)
    composition_rules_version: str = Field(min_length=1, max_length=80)
    linkedin_body: str = Field(min_length=1)
    word_count: int = Field(ge=1)
    status: LinkedInCompositionStatus

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != LINKEDIN_COMPOSITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported LinkedIn composition schema_version: {value!r}")
        return value


def article_digest(article_body: str) -> str:
    """Stable current-run identity of the accepted source article."""

    return "sha256:" + hashlib.sha256(article_body.encode("utf-8")).hexdigest()


def _first_sentence(text: str) -> str:
    stripped = text.strip()
    for mark in (". ", "! ", "? ", "\n"):
        index = stripped.find(mark)
        if index > 0:
            return stripped[: index + 1].strip().lower()
    return stripped.lower()


def accept_linkedin_composition(
    *,
    linkedin_body: str,
    article_body: str,
    run_id: str,
    signal_id: str,
    configuration_identity: ConfigurationIdentity,
    strategy_id: str,
    strategy_version: str,
) -> LinkedInCompositionRecord:
    """Deterministic Release 1 LinkedIn channel acceptance.

    Returns the strict traceability record on success; raises
    ``LinkedInCompositionError`` otherwise. Never falls back to another
    platform body and never revises.
    """

    if not isinstance(linkedin_body, str) or not linkedin_body.strip():
        raise LinkedInCompositionError(
            "LinkedIn composition is empty or malformed — nothing acceptable to publish"
        )
    if not isinstance(article_body, str) or not article_body.strip():
        raise LinkedInCompositionError(
            "accepted source article is missing — LinkedIn composition has no lineage"
        )
    body = linkedin_body.strip()
    article = article_body.strip()

    if body == article:
        raise LinkedInCompositionError(
            "LinkedIn body is identical to the Wix article — not a channel-native composition"
        )
    if _first_sentence(body) == _first_sentence(article):
        raise LinkedInCompositionError(
            "LinkedIn opening copies the Wix article opening — not channel-native"
        )
    shared = repeated_cross_platform_phrases({"blog": article, "linkedin": body})
    if shared:
        phrases = "; ".join(item["phrase"][:80] for item in shared[:3])
        raise LinkedInCompositionError(
            f"LinkedIn body copies sentence-length prose from the Wix article: {phrases}"
        )

    word_count = len(body.split())
    if not (LINKEDIN_MIN_WORDS <= word_count <= LINKEDIN_MAX_WORDS):
        raise LinkedInCompositionError(
            f"LinkedIn body is {word_count} words — outside the accepted "
            f"{LINKEDIN_MIN_WORDS}–{LINKEDIN_MAX_WORDS} tolerance of the "
            f"{_LINKEDIN_WORDS[0]}–{_LINKEDIN_WORDS[1]} Release 1 target"
        )

    try:
        validate_platform_output("linkedin", body)
    except ValueError as exc:
        raise LinkedInCompositionError(
            f"LinkedIn platform output validation failed: {exc}"
        ) from exc

    return LinkedInCompositionRecord(
        run_id=run_id,
        signal_id=signal_id,
        source_article_digest=article_digest(article_body),
        configuration_identity=configuration_identity,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        composition_rules_version=LINKEDIN_COMPOSITION_RULES_VERSION,
        linkedin_body=body,
        word_count=word_count,
        status=LinkedInCompositionStatus.ACCEPTED,
    )


def verify_linkedin_composition_record(
    record: LinkedInCompositionRecord,
    *,
    run_id: str,
    configuration_identity: ConfigurationIdentity,
    article_body: str,
) -> None:
    """Fail closed on cross-run, configuration, or source-article drift."""

    if record.run_id != run_id:
        raise LinkedInCompositionError(
            "LinkedIn composition record belongs to a different run: "
            f"record={record.run_id!r} expected={run_id!r}"
        )
    if record.configuration_identity != configuration_identity:
        raise LinkedInCompositionError(
            "LinkedIn composition record configuration identity mismatch"
        )
    if record.source_article_digest != article_digest(article_body):
        raise LinkedInCompositionError(
            "LinkedIn composition record does not match the accepted source article"
        )
