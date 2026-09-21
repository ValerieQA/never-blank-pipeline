# Research provenance for the Canonical Editorial Map v1

*Issue #283 · 21 September 2026 · design authority: `CANONICAL_EDITORIAL_MAP_v1.md`*

This index lists every document the map was built from: where it lives, which language it is in, what it covers and which parts of the map rely on it. The map's evidence codes are explained in its section 0.

## Documents in this folder

| File | Language | What it is | Map sections that rely on it |
|---|---|---|---|
| `CANONICAL_EDITORIAL_MAP_v1.md` | EN | **Design authority.** Final spec: invariants, entities, flow S-00…S-15, precedence, Autonomous Resolution Protocol, knowledge register, checks, memory, observability, walkthroughs, open items | — |
| `research/REPO_TRACK_87ea0f4.md` | EN | Read-only analysis of `never-blank-pipeline` at `87ea0f4`: what the current engine executes, where each AI-shaped behaviour is produced, engine vs client conflicts, gap matrix, reconciliation with #277/#281 | Evidence code `REPO`; §5.3 facts a–j are the Teardown/current-engine debt recorded in #281 |
| `research/EDITORIAL_KNOWLEDGE_MAP_v0.1_superseded.md` | EN | First knowledge map (66 entries, 3 walkthroughs). **Superseded** by v1; kept for traceability of entry IDs and corrections | Origin of most `K-*` IDs |

## Documents not yet in the repository

These are in the Claude project workspace. They are in Russian unless noted. Under the project's language rule they need an English version before they go into the repository.

| Document | Language | What it covers | Map evidence it supports |
|---|---|---|---|
| External research: editorial mechanisms for AI writing, extended for US and international audiences | RU | Planning before generation, exemplars vs rules, why AI prose reads as AI, editorial workflows, multi-stage architectures, controlled variation, measurement, products; 13 article teardowns; LinkedIn short-form; US SMB/B2B readers; global-English readers; AI marketing field experiments | `RES`, `VEND`, `OBS`; `K-PRC-*`, `K-MAT-*`, `K-OPN-*`, `K-REV-*`, `K-CON-*`, `K-END-*`, `K-RDR-*`, `K-EXM-*`, `K-DIV-*`, `K-DST-LI-*` |
| Research: AI content on Instagram, Facebook, Threads, Telegram | RU | How each platform treats AI text and media, what authors can see, what performs | `PLAT`, `VEND`; `K-DST-META-*`, `K-DST-FB-*`, `K-DST-IG-*`, `K-DST-TH-*`, `K-DST-TG-*`, `K-DST-ALL-01` |
| GPT research: designing an AI newsroom that writes specifically | RU | STORM, DOME, DPWriter, style-imitation and human-detection studies, contemporary corpus | Supporting `RES` for `K-PRC-01`, `K-PRC-05`, `K-PRC-07`. Citations not independently re-verified |
| Cross-review rounds 1–4 (Claude ↔ GPT) and flow map v2 | RU | Decisions that shaped v1: siblings, Evidence Core → Interpretation Boundary, editorial units, strategy bundle, precedence, autonomy | Invariants I-01…I-13, §5, §6, §7 |
| Sample pack of real engine outputs (2026-09-15) | RU with EN bodies | 12 real article and post bodies from the engine's history | `OBS`; tempting inadmissible interpretations in walkthroughs B and C |
| `NBX-engine` runs: Invisalign dry-run, routed repeat after #279/#280, historical 11-element control, `stage_routing.json` | GitHub Actions artifacts | Controlled runs of the current engine | `NBX-engine`. **Claude did not see the primary artifacts**; entries citing them rely on descriptions in #277/#283 |

## Rules for this provenance

1. **Research is evidence, not policy.** A finding enters the system only through a knowledge record with a status and a tier (map §8.1). No finding becomes a hard check without approval (I-13).
2. **Platform knowledge expires.** `K-DST-*` records were checked on 2026-09-21 and must be reviewed by 2026-12-21. After that they are automatically demoted (map §6).
3. **Unverified inputs are marked.** GPT-research citations and `NBX-engine` artifacts are marked as not independently verified wherever they are used.
