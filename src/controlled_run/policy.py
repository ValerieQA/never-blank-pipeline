"""
src/controlled_run/policy.py
ControlledRunPolicy — immutable policy object for controlled-run isolation.

This is the PRIMARY protection mechanism. The env-var NB_CONTROLLED_RUN=1
is defense-in-depth only. ControlledRunPolicy is:
  1. Explicitly created by the orchestrator (scripts/controlled_run.py)
  2. Explicitly passed to every adapter/boundary that might do a write
  3. Checked by calling policy.check(operation, adapter=...) BEFORE any
     network, file, or external-provider call

Every check is recorded to policy.audit_trail for evidence-based validation.

## Usage

    policy = ControlledRunPolicy(
        run_id="abc123",
        image_generation_allowed=True,
    )
    # In a publisher:
    policy.check("publication", adapter="WixPublisher")          # raises PolicyViolation
    # In image pipeline:
    policy.check("image_generation", adapter="upload_to_cloudinary")  # raises PolicyViolation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


class PolicyViolation(Exception):
    """Raised by ControlledRunPolicy.check() when an operation is not allowed."""

    def __init__(self, operation: str, adapter: str, run_id: str):
        self.operation = operation
        self.adapter   = adapter
        self.run_id    = run_id
        super().__init__(
            f"PolicyViolation: operation={operation!r} is not allowed in controlled-run "
            f"(adapter={adapter!r}, run_id={run_id!r}). "
            "This guard fires BEFORE any network/file/external-provider call."
        )


@dataclass
class AuditEntry:
    """One recorded policy check — both allowed and blocked attempts are logged."""
    operation:             str
    allowed:               bool
    adapter:               str
    timestamp:             str
    run_id:                str
    blocked_before_network: bool  # True when the guard fires before any I/O

    def to_dict(self) -> dict:
        return {
            "operation":             self.operation,
            "allowed":               self.allowed,
            "adapter":               self.adapter,
            "timestamp":             self.timestamp,
            "run_id":                self.run_id,
            "blocked_before_network": self.blocked_before_network,
        }


# Mapping: operation name → attribute on ControlledRunPolicy that allows it
_OPERATION_TO_ATTR: dict[str, str] = {
    "publication":       "publication_allowed",
    "external_drafts":   "external_drafts_allowed",
    "permanent_storage": "permanent_storage_allowed",
    "history_write":     "history_writes_allowed",
    "database_write":    "database_writes_allowed",
    "cache_read":        "cache_reads_allowed",
    "cache_write":       "cache_writes_allowed",
    "image_reuse":       "image_reuse_allowed",
    "image_generation":  "image_generation_allowed",
    "cloudinary_upload": "permanent_storage_allowed",
}


@dataclass(frozen=True)
class ControlledRunPolicy:
    """
    Immutable policy object created once by the orchestrator and passed
    to all adapters/boundaries.

    frozen=True prevents reassignment of fields but allows mutation of
    the audit_trail list (lists are mutable objects; we append, not reassign).

    All fields default to the most restrictive (False = not allowed).
    """
    run_id:                    str
    publication_allowed:       bool = False
    external_drafts_allowed:   bool = False
    permanent_storage_allowed: bool = False
    history_writes_allowed:    bool = False
    database_writes_allowed:   bool = False
    cache_reads_allowed:       bool = False
    cache_writes_allowed:      bool = False
    image_reuse_allowed:       bool = False
    image_generation_allowed:  bool = False

    # Mutable audit log (frozen prevents reassignment; append is fine)
    audit_trail: list = field(default_factory=list)

    def check(self, operation: str, *, adapter: str = "unknown") -> None:
        """
        Check whether `operation` is allowed by this policy.

        Records the check to audit_trail (both allowed and blocked).
        Raises PolicyViolation BEFORE any network/file/external call when blocked.

        Args:
            operation: One of the keys in _OPERATION_TO_ATTR, e.g. "publication".
            adapter:   Human-readable name of the calling adapter for audit log.
        """
        attr = _OPERATION_TO_ATTR.get(operation)
        if attr is None:
            # Unknown operations are fail-closed: block them and log.
            allowed = False
        else:
            allowed = getattr(self, attr, False)

        entry = AuditEntry(
            operation             = operation,
            allowed               = allowed,
            adapter               = adapter,
            timestamp             = datetime.now(timezone.utc).isoformat(),
            run_id                = self.run_id,
            blocked_before_network = not allowed,
        )
        self.audit_trail.append(entry)

        if not allowed:
            raise PolicyViolation(operation, adapter, self.run_id)

    def audit_summary(self) -> dict:
        """
        Build a summary of the audit trail for validation reports.
        Verification is grounded in recorded entries, not declared policy flags.
        """
        blocked = [e for e in self.audit_trail if not e.allowed]
        allowed = [e for e in self.audit_trail if e.allowed]
        return {
            "run_id":           self.run_id,
            "total_checks":     len(self.audit_trail),
            "blocked_attempts": len(blocked),
            "allowed_attempts": len(allowed),
            "blocked_operations": [e.to_dict() for e in blocked],
            "allowed_operations": [e.to_dict() for e in allowed],
            "all_entries":      [e.to_dict() for e in self.audit_trail],
            "verification_source": "policy.audit_trail (evidence-based, not declared)",
        }
