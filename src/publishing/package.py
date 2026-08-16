"""Canonical Release 1 publication packages (Issue #100 / Story #17).

The publication package is the final internal contract between accepted run
evidence and an external publishing adapter: a strict, frozen, run-bound,
channel-specific representation of exactly what Never Blank proposes to send
to Wix or LinkedIn. It is composed only from canonical accepted artifacts —
``generated.json``, ``linkedin_composition.json``, and the run's immutable
visual passport — plus explicit non-secret target identity. Credentials never
enter the package; credential readiness belongs to the Story #17 preflight
(Issue #101).

Packages are NOT persisted as run artifacts (decision recorded on Issue
#100): every content field is reconstructible from existing create-once run
artifacts, and the preflight verdict binds to the deterministic
``package_digest()`` — sha256 over the canonical JSON bytes of the frozen
model.

Cross-run protection is construction-time deterministic. The run-binding
witness is the visual passport's own accepted Story #15 semantics:

* ``reused=False`` — the generated artifact, the passport, and the package
  must all belong to the same run;
* ``reused=True`` — the passport must belong to the publication run and the
  generated artifact must belong to the passport's ``origin_run_id``.

Plus digest equality between the accepted article and every lineage claim,
and exact configuration-identity equality across all inputs. Mixing run A's
article with run B's visual or configuration fails at construction even when
each component is individually valid.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.editorial.linkedin_composition import (
    LinkedInCompositionRecord,
    LinkedInCompositionStatus,
    article_digest,
)
from src.strategy.execution_context import ConfigurationIdentity
from src.visual.contract import LinkedInVisualState, VisualAssetsRecord

PUBLICATION_PACKAGE_SCHEMA_VERSION = "1.0"

_REMOTE_URL = re.compile(r"^https://[^\s]+$")


class PackageFailureCategory(str, Enum):
    """Why a canonical publication package could not be constructed.

    The category carries the *scope* of the failure, which the Story #17
    preflight (Issue #101) needs in order to decide whether one channel is
    isolated or the whole run is blocked. Channel-scoped categories mean the
    channel's own publication payload is unusable while the run's canonical
    evidence stays trustworthy; run-scoped categories mean that evidence is
    itself inconsistent, so no channel may publish.
    """

    TARGET = "target"                    # channel: unusable publication target
    CHANNEL_PACKAGE = "channel_package"  # channel: unusable channel payload
    CONFIGURATION = "configuration"      # run: authoritative configuration drift
    PROVENANCE = "provenance"            # run: cross-run / cross-signal evidence
    LINEAGE = "lineage"                  # run: article/visual/composition lineage

    @property
    def is_run_scoped(self) -> bool:
        return self in _RUN_SCOPED_CATEGORIES


_RUN_SCOPED_CATEGORIES = frozenset(
    {
        PackageFailureCategory.CONFIGURATION,
        PackageFailureCategory.PROVENANCE,
        PackageFailureCategory.LINEAGE,
    }
)


class PublicationPackageError(Exception):
    """A canonical publication package could not be constructed.

    ``category`` classifies the failure so callers never have to infer scope
    from the message text.
    """

    def __init__(
        self,
        message: str,
        category: PackageFailureCategory = PackageFailureCategory.CHANNEL_PACKAGE,
    ) -> None:
        super().__init__(message)
        self.category = category

    @property
    def is_run_scoped(self) -> bool:
        return self.category.is_run_scoped


def canonical_slug(title: str) -> str:
    """Deterministic Wix slug of the accepted headline (single source)."""

    slug = re.sub(r"[^\w\s-]", "", title.lower().strip())
    return re.sub(r"[\s_]+", "-", slug)[:80]


class _PackageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def package_digest(self) -> str:
        """Deterministic identity of this exact package.

        sha256 over canonical JSON bytes (sorted keys, compact separators)
        of the frozen model. The Story #17 preflight (Issue #101) binds its
        preserved per-channel verdict to this digest instead of persisting a
        second copy of the publication content.
        """

        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_identifier(value: str, name: str) -> str:
    if value != value.strip() or any(ch.isspace() for ch in value):
        raise ValueError(f"{name} must be a whitespace-free identifier")
    return value


class WixPublicationTarget(_PackageModel):
    """Non-secret Wix target identity: where the package is intended to go."""

    site_id: str = Field(min_length=1, max_length=200)
    owner_member_id: str = Field(min_length=1, max_length=200)
    category_ids: tuple[str, ...] = Field(default=(), max_length=20)
    tag_ids: tuple[str, ...] = Field(default=(), max_length=50)

    @field_validator("site_id", "owner_member_id")
    @classmethod
    def _identifier(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)

    @field_validator("category_ids", "tag_ids")
    @classmethod
    def _identifier_items(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        for item in value:
            if not item:
                raise ValueError(f"{info.field_name} entries must be non-empty")
            _validate_identifier(item, info.field_name)
        return value


class LinkedInPublicationTarget(_PackageModel):
    """Non-secret LinkedIn target identity (Zernio account reference)."""

    account_id: str = Field(min_length=1, max_length=200)

    @field_validator("account_id")
    @classmethod
    def _identifier(cls, value: str, info) -> str:
        return _validate_identifier(value, info.field_name)


class WixPublicationPackage(_PackageModel):
    """Exactly what Never Blank proposes to publish to Wix for one run."""

    schema_version: str = PUBLICATION_PACKAGE_SCHEMA_VERSION
    channel: Literal["wix"] = "wix"
    run_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    configuration_identity: ConfigurationIdentity
    source_article_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=500)
    slug: str = Field(min_length=1, max_length=80)
    body_markdown: str = Field(min_length=1)
    cover_image_url: str = Field(min_length=1, max_length=2000)
    target: WixPublicationTarget

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != PUBLICATION_PACKAGE_SCHEMA_VERSION:
            raise ValueError(f"unsupported publication package schema_version: {value!r}")
        return value

    @field_validator("cover_image_url")
    @classmethod
    def _remote_cover(cls, value: str) -> str:
        if not _REMOTE_URL.match(value):
            raise ValueError(
                "cover image URL must be a publishable https URL "
                "(a local filesystem path never crosses the publishing boundary)"
            )
        return value

    @model_validator(mode="after")
    def _self_consistent(self) -> "WixPublicationPackage":
        # The Wix body IS the accepted article, so the package is
        # self-proving: its lineage digest must be the digest of its own body.
        if article_digest(self.body_markdown) != self.source_article_digest:
            raise ValueError(
                "source_article_digest does not match the package body — "
                "the Wix package must carry exactly the accepted article"
            )
        if self.slug != canonical_slug(self.title):
            raise ValueError(
                "slug is not the deterministic slug of the package title"
            )
        return self


class LinkedInPublicationPackage(_PackageModel):
    """Exactly what Never Blank proposes to publish to LinkedIn for one run."""

    schema_version: str = PUBLICATION_PACKAGE_SCHEMA_VERSION
    channel: Literal["linkedin"] = "linkedin"
    run_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    configuration_identity: ConfigurationIdentity
    source_article_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    linkedin_body: str = Field(min_length=1)
    linkedin_image_url: Optional[str] = Field(default=None, max_length=2000)
    target: LinkedInPublicationTarget

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != PUBLICATION_PACKAGE_SCHEMA_VERSION:
            raise ValueError(f"unsupported publication package schema_version: {value!r}")
        return value

    @field_validator("linkedin_image_url")
    @classmethod
    def _remote_visual(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _REMOTE_URL.match(value):
            raise ValueError(
                "LinkedIn visual URL must be a publishable https URL "
                "(a local filesystem path never crosses the publishing boundary)"
            )
        return value


def _require(
    condition: bool,
    message: str,
    category: PackageFailureCategory = PackageFailureCategory.CHANNEL_PACKAGE,
) -> None:
    if not condition:
        raise PublicationPackageError(message, category)


def _required_str(
    mapping: Mapping,
    key: str,
    artifact: str,
    category: PackageFailureCategory = PackageFailureCategory.CHANNEL_PACKAGE,
) -> str:
    value = mapping.get(key)
    _require(
        isinstance(value, str) and bool(value.strip()),
        f"{artifact} field {key!r} must be a non-blank string",
        category,
    )
    return value  # type: ignore[return-value]


def _configuration_of(mapping: Mapping, artifact: str) -> ConfigurationIdentity:
    data = mapping.get("configuration_identity")
    _require(
        isinstance(data, dict),
        f"{artifact} carries no configuration identity",
        PackageFailureCategory.CONFIGURATION,
    )
    try:
        return ConfigurationIdentity.model_validate(data)
    except Exception as exc:  # noqa: BLE001 — malformed identity fails closed
        raise PublicationPackageError(
            f"{artifact} configuration identity is invalid",
            PackageFailureCategory.CONFIGURATION,
        ) from exc


def _bind_generated_to_run(
    *,
    run_id: str,
    signal_id: str,
    configuration_identity: ConfigurationIdentity,
    generated: Mapping,
    visual_record: VisualAssetsRecord,
) -> str:
    """Shared construction-time binding for both channels.

    Returns the accepted article body once every run/identity/digest
    relationship between the generated artifact, the visual passport, the
    authoritative configuration, and the publication run has been proven.
    """

    _require(
        bool(run_id and run_id.strip()),
        "publication run_id must be non-empty",
        PackageFailureCategory.PROVENANCE,
    )
    _require(
        bool(signal_id and signal_id.strip()),
        "signal_id must be non-empty",
        PackageFailureCategory.PROVENANCE,
    )
    _require(
        isinstance(generated, Mapping),
        "generated artifact must be a mapping",
        PackageFailureCategory.PROVENANCE,
    )
    _require(
        visual_record.signal_id == signal_id,
        "visual passport belongs to a different signal",
        PackageFailureCategory.PROVENANCE,
    )
    generated_signal = _required_str(
        generated, "signal_id", "generated artifact", PackageFailureCategory.PROVENANCE
    )
    _require(
        generated_signal == signal_id,
        "generated artifact belongs to a different signal",
        PackageFailureCategory.PROVENANCE,
    )
    generated_run = _required_str(
        generated, "run_id", "generated artifact", PackageFailureCategory.PROVENANCE
    )
    _require(
        visual_record.run_id == run_id,
        "visual passport belongs to a different publication run",
        PackageFailureCategory.PROVENANCE,
    )
    if visual_record.reused:
        _require(
            generated_run == visual_record.origin_run_id,
            "cross-run substitution: generated artifact does not belong to "
            "the visual passport's origin run",
            PackageFailureCategory.PROVENANCE,
        )
    else:
        _require(
            generated_run == run_id,
            "cross-run substitution: generated artifact does not belong to "
            "the publication run",
            PackageFailureCategory.PROVENANCE,
        )
    generated_configuration = _configuration_of(generated, "generated artifact")
    _require(
        generated_configuration == configuration_identity,
        "generated artifact configuration does not match the run's "
        "authoritative configuration identity",
        PackageFailureCategory.CONFIGURATION,
    )
    article_body = _required_str(
        generated, "blog_article", "generated artifact", PackageFailureCategory.PROVENANCE
    )
    _require(
        article_digest(article_body) == visual_record.source_article_digest,
        "cross-run substitution: visual passport was not produced from the "
        "accepted article",
        PackageFailureCategory.LINEAGE,
    )
    return article_body


def build_wix_publication_package(
    *,
    run_id: str,
    signal_id: str,
    configuration_identity: ConfigurationIdentity,
    generated: Mapping,
    visual_record: Optional[VisualAssetsRecord],
    target: WixPublicationTarget,
) -> WixPublicationPackage:
    """Build the canonical Wix package from accepted run evidence only."""

    _require(
        isinstance(visual_record, VisualAssetsRecord),
        "the required Wix visual passport is missing",
        PackageFailureCategory.PROVENANCE,
    )
    assert visual_record is not None  # for type-checkers; _require guards above
    article_body = _bind_generated_to_run(
        run_id=run_id,
        signal_id=signal_id,
        configuration_identity=configuration_identity,
        generated=generated,
        visual_record=visual_record,
    )
    cover = visual_record.wix_url
    _require(
        bool(cover),
        "the visual passport carries no required Wix derivative",
        PackageFailureCategory.LINEAGE,
    )
    title = _required_str(
        generated, "headline", "generated artifact", PackageFailureCategory.PROVENANCE
    )
    try:
        return WixPublicationPackage(
            run_id=run_id,
            signal_id=signal_id,
            configuration_identity=configuration_identity,
            source_article_digest=article_digest(article_body),
            title=title,
            slug=canonical_slug(title),
            body_markdown=article_body,
            cover_image_url=cover,  # type: ignore[arg-type]
            target=target,
        )
    except PublicationPackageError:
        raise
    except Exception as exc:  # noqa: BLE001 — strict model rejection fails closed
        raise PublicationPackageError(
            f"Wix publication package is invalid: {exc}"
        ) from exc


def build_linkedin_publication_package(
    *,
    run_id: str,
    signal_id: str,
    configuration_identity: ConfigurationIdentity,
    generated: Mapping,
    linkedin_composition: Mapping,
    visual_record: Optional[VisualAssetsRecord],
    target: LinkedInPublicationTarget,
) -> LinkedInPublicationPackage:
    """Build the canonical LinkedIn package from accepted run evidence only.

    The body comes exclusively from the accepted canonical LinkedIn
    composition record — there is no fallback to ``reading`` or any other
    channel body, and the composition must provably belong to the same
    accepted article and generation run.
    """

    _require(
        isinstance(visual_record, VisualAssetsRecord),
        "the visual passport is missing — LinkedIn visual state cannot be proven",
        PackageFailureCategory.PROVENANCE,
    )
    assert visual_record is not None
    article_body = _bind_generated_to_run(
        run_id=run_id,
        signal_id=signal_id,
        configuration_identity=configuration_identity,
        generated=generated,
        visual_record=visual_record,
    )
    _require(
        isinstance(linkedin_composition, Mapping),
        "linkedin composition artifact must be a mapping",
    )
    try:
        composition = LinkedInCompositionRecord.model_validate(linkedin_composition)
    except Exception as exc:  # noqa: BLE001 — malformed composition fails closed
        raise PublicationPackageError(
            "linkedin composition artifact is invalid"
        ) from exc
    _require(
        composition.status is LinkedInCompositionStatus.ACCEPTED,
        "linkedin composition is not an accepted composition",
    )
    _require(
        composition.signal_id == signal_id,
        "linkedin composition belongs to a different signal",
        PackageFailureCategory.PROVENANCE,
    )
    generated_run = generated["run_id"]
    _require(
        composition.run_id == generated_run,
        "cross-run substitution: linkedin composition does not belong to "
        "the generation run",
        PackageFailureCategory.PROVENANCE,
    )
    _require(
        composition.source_article_digest == article_digest(article_body),
        "cross-run substitution: linkedin composition was not accepted "
        "against the accepted article",
        PackageFailureCategory.LINEAGE,
    )
    _require(
        composition.configuration_identity == configuration_identity,
        "linkedin composition configuration does not match the run's "
        "authoritative configuration identity",
        PackageFailureCategory.CONFIGURATION,
    )
    generated_linkedin = _required_str(
        generated, "linkedin_post", "generated artifact", PackageFailureCategory.PROVENANCE
    )
    _require(
        composition.linkedin_body == generated_linkedin,
        "generated linkedin_post does not match the accepted canonical "
        "LinkedIn composition — no channel-body fallback is permitted",
        PackageFailureCategory.LINEAGE,
    )
    if visual_record.linkedin_visual is LinkedInVisualState.VALID:
        linkedin_image_url = visual_record.linkedin_url
        _require(
            bool(linkedin_image_url),
            "visual passport claims a valid LinkedIn derivative that is absent",
            PackageFailureCategory.LINEAGE,
        )
    else:
        linkedin_image_url = None
    try:
        return LinkedInPublicationPackage(
            run_id=run_id,
            signal_id=signal_id,
            configuration_identity=configuration_identity,
            source_article_digest=article_digest(article_body),
            linkedin_body=composition.linkedin_body,
            linkedin_image_url=linkedin_image_url,
            target=target,
        )
    except PublicationPackageError:
        raise
    except Exception as exc:  # noqa: BLE001 — strict model rejection fails closed
        raise PublicationPackageError(
            f"LinkedIn publication package is invalid: {exc}"
        ) from exc
