"""
Tests for ContentAssignment intake contract (Task #24).

Covers all 13 acceptance-criteria test cases plus negative tests for
the PM review findings (findings 3–5).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

from src.intake.content_assignment import (
    ContentAssignment,
    CorrelationMetadata,
    from_jsonl_signal,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TS_UTC = datetime(2026, 8, 11, 10, 0, 0, tzinfo=timezone.utc)

BASE = dict(
    assignment_id="sig-001",
    origin="jsonl",
    submitted_at=TS_UTC,
    strategy_ref="never-blank-v1",
    strategy_version="1.0.0",
)

SAMPLE_JSONL = {
    "SIGNAL_ID": "sig-042",
    "HEADLINE": "AI adoption accelerates in SMBs",
    "CORE_FACT": "According to Gartner, 60 percent of SMBs plan to adopt AI tools by 2027.",
    "TARGET_AUDIENCE": "agencies and consultants",
    "REGION": "global",
    "INDUSTRY": "technology",
}


def _make(**overrides) -> ContentAssignment:
    return ContentAssignment(**{**BASE, "topic": "default topic", **overrides})


# ===========================================================================
# 1. Valid topic-only assignment
# ===========================================================================

def test_valid_topic_only():
    ca = _make(topic="AI adoption trends", source_material=None)
    assert ca.topic == "AI adoption trends"
    assert ca.source_material is None


# ===========================================================================
# 2. Valid source_material-only assignment
# ===========================================================================

def test_valid_source_material_only():
    ca = _make(topic=None, source_material="Gartner report: 60% SMBs adopt AI by 2027.")
    assert ca.source_material.startswith("Gartner")
    assert ca.topic is None


# ===========================================================================
# 3. Valid assignment containing both
# ===========================================================================

def test_valid_both_fields():
    ca = _make(topic="AI in SMBs", source_material="Gartner 2027 forecast.")
    assert ca.topic == "AI in SMBs"
    assert ca.source_material == "Gartner 2027 forecast."


# ===========================================================================
# 4. Rejection when both are missing
# ===========================================================================

def test_rejection_both_missing():
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_material'"):
        ContentAssignment(**{**BASE})


# ===========================================================================
# 5. Rejection when both contain only whitespace
# ===========================================================================

def test_rejection_both_whitespace():
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_material'"):
        ContentAssignment(**{**BASE, "topic": "   ", "source_material": "\t\n"})


def test_rejection_topic_none_source_whitespace():
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_material'"):
        ContentAssignment(**{**BASE, "topic": None, "source_material": "   "})


# ===========================================================================
# 6. Rejection of a timezone-naive timestamp
# ===========================================================================

def test_rejection_naive_timestamp():
    naive = datetime(2026, 8, 11, 10, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _make(submitted_at=naive)


# ===========================================================================
# 7. Acceptance and preservation of a timezone-aware timestamp
# ===========================================================================

def test_timezone_aware_timestamp_preserved():
    eastern = timezone(timedelta(hours=-5))
    ts = datetime(2026, 8, 11, 5, 0, 0, tzinfo=eastern)
    ca = _make(submitted_at=ts)
    assert ca.submitted_at == ts
    assert ca.submitted_at.tzinfo is not None


def test_utc_timestamp_preserved():
    ca = _make()
    assert ca.submitted_at == TS_UTC


# ===========================================================================
# 8. Strategy reference and version validation
# ===========================================================================

def test_strategy_ref_empty_rejected():
    with pytest.raises(ValueError, match="strategy_ref"):
        _make(strategy_ref="")


def test_strategy_ref_whitespace_rejected():
    with pytest.raises(ValueError, match="strategy_ref"):
        _make(strategy_ref="   ")


def test_strategy_version_empty_rejected():
    with pytest.raises(ValueError, match="strategy_version"):
        _make(strategy_version="")


def test_strategy_ref_and_version_preserved():
    ca = _make()
    assert ca.strategy_ref == "never-blank-v1"
    assert ca.strategy_version == "1.0.0"


# ===========================================================================
# 9. Serialization / deserialization round trip
# ===========================================================================

def test_round_trip_full():
    ca = ContentAssignment(
        topic="AI in SMBs",
        source_material="Gartner 2027 forecast.",
        user_instruction="Focus on mid-market agencies.",
        target_audience="agencies",
        publishing_constraints={"linkedin": {"dry_run": True}},
        references=[{"url": "https://example.com", "label": "primary"}],
        correlation=CorrelationMetadata(
            external_request_id="req-123",
            conversation_id="conv-456",
        ),
        **BASE,
    )
    data = ca.to_dict()

    assert isinstance(data["submitted_at"], str)
    assert "+00:00" in data["submitted_at"]

    ca2 = ContentAssignment.from_dict(data)
    assert ca2.assignment_id == ca.assignment_id
    assert ca2.topic == ca.topic
    assert ca2.source_material == ca.source_material
    assert ca2.submitted_at == ca.submitted_at
    assert ca2.correlation.external_request_id == "req-123"
    assert ca2.correlation.conversation_id == "conv-456"


def test_to_dict_is_json_serializable():
    ca = _make()
    serialized = json.dumps(ca.to_dict())
    assert "default topic" in serialized


def test_round_trip_minimal():
    ca = _make()
    ca2 = ContentAssignment.from_dict(ca.to_dict())
    assert ca2.assignment_id == ca.assignment_id
    assert ca2.submitted_at == ca.submitted_at


# ===========================================================================
# 10. Invalid serialized input with actionable English error
# ===========================================================================

def test_invalid_missing_submitted_at():
    data = {**_make().to_dict(), "submitted_at": None}
    with pytest.raises(ValueError, match="submitted_at"):
        ContentAssignment.from_dict(data)


def test_invalid_bad_timestamp_format():
    data = {**_make().to_dict(), "submitted_at": "not-a-date"}
    with pytest.raises(ValueError, match="not a valid ISO-8601"):
        ContentAssignment.from_dict(data)


def test_invalid_not_a_dict():
    with pytest.raises(ValueError, match="expects a dict"):
        ContentAssignment.from_dict("not a dict")


# ===========================================================================
# 11. Existing JSONL signal adaptation
# ===========================================================================

def test_from_jsonl_signal_basic():
    ca = from_jsonl_signal(
        SAMPLE_JSONL,
        strategy_ref="never-blank-v1",
        strategy_version="1.0.0",
    )
    assert ca.assignment_id == "sig-042"
    assert ca.origin == "jsonl"
    assert ca.topic == "AI adoption accelerates in SMBs"
    assert "60 percent" in ca.source_material
    assert ca.target_audience == "agencies and consultants"
    assert ca.submitted_at.tzinfo is not None


def test_from_jsonl_signal_missing_signal_id():
    bad = {k: v for k, v in SAMPLE_JSONL.items() if k != "SIGNAL_ID"}
    with pytest.raises(ValueError, match="SIGNAL_ID"):
        from_jsonl_signal(bad, strategy_ref="r", strategy_version="1.0.0")


def test_from_jsonl_signal_custom_submitted_at():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ca = from_jsonl_signal(
        SAMPLE_JSONL,
        strategy_ref="never-blank-v1",
        strategy_version="1.0.0",
        submitted_at=ts,
    )
    assert ca.submitted_at == ts


def test_from_jsonl_signal_does_not_mutate_input():
    original = dict(SAMPLE_JSONL)
    from_jsonl_signal(SAMPLE_JSONL, strategy_ref="r", strategy_version="1.0.0")
    assert SAMPLE_JSONL == original


def test_from_jsonl_signal_invalid_publishing_constraints_not_silently_repaired():
    """A list passed as publishing_constraints must fail validation, not be coerced to {}."""
    with pytest.raises(ValueError):
        from_jsonl_signal(
            SAMPLE_JSONL,
            strategy_ref="r",
            strategy_version="1.0.0",
            publishing_constraints=[],  # type: ignore[arg-type]
        )


def test_from_jsonl_signal_invalid_references_not_silently_repaired():
    """A dict passed as references must fail validation, not be coerced to []."""
    with pytest.raises(ValueError):
        from_jsonl_signal(
            SAMPLE_JSONL,
            strategy_ref="r",
            strategy_version="1.0.0",
            references={},  # type: ignore[arg-type]
        )


# ===========================================================================
# 12. Correlation metadata validation
# ===========================================================================

def test_correlation_valid():
    cm = CorrelationMetadata(external_request_id="req-999", conversation_id="conv-abc")
    assert cm.external_request_id == "req-999"
    assert cm.conversation_id == "conv-abc"


def test_correlation_all_optional():
    cm = CorrelationMetadata()
    assert cm.external_request_id is None
    assert cm.conversation_id is None


def test_correlation_non_string_rejected():
    with pytest.raises(ValueError, match="must be a string"):
        CorrelationMetadata(external_request_id=42)


def test_correlation_empty_string_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        CorrelationMetadata(external_request_id="")


def test_correlation_whitespace_only_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        CorrelationMetadata(conversation_id="   ")


def test_correlation_unknown_field_rejected():
    with pytest.raises(ValueError):
        CorrelationMetadata.model_validate(
            {"external_request_id": "r", "telegram_update": {}}
        )


def test_correlation_round_trip():
    cm = CorrelationMetadata(external_request_id="req-1", conversation_id="conv-2")
    assert CorrelationMetadata.model_validate(cm.to_dict()) == cm


def test_correlation_stored_on_assignment():
    cm = CorrelationMetadata(external_request_id="req-x")
    ca = _make(correlation=cm)
    assert ca.correlation.external_request_id == "req-x"


# ===========================================================================
# 13. Transport payload not accepted into core contract
# ===========================================================================

def test_transport_payload_unknown_correlation_field():
    """Telegram Update fields must be rejected by CorrelationMetadata."""
    with pytest.raises(ValueError):
        CorrelationMetadata.model_validate({
            "external_request_id": "r",
            "update_id": 123456,
            "message": {"text": "hello"},
        })


def test_transport_payload_not_accepted_as_correlation_type():
    """Passing a raw dict as correlation= must raise."""
    with pytest.raises(ValueError):
        _make(correlation={"external_request_id": "r"})  # type: ignore[arg-type]


def test_fake_transport_adapter_proves_neutrality():
    """
    A fake UI adapter strips transport-specific metadata before constructing
    ContentAssignment; those keys must not appear in to_dict() output.
    """

    def fake_ui_adapter(raw: dict) -> ContentAssignment:
        _http_headers = raw.pop("http_headers", {})
        _session_token = raw.pop("browser_session_token", None)
        return ContentAssignment(
            assignment_id=raw["request_id"],
            origin="ui",
            topic=raw.get("topic"),
            source_material=raw.get("source_material"),
            submitted_at=raw["submitted_at"],
            strategy_ref=raw["strategy_ref"],
            strategy_version=raw["strategy_version"],
            correlation=CorrelationMetadata(external_request_id=raw["request_id"]),
        )

    raw = {
        "request_id": "ui-req-007",
        "topic": "Remote work productivity",
        "source_material": None,
        "submitted_at": TS_UTC,
        "strategy_ref": "never-blank-v1",
        "strategy_version": "1.0.0",
        "http_headers": {"X-Session": "abc"},
        "browser_session_token": "tok_xyz",
    }

    ca = fake_ui_adapter(raw)
    data = ca.to_dict()
    serialized = json.dumps(data)
    assert "http_headers" not in data
    assert "browser_session_token" not in data
    assert "X-Session" not in serialized


# ===========================================================================
# Finding 3 — explicit type enforcement on optional fields
# ===========================================================================

def test_topic_non_string_rejected():
    with pytest.raises(ValueError, match="topic must be a string"):
        _make(topic=42, source_material="valid source")


def test_source_material_non_string_rejected():
    with pytest.raises(ValueError, match="source_material must be a string"):
        _make(topic="valid topic", source_material={"url": "http://x.com"})


def test_user_instruction_non_string_rejected():
    with pytest.raises(ValueError, match="user_instruction must be a string"):
        _make(user_instruction=["do this"])


def test_target_audience_non_string_rejected():
    with pytest.raises(ValueError, match="target_audience must be a string"):
        _make(target_audience=123)


def test_topic_none_valid_when_source_present():
    ca = _make(topic=None, source_material="valid source material")
    assert ca.topic is None


def test_source_material_none_valid_when_topic_present():
    ca = _make(topic="valid topic", source_material=None)
    assert ca.source_material is None


# ===========================================================================
# Finding 4 — JSON-compatibility of publishing_constraints and references
# ===========================================================================

def test_publishing_constraints_with_set_rejected():
    with pytest.raises(ValueError, match="non-JSON-serializable"):
        _make(publishing_constraints={"channels": {1, 2, 3}})


def test_publishing_constraints_with_datetime_value_rejected():
    with pytest.raises(ValueError, match="non-JSON-serializable"):
        _make(publishing_constraints={"since": datetime(2026, 1, 1, tzinfo=timezone.utc)})


def test_publishing_constraints_nested_valid():
    ca = _make(publishing_constraints={"linkedin": {"dry_run": True, "max_length": 500}})
    assert ca.publishing_constraints["linkedin"]["dry_run"] is True


def test_references_with_non_json_value_rejected():
    with pytest.raises(ValueError, match="non-JSON-serializable"):
        _make(references=[{"url": "https://x.com", "obj": object()}])


def test_references_nested_valid():
    refs = [{"url": "https://gartner.com", "label": "primary", "year": 2027}]
    ca = _make(references=refs)
    assert ca.references[0]["year"] == 2027


# ===========================================================================
# Finding 5 — unknown top-level fields in from_dict()
# ===========================================================================

def test_from_dict_unknown_field_rejected():
    data = {**_make().to_dict(), "telegram_update": {"update_id": 99}}
    with pytest.raises(ValueError, match="unknown field"):
        ContentAssignment.from_dict(data)


def test_from_dict_unknown_transport_key_actionable_message():
    data = {**_make().to_dict(), "http_session": "tok_abc"}
    with pytest.raises(ValueError, match="http_session"):
        ContentAssignment.from_dict(data)


def test_from_dict_known_fields_accepted():
    ca = _make(
        user_instruction="Test instruction",
        target_audience="agencies",
        publishing_constraints={"wix": {"dry_run": True}},
        references=[{"url": "https://example.com"}],
        correlation=CorrelationMetadata(external_request_id="req-1"),
    )
    ca2 = ContentAssignment.from_dict(ca.to_dict())
    assert ca2.user_instruction == "Test instruction"
    assert ca2.correlation.external_request_id == "req-1"
