"""Fail-closed publication preflight (Issue #101 / Story #17).

Immediately before any external Wix/LinkedIn side effect, Never Blank must
prove: *this exact frozen package, for this exact run and target, passed all
applicable Release 1 checks and is allowed to cross the external boundary.*
If a deterministic ALLOW does not exist for that exact package, the publisher
is never called.

Release 1 semantics:

* **run-level BLOCK** — a shared integrity failure (provenance, authoritative
  configuration, freshness/strategy lineage, an override attempt on a
  blocking shared condition) blocks every channel; no publisher is
  constructed at all;
* **per-channel BLOCK** — a channel-scoped failure (that channel's package,
  target, or credential readiness) blocks only that channel; a valid channel
  still publishes when no run-level failure exists.

**Override**: Release 1 has no trustworthy authorization identity, so an
override never converts BLOCK into ALLOW. The verdict records the truthful
state (``none`` / ``attempted_rejected``) and never claims an authorized
human actor — there is deliberately no ``authorized_by`` field, and no
identity is inferred from Sheets access, git configuration, environment,
CLI flags, or the process user.

**Trust boundary**: credential *presence* is recorded as a boolean. No key,
token, raw provider object, or adapter response is ever evaluated into or
persisted by this contract.

This module owns no business rules of its own: provenance comes from
``verify_run_provenance`` (#98), package validity from the strict #100
models, freshness/strategy lineage from the checks the canonical entrypoint
already performs. Preflight composes their results into one preserved
per-channel verdict bound to the exact package digest.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.artifacts.provenance import ProvenanceError, verify_run_provenance
from src.publishing.package import (
    LinkedInPublicationPackage,
    PackageFailureCategory,
    LinkedInPublicationTarget,
    WixPublicationPackage,
    WixPublicationTarget,
)
from src.strategy.execution_context import ConfigurationIdentity

PREFLIGHT_SCHEMA_VERSION = "1.0"

#: Environment variable carrying each channel's credential secret. Only the
#: PRESENCE of a value is ever read here; the value itself is read solely by
#: the adapter when it executes an already-ALLOWed call.
CHANNEL_CREDENTIAL_ENV = {
    "wix": "NB_WIX_API_KEY",
    "linkedin": "NB_ZERNIO_API_KEY",
}


class PreflightDisposition(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class OverrideState(str, Enum):
    """Truthful Release 1 override semantics — never an authorization claim."""

    NONE = "none"
    ATTEMPTED_REJECTED = "attempted_rejected"


class BlockingReason(str, Enum):
    """Machine-readable blocking reasons."""

    PROVENANCE_FAILED = "provenance_failed"
    CONFIGURATION_MISMATCH = "configuration_mismatch"
    FRESHNESS_FAILED = "freshness_failed"
    READINESS_FAILED = "readiness_failed"
    RUN_EVIDENCE_INCONSISTENT = "run_evidence_inconsistent"
    OVERRIDE_ATTEMPTED_ON_BLOCKING_CONDITION = (
        "override_attempted_on_blocking_condition"
    )
    RUN_BLOCKED = "run_blocked"
    PACKAGE_INVALID = "package_invalid"
    PACKAGE_DIGEST_MISMATCH = "package_digest_mismatch"
    TARGET_MISSING = "target_missing"
    CREDENTIAL_MISSING = "credential_missing"


class _PreflightModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceVerdict(_PreflightModel):
    verified: bool
    run_kind: Optional[str] = None
    stopped_after: Optional[str] = None
    failure_reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _truthful(self) -> "ProvenanceVerdict":
        if self.verified and self.failure_reason is not None:
            raise ValueError("a verified provenance result carries no failure reason")
        if not self.verified and not self.failure_reason:
            raise ValueError("a failed provenance result must state its reason")
        return self


class FreshnessVerdict(_PreflightModel):
    """Existing Release 1 strategy-lineage rules only — no new TTL."""

    verified: bool
    rules: tuple[str, ...] = Field(default=(), max_length=10)
    failure_reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _truthful(self) -> "FreshnessVerdict":
        if self.verified and self.failure_reason is not None:
            raise ValueError("a verified freshness result carries no failure reason")
        if not self.verified and not self.failure_reason:
            raise ValueError("a failed freshness result must state its reason")
        return self


class ReadinessVerdict(_PreflightModel):
    """The existing publication-readiness rule, evaluated as a shared check.

    The rule itself is unchanged (``ResearchContext.article_ready`` plus the
    signal's source-premise state); Issue #101 only moves its final
    publication-authorization decision into the auditable boundary, so a
    readiness stop is preserved evidence instead of an undocumented
    pre-preflight return.
    """

    verified: bool
    failure_reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _truthful(self) -> "ReadinessVerdict":
        if self.verified and self.failure_reason is not None:
            raise ValueError("a verified readiness result carries no failure reason")
        if not self.verified and not self.failure_reason:
            raise ValueError("a failed readiness result must state its reason")
        return self


class ChannelPackageOutcome:
    """Per-channel result of canonical package construction.

    Channels are built independently so that a channel-local package or
    target failure becomes a typed channel BLOCK instead of collapsing the
    whole run. A failed channel carries no package and therefore no digest —
    a digest is never fabricated for a package that does not exist.

    A failure also carries the #100 builder's typed
    :class:`~src.publishing.package.PackageFailureCategory`, because the same
    builders enforce two different classes of invariant: the channel's own
    payload/target validity, and shared run-integrity (configuration,
    cross-run/cross-signal substitution, article/visual/composition lineage).
    Only the first class may isolate one channel; the second means the run's
    canonical evidence is inconsistent, so no channel may publish. The scope
    comes from the category, never from matching message text.
    """

    __slots__ = ("channel", "package", "failure_reason", "failure_category")

    def __init__(
        self,
        channel: str,
        *,
        package=None,
        failure_reason: Optional[str] = None,
        failure_category: Optional[PackageFailureCategory] = None,
    ) -> None:
        if (package is None) == (failure_reason is None):
            raise ValueError(
                "a channel outcome is either a valid package or a typed failure"
            )
        if failure_reason is not None and failure_category is None:
            raise ValueError("a channel failure must carry its typed category")
        self.channel = channel
        self.package = package
        self.failure_reason = failure_reason
        self.failure_category = failure_category

    @property
    def failure_is_run_scoped(self) -> bool:
        return (
            self.failure_category is not None
            and self.failure_category.is_run_scoped
        )

    @classmethod
    def valid(cls, channel: str, package) -> "ChannelPackageOutcome":
        return cls(channel, package=package)

    @classmethod
    def failed(
        cls,
        channel: str,
        reason: str,
        *,
        category: PackageFailureCategory = PackageFailureCategory.CHANNEL_PACKAGE,
    ) -> "ChannelPackageOutcome":
        return cls(channel, failure_reason=reason, failure_category=category)


class ChannelPreflightVerdict(_PreflightModel):
    """The authorization record of one channel's exact publication package."""

    channel: str = Field(min_length=1, max_length=40)
    # Absent only for the explicit state "the canonical package could not be
    # constructed" — a digest is never fabricated for a package that does not
    # exist, and an ALLOW always carries a real one.
    package_digest: Optional[str] = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    target: Optional[Union[WixPublicationTarget, LinkedInPublicationTarget]] = None
    package_failure_reason: Optional[str] = Field(default=None, max_length=500)
    package_valid: bool
    credential_ready: bool
    disposition: PreflightDisposition
    blocking_reasons: tuple[BlockingReason, ...] = Field(default=(), max_length=10)

    @field_validator("channel")
    @classmethod
    def _release1_channel(cls, value: str) -> str:
        if value not in CHANNEL_CREDENTIAL_ENV:
            raise ValueError(f"unsupported Release 1 publication channel: {value!r}")
        return value

    @model_validator(mode="after")
    def _disposition_matches_reasons(self) -> "ChannelPreflightVerdict":
        if self.disposition is PreflightDisposition.ALLOW:
            if self.blocking_reasons:
                raise ValueError("an ALLOW verdict cannot carry blocking reasons")
            if not (self.package_valid and self.credential_ready):
                raise ValueError(
                    "an ALLOW verdict requires a valid package and a ready credential"
                )
            if self.package_digest is None or self.target is None:
                raise ValueError(
                    "an ALLOW verdict requires the digest and target of a real "
                    "canonical package"
                )
        elif not self.blocking_reasons:
            raise ValueError("a BLOCK verdict must state at least one blocking reason")
        if self.package_valid and self.package_failure_reason is not None:
            raise ValueError("a valid package carries no construction failure reason")
        if not self.package_valid and self.package_digest is not None:
            raise ValueError(
                "a package that failed validation cannot present a package digest"
            )
        return self


class PreflightResult(_PreflightModel):
    """Immutable per-run record of what was authorized to cross the boundary."""

    schema_version: str = PREFLIGHT_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    configuration_identity: ConfigurationIdentity
    evaluated_at: datetime
    override_state: OverrideState
    provenance: ProvenanceVerdict
    readiness: ReadinessVerdict
    freshness: FreshnessVerdict
    configuration_consistent: bool
    run_disposition: PreflightDisposition
    run_blocking_reasons: tuple[BlockingReason, ...] = Field(default=(), max_length=10)
    channels: tuple[ChannelPreflightVerdict, ...] = Field(min_length=1, max_length=2)

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != PREFLIGHT_SCHEMA_VERSION:
            raise ValueError(f"unsupported preflight schema_version: {value!r}")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "PreflightResult":
        channels = [item.channel for item in self.channels]
        if len(set(channels)) != len(channels):
            raise ValueError("preflight channels must be unique")
        if self.run_disposition is PreflightDisposition.BLOCK:
            if not self.run_blocking_reasons:
                raise ValueError("a run-level BLOCK must state its reasons")
            if any(
                item.disposition is PreflightDisposition.ALLOW for item in self.channels
            ):
                raise ValueError(
                    "a run-level BLOCK cannot leave any channel allowed to publish"
                )
        elif self.run_blocking_reasons:
            raise ValueError("run blocking reasons require a run-level BLOCK")
        return self

    def allowed_channels(self) -> tuple[str, ...]:
        return tuple(
            item.channel
            for item in self.channels
            if item.disposition is PreflightDisposition.ALLOW
        )

    def verdict_for(self, channel: str) -> Optional[ChannelPreflightVerdict]:
        for item in self.channels:
            if item.channel == channel:
                return item
        return None


def _credential_ready(channel: str) -> bool:
    """Presence only — the value is never read, logged, or persisted here."""

    return bool(os.getenv(CHANNEL_CREDENTIAL_ENV[channel], "").strip())


def evaluate_publication_preflight(
    *,
    packages_dir: Path,
    run_id: str,
    signal_id: str,
    configuration_identity: ConfigurationIdentity,
    channel_outcomes: "Sequence[ChannelPackageOutcome]",
    override_attempted: bool,
    readiness: ReadinessVerdict,
    freshness: FreshnessVerdict,
    now: Optional[datetime] = None,
) -> PreflightResult:
    """Evaluate the fail-closed publication preflight for one run.

    ``channel_outcomes`` carries each channel's independent construction
    result: either the frozen canonical package that will be handed to that
    publisher on ALLOW — its digest is computed from that exact object and
    recorded here — or a typed construction failure, which becomes a
    channel-scoped BLOCK rather than a whole-run stop.

    This is the single publication-authorization boundary: shared readiness,
    provenance, configuration, freshness and override state are all evaluated
    here, so every publication decision inside Story #17's authorization model
    is explained by the preserved verdict.
    """

    run_reasons: list[BlockingReason] = []

    # ── shared: provenance (Story #16 verifier, never reimplemented) ─────────
    try:
        report = verify_run_provenance(Path(packages_dir), signal_id, run_id)
        provenance = ProvenanceVerdict(
            verified=True,
            run_kind=report.run_kind,
            stopped_after=report.stopped_after,
        )
    except (ProvenanceError, FileNotFoundError, ValueError, OSError) as exc:
        provenance = ProvenanceVerdict(
            verified=False, failure_reason=f"{type(exc).__name__}: {exc}"[:500]
        )
        run_reasons.append(BlockingReason.PROVENANCE_FAILED)

    # ── shared: publication readiness (existing rule, now auditable) ─────────
    if not readiness.verified:
        run_reasons.append(BlockingReason.READINESS_FAILED)

    # ── shared: authoritative configuration identity ─────────────────────────
    packages = [
        outcome.package for outcome in channel_outcomes if outcome.package is not None
    ]
    configuration_consistent = all(
        package.configuration_identity == configuration_identity
        for package in packages
    )
    if not configuration_consistent:
        run_reasons.append(BlockingReason.CONFIGURATION_MISMATCH)

    # ── shared: existing freshness/strategy lineage result ───────────────────
    if not freshness.verified:
        run_reasons.append(BlockingReason.FRESHNESS_FAILED)

    # ── shared: run identity of the packages themselves ──────────────────────
    if any(package.run_id != run_id for package in packages):
        run_reasons.append(BlockingReason.RUN_BLOCKED)

    # ── shared: run-scoped construction failures ─────────────────────────────
    # A builder failure that proves the run's canonical evidence is
    # inconsistent (authoritative configuration drift, cross-run/cross-signal
    # substitution, article/visual/composition lineage corruption) is never
    # downgraded to a single-channel BLOCK: the whole run stops.
    for outcome in channel_outcomes:
        if not outcome.failure_is_run_scoped:
            continue
        if outcome.failure_category is PackageFailureCategory.CONFIGURATION:
            run_reasons.append(BlockingReason.CONFIGURATION_MISMATCH)
        else:
            run_reasons.append(BlockingReason.RUN_EVIDENCE_INCONSISTENT)

    # ── override: never converts BLOCK into ALLOW (Release 1 decision) ───────
    override_state = OverrideState.NONE
    if override_attempted:
        override_state = OverrideState.ATTEMPTED_REJECTED
        if run_reasons:
            run_reasons.append(
                BlockingReason.OVERRIDE_ATTEMPTED_ON_BLOCKING_CONDITION
            )

    run_blocked = bool(run_reasons)

    # ── per-channel verdicts ─────────────────────────────────────────────────
    channels: list[ChannelPreflightVerdict] = []
    for outcome in channel_outcomes:
        channel_reasons: list[BlockingReason] = []
        package = outcome.package
        if package is None:
            # The canonical package could not be constructed: an explicit,
            # fail-closed channel state carrying no digest and no target.
            package_valid = False
            if outcome.failure_category is PackageFailureCategory.TARGET:
                channel_reasons.append(BlockingReason.TARGET_MISSING)
            elif outcome.failure_is_run_scoped:
                # The channel is blocked because the run's evidence is
                # inconsistent, not because its own payload was unusable.
                channel_reasons.append(BlockingReason.RUN_EVIDENCE_INCONSISTENT)
            else:
                channel_reasons.append(BlockingReason.PACKAGE_INVALID)
            digest = None
            target = None
        else:
            package_valid = _target_is_identified(package)
            if not package_valid:
                channel_reasons.append(BlockingReason.TARGET_MISSING)
            digest = package.package_digest() if package_valid else None
            target = package.target if package_valid else None
        credential_ready = _credential_ready(outcome.channel)
        if not credential_ready:
            channel_reasons.append(BlockingReason.CREDENTIAL_MISSING)
        if run_blocked:
            channel_reasons.append(BlockingReason.RUN_BLOCKED)
        disposition = (
            PreflightDisposition.BLOCK
            if channel_reasons
            else PreflightDisposition.ALLOW
        )
        channels.append(
            ChannelPreflightVerdict(
                channel=outcome.channel,
                package_digest=digest,
                target=target,
                package_failure_reason=(
                    outcome.failure_reason[:500] if outcome.failure_reason else None
                ),
                package_valid=package_valid,
                credential_ready=credential_ready,
                disposition=disposition,
                blocking_reasons=tuple(dict.fromkeys(channel_reasons)),
            )
        )

    return PreflightResult(
        run_id=run_id,
        signal_id=signal_id,
        configuration_identity=configuration_identity,
        evaluated_at=now or datetime.now(timezone.utc),
        override_state=override_state,
        provenance=provenance,
        readiness=readiness,
        freshness=freshness,
        configuration_consistent=configuration_consistent,
        run_disposition=(
            PreflightDisposition.BLOCK if run_blocked else PreflightDisposition.ALLOW
        ),
        run_blocking_reasons=tuple(dict.fromkeys(run_reasons)),
        channels=tuple(channels),
    )


def _target_is_identified(
    package: Union[WixPublicationPackage, LinkedInPublicationPackage]
) -> bool:
    """The target lives in the package (#100) and is never re-read from env."""

    target = package.target
    if isinstance(target, WixPublicationTarget):
        return bool(target.site_id and target.owner_member_id)
    return bool(target.account_id)
