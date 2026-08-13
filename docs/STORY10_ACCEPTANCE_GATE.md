# Story 10 Acceptance Gate

Run the complete, offline acceptance gate from the repository root:

```bash
python3 -m pytest -m story10
```

Expected result: `10 passed`, with zero failures and zero skips (the deselected
count may grow as unrelated tests are added).
The tests use fakes at provider and publisher boundaries; no network connection,
production credentials, or live publication is required.

## What the gate proves

- The production Never Blank configuration and a separate fictional alternate
  business both pass the unchanged strict `BusinessStrategyConfiguration` schema.
- Changing configured audience, positioning, proof boundaries, claims,
  restrictions, voice, CTA rules, and Wix/LinkedIn rules changes the actual
  inputs received by research, Decision Lens, Voice, and channel composition.
- The two configurations produce different four-field configuration identities
  and hashes, and each run preserves its exact immutable strategy snapshot.
- A generated artifact or snapshot from another configuration is rejected before
  generation or publisher construction and the source run remains unchanged.
- A rejected reuse directory that contains only its create-once configuration
  snapshot is not treated as a completed run or a valid completed artifact set.

The prohibited-phrase check exercised by the underlying strategy suite is a
deterministic exact/normalized phrase guard. It is not semantic claims analysis.

## Acceptance scenario map

| Acceptance evidence | Active Story #10 node ID |
|---|---|
| Strict fictional fixture, material differences, R1/provider isolation | `tests/test_story10_gate.py::test_alternate_fixture_passes_strict_contract_without_core_leakage` |
| Missing/corrupt/inactive/blank/unknown configuration fails closed | `tests/test_story10_gate.py::test_strict_loading_fails_closed_without_defaults[missing]` and the `corrupt`, `inactive`, `blank`, and `unknown` parameter nodes |
| Research, Decision Lens, Voice, CTA, Wix, and LinkedIn inputs change | `tests/test_story10_gate.py::test_alternate_configuration_changes_actual_consumer_inputs` |
| Distinct hashes and exact immutable snapshots for two runs | `tests/test_story10_gate.py::test_two_configurations_preserve_distinct_hashes_and_exact_snapshots` |
| Foreign generated identity is rejected before side effects | `tests/test_story10_gate.py::test_cross_configuration_reuse_fails_before_generation_or_publishers[generated]` |
| Foreign historical snapshot is rejected and source bytes remain unchanged | `tests/test_story10_gate.py::test_cross_configuration_reuse_fails_before_generation_or_publishers[snapshot]` |

## Product-owner manual verification

1. Run `python3 -m pytest -m story10` and confirm zero failed and zero skipped.
2. Run with `-s` if captured stage traces are needed during review.
3. Inspect `strategy/current/business_strategy.json` and
   `tests/fixtures/business_strategy_alternate.json`; confirm that their business
   identity, audience, positioning, proof, claims, restrictions, voice, CTA, and
   channel rules are materially different.
4. Confirm the test output includes both configuration IDs and different
   `sha256:` identities when using `-s` or a debugger.
5. Confirm each successful test run has a matching `business_strategy.json` and
   `generated.json` identity in its isolated temporary run directory.
6. Confirm the cross-configuration reuse scenarios return failure before
   generation/publishers and do not modify the source snapshot.
7. Run `python3 -m pytest -m story9` and confirm the prior acceptance gate remains green.
