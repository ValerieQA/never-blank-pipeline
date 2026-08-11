"""
Tests for ContentAssignment intake contract (Task #24).

Covers all 13 acceptance-criteria test cases plus regression checks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from src.intake.content_assignment import (
    ContentAssignment,
    CorrelationMetadata,
    from_jsonl_signal,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TS_UTC = datetime(2026, 8, 11, 10, 0, 0, tzinfo=timezone.utc)

MINIMAL_KWARGS = dict(
    assignment_id="sig-001",
    origin="jsonl",
    submitted_at=TS_UTC,
    strategy_ref="never-blank-v1",
    strategy_version="1.0.0",
)

SAMPLE_JSONL_SIGNAL = {
    "SIGNAL_ID": "sig-042",
    "HEADLINE": "AI adoption accelerates in SMBs",
    "CORE_FACT": "According to Gartner, 60 percent of SMBs plan to adopt AI tools by 2027.",
    "TARGET_AUDIENCE": "agencies and consultants",
    "REGION": "global",
    "INDUSTRY": "technology",
}


# ---------------------------------------------------------------------------
# 1. Valid topic-only assignment
# ---------------------------------------------------------------------------

def test_valid_topic_only():
    ca = ContentAssignment(topic="AI adoption trends", **MINIMAL_KWARGS)
    assert ca.topic == "AI adoption trends"
    assert ca.source_material is None


# ---------------------------------------------------------------------------
# 2. Valid source_material-only assignment
# ---------------------------------------------------------------------------

def test_valid_source_material_only():
    ca = ContentAssignment(
        source_material="Gartner report: 60% of SMBs will adopt AI by 2027.",
        **MINIMAL_KWARGS,
    )
    assert ca.source_material.startswith("Gartner")
    assert ca.topic is None


# ---------------------------------------------------------------------------
# 3. Valid assignment containing both
# ---------------------------------------------------------------------------

def test_valid_both_topic_and_source_material():
    ca = ContentAssignment(
        topic="AI in SMBs",
        source_material="Gartner 2027 forecast.",
        **MINIMAL_KWARGS,
    )
    assert ca.topic == "AI in SMBs"
    assert ca.source_material == "Gartner 2027 forecast."


# ---------------------------------------------------------------------------
# 4. Rejection when both are missing
# ---------------------------------------------------------------------------

def test_rejection_both_missing():
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_material'"):
        ContentAssignment(**MINIMAL_KWARGS)


# ---------------------------------------------------------------------------
# 5. Rejection when both contain only whitespace
# ---------------------------------------------------------------------------

def test_rejection_both_whitespace():
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_material'"):
        ContentAssignment(topic="   ", source_material="\t\n", **MINIMAL_KWARGS)


def test_rejection_topic_none_source_whitespace():
    with pytest.raises(ValueError, match="At least one of 'topic' or 'source_material'"):
        ContentAssignment(topic=None, source_material="   ", **MINIMAL_KWARGS)


# ---------------------------------------------------------------------------
# 6. Rejection of a timezone-naive timestamp
# ---------------------------------------------------------------------------

def test_rejection_naive_timestamp():
    naive = datetime(2026, 8, 11, 10, 0, 0)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        ContentAssignment(topic="Test", submitted_at=naive, **{
            k: v for k, v in MINIMAL_KWARGS.items() if k != "submitted_at"
        })


# ---------------------------------------------------------------------------
# 7. Acceptance and preservation of a timezone-aware timestamp
# ---------------------------------------------------------------------------

def test_timezone_aware_timestamp_preserved():
    eastern = timezone(timedelta(hours=-5))
    ts = datetime(2026, 8, 11, 5, 0, 0, tzinfo=eastern)
    ca = ContentAssignment(topic="Timezone test", submitted_at=ts, **{
        k: v for k, v in MINIMAL_KWARGS.items() if k != "submitted_at"
    })
    assert ca.submitted_at == ts
    assert ca.submitted_at.tzinfo is not None


def test_utc_timestamp_preserved():
    ca = ContentAssignment(topic="UTC test", **MINIMAL_KWARGS)
    assert ca.submitted_at == TS_UTC


# ---------------------------------------------------------------------------
# 8. Strategy reference and version validation
# ---------------------------------------------------------------------------

def test_strategy_ref_required():
    with pytest.raises(ValueError, match="strategy_ref"):
        ContentAssignment(topic="Test", strategy_ref="", **{
            k: v for k, v in MINIMAL_KWARGS.items() if k != "strategy_ref"
        })


def test_strategy_ref_whitespace_only_rejected():
    with pytest.raises(ValueError, match="strategy_ref"):
        ContentAssignment(topic="Test", strategy_ref="   ", **{
            k: v for k, v in MINIMAL_KWARGS.items() if k != "strategy_ref"
        })


def test_strategy_version_required():
    with pytest.raises(ValueError, match="strategy_version"):
        ContentAssignment(topic="Test", strategy_version="", **{
            k: v for k, v in MINIMAL_KWARGS.items() if k != "strategy_version"
        })


def test_strategy_ref_and_version_preserved():
    ca = ContentAssignment(topic="Test", **MINIMAL_KWARGS)
    assert ca.strategy_ref == "never-blank-v1"
    assert ca.strategy_version == "1.0.0"


# ---------------------------------------------------------------------------
# 9. Serialization / deserialization round trip
# ---------------------------------------------------------------------------

def test_round_trip():
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
        **MINIMAL_KWARGS,
    )
    data = ca.to_dict()

    # Serialized timestamp is a string
    assert isinstance(data["submitted_at"], str)
    assert "+00:00" in data["submitted_at"] or "Z" in data["submitted_at"] or "00:00" in data["submitted_at"]

    # Round-trip
    ca2 = ContentAssignment.from_dict(data)
    assert ca == ca2


def test_to_dict_is_json_serializable():
    ca = ContentAssignment(topic="Test", **MINIMAL_KWARGS)
    data = ca.to_dict()
    serialized = json.dumps(data)  # must not raise
    assert "Test" in serialized


# ---------------------------------------------------------------------------
# 10. Invalid serialized input with actionable English error
# ---------------------------------------------------------------------------

def test_invalid_serialized_missing_submitted_at():
    data = {
        "assignment_id": "sig-001",
        "origin": "jsonl",
        "topic": "Test",
        "submitted_at": None,
        "strategy_ref": "never-blank-v1",
        "strategy_version": "1.0.0",
    }
    with pytest.raises(ValueError, match="submitted_at must be an ISO-8601"):
        ContentAssignment.from_dict(data)


def test_invalid_serialized_bad_timestamp_format():
    data = {
        "assignment_id": "sig-001",
        "origin": "jsonl",
        "topic": "Test",
        "submitted_at": "not-a-date",
        "strategy_ref": "never-blank-v1",
        "strategy_version": "1.0.0",
    }
    with pytest.raises(ValueError, match="not a valid ISO-8601"):
        ContentAssignment.from_dict(data)


def test_invalid_serialized_not_a_dict():
    with pytest.raises(ValueError, match="ContentAssignment.from_dict expects a dict"):
        ContentAssignment.from_dict("not a dict")


# ---------------------------------------------------------------------------
# 11. Existing JSONL signal adaptation
# ---------------------------------------------------------------------------

def test_from_jsonl_signal_basic():
    ca = from_jsonl_signal(
        SAMPLE_JSONL_SIGNAL,
        strategy_ref="never-blank-v1",
        strategy_version="1.0.0",
    )
    assert ca.assignment_id == "sig-042"
    assert ca.origin == "jsonl"
    assert ca.topic == "AI adoption accelerates in SMBs"
    assert "60 percent" in ca.source_material
    assert ca.target_audience == "agencies and consultants"
    assert ca.submitted_at.tzinfo is not None  # always tz-aware


def test_from_jsonl_signal_missing_signal_id_raises():
    bad_signal = dict(SAMPLE_JSONL_SIGNAL)
    del bad_signal["SIGNAL_ID"]
    with pytest.raises(ValueError, match="SIGNAL_ID"):
        from_jsonl_signal(bad_signal, strategy_ref="r", strategy_version="1.0.0")


def test_from_jsonl_signal_custom_submitted_at():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ca = from_jsonl_signal(
        SAMPLE_JSONL_SIGNAL,
        strategy_ref="never-blank-v1",
        strategy_version="1.0.0",
        submitted_at=ts,
    )
    assert ca.submitted_at == ts


def test_from_jsonl_signal_downstream_fields_unchanged():
    """
    The adapter must not alter research fields.  Verify that the raw signal
    dict passed to ResearchContext.from_dict() downstream is unmodified.
    """
    original = dict(SAMPLE_JSONL_SIGNAL)
    from_jsonl_signal(
        SAMPLE_JSONL_SIGNAL,
        strategy_ref="r",
        strategy_version="1.0.0",
    )
    assert SAMPLE_JSONL_SIGNAL == original  # adapter must not mutate the input


# ---------------------------------------------------------------------------
# 12. Correlation metadata validation
# ---------------------------------------------------------------------------

def test_correlation_metadata_valid():
    cm = CorrelationMetadata(
        external_request_id="req-999",
        conversation_id="conv-abc",
    )
    assert cm.external_request_id == "req-999"
    assert cm.conversation_id == "conv-abc"


def test_correlation_metadata_all_optional():
    cm = CorrelationMetadata()
    assert cm.external_request_id is None
    assert cm.conversation_id is None


def test_correlation_metadata_non_string_rejected():
    with pytest.raises(ValueError, match="external_request_id must be a string"):
        CorrelationMetadata(external_request_id=42)


def test_correlation_metadata_unknown_field_rejected():
    with pytest.raises(ValueError, match="unknown fields"):
        CorrelationMetadata.from_dict({"external_request_id": "r", "telegram_update": {}})


def test_correlation_round_trip():
    cm = CorrelationMetadata(external_request_id="req-1", conversation_id="conv-2")
    assert CorrelationMetadata.from_dict(cm.to_dict()) == cm


def test_correlation_stored_on_assignment():
    cm = CorrelationMetadata(external_request_id="req-x")
    ca = ContentAssignment(topic="Test", correlation=cm, **MINIMAL_KWARGS)
    assert ca.correlation.external_request_id == "req-x"


# ---------------------------------------------------------------------------
# 13. Proof that arbitrary transport payloads are not accepted
# ---------------------------------------------------------------------------

def test_transport_payload_not_accepted_in_correlation():
    """
    A Telegram Update object, WhatsApp message dict, or raw HTTP headers
    must not be accepted through the correlation field.
    """
    telegram_update = {
        "update_id": 123456,
        "message": {"message_id": 1, "text": "hello", "chat": {"id": 789}},
    }
    with pytest.raises(ValueError, match="unknown fields"):
        CorrelationMetadata.from_dict({"external_request_id": "r", **telegram_update})


def test_transport_payload_not_accepted_as_correlation_type():
    """
    Passing a raw dict as correlation= to ContentAssignment must raise.
    """
    with pytest.raises(ValueError, match="CorrelationMetadata instance"):
        ContentAssignment(
            topic="Test",
            correlation={"external_request_id": "r"},  # type: ignore[arg-type]
            **MINIMAL_KWARGS,
        )


def test_fake_transport_adapter_proves_transport_neutrality():
    """
    A fake adapter (simulating a future UI or API transport) can build a
    ContentAssignment without any transport-specific object appearing in the
    contract.  Only the normalised string identifiers are carried through.
    """

    def fake_ui_adapter(raw_request: dict) -> ContentAssignment:
        """
        Simulates a UI transport adapter: extracts only the normalised
        fields and discards all UI-specific metadata (session tokens,
        HTTP headers, browser fingerprints).
        """
        # UI-specific fields — must NOT leak into core contract
        _http_headers = raw_request.pop("http_headers", {})
        _browser_session = raw_request.pop("browser_session_token", None)

        return ContentAssignment(
            assignment_id=raw_request["request_id"],
            origin="ui",
            topic=raw_request.get("topic"),
            source_material=raw_request.get("source_material"),
            submitted_at=raw_request["submitted_at"],
            strategy_ref=raw_request["strategy_ref"],
            strategy_version=raw_request["strategy_version"],
            correlation=CorrelationMetadata(
                external_request_id=raw_request["request_id"],
            ),
        )

    raw_ui_request = {
        "request_id": "ui-req-007",
        "topic": "Remote work productivity",
        "source_material": None,
        "submitted_at": TS_UTC,
        "strategy_ref": "never-blank-v1",
        "strategy_version": "1.0.0",
        # Transport-specific — must be stripped by adapter, not stored in core contract
        "http_headers": {"X-Session": "abc", "User-Agent": "Mozilla/5.0"},
        "browser_session_token": "tok_xyz",
    }

    ca = fake_ui_adapter(raw_ui_request)

    assert ca.origin == "ui"
    assert ca.assignment_id == "ui-req-007"
    assert ca.topic == "Remote work productivity"

    # No transport payload in serialized output
    data = ca.to_dict()
    assert "http_headers" not in data
    assert "browser_session_token" not in data
    assert "X-Session" not in json.dumps(data)
