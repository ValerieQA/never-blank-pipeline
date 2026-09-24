# Decision Lens profile reconciliation — revision 1.3 (Issue #299)

The reconciliation #151 deferred and Step 5 §1.2 of
`docs/editorial/architecture/06_STEP5_MIGRATION_MAP.md` then defined, applied to
`config/prompts/decision_lens/never_blank.yaml`. Step 5 calls it the
**precondition for cutover**: the #58 Lens becomes the S-01 relevance screen for
every target path, so the profile has to say what the target actually consumes.

This is the reasoning the acceptance evidence asks for beside the diff.

## What #151 was waiting for

The switch at `scripts/generate_and_publish.py:1493-1549` sends a role with
`decision_policy == "role_bounded_r1"` to `decision_policy.json` and everything
else to the #58 Lens. Both Never Blank roles are `role_bounded_r1`, so **only the
research Friday/Sunday path uses #58 in production**. The bypass was deliberate
and is documented at `:1478-1486`: the Lens's audience-transfer rules predated
the corrected Monday strategy, and a live Wednesday run was stopped with
`revise`. That is the #151 debt — a gate whose semantics no longer matched the
engine around it, left in place and routed around.

Step 5 §1.2 resolves it in four verdicts, and revision 1.3 is those four
verdicts written into the instructions:

| Verdict (Step 5 §1.2) | What revision 1.3 says |
|---|---|
| `revise` / `hold` become an enrichment REPLAN, not a stop | The dispositions section states that `revise`/`hold` "is not a stop and not a request for a better angle: it sends the signal back for more research on the gap your disposition_reasons name", and asks which of evidence or audience connection is missing |
| `reject` / `irrelevant` / `insufficient_evidence` → `SKIP` | Each is described as what it is: not for this audience and more research would not change that, or the evidence does not carry an audience judgment either way |
| Angle fields: recorded as hints only | A new section says `supported_editorial_angle` and `defensible_perspective` "are recorded as hints and are consumed by nothing", and that a good angle is not a reason to proceed nor its absence a reason not to. The `proceed` bullet no longer requires them |
| Relevance plus claim mode feed the boundary (AD-08) | Claim mode is named as "the one judgment of yours that binds a later stage", with the mapping spelled out: `direct_audience_claim` → `direct_audience`, `bounded_external_case` → `bounded_external_case` |

## What changed in the file

- `version: "1.2"` → `"1.3"`. The file's own rule is that "changing judgment
  semantics requires bumping `version` in a reviewed commit", and this changes
  what the Lens is asked to decide on.
- Three instruction sections: the claim-mode bullet list gains the
  audience-transfer mapping; a new "What your judgment decides, and what it does
  not" section demotes the angle fields; the dispositions list says what each
  disposition is acted on as.
- A header comment recording why the profile identity did not move.

## What did **not** change, and why

- **`profile_id` / `profile_version` stay at `never-blank-editorial-lens` /
  `1.2`.** The file distinguishes the two concepts itself: profile identity is
  the complete lens profile these instructions implement, `version` is the
  instruction revision. The judgment's fields, its relevance bar, its two claim
  modes and its two criteria are all unchanged, so the profile is the same
  profile. Moving `profile_version` would also mean moving
  `RELEASE1_LENS_PROFILE` in `src/editorial/decision_lifecycle.py`, and every
  `decision.json` already written would fail lens-profile revalidation on reuse
  through `--from-package`. A reconciliation that invalidated the stored
  decisions of past runs would be a migration, not a reconciliation.
- **The decision contract.** `src/editorial/decision_contract.py` is untouched:
  `supported_editorial_angle` and `defensible_perspective` are still required
  fields of `DecisionLensJudgment`, so every artifact already written still
  validates. AD-09 says the angle fields "may be recorded as hints" — recorded
  is exactly what they are. Deleting them from the contract to enforce AD-09
  would have broken the artifacts it was protecting.
- **The evaluator.** `_ALLOWED_OUTPUT_KEYS` is unchanged, so the response shape
  the model must return is the same shape as before.

## Where "hints decide nothing" is checked rather than promised

`src/editorial_core/relevance_screen.py` makes AD-09 structural instead of
textual. `RelevanceAssessment.for_boundary()` returns a `BoundaryInput` carrying
relevance, the audience transfer and the relevance bases — and there is nowhere
in that type to put an angle. The hints are kept beside it, in the written
entity, with `consumed_downstream: false` in the record itself so a reader of one
relevance reference can see the rule without knowing AD-09.
`tests/test_299_evidence_core.py` asserts both halves: the hints are present in
the assessment and in `decision.json`, and absent from everything S-04 receives.

## Production effect, stated plainly

The only live path that reads this profile is research Friday/Sunday (no
`--editorial-role`). On that path the Lens is now asked for relevance and claim
mode and told that the angle decides nothing, so a signal with direct relevance
and sufficient evidence but no compelling angle can now be `proceed` where it
might previously have been `revise`. That narrowing **is** the reconciliation
Step 5 required: two components must not decide the angle, and the angle fields
were already consumed by nothing (Step 5 §1.2: "VERIFIED. AD-09 is already true
in practice").

Nothing else moves. The canonical S-01 that consumes this screen
(`src/editorial_core/`) is reached by no live script, makes no external publish
call, and runs only where a caller constructs it.
