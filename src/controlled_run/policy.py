"""
src/controlled_run/policy.py
ControlledRunPolicy — immutable policy object for controlled-run isolation.

This is the PRIMARY protection mechanism. An env-var such as
NB_CONTROLLED_RUN=1 is defense-in-depth only, never the primary guard.
ControlledRunPolicy is:

1. Explicitly created by the orchestrator (a future Story-8 runner).
2. Explicitly passed to every adapter/boundary that might do a write
   (dependency injection — no reliance on module-level env-var checks).
3. Checked by calling policy.check(operation, adapter=...) BEFORE any
   network, file, or external-provider call — this is a contract every
   boundary must follow; see "What this object does NOT prove" below for
   how that contract gets verified.

Every check is recorded to policy.audit_trail for evidence-based
validation — both allowed and blocked attempts.

## Scope

This module is Story 1 (Policy foundation) of the Controlled E2E Run
epic — see strategy/decision_log.md, Часть 24, решения 101-109, and the
PR #6 review that corrected this contract. It defines the policy object
and its own exceptions only. It does not wire into BasePublisher,
research providers, artifact storage, or the visual pipeline — those are
separate stories (2-8), landed and reviewed one at a time.

There are 10 independently gated operations, each with its own boolean
capability field — no operation is an alias of another. In particular
"cloudinary_upload" and "permanent_storage" are separate capabilities:
enabling permanent storage in general does not implicitly enable
Cloudinary uploads, and vice versa.

## What this object does NOT prove

ControlledRunPolicy proves two things: whether a given `check()` call was
allowed or rejected, and that every such call was recorded, in order,
in an audit trail that cannot be edited after the fact (see AuditEntry).

It does NOT and cannot prove that a caller made no network/file/external
call *before* invoking check(). Nothing in this module can observe a
caller's code before it reaches the gate. "Check before I/O" is a
contract that later stories' boundaries (BasePublisher, providers, image
pipeline, ...) must uphold and that must be demonstrated by boundary-
level tests asserting execution order — e.g. a fake HTTP/storage client
whose call count is asserted to be zero at the point PolicyViolation is
raised. Story 1 supplies the gate and the evidence trail; proving the
gate is actually reached first is Story 2+'s job.

## Usage

    policy = ControlledRunPolicy(
        run_id="abc123",
        image_generation_allowed=True,
    )

    # At a boundary that is about to do external I/O:
    policy.check("publication", adapter="WixPublisher")       # raises PolicyViolation if blocked
    policy.check("image_generation", adapter="dalle_provider")  # raises PolicyViolation if blocked

    # For a validation/audit report:
    summary = policy.audit_summary()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


class PolicyRequiredError(Exception):
    """
    Raised when a controlled-run boundary is reached without a ControlledRunPolicy.

    In the controlled-run execution path, every publisher and adapter that
    performs external I/O MUST receive an explicit ControlledRunPolicy. If
    the boundary is reached without one, this error fires instead of a
    silent pass-through or an unrelated AttributeError.
    """

    def __init__(self, adapter: str):
        self.adapter = adapter
        super().__init__(
            f"PolicyRequiredError: {adapter!r} reached a controlled-run boundary "
            "but no ControlledRunPolicy was provided. "
            "Pass policy=<ControlledRunPolicy> to the adapter."
        )


class PolicyViolation(Exception):
    """Raised by ControlledRunPolicy.check() when an operation is not allowed."""

    def __init__(self, operation: str, adapter: str, run_id: str):
        self.operation = operation
        self.adapter = adapter
        self.run_id = run_id
        super().__init__(
            f"PolicyViolation: operation={operation!r} is not allowed in controlled-run "
            f"(adapter={adapter!r}, run_id={run_id!r}). "
            "This guard fires BEFORE any network/file/external-provider call."
        )


@dataclass(frozen=True)
class AuditEntry:
    """
    One recorded policy check — both allowed and blocked attempts are logged.

    frozen=True: an entry cannot be edited after creation. This is what
    makes the audit trail usable as evidence — no downstream code can
    flip `allowed` on a past entry or otherwise rewrite history.

    blocked_by_policy reflects only what ControlledRunPolicy.check() can
    actually observe: whether it allowed or rejected this specific call.
    It does NOT claim anything about whether the caller performed I/O
    before or after this check — see the module docstring's "What this
    object does NOT prove".
    """

    operation: str
    allowed: bool
    adapter: str
    timestamp: str
    run_id: str
    blocked_by_policy: bool  # True iff this check() call raised PolicyViolation

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "allowed": self.allowed,
            "adapter": self.adapter,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "blocked_by_policy": self.blocked_by_policy,
        }


# Mapping: operation name -> attribute on ControlledRunPolicy that allows it.
# 10 operations, 10 independent capability fields — no operation aliases
# another. cloudinary_upload has its own flag; enabling permanent_storage
# does not implicitly enable it, and vice versa.
_OPERATION_TO_ATTR: dict[str, str] = {
    "publication": "publication_allowed",
    "external_drafts": "external_drafts_allowed",
    "permanent_storage": "permanent_storage_allowed",
    "history_write": "history_writes_allowed",
    "database_write": "database_writes_allowed",
    "cache_read": "cache_reads_allowed",
    "cache_write": "cache_writes_allowed",
    "image_reuse": "image_reuse_allowed",
    "image_generation": "image_generation_allowed",
    "cloudinary_upload": "cloudinary_upload_allowed",
}


@dataclass(frozen=True)
class ControlledRunPolicy:
    """
    Immutable policy object created once by the orchestrator and passed
    to all adapters/boundaries via dependency injection.

    frozen=True prevents reassignment of the declared fields (including
    the internal audit log reference). The audit trail itself is exposed
    only through the read-only `audit_trail` property below, which
    returns a fresh tuple snapshot on every access — callers cannot
    clear it, append to it, or index-assign into it through the public
    API. Combined with AuditEntry being frozen, no code using the public
    API can fabricate, delete, or rewrite a past entry.

    Caveat: Python has no true field privacy. `_audit_log` is a naming
    convention (single underscore), not a hard guarantee — code that
    deliberately reaches past the public API (`policy._audit_log`) can
    still mutate it. What this design actually guarantees is that the
    *intended, documented* way of reading the trail (`policy.audit_trail`)
    cannot be used to corrupt it, and that entries already appended can
    never be edited in place.

    All capability fields default to the most restrictive setting
    (False = not allowed).
    """

    run_id: str
    publication_allowed: bool = False
    external_drafts_allowed: bool = False
    permanent_storage_allowed: bool = False
    history_writes_allowed: bool = False
    database_writes_allowed: bool = False
    cache_reads_allowed: bool = False
    cache_writes_allowed: bool = False
    image_reuse_allowed: bool = False
    image_generation_allowed: bool = False
    cloudinary_upload_allowed: bool = False

    # Internal, append-only log. Not part of equality/repr — it's
    # runtime bookkeeping, not policy identity.
    _audit_log: list = field(default_factory=list, repr=False, compare=False)

    @property
    def audit_trail(self) -> tuple[AuditEntry, ...]:
        """
        Read-only snapshot of every recorded check, in call order.

        Returns a new tuple on every access. Tuples have no append/clear/
        item-assignment, so this value cannot be used to mutate the
        policy's internal record — and because it's a fresh copy, even
        mutating a list built from it (e.g. `list(policy.audit_trail)`)
        has no effect on the policy itself.
        """
        return tuple(self._audit_log)

    def check(self, operation: str, *, adapter: str = "unknown") -> None:
        """
        Check whether `operation` is allowed by this policy.

        Records the check to the internal audit log (both allowed and
        blocked). Raises PolicyViolation when the operation is blocked.
        This method is the only code path that appends to the audit log.

        Args:
            operation: One of the keys in _OPERATION_TO_ATTR, e.g. "publication".
            adapter: Human-readable name of the calling adapter, for the audit log.
        """
        attr = _OPERATION_TO_ATTR.get(operation)
        if attr is None:
            # Unknown operations are fail-closed: block them and log.
            allowed = False
        else:
            allowed = getattr(self, attr, False)

        entry = AuditEntry(
            operation=operation,
            allowed=allowed,
            adapter=adapter,
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=self.run_id,
            blocked_by_policy=not allowed,
        )
        self._audit_log.append(entry)

        if not allowed:
            raise PolicyViolation(operation, adapter, self.run_id)

    def audit_summary(self) -> dict:
        """
        Build a summary of the audit trail for validation reports.

        Verification is grounded in recorded entries (evidence-based),
        not in the declared policy flags — a report built from this
        summary reflects what was actually checked at runtime. It does
        not and cannot certify that no I/O happened before a given
        check() call; see the module docstring.
        """
        trail = self.audit_trail
        blocked = [e for e in trail if not e.allowed]
        allowed = [e for e in trail if e.allowed]
        return {
            "run_id": self.run_id,
            "total_checks": len(trail),
            "blocked_attempts": len(blocked),
            "allowed_attempts": len(allowed),
            "blocked_operations": [e.to_dict() for e in blocked],
            "allowed_operations": [e.to_dict() for e in allowed],
            "all_entries": [e.to_dict() for e in trail],
            "verification_source": "policy.audit_trail (evidence-based, not declared)",
        }
