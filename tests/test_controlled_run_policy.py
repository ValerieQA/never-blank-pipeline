"""
Story 1 — Policy foundation tests.

Scope: src/controlled_run/policy.py only (ControlledRunPolicy, AuditEntry,
PolicyRequiredError, PolicyViolation). No dependency on BasePublisher,
research providers, artifact storage, or the orchestrator — those are
later, separately reviewed stories (see strategy/decision_log.md,
Часть 24, решения 103-104).

Revised after PR #6 review (changes requested): cloudinary_upload is no
longer aliased to permanent_storage, the audit trail is exposed as a
read-only tuple with frozen entries, and blocked_before_network was
removed in favor of blocked_by_policy (a claim the object can actually
back up).
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.controlled_run.policy import (
    AuditEntry,
    ControlledRunPolicy,
    PolicyRequiredError,
    PolicyViolation,
)

ALL_OPERATIONS = [
    "publication",
    "external_drafts",
    "permanent_storage",
    "history_write",
    "database_write",
    "cache_read",
    "cache_write",
    "image_reuse",
    "cloudinary_upload",
    "image_generation",
]


# ---------------------------------------------------------------------------
# Default policy is fully closed
# ---------------------------------------------------------------------------

def test_default_policy_blocks_all_capabilities():
    """All fields default to False — a bare ControlledRunPolicy(run_id=...) is fail-closed."""
    policy = ControlledRunPolicy(run_id="default-closed")
    for op in ALL_OPERATIONS:
        with pytest.raises(PolicyViolation):
            policy.check(op, adapter=f"test_{op}")
    assert len(policy.audit_trail) == len(ALL_OPERATIONS)
    assert all(e.blocked_by_policy for e in policy.audit_trail)
    assert all(not e.allowed for e in policy.audit_trail)


# ---------------------------------------------------------------------------
# Explicit allow flips one capability without opening the others.
# All 10 operations are independent — none aliases another.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("operation,attr", [
    ("publication", "publication_allowed"),
    ("external_drafts", "external_drafts_allowed"),
    ("permanent_storage", "permanent_storage_allowed"),
    ("history_write", "history_writes_allowed"),
    ("database_write", "database_writes_allowed"),
    ("cache_read", "cache_reads_allowed"),
    ("cache_write", "cache_writes_allowed"),
    ("image_reuse", "image_reuse_allowed"),
    ("image_generation", "image_generation_allowed"),
    ("cloudinary_upload", "cloudinary_upload_allowed"),
])
def test_allowing_one_capability_does_not_open_others(operation, attr):
    policy = ControlledRunPolicy(run_id="one-open", **{attr: True})

    # The explicitly allowed operation passes without raising.
    policy.check(operation, adapter="test_allowed")
    last = policy.audit_trail[-1]
    assert last.allowed is True
    assert last.blocked_by_policy is False

    # Every other operation is still blocked — no aliasing, no leakage.
    for op in ALL_OPERATIONS:
        if op == operation:
            continue
        with pytest.raises(PolicyViolation):
            policy.check(op, adapter=f"test_{op}")


# ---------------------------------------------------------------------------
# cloudinary_upload and permanent_storage are independent in both directions
# (PR #6 review: they must not be aliased — least privilege).
# ---------------------------------------------------------------------------

def test_permanent_storage_allowed_does_not_imply_cloudinary_upload():
    policy = ControlledRunPolicy(run_id="ps-not-cu", permanent_storage_allowed=True)
    policy.check("permanent_storage", adapter="storage_adapter")
    with pytest.raises(PolicyViolation):
        policy.check("cloudinary_upload", adapter="cloudinary_adapter")


def test_cloudinary_upload_allowed_does_not_imply_permanent_storage():
    policy = ControlledRunPolicy(run_id="cu-not-ps", cloudinary_upload_allowed=True)
    policy.check("cloudinary_upload", adapter="cloudinary_adapter")
    with pytest.raises(PolicyViolation):
        policy.check("permanent_storage", adapter="storage_adapter")


def test_cloudinary_upload_and_permanent_storage_both_allowed_independently():
    policy = ControlledRunPolicy(
        run_id="both-open",
        permanent_storage_allowed=True,
        cloudinary_upload_allowed=True,
    )
    policy.check("permanent_storage", adapter="storage_adapter")
    policy.check("cloudinary_upload", adapter="cloudinary_adapter")
    assert all(e.allowed for e in policy.audit_trail)


# ---------------------------------------------------------------------------
# permanent_storage and image_generation are independently gated
# ---------------------------------------------------------------------------

def test_permanent_storage_and_image_generation_are_separate_capabilities():
    """
    permanent_storage gates writing bytes to durable storage.
    image_generation gates producing the bytes in the first place.
    Allowing one must not implicitly allow the other.
    """
    policy = ControlledRunPolicy(
        run_id="sep-test",
        image_generation_allowed=True,
        permanent_storage_allowed=False,
    )

    policy.check("image_generation", adapter="test_generator")
    last = policy.audit_trail[-1]
    assert last.allowed is True
    assert last.blocked_by_policy is False

    with pytest.raises(PolicyViolation):
        policy.check("permanent_storage", adapter="test_storage")
    last = policy.audit_trail[-1]
    assert last.allowed is False
    assert last.blocked_by_policy is True

    ops = [e.operation for e in policy.audit_trail]
    assert "image_generation" in ops
    assert "permanent_storage" in ops
    assert ops.index("image_generation") != ops.index("permanent_storage")


# ---------------------------------------------------------------------------
# Unknown operations are fail-closed, not a KeyError
# ---------------------------------------------------------------------------

def test_unknown_operation_is_fail_closed_not_keyerror():
    policy = ControlledRunPolicy(run_id="unknown-op")
    with pytest.raises(PolicyViolation):
        policy.check("some_future_capability_not_yet_mapped", adapter="test")
    last = policy.audit_trail[-1]
    assert last.allowed is False
    assert last.blocked_by_policy is True


# ---------------------------------------------------------------------------
# Immutability: policy fields frozen, AuditEntry frozen, audit_trail
# read-only and cannot be used to fabricate, clear, or rewrite entries.
# ---------------------------------------------------------------------------

def test_policy_fields_are_frozen():
    policy = ControlledRunPolicy(run_id="frozen-test")
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.publication_allowed = True  # type: ignore[misc]


def test_audit_entry_is_frozen():
    """A caller cannot rewrite `allowed` (or any field) on a past entry."""
    policy = ControlledRunPolicy(run_id="entry-frozen", publication_allowed=True)
    policy.check("publication", adapter="a")
    entry = policy.audit_trail[0]
    assert isinstance(entry, AuditEntry)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.allowed = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.blocked_by_policy = True  # type: ignore[misc]


def test_audit_trail_is_a_tuple_with_no_mutating_methods():
    policy = ControlledRunPolicy(run_id="tuple-check")
    with pytest.raises(PolicyViolation):
        policy.check("publication", adapter="a")
    trail = policy.audit_trail
    assert isinstance(trail, tuple)
    assert not hasattr(trail, "append")
    assert not hasattr(trail, "clear")
    assert not hasattr(trail, "__setitem__")


def test_audit_trail_snapshot_is_independent_of_caller_mutation():
    """
    Mutating a copy derived from policy.audit_trail (e.g. list(...)) must
    never affect the policy's own record — the property returns a fresh
    snapshot, not a reference to live internal state.
    """
    policy = ControlledRunPolicy(run_id="snapshot-isolated")
    with pytest.raises(PolicyViolation):
        policy.check("publication", adapter="a")

    mutable_copy = list(policy.audit_trail)
    fake_entry = AuditEntry(
        operation="publication",
        allowed=True,  # fabricated — this check never actually passed
        adapter="attacker",
        timestamp="1970-01-01T00:00:00+00:00",
        run_id=policy.run_id,
        blocked_by_policy=False,
    )
    mutable_copy.append(fake_entry)
    mutable_copy.clear()

    # Neither mutation reaches the policy's own record.
    assert len(policy.audit_trail) == 1
    assert policy.audit_trail[0].operation == "publication"
    assert policy.audit_trail[0].allowed is False


def test_audit_trail_records_checks_and_is_not_externally_settable():
    """check() is the only way to add to the trail; there is no public setter."""
    policy = ControlledRunPolicy(run_id="mutable-log")
    assert policy.audit_trail == ()
    with pytest.raises(PolicyViolation):
        policy.check("publication", adapter="test")
    assert len(policy.audit_trail) == 1
    assert isinstance(policy.audit_trail[0], AuditEntry)
    with pytest.raises(AttributeError):
        policy.audit_trail = ()  # type: ignore[misc]  # no setter — it's a property


# ---------------------------------------------------------------------------
# Each policy instance owns its own audit_trail (no shared mutable default)
# ---------------------------------------------------------------------------

def test_audit_trail_not_shared_between_instances():
    p1 = ControlledRunPolicy(run_id="p1")
    p2 = ControlledRunPolicy(run_id="p2")
    with pytest.raises(PolicyViolation):
        p1.check("publication", adapter="test")
    assert len(p1.audit_trail) == 1
    assert len(p2.audit_trail) == 0


# ---------------------------------------------------------------------------
# audit_summary() is evidence-based (built from audit_trail, not flags)
# ---------------------------------------------------------------------------

def test_audit_summary_is_evidence_based():
    policy = ControlledRunPolicy(run_id="summary-test", image_generation_allowed=True)
    policy.check("image_generation", adapter="gen")
    with pytest.raises(PolicyViolation):
        policy.check("publication", adapter="pub")

    summary = policy.audit_summary()
    assert summary["run_id"] == "summary-test"
    assert summary["total_checks"] == 2
    assert summary["allowed_attempts"] == 1
    assert summary["blocked_attempts"] == 1
    assert "evidence" in summary["verification_source"].lower()
    assert all(e["blocked_by_policy"] for e in summary["blocked_operations"])
    assert len(summary["all_entries"]) == 2


def test_audit_summary_on_untouched_policy_is_empty():
    policy = ControlledRunPolicy(run_id="untouched")
    summary = policy.audit_summary()
    assert summary["total_checks"] == 0
    assert summary["blocked_attempts"] == 0
    assert summary["allowed_attempts"] == 0


# ---------------------------------------------------------------------------
# Exception messages carry the diagnostic fields (not just a generic string)
# ---------------------------------------------------------------------------

def test_policy_violation_message_includes_operation_adapter_run_id():
    policy = ControlledRunPolicy(run_id="msg-test-run")
    with pytest.raises(PolicyViolation) as exc_info:
        policy.check("publication", adapter="WixPublisher")
    err = exc_info.value
    assert err.operation == "publication"
    assert err.adapter == "WixPublisher"
    assert err.run_id == "msg-test-run"
    assert "publication" in str(err)
    assert "WixPublisher" in str(err)
    assert "msg-test-run" in str(err)


def test_policy_required_error_message_includes_adapter():
    err = PolicyRequiredError(adapter="TelegramPublisher")
    assert err.adapter == "TelegramPublisher"
    assert "TelegramPublisher" in str(err)
    assert "ControlledRunPolicy" in str(err)


# ---------------------------------------------------------------------------
# Default adapter label ("unknown") when the caller doesn't supply one
# ---------------------------------------------------------------------------

def test_check_defaults_adapter_to_unknown():
    policy = ControlledRunPolicy(run_id="no-adapter-arg")
    with pytest.raises(PolicyViolation):
        policy.check("publication")
    assert policy.audit_trail[-1].adapter == "unknown"
