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
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.artifacts.provenance import ProvenanceError, verify_run_provenance
from src.publishing.package import (
    LinkedInPublicationPackage,
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


class ChannelPreflightVerdict(_PreflightModel):
    """The authorization record of one channel's exact publication package."""

    channel: str = Field(min_length=1, max_length=40)
    package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target: Union[WixPublicationTarget, LinkedInPublicationTarget]
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
        elif not self.blocking_reasons:
            raise ValueError("a BLOCK verdict must state at least one blocking reason")
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
    wix_package: WixPublicationPackage,
    linkedin_package: LinkedInPublicationPackage,
    override_attempted: bool,
    freshness: FreshnessVerdict,
    now: Optional[datetime] = None,
) -> PreflightResult:
    """Evaluate the fail-closed publication preflight for one run.

    The packages passed here are the exact frozen objects that will be handed
    to the publishers on ALLOW: their digests are computed from these objects
    and recorded in the verdict, so the preserved authorization identifies the
    exact external side effect.
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

    # ── shared: authoritative configuration identity ─────────────────────────
    configuration_consistent = (
        wix_package.configuration_identity == configuration_identity
        and linkedin_package.configuration_identity == configuration_identity
    )
    if not configuration_consistent:
        run_reasons.append(BlockingReason.CONFIGURATION_MISMATCH)

    # ── shared: existing freshness/strategy lineage result ───────────────────
    if not freshness.verified:
        run_reasons.append(BlockingReason.FRESHNESS_FAILED)

    # ── shared: run identity of the packages themselves ──────────────────────
    if wix_package.run_id != run_id or linkedin_package.run_id != run_id:
        run_reasons.append(BlockingReason.RUN_BLOCKED)

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
    for channel, package in (("wix", wix_package), ("linkedin", linkedin_package)):
        channel_reasons: list[BlockingReason] = []
        # The package exists and is strict-valid by construction (#100 models
        # reject anything else); preflight records that fact and binds to it.
        package_valid = True
        target_present = _target_is_identified(package)
        if not target_present:
            package_valid = False
            channel_reasons.append(BlockingReason.TARGET_MISSING)
        credential_ready = _credential_ready(channel)
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
                channel=channel,
                package_digest=package.package_digest(),
                target=package.target,
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
