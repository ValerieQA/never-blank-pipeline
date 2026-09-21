# Checkpoint after Step 6

*Implementation architecture · 21 September 2026 · for GPT review. After acceptance, the next phase is turning slices into issues, then orchestrator tasks. Cowork does neither.*

**Document:** `07_STEP6_VERTICAL_SLICES.md`

Nothing was written to GitHub. No code. No generation.

---

## 1. What Step 6 contains

| Part | Content |
|---|---|
| §0.1 | **CE-1** canonical-engine invariant, stated verbatim from the review and made checkable: one topology registry; a topology digest in every manifest; a CI placement rule (no weekday or clock decisions in the editorial core, no stage selection by destination); the clone check |
| §0.2 | Rules for every slice: six destinations from the start; no production impact before SL-11; no human in the run; evidence of done; **measure before optimizing**; each slice mergeable on its own |
| §1 | Slice dependency map |
| §2 | 15 slices, each with goal, what it builds, proof, production safety, non-goals and dependencies |
| §3 | Coverage check against entities, stages, invariants, publication safety, six destinations, budget and retirement of current paths |

## 2. The slices

| Slice | Capability | Proves |
|---|---|---|
| SL-0 | C0 publication safety | No double publication (fault injection over all six destinations) |
| SL-1 | Canonical skeleton | One topology (digest equal across configurations), trace, ledger, ARP, counters, CE-1 CI rule |
| SL-2 | Knowledge register v0 | Validator, loader, weak-candidate limits, mandatory containment; `K-DST` for all six |
| SL-3 | Evidence Core (S-00…S-03) | Real cores with references; #58 profile reconciled |
| SL-4 | Boundary (S-04, S-05) | Walkthrough regressions (uranium SKIP, Ramp, breakfast founder); boundary commit |
| SL-5 | Planning ×6 (S-06…S-11) | An approved plan per destination; V-P02 and V-P03 behaviour; independent openings |
| SL-6 | Writing + checks ×6 (S-12, S-13) | Ownership-based routes, including the R2 branches |
| **SL-7** | **Six-destination canonical shadow run + budget baseline** | **Measured calls and tokens per stage and destination; no optimization; sets the ceiling** |
| SL-8a–d | Capability: Facebook, Instagram, Threads, Telegram | Package, preflight, markers, collector; Instagram image |
| SL-9 | Capability: Wix, LinkedIn on canonical texts | No LinkedIn recomposition; conditional link |
| SL-10 | Optional optimization | Only after SL-7; per-lever non-regression; scope never reduced |
| SL-11 | Canonical run live | Single publisher; current triggers repointed or retired in the same change; go-live gate; **complete when all six publish** |
| SL-12 | Observation ×6 (S-15) | Raw metrics; queue items; blended score removed |
| SL-13 | Clone check | Configuration-only change, same topology digest, full six-destination run |
| SL-14 | Removal | Unreachable legacy code deleted |

## 3. For the reviewer

1. **Go-live gate (SL-11).** Hard-check failures 0; manifest verification 100 %; label violations 0; fault-injection duplicates 0; cost within the measured ceiling; plus an **offline owner quality review**. The number of consecutive shadow runs is set at planning. The owner review is the owner's decision, offline, and never a per-run gate.
2. **Partial go-live is allowed only as rollout scope.** A destination whose capability slice is not done runs `generate_only` inside the same canonical run. The run is complete only when all six publish.
3. **No open architecture questions remain.** Items still to test, carried into slices:
   - the LinkedIn digest mismatch (SL-0 / SL-9);
   - Wix lookup by slug (SL-0);
   - the default artifact retention (SL-0).

---

## Кратко по-русски (для Светы)

- **Шаг 6 готов:** работа нарезана на 15 проверяемых кусков, все шесть площадок — с самого начала.
- **Правило «один движок, дни и площадки — только настройки» теперь проверяется автоматически.**
- **Отдельный кусок (SL-7) — замер реальной стоимости** на шести площадках до любой оптимизации.
- **Включение** — только после твоей выборочной оценки текстов вне прогона.
- **Архитектура на этом закончена.** Дальше GPT или Claude Code превращают куски в задачи на GitHub.
