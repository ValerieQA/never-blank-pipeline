"""
Tests for RunContext and run ID factory (Task #25).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from src.intake.content_assignment import ContentAssignment, CorrelationMetadata
from src.run.run_context import ExecutionMode, RunContext, create_run_id, _SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TS_UTC = datetime(2026, 8, 11, 10, 0, 0, tzinfo=timezone.utc)

_ASSIGNMENT = ContentAssignment(
    assignment_id="sig-001",
    origin="jsonl",
    topic="AI adoption in SMBs",
    submitted_at=TS_UTC,
    strategy_ref="never-blank-v1",
    strategy_version="1.0.0",
)

_ASSIGNMENT_WITH_CORRELATION = ContentAssignment(
    assignment_id="sig-002",
    origin="api",
    topic="Remote work trends",
    submitted_at=TS_UTC,
    strategy_ref="never-blank-v1",
    strategy_version="1.0.0",
    correlation=CorrelationMetadata(
        external_request_id="req-abc",
        conversation_id="conv-xyz",
    ),
)


def _make_rc(**kwargs) -> RunContext:
    defaults = dict(
        assignment=_ASSIGNMENT,
        execution_mode=ExecutionMode.DRY_RUN,
        started_at=TS_UTC,
    )
    defaults.update(kwargs)
    return RunContext.from_assignment(**defaults)


# ===========================================================================
# create_run_id — uniqueness and UUID v4 format
# ===========================================================================

def test_100_run_ids_are_unique():
    ids = [create_run_id() for _ in range(100)]
    assert len(set(ids)) == 100, "All 100 run IDs must be unique"


def test_run_ids_are_nonempty():
    for _ in range(20):
        rid = create_run_id()
        assert rid and rid.strip(), "run_id must be non-empty"


def test_run_ids_are_valid_uuid4():
    for _ in range(20):
        rid = create_run_id()
        parsed = uuid.UUID(rid, version=4)
        assert str(parsed) == rid, f"run_id {rid!r} is not a canonical UUID v4"
        assert parsed.version == 4, "run_id must be UUID v4"


# ===========================================================================
# from_assignment — uniqueness per invocation
# ===========================================================================

@pytest.mark.story9
def test_same_assignment_yields_different_run_ids():
    rc1 = _make_rc()
    rc2 = _make_rc()
    assert rc1.run_id != rc2.run_id, (
        "Two from_assignment() calls on the same assignment must produce "
        "different run_id values"
    )


@pytest.mark.story9
def test_100_from_assignment_calls_are_unique():
    ids = [RunContext.from_assignment(_ASSIGNMENT, ExecutionMode.DRY_RUN).run_id
           for _ in range(100)]
    assert len(set(ids)) == 100


# ===========================================================================
# Caller correlation preserved; run_id independent
# ===========================================================================

def test_external_correlation_preserved_separately():
    rc = _make_rc(assignment=_ASSIGNMENT_WITH_CORRELATION)
    assert rc.external_correlation_id == "req-abc", (
        "external_request_id must be copied to external_correlation_id"
    )
    # run_id must not be derived from the correlation id
    assert rc.run_id != "req-abc"
    assert uuid.UUID(rc.run_id, version=4).version == 4


def test_conversation_id_not_copied():
    rc = _make_rc(assignment=_ASSIGNMENT_WITH_CORRELATION)
    data = rc.to_dict()
    assert "conversation_id" not in data
    assert data.get("external_correlation_id") == "req-abc"


def test_two_contexts_same_correlation_have_different_run_ids():
    rc1 = _make_rc(assignment=_ASSIGNMENT_WITH_CORRELATION)
    rc2 = _make_rc(assignment=_ASSIGNMENT_WITH_CORRELATION)
    assert rc1.run_id != rc2.run_id


def test_no_correlation_means_none():
    rc = _make_rc(assignment=_ASSIGNMENT)
    assert rc.external_correlation_id is None


# ===========================================================================
# started_at defaults and normalization
# ===========================================================================

def test_started_at_defaults_to_utc():
    rc = RunContext.from_assignment(_ASSIGNMENT, ExecutionMode.DRY_RUN)
    assert rc.started_at.tzinfo is not None
    assert rc.started_at.utcoffset().total_seconds() == 0, (
        "Default started_at must be in UTC"
    )


def test_supplied_utc_timestamp_preserved():
    rc = _make_rc(started_at=TS_UTC)
    assert rc.started_at == TS_UTC


def test_non_utc_aware_timestamp_normalized_to_utc():
    eastern = timezone(timedelta(hours=-5))
    ts_eastern = datetime(2026, 8, 11, 5, 0, 0, tzinfo=eastern)
    rc = _make_rc(started_at=ts_eastern)
    assert rc.started_at.tzinfo == timezone.utc
    assert rc.started_at == ts_eastern.astimezone(timezone.utc)


def test_naive_timestamp_rejected():
    naive = datetime(2026, 8, 11, 10, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _make_rc(started_at=naive)


# ===========================================================================
# Invalid and blank identifiers
# ===========================================================================

def test_blank_assignment_id_rejected():
    bad = ContentAssignment(
        assignment_id="   ",
        origin="test",
        topic="topic",
        submitted_at=TS_UTC,
        strategy_ref="ref",
        strategy_version="1.0.0",
    ) if False else None  # ContentAssignment already rejects blank assignment_id
    # Verify directly on RunContext construction
    with pytest.raises(ValueError, match="assignment_id"):
        RunContext(
            run_id=create_run_id(),
            assignment_id="   ",
            started_at=TS_UTC,
            strategy_ref="r",
            strategy_version="1.0.0",
            execution_mode=ExecutionMode.DRY_RUN,
            schema_version=_SCHEMA_VERSION,
        )


def test_blank_strategy_ref_rejected():
    with pytest.raises(ValueError, match="strategy_ref"):
        RunContext(
            run_id=create_run_id(),
            assignment_id="sig-001",
            started_at=TS_UTC,
            strategy_ref="   ",
            strategy_version="1.0.0",
            execution_mode=ExecutionMode.DRY_RUN,
            schema_version=_SCHEMA_VERSION,
        )


def test_blank_strategy_version_rejected():
    with pytest.raises(ValueError, match="strategy_version"):
        RunContext(
            run_id=create_run_id(),
            assignment_id="sig-001",
            started_at=TS_UTC,
            strategy_ref="ref",
            strategy_version="",
            execution_mode=ExecutionMode.DRY_RUN,
            schema_version=_SCHEMA_VERSION,
        )


def test_blank_external_correlation_id_rejected():
    with pytest.raises(ValueError, match="external_correlation_id"):
        RunContext(
            run_id=create_run_id(),
            assignment_id="sig-001",
            external_correlation_id="   ",
            started_at=TS_UTC,
            strategy_ref="ref",
            strategy_version="1.0.0",
            execution_mode=ExecutionMode.DRY_RUN,
            schema_version=_SCHEMA_VERSION,
        )


def test_non_uuid4_run_id_rejected():
    with pytest.raises(ValueError, match="UUID v4"):
        RunContext(
            run_id="not-a-uuid",
            assignment_id="sig-001",
            started_at=TS_UTC,
            strategy_ref="ref",
            strategy_version="1.0.0",
            execution_mode=ExecutionMode.DRY_RUN,
            schema_version=_SCHEMA_VERSION,
        )


# ===========================================================================
# Execution mode
# ===========================================================================

def test_invalid_execution_mode_rejected():
    with pytest.raises(ValueError):
        RunContext(
            run_id=create_run_id(),
            assignment_id="sig-001",
            started_at=TS_UTC,
            strategy_ref="ref",
            strategy_version="1.0.0",
            execution_mode="live",  # type: ignore[arg-type]
            schema_version=_SCHEMA_VERSION,
        )


def test_dry_run_mode_accepted():
    rc = _make_rc(execution_mode=ExecutionMode.DRY_RUN)
    assert rc.execution_mode == ExecutionMode.DRY_RUN


def test_controlled_live_mode_accepted():
    rc = _make_rc(execution_mode=ExecutionMode.CONTROLLED_LIVE)
    assert rc.execution_mode == ExecutionMode.CONTROLLED_LIVE


def test_execution_mode_enum_values():
    assert ExecutionMode.DRY_RUN.value == "dry-run"
    assert ExecutionMode.CONTROLLED_LIVE.value == "controlled-live"


# ===========================================================================
# schema_version is deterministic
# ===========================================================================

def test_schema_version_is_fixed():
    rc = _make_rc()
    assert rc.schema_version == "1.0"


def test_schema_version_wrong_value_rejected():
    with pytest.raises(ValueError, match="schema_version"):
        RunContext(
            run_id=create_run_id(),
            assignment_id="sig-001",
            started_at=TS_UTC,
            strategy_ref="ref",
            strategy_version="1.0.0",
            execution_mode=ExecutionMode.DRY_RUN,
            schema_version="2.0",
        )


# ===========================================================================
# Serialization round-trip
# ===========================================================================

def test_round_trip():
    rc = _make_rc(assignment=_ASSIGNMENT_WITH_CORRELATION)
    data = rc.to_dict()

    assert isinstance(data["started_at"], str)
    assert "+00:00" in data["started_at"]

    rc2 = RunContext.from_dict(data)
    assert rc2.run_id == rc.run_id
    assert rc2.assignment_id == rc.assignment_id
    assert rc2.external_correlation_id == rc.external_correlation_id
    assert rc2.started_at == rc.started_at
    assert rc2.execution_mode == rc.execution_mode
    assert rc2.schema_version == rc.schema_version


def test_to_dict_is_json_serializable():
    rc = _make_rc()
    serialized = json.dumps(rc.to_dict())
    assert rc.run_id in serialized


# ===========================================================================
# Serialized form contains no content fields or secrets
# ===========================================================================

def test_serialized_form_excludes_content_fields():
    assignment_with_content = ContentAssignment(
        assignment_id="sig-003",
        origin="jsonl",
        topic="Sensitive editorial topic",
        source_material="Confidential source document.",
        user_instruction="Do not publish externally.",
        target_audience="internal only",
        references=[{"url": "https://internal.example.com"}],
        submitted_at=TS_UTC,
        strategy_ref="never-blank-v1",
        strategy_version="1.0.0",
    )
    rc = RunContext.from_assignment(assignment_with_content, ExecutionMode.DRY_RUN,
                                   started_at=TS_UTC)
    serialized = json.dumps(rc.to_dict())

    assert "Sensitive editorial topic" not in serialized
    assert "Confidential source document" not in serialized
    assert "Do not publish externally" not in serialized
    assert "internal.example.com" not in serialized
    assert "internal only" not in serialized


# ===========================================================================
# Unknown fields rejected in from_dict
# ===========================================================================

def test_from_dict_unknown_field_rejected():
    data = {**_make_rc().to_dict(), "signal_payload": {"raw": "data"}}
    with pytest.raises(ValueError, match="unknown field"):
        RunContext.from_dict(data)


def test_from_dict_invalid_not_a_dict():
    with pytest.raises(ValueError, match="expects a dict"):
        RunContext.from_dict("not a dict")


def test_from_dict_naive_timestamp_rejected():
    data = {**_make_rc().to_dict(), "started_at": "2026-08-11T10:00:00"}
    with pytest.raises(ValueError, match="timezone-aware"):
        RunContext.from_dict(data)


def test_from_dict_bad_timestamp_format_rejected():
    data = {**_make_rc().to_dict(), "started_at": "not-a-date"}
    with pytest.raises(ValueError, match="not a valid ISO-8601"):
        RunContext.from_dict(data)


# ===========================================================================
# from_assignment rejects non-ContentAssignment input
# ===========================================================================

def test_from_assignment_rejects_raw_dict():
    with pytest.raises(ValueError, match="ContentAssignment instance"):
        RunContext.from_assignment(
            {"assignment_id": "sig-001"},  # type: ignore[arg-type]
            ExecutionMode.DRY_RUN,
        )
