"""Contract tests for the transport-neutral intake boundary (Task #29)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.intake import (
    ContentAssignment,
    IntakeAdapter,
    IntakeAdapterError,
    JsonlIntakeAdapter,
    UnsupportedTransportAdapter,
)


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


class FakeIntakeAdapter:
    """Test-only adapter proving core consumers need only the protocol."""

    def adapt(self, payload, *, strategy_ref, strategy_version, submitted_at):
        return ContentAssignment(
            assignment_id="fake-001",
            origin="fake-test",
            topic="Contract boundary",
            submitted_at=submitted_at,
            strategy_ref=strategy_ref,
            strategy_version=strategy_version,
        )


def _adapt(adapter: IntakeAdapter) -> ContentAssignment:
    return adapter.adapt(
        {"provider_specific": object()},
        strategy_ref="strategy-1",
        strategy_version="1.0.0",
        submitted_at=NOW,
    )


def test_fake_adapter_satisfies_contract_without_provider_payload_leakage():
    adapter = FakeIntakeAdapter()
    assert isinstance(adapter, IntakeAdapter)

    assignment = _adapt(adapter)

    assert assignment.assignment_id == "fake-001"
    assert assignment.origin == "fake-test"
    assert "provider_specific" not in assignment.to_dict()


def test_jsonl_release_1_adapter_returns_normalized_assignment():
    assignment = JsonlIntakeAdapter().adapt(
        {"SIGNAL_ID": "sig-29", "HEADLINE": "Adapter boundary"},
        strategy_ref="strategy-1",
        strategy_version="1.0.0",
        submitted_at=NOW,
    )

    assert assignment.assignment_id == "sig-29"
    assert assignment.origin == "jsonl"
    assert assignment.submitted_at == NOW


def test_jsonl_adapter_wraps_invalid_payload_as_controlled_failure():
    with pytest.raises(IntakeAdapterError, match="JSONL intake rejected"):
        JsonlIntakeAdapter().adapt(
            {"HEADLINE": "missing identity"},
            strategy_ref="strategy-1",
            strategy_version="1.0.0",
            submitted_at=NOW,
        )


@pytest.mark.parametrize("transport", ["telegram", "whatsapp", "client-portal"])
def test_unsupported_non_production_stub_cannot_return_success(transport):
    with pytest.raises(IntakeAdapterError, match="not implemented for Release 1"):
        _adapt(UnsupportedTransportAdapter(transport))
