"""Never Blank Wednesday Golden product contract (Issue #143).

This module deliberately lives in the Never Blank product namespace.  It
defines the configured editorial movement and the source-selection questions
for this one product stream. It does not define generic editorial-role
identity, assignment persistence, scheduler semantics, or pipeline wiring;
Wednesday reuses those generic capabilities without importing Monday policy.

The source policy remains declarative. The Wednesday workflow carries the
equivalent configured criteria through the generic role-eligibility selector
merged in Issue #142; this module does not implement a second judgment path.
Research, Decision Lens, and configured Golden acceptance remain the later
fail-closed boundaries for evidence and editorial meaning.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "never_blank"
    / "wednesday_golden.yaml"
)


class _ProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldenStageId(str, Enum):
    EVENT = "event"
    OBVIOUS_READING_X = "obvious_reading_x"
    TURN = "turn"
    OVERLOOKED_Y = "overlooked_y"
    PRIMARY_MECHANISM = "primary_mechanism"
    EVIDENCE_FOR_Y = "evidence_for_y"
    BOUNDED_BUSINESS_QUESTION = "bounded_business_question"
    NEVER_BLANK_INSIGHT = "never_blank_insight"
    CLOSE_AND_CTA = "close_and_cta"


GOLDEN_STAGE_ORDER = tuple(GoldenStageId)


class GoldenStage(_ProductModel):
    stage_id: GoldenStageId
    editorial_function: str = Field(min_length=1, max_length=600)


class EditorialProhibition(_ProductModel):
    prohibition_id: str = Field(min_length=1, max_length=100)
    rule: str = Field(min_length=1, max_length=600)


class TitleContract(_ProductModel):
    intent: str = Field(min_length=1, max_length=600)
    required: tuple[str, ...] = Field(min_length=1)
    forbidden: tuple[str, ...] = Field(min_length=1)


class TextShapeContract(_ProductModel):
    central_discoveries: Literal[1]
    primary_mechanisms: Literal[1]
    wix: tuple[str, ...] = Field(min_length=1)
    linkedin: tuple[str, ...] = Field(min_length=1)
    shared_discovery_key: str = Field(min_length=1, max_length=100)


class SourceKind(str, Enum):
    CURRENT_EVENT = "current_business_event"
    BUSINESS_DECISION = "business_decision"
    ACQUISITION = "acquisition"
    STRATEGIC_SHIFT = "strategic_shift"
    HISTORICAL_CASE = "historical_business_case"
    PRODUCT_MARKET_BEHAVIOR = "product_market_behavior"
    CORPORATE_CASE = "credible_corporate_case"
    OTHER_DOCUMENTED_EVENT = "other_documented_event"


class TransferMode(str, Enum):
    BOUNDED_QUESTION = "bounded_business_question"
    SAME_CONTEXT_ONLY = "source_context_only"
    UNIVERSALIZED_OUTCOME = "universalized_external_outcome"


class WednesdaySourcePolicy(_ProductModel):
    allowed_source_kinds: tuple[SourceKind, ...] = Field(min_length=1)
    same_day_required: bool
    large_company_cases_allowed: bool
    require_documented_fact: bool
    require_obvious_reading_x: bool
    require_overlooked_y: bool
    require_evidence_supporting_y: bool
    require_compound_presence_relevance: bool
    required_primary_mechanisms: Literal[1]
    required_transfer_mode: Literal[TransferMode.BOUNDED_QUESTION]

    @model_validator(mode="after")
    def _unique_source_kinds(self) -> Self:
        if len(set(self.allowed_source_kinds)) != len(self.allowed_source_kinds):
            raise ValueError("allowed source kinds must be unique")
        return self


class GoldenReferenceKind(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class GoldenReference(_ProductModel):
    """A reasoning annotation, never prose for the model to imitate."""

    reference_id: str = Field(min_length=1, max_length=120)
    reference_kind: GoldenReferenceKind
    signal_id: str = Field(min_length=1, max_length=120)
    source_url: str = Field(min_length=1, max_length=2000)
    obvious_reading_x: str = Field(min_length=1, max_length=1000)
    overlooked_y: str = Field(min_length=1, max_length=1000)
    primary_mechanism: str = Field(min_length=1, max_length=1000)
    evidence_basis: tuple[str, ...] = Field(min_length=1)
    bounded_business_question: str = Field(min_length=1, max_length=1000)
    usage_rule: Literal["reasoning_reference_only_do_not_imitate_wording"]

    @model_validator(mode="after")
    def _x_and_y_are_distinct(self) -> Self:
        normalize = lambda value: " ".join(value.lower().split())
        if normalize(self.obvious_reading_x) == normalize(self.overlooked_y):
            raise ValueError("obvious reading X and overlooked Y must be distinct")
        return self


class WednesdayGoldenProfile(_ProductModel):
    profile_id: str = Field(min_length=1, max_length=120)
    profile_version: str = Field(min_length=1, max_length=40)
    editorial_role_id: str = Field(min_length=1, max_length=120)
    acceptance_rubric_path: str = Field(min_length=1, max_length=500)
    acceptance_rubric_identity: str = Field(min_length=1, max_length=200)
    cta_id: str = Field(min_length=1, max_length=100)
    website_destination: str = Field(min_length=1, max_length=2000)
    reasoning_movement: tuple[GoldenStage, ...] = Field(min_length=1)
    prohibitions: tuple[EditorialProhibition, ...] = Field(min_length=1)
    title: TitleContract
    text_shape: TextShapeContract
    source_policy: WednesdaySourcePolicy

    @model_validator(mode="after")
    def _coherent_profile(self) -> Self:
        stage_ids = tuple(stage.stage_id for stage in self.reasoning_movement)
        if stage_ids != GOLDEN_STAGE_ORDER:
            raise ValueError(
                "Golden reasoning movement must contain the canonical stages "
                "once and in order"
            )
        prohibition_ids = [item.prohibition_id for item in self.prohibitions]
        if len(set(prohibition_ids)) != len(prohibition_ids):
            raise ValueError("prohibition IDs must be unique")
        return self

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PROFILE_PATH) -> "WednesdayGoldenProfile":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Wednesday Golden profile {path} is not a mapping")
        return cls.model_validate(raw)

    def source_eligibility_rules(self) -> tuple[str, ...]:
        """Render product criteria for the accepted generic selector seam."""

        policy = self.source_policy
        kinds = ", ".join(kind.value for kind in policy.allowed_source_kinds)
        return (
            f"The source is a documented case in one of these classes: {kinds}.",
            "The case contains a recognizable obvious reading X and enough factual "
            "substance to investigate one overlooked Y and exactly one primary mechanism.",
            "The documented material can support Y; surprise or analogy alone is not "
            "eligibility.",
            "The case has a genuine documented connection to Compound Presence; do not "
            "force an unrelated interesting story into the role.",
            "Same-day or breaking-news status is not required; historical cases may qualify.",
            "A credible large-company case may qualify, but its outcome may transfer only "
            "as a bounded question for the configured audience, never as their predicted result.",
        )

    def generation_rules(self, surface: Literal["wix", "linkedin"]) -> tuple[str, ...]:
        """Render deterministic product rules for the existing prompt constructor.

        The canonical entrypoint now carries the corresponding declared role
        through the generic renderer. This product renderer remains useful for
        strict profile tests and for proving equivalence of the configured
        product contract without placing Golden vocabulary in Engine code.
        """

        rules = [
            f"Execute editorial role {self.editorial_role_id}.",
            "Preserve this reasoning movement; headings and literal wording are optional: "
            + " -> ".join(
                f"{stage.stage_id.value}: {stage.editorial_function}"
                for stage in self.reasoning_movement
            ),
            f"Title intent: {self.title.intent}",
        ]
        rules.extend(f"Title requirement: {item}" for item in self.title.required)
        rules.extend(f"Title prohibition: {item}" for item in self.title.forbidden)
        rules.extend(
            f"Editorial prohibition [{item.prohibition_id}]: {item.rule}"
            for item in self.prohibitions
        )
        shape = self.text_shape.wix if surface == "wix" else self.text_shape.linkedin
        rules.extend(f"{surface.upper()} rule: {item}" for item in shape)
        rules.extend(
            (
                f"Both Wix and LinkedIn must preserve central discovery "
                f"{self.text_shape.shared_discovery_key}.",
                f"Use configured CTA {self.cta_id}; close with contextual Never Blank "
                f"philosophy and the configured destination {self.website_destination}.",
            )
        )
        return tuple(rules)


def load_golden_reference(path: Path | str) -> GoldenReference:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Golden reference {path} is not a mapping")
    return GoldenReference.model_validate(raw)
