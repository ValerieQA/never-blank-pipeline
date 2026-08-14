# Story #12 acceptance — Decision Lens on the canonical Release 1 path

Issue #61. Gate: `python3 -m pytest -m story12` — **20 passed, 0 failed,
0 skipped** (all through the real production entrypoint; injected deterministic
evaluator/provider fakes; no live LLM/network/publication calls).

The business process proven end to end:

    current research → Decision Lens evaluation → canonical immutable decision
    → persisted/reloaded business gate → downstream work only for PROCEED

## Criterion → acceptance node IDs

All node IDs are in `tests/test_story12_gate.py`.

| # | Acceptance criterion | Node ID(s) |
|---|---|---|
| 1 | Controlled current-run research reaches the actual production Decision Lens; evaluator receives exact trusted research/strategy/audience/execution context; `decision.json` persisted before narrative/editorial; strict-reloaded PROCEED authorizes downstream | `test_s12_proceed_lifecycle_authorizes_downstream_through_production_path` |
| 2 | Two runs cannot share or overwrite `decision.json` | `test_s12_two_runs_cannot_share_or_overwrite_decision_json` |
| 3 | `run_id`/`assignment_id`/`signal_id` independent across research → evaluator → persisted decision → strict reload | `test_s12_independent_identities_preserved_research_to_reload` |
| 4 | `REVISE`/`HOLD`/`REJECT`/`INSUFFICIENT_EVIDENCE` are business stops with zero downstream effects (decision persisted honestly) | `test_s12_non_success_disposition_is_a_business_stop[revise\|hold\|reject\|insufficient_evidence]` |
| 5 | Contract blocks continuation on blocked evidence (rejected citation with PROCEED) | `test_s12_blocked_evidence_contract_violation_stops` |
| 6 | Unsupported claim cannot proceed | `test_s12_unsupported_claim_cannot_proceed` |
| 7 | Invalid evidence/source citation stops, nothing persisted | `test_s12_invalid_citation_stops` |
| 8 | Malformed evaluator output / transport error / timeout stop with no synthetic decision | `test_s12_malformed_output_and_evaluator_failure_stop[malformed-output\|transport-error\|transport-timeout]` |
| 9 | Cross-run, research-digest, audience, configuration, and lens-profile mismatch fail closed at the production reuse boundary | `test_s12_lineage_mismatches_fail_closed_at_the_production_boundary` |
| 10 | `--from-package` reuses the original immutable decision: Decision Lens never re-run, artifacts never rewritten | `test_s12_reuse_preserves_original_decision_without_reevaluation` |
| 11 | Missing/corrupt/non-canonical source decision blocks reuse before side effects | `test_s12_invalid_source_decision_blocks_reuse_before_side_effects[missing\|corrupt\|non_canonical]` |
| 12 | No prompts, provider objects, credentials, or raw exception content in persisted artifacts | `test_s12_no_prompts_secrets_or_provider_objects_in_persisted_artifacts`, `test_s12_credentialed_evaluator_failure_leaks_nothing` |

Zero-side-effect proof (criteria 4–8, 11) asserts, through the real
entrypoint: no narrative/article generation, no hook/story/voice or platform
composition (all behind `generate_article`), no visual/image preparation, no
generated package, no Wix or LinkedIn publisher calls, no publication/history
effects. Unresolved contradiction / material uncertainty blocking is enforced
by the #58 contextual contract exercised by these same paths (unit-proved in
`tests/test_decision_lens_contract.py::test_proceed_cannot_ignore_unresolved_research_blocker`).

## Representative traces (real entrypoint output)

**PROCEED (dry-run):**

    ✓  research: READY (…/sig-test-001/runs/391ff26c-…/research.json)
    ✓  decision: PROCEED (…/sig-test-001/runs/391ff26c-…/decision.json) [never-blank-decision-lens/1.0]
    ✓  Saved …/sig-test-001/runs/391ff26c-…/generated.json

**HOLD (canonical business stop; decision persisted, run exits 1):**

    ✓  research: READY (…/runs/82953ffb-…/research.json)
    ERROR: decision gate blocked generation: Decision Lens disposition is 'hold' —
    the run stops before any narrative, editorial, visual, package, or publisher work

**Invalid citation (evaluator failure; nothing persisted, run exits 1):**

    ✓  research: READY (…/runs/20181e31-…/research.json)
    ERROR: decision gate blocked generation: Decision Lens evaluation failed
    (invalid_citation): decision cites evidence absent from current-run research: evidence-invented

## Prior story gates and CI

- Story #9: 43 passed · Story #10: 10 passed · Story #11: 76 passed (0 failed each)
- Focused dependencies: #58 76 passed · #59 35 passed · #60 25 passed
- Full suite: failure node IDs exactly match the accepted 16-entry baseline
  (`tests/accepted_full_suite_failures.txt`); independently enforced by the
  repository `PR Tests` CI gate.

Story #12 closes only after independent review and product-owner acceptance.
