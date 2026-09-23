---
stream_id: ladderworks-weekly
version: "1"
role_id: ladderworks-weekly-documented-case
selection: first_valid
---

# Weekly note — CLIENT: LADDERWORKS

## Purpose

A fixture client contract whose ladder is ordered weakest first and whose
mappings are not: the second level maps lower than the first, so a claim the
client calls stronger would be allowed to assert less, and the effective ceiling
would depend on which of the two the run happened to pick.

## Selection

### Usable

- The signal names a part, a tolerance or a lead time a small shop runs.

## Plan

### claim_strength_ceiling

- observed on one shop floor → universal level 3
- confirmed by the manufacturer → universal level 2
- established across the trade → universal level 4
