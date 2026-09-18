"""Release 1 editorial acceptance boundary (Issue #89 / Story #13).

Answers one business question about the generated Wix article: is it good
enough that the business should put its name on it? A technically valid
article is not automatically publishable.

Minimal Release 1 lifecycle, deliberately small:

    generated article → editorial acceptance
    → ACCEPT: continue with the original article
    → REJECT: stop immediately (no automatic revision)
    → REVISE: revise the article exactly once → editorial acceptance recheck
        → ACCEPT: continue with the revised article
        → anything else (REVISE/REJECT/malformed/failure): stop.

Maximum automatic revisions: one. There is no open-ended self-revision loop,
no generalized scoring platform, and no rubric registry.

The boundary judges article quality only. It may flag unsupported factual
claims and require their removal or correction, but it never invents
evidence, never changes Decision Lens semantics, and never re-runs Story #12.
Revision operates on the canonical Wix article body alone — it never
regenerates LinkedIn, Instagram, Facebook, Threads, or Telegram content, and
a failed revision is never silently treated as a successful one.

Reviewer and revision providers are narrow injectable transports (the same
pattern as the Issue #59 Decision Lens transport); deterministic tests inject
fakes and never call live LLMs. Raw provider output and exception messages
never cross the boundary — failures carry evaluator-authored bounded detail
only (exception class names, never messages).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol, Self

import json

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.research.evidence import NormalizedResearchArtifact


DEFAULT_RUBRIC_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "prompts"
    / "editorial_acceptance"
    / "never_blank.yaml"
)

_MAX_DETAIL_LENGTH = 500


class _AcceptanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditorialAcceptanceError(RuntimeError):
    """Editorial acceptance cannot produce a trustworthy verdict — fail closed."""


class EditorialReviewTransport(Protocol):
    """Narrow injectable boundary to the editorial reviewer model."""

    def complete(self, *, instructions: str, request: str) -> str: ...


class ArticleRevisionTransport(Protocol):
    """Narrow injectable boundary to the single-article revision model."""

    def complete(self, *, instructions: str, request: str) -> str: ...


class RevisionContext(BaseModel):
    """What the reviser inherits besides the rubric (#254 D10, temporary #253).

    ENGINE mechanics (#240 D12): the reviser rewrites the article that actually
    ships, so it receives the run's editorial role, its configured voice and
    every client lens routed to revision — as data, verbatim. What those texts
    say is the client's; this carries them and says nothing of its own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_rules: str = Field(min_length=1)
    voice: tuple[str, ...] = Field(min_length=1)
    lenses: tuple[str, ...] = ()


class EditorialDisposition(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


class RubricCriterion(_AcceptanceModel):
    criterion_id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)


class EditorialAcceptanceRubric(_AcceptanceModel):
    """Versioned Release 1 editorial acceptance rubric (externalized)."""

    rubric_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1, max_length=20)
    instructions: str = Field(min_length=1)
    revision_instructions: str = Field(min_length=1)

    @property
    def identity(self) -> str:
        return f"{self.rubric_id}/{self.version}"

    @property
    def criterion_ids(self) -> frozenset[str]:
        return frozenset(item.criterion_id for item in self.criteria)

    @model_validator(mode="after")
    def _unique_criteria(self) -> Self:
        ids = [item.criterion_id for item in self.criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("rubric criterion IDs must be unique")
        return self

    @classmethod
    def load(cls, path: Path | str = DEFAULT_RUBRIC_PATH) -> "EditorialAcceptanceRubric":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"rubric artifact {path} is not a mapping")
        return cls.model_validate(data)


class EditorialReview(_AcceptanceModel):
    """One strict typed editorial review verdict."""

    rubric_id: str = Field(min_length=1, max_length=120)
    rubric_version: str = Field(min_length=1, max_length=40)
    disposition: EditorialDisposition
    failed_criterion_ids: tuple[str, ...] = Field(default=(), max_length=20)
    rationale: str = Field(min_length=1, max_length=2000)
    revision_guidance: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _disposition_matches_criteria(self) -> Self:
        if len(set(self.failed_criterion_ids)) != len(self.failed_criterion_ids):
            raise ValueError("failed criterion IDs must be unique")
        if self.disposition is EditorialDisposition.ACCEPT and self.failed_criterion_ids:
            raise ValueError(
                "an ACCEPT verdict cannot carry failed criteria — an article "
                "with failed criteria is not publishable acceptance"
            )
        if (
            self.disposition is not EditorialDisposition.ACCEPT
            and not self.failed_criterion_ids
        ):
            raise ValueError(
                "a non-ACCEPT verdict must name the failed rubric criteria"
            )
        return self


class EditorialAcceptanceOutcome(_AcceptanceModel):
    """Result of the complete Release 1 acceptance lifecycle for one article."""

    accepted: bool
    revised: bool
    final_article_body: str = Field(min_length=1)
    initial_review: EditorialReview
    final_review: EditorialReview | None = None
    audit: dict

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.revised and self.final_review is None:
            raise ValueError("a revised outcome must preserve the final review")
        return self


_ALLOWED_REVIEW_KEYS = frozenset({
    "disposition",
    "failed_criterion_ids",
    "rationale",
    "revision_guidance",
})


def _review_article(
    reviewer: EditorialReviewTransport,
    rubric: EditorialAcceptanceRubric,
    *,
    article_body: str,
    research: NormalizedResearchArtifact,
    run_id: str,
) -> EditorialReview:
    """Run one editorial review; fail closed on any untrustworthy output."""

    request = json.dumps(
        {
            "run_id": run_id,
            "article": article_body,
            "rubric": {
                "rubric_id": rubric.rubric_id,
                "version": rubric.version,
                "criteria": [
                    {"criterion_id": c.criterion_id, "description": c.description}
                    for c in rubric.criteria
                ],
            },
            "accepted_evidence": [
                {"evidence_id": item.evidence_id, "claim": item.claim}
                for item in research.evidence
            ],
            "note": (
                "Judge article quality against the rubric. Factual claims must be "
                "grounded in the accepted evidence above; never invent support."
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        raw = reviewer.complete(instructions=rubric.instructions, request=request)
    except Exception as exc:  # noqa: BLE001 — boundary normalizes transport errors
        raise EditorialAcceptanceError(
            f"editorial reviewer transport failed ({type(exc).__name__})"
        ) from exc

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise EditorialAcceptanceError(
            "editorial reviewer output is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise EditorialAcceptanceError("editorial reviewer output is not a JSON object")
    unknown = sorted(set(data) - _ALLOWED_REVIEW_KEYS)
    if unknown:
        raise EditorialAcceptanceError(
            "editorial reviewer output contains unknown fields: " + ", ".join(unknown)
        )
    unknown_criteria = sorted(
        set(data.get("failed_criterion_ids") or ()) - rubric.criterion_ids
    )
    if unknown_criteria:
        raise EditorialAcceptanceError(
            "editorial reviewer cited criteria outside the rubric: "
            + ", ".join(unknown_criteria)[:_MAX_DETAIL_LENGTH]
        )
    try:
        return EditorialReview(
            rubric_id=rubric.rubric_id,
            rubric_version=rubric.version,
            disposition=data.get("disposition"),
            failed_criterion_ids=tuple(data.get("failed_criterion_ids") or ()),
            rationale=data.get("rationale"),
            revision_guidance=data.get("revision_guidance") or "",
        )
    except ValidationError as exc:
        raise EditorialAcceptanceError(
            "editorial reviewer output does not satisfy the review contract"
        ) from exc


def _revise_article(
    revisor: ArticleRevisionTransport,
    rubric: EditorialAcceptanceRubric,
    *,
    article_body: str,
    review: EditorialReview,
    run_id: str,
    sources_of_record: str | None = None,
    revision_context: RevisionContext | None = None,
) -> str:
    """Perform the single controlled revision of the Wix article body only.

    ``sources_of_record`` (#155) carries the run's actual citable sources so a
    revision addressing one criterion cannot delete the attribution the
    publication gate requires — nor invent a replacement for it.
    """

    failed = [
        {"criterion_id": c.criterion_id, "description": c.description}
        for c in rubric.criteria
        if c.criterion_id in review.failed_criterion_ids
    ]
    payload = {
        "run_id": run_id,
        "article": article_body,
        "failed_criteria": failed,
        "revision_guidance": review.revision_guidance,
        "rationale": review.rationale,
        "note": (
            "Revise this one article to address the failed criteria. Do not "
            "invent facts or evidence. Return only the revised article text."
        ),
    }
    if revision_context is not None:
        payload["editorial_role"] = revision_context.role_rules
        payload["voice"] = list(revision_context.voice)
        payload["note"] += (
            " The editorial_role and voice in this request bind the revision "
            "exactly as they bound the draft."
        )
        if revision_context.lenses:
            payload["client_lenses"] = list(revision_context.lenses)
            payload["note"] += (
                " Follow every client lens in this request; they are the "
                "client's own rules for this revision."
            )
    if sources_of_record:
        payload["sources_of_record"] = sources_of_record
        payload["note"] += (
            " Keep the article's source attribution intact: the sources of "
            "record below are the only ones that may appear, and the article "
            "must still name them after your revision."
        )
    request = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        revised = revisor.complete(
            instructions=rubric.revision_instructions, request=request
        )
    except Exception as exc:  # noqa: BLE001
        raise EditorialAcceptanceError(
            f"article revision transport failed ({type(exc).__name__})"
        ) from exc
    if not isinstance(revised, str) or not revised.strip():
        raise EditorialAcceptanceError(
            "article revision returned no usable article; the original article "
            "is not silently accepted"
        )
    return revised


def run_editorial_acceptance(
    *,
    article_body: str,
    research: NormalizedResearchArtifact,
    run_id: str,
    rubric: EditorialAcceptanceRubric,
    reviewer: EditorialReviewTransport,
    revisor: ArticleRevisionTransport,
    sources_of_record: str | None = None,
    revision_context: RevisionContext | None = None,
) -> EditorialAcceptanceOutcome:
    """Run the complete Release 1 acceptance lifecycle for one generated article.

    Raises ``EditorialAcceptanceError`` for reviewer/revision transport
    failures and malformed output. Returns an outcome with ``accepted=False``
    for honest editorial stops (REJECT, or a revision that still fails
    review); both reviews are preserved whenever a revision occurred.
    """

    initial = _review_article(
        reviewer, rubric, article_body=article_body, research=research, run_id=run_id
    )

    def _audit(final: EditorialReview | None, revised: bool, accepted: bool) -> dict:
        effective = final if final is not None else initial
        return {
            "rubric": rubric.identity,
            "accepted": accepted,
            "revised": revised,
            "final_disposition": effective.disposition.value,
            "initial_review": initial.model_dump(mode="json"),
            "final_review": None if final is None else final.model_dump(mode="json"),
        }

    if initial.disposition is EditorialDisposition.ACCEPT:
        return EditorialAcceptanceOutcome(
            accepted=True, revised=False, final_article_body=article_body,
            initial_review=initial, final_review=None,
            audit=_audit(None, False, True),
        )
    if initial.disposition is EditorialDisposition.REJECT:
        return EditorialAcceptanceOutcome(
            accepted=False, revised=False, final_article_body=article_body,
            initial_review=initial, final_review=None,
            audit=_audit(None, False, False),
        )

    # REVISE: exactly one controlled revision, then exactly one recheck.
    revised_body = _revise_article(
        revisor, rubric, article_body=article_body, review=initial, run_id=run_id,
        sources_of_record=sources_of_record,
        revision_context=revision_context,
    )
    final = _review_article(
        reviewer, rubric, article_body=revised_body, research=research, run_id=run_id
    )
    accepted = final.disposition is EditorialDisposition.ACCEPT
    return EditorialAcceptanceOutcome(
        accepted=accepted,
        revised=True,
        final_article_body=revised_body,
        initial_review=initial,
        final_review=final,
        audit=_audit(final, True, accepted),
    )


class LlmChatEditorialReviewTransport:
    """Production reviewer transport backed by the repository LLM client."""

    def complete(self, *, instructions: str, request: str) -> str:
        from src.utils.llm_client import chat, model_enrich

        return chat(system=instructions, user=request, json_mode=True, model=model_enrich())


class LlmChatArticleRevisionTransport:
    """Production revision transport backed by the repository LLM client."""

    def complete(self, *, instructions: str, request: str) -> str:
        from src.utils.llm_client import chat, model_article

        return chat(system=instructions, user=request, model=model_article())
