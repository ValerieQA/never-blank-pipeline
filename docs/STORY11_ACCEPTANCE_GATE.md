# Story 11 acceptance gate

Run the complete offline acceptance gate from the repository root:

```bash
python3 -m pytest -m story11
```

Expected result: **76 passed, 0 failed, 0 skipped**. The gate uses deterministic
providers/transports and isolated temporary run namespaces. It makes no live Exa,
Wix, or LinkedIn call and needs no production credential.

Story 11 distinguishes retrieval completion from evidence readiness. A normal Exa
retrieval is deliberately persisted as `COMPLETE` with `NOT_ASSESSED` evidence and
`NEEDS_REVIEW`, then held before Decision Lens/editorial. The controlled READY
provider is test evidence for the accepted downstream route; it is not an automatic
assessment capability and does not imply that Exa output is automatically publishable.

## Scenario-to-node-ID matrix

Every node below is active and collectable with
`python3 -m pytest -m story11 --collect-only -q`.

| Acceptance evidence | Exact pytest node ID |
|---|---|
| Typed source priority/request construction | `tests/test_research_artifact_lifecycle.py::test_source_priority_is_deterministic_and_typed` |
| Canonical bytes, strict reload, timestamps, IDs, full configuration identity, evidence/interpretation separation, uncertainty and contradiction | `tests/test_research_artifact_lifecycle.py::test_ready_envelope_is_persisted_canonically_and_strictly_reloaded` |
| Controlled READY reaches real `main()` editorial boundary only after persisted research | `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_ready_research_before_editorial` |
| Honest Exa retrieval is `NOT_ASSESSED / NEEDS_REVIEW` and held | `tests/test_research_artifact_lifecycle.py::test_canonical_main_holds_honest_exa_retrieval_before_editorial` |
| Complete but `NEEDS_REVIEW` blocks | `tests/test_research_artifact_lifecycle.py::test_non_ready_complete_result_is_persisted_honestly_then_blocked[needs_review]` |
| Insufficient evidence blocks | `tests/test_research_artifact_lifecycle.py::test_non_ready_complete_result_is_persisted_honestly_then_blocked[insufficient]` |
| Rejected/blocked evidence blocks | `tests/test_research_artifact_lifecycle.py::test_non_ready_complete_result_is_persisted_honestly_then_blocked[blocked]` |
| `NOT_ASSESSED`, `CONFLICTING`, and `REJECTED` cannot be READY | `tests/test_research_evidence_contract.py::test_ready_rejects_blocking_evidence_dispositions[not_assessed]`, `tests/test_research_evidence_contract.py::test_ready_rejects_blocking_evidence_dispositions[conflicting]`, `tests/test_research_evidence_contract.py::test_ready_rejects_blocking_evidence_dispositions[rejected]` |
| Unresolved contradiction is preserved and blocks READY | `tests/test_research_evidence_contract.py::test_ready_rejects_unresolved_contradiction` |
| Unresolved material uncertainty is preserved and blocks READY | `tests/test_research_evidence_contract.py::test_ready_rejects_unresolved_material_uncertainty` |
| Partial result is persisted honestly and held | `tests/test_research_artifact_lifecycle.py::test_partial_result_with_artifact_is_persisted_then_blocked` |
| Empty, timeout, authentication, rate-limit, malformed and unavailable failures persist as typed failed envelopes and block canonical `main()` | `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_typed_provider_failure_before_side_effects[empty]`, `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_typed_provider_failure_before_side_effects[timeout]`, `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_typed_provider_failure_before_side_effects[authentication]`, `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_typed_provider_failure_before_side_effects[rate_limited]`, `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_typed_provider_failure_before_side_effects[malformed]`, `tests/test_research_artifact_lifecycle.py::test_canonical_main_persists_typed_provider_failure_before_side_effects[unavailable]` |
| Real Exa exception normalization and bounded sanitized failures | `tests/test_research_provider_adapter.py::test_exa_exceptions_are_normalized_and_do_not_cross_boundary[error0-timeout]`, `tests/test_research_provider_adapter.py::test_exa_exceptions_are_normalized_and_do_not_cross_boundary[error1-authentication]`, `tests/test_research_provider_adapter.py::test_exa_exceptions_are_normalized_and_do_not_cross_boundary[error2-rate_limited]`, `tests/test_research_provider_adapter.py::test_exa_exceptions_are_normalized_and_do_not_cross_boundary[error3-malformed_response]`, `tests/test_research_provider_adapter.py::test_exa_exceptions_are_normalized_and_do_not_cross_boundary[error4-source_retrieval_failed]` |
| Individual source failure retains safe sources as honest partial research | `tests/test_research_provider_adapter.py::test_individual_source_failure_retains_successful_sources` |
| Naive/non-UTC request and retrieval timestamps fail strict validation | `tests/test_research_provider_adapter.py::test_request_and_freshness_reject_naive_and_non_utc[timestamp0]`, `tests/test_research_provider_adapter.py::test_request_and_freshness_reject_naive_and_non_utc[timestamp1]`, `tests/test_research_provider_adapter.py::test_source_attempt_and_retrieval_timestamps_require_strict_utc[timestamp0]`, `tests/test_research_provider_adapter.py::test_source_attempt_and_retrieval_timestamps_require_strict_utc[timestamp1]` |
| Provider invocation before run start and future-invalid timing fail closed | `tests/test_research_artifact_lifecycle.py::test_provider_invocation_before_current_run_is_rejected`, `tests/test_research_artifact_lifecycle.py::test_future_invalid_provider_timing_fails_closed` |
| Run/assignment/signal/configuration lineage mismatch fails closed | `tests/test_research_artifact_lifecycle.py::test_current_run_identity_and_configuration_mismatch_fail_closed` |
| Malformed and non-canonical research fail strict reload | `tests/test_research_artifact_lifecycle.py::test_corrupt_and_noncanonical_research_are_rejected` |
| Create-once collision and atomic failure protection | `tests/test_research_artifact_lifecycle.py::test_existing_research_artifact_is_never_overwritten`, `tests/test_research_artifact_lifecycle.py::test_simulated_commit_failure_leaves_no_target_or_temp_file` |
| Two fresh runs use distinct immutable run namespaces | `tests/test_research_artifact_lifecycle.py::test_two_generation_runs_keep_distinct_immutable_research_artifacts` |
| Valid `--from-package` loads original READY lineage, makes no provider call, and does not rewrite source artifacts | `tests/test_research_artifact_lifecycle.py::test_from_package_reuses_original_ready_lineage_without_provider_or_rewrite` |
| Missing, corrupt, non-canonical and non-ready reuse lineage block before side effects | `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[missing]`, `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[corrupt]`, `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[noncanonical]`, `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[nonready]` |
| Cross-run, assignment, signal and configuration-mismatched reuse lineage blocks before side effects | `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[cross_run]`, `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[assignment]`, `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[signal]`, `tests/test_research_artifact_lifecycle.py::test_from_package_rejects_invalid_research_lineage_before_side_effects[configuration]` |
| Client user-info URL blocks before provider/downstream work | `tests/test_research_artifact_lifecycle.py::test_canonical_entrypoint_rejects_client_userinfo_before_provider_or_side_effects[https://alice:hunter2@example.com/report-secrets0]` |
| Provider user-info URL is retained only as a sanitized failed envelope | `tests/test_research_artifact_lifecycle.py::test_provider_userinfo_is_persisted_only_as_sanitized_failed_envelope` |
| Direct, preferred and discovery provider paths reject user-info | `tests/test_research_provider_adapter.py::test_provider_returned_userinfo_is_sanitized_before_canonical_records[direct]`, `tests/test_research_provider_adapter.py::test_provider_returned_userinfo_is_sanitized_before_canonical_records[preferred]`, `tests/test_research_provider_adapter.py::test_provider_returned_userinfo_is_sanitized_before_canonical_records[discovery]` |
| Mixed safe/unsafe retrieval remains honest PARTIAL | `tests/test_research_provider_adapter.py::test_unsafe_discovery_result_with_safe_result_is_honest_partial` |
| Legitimate `@` in path/query remains valid | `tests/test_research_provider_adapter.py::test_at_outside_authority_remains_valid_end_to_end[https://example.com/path/@name]`, `tests/test_research_provider_adapter.py::test_at_outside_authority_remains_valid_end_to_end[https://example.com/path?mention=@name]` |
| Provider envelope serialization remains deterministic and lossless | `tests/test_research_provider_adapter.py::test_envelope_serialization_is_deterministic_strict_and_lossless` |

## Product-owner verification checklist

- Run the gate command and confirm 76 passed with zero failed or skipped.
- In `test_ready_envelope_is_persisted_canonically_and_strictly_reloaded`, inspect
  run start/request/provider/retrieval ordering, known publication time, source and
  evidence IDs, separate interpretation, explicit uncertainty and resolved
  contradiction, and all four configuration-identity fields.
- Confirm the immutable location is
  `<signal_id>/runs/<run_id>/research.json` and its bytes equal strict canonical
  `ResearchResultEnvelope.canonical_json()` output.
- Use `test_canonical_main_persists_ready_research_before_editorial` as the
  successful controlled READY trace.
- Use `test_canonical_main_holds_honest_exa_retrieval_before_editorial` as the
  honest Exa `NEEDS_REVIEW` trace; automatic evidence assessment is not implemented.
- Use the invocation-before-run and invalid-reuse tests as rejected traces and
  confirm Decision Lens/editorial, images, generated-package mutation, and
  publishers remain untouched.
- Use the valid `--from-package` test to confirm publication reuse makes no new
  provider call, validates the original `source_run_id`, and leaves original
  `research.json` and `generated.json` bytes unchanged. Reuse does not claim fresh
  research for the publication run.
