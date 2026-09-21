# Architecture decisions: OPEN-15, OPEN-18, OPEN-19, OPEN-21 and decisions made in Step 1

*Implementation architecture · 21 September 2026 · design authority: `CANONICAL_EDITORIAL_MAP_v1.md` · evidence: `00_STEP0_ARCHITECTURE_IMPACT_DELTA.md`, cross-review rounds 3–4, map walkthroughs A–D*

These are engineering and architecture decisions. None of them is a product fork for the owner. Each one records the decision, the alternatives considered, the rationale, and what would reverse it.

**Status of every decision below: ACCEPTED for architecture.** Its thresholds and limits are implementation parameters (OPEN-22, OPEN-25), not part of the decision. Two decisions accept the architecture without enabling production behaviour: **AD-03** (architecture resolved; production behavior disabled pending observation) and **AD-04** (schema ready; behaviour deferred).

---

## AD-01 · OPEN-19: where the strategy lives — Model C, with a leading-material set

**Decision.** Model C.

- **Shared across all destinations of an Editorial Unit:** Evidence Core, Interpretation Boundary, anchor interpretation, and a **leading-material set** of one or two items (evidence claims or assets).
- **Per destination:** the full Editorial Strategy (editorial job, angle, thesis within the anchor, focal subject, reader path, opening, reveal, concession placement, ending) and all adaptation.
- **Link between the two:** each destination strategy must foreground and use at least one member of the unit's leading-material set as its **primary evidentiary carrier**. It does not have to appear in the first line or the opening move. Opening and reveal mechanics stay independent per destination (`opening` and `leading_material_ref` are separate fields of E-13).
- **Size of the set:** one by default. A second item is allowed only if both items support the anchor.

**Alternatives considered**

| Option | Why rejected |
|---|---|
| **A.** One strategy per unit; destinations only adapt | The shared strategy becomes a hidden parent and breaks I-06 in substance. The current engine is effectively A (LinkedIn is recomposed from the accepted Wix article). That is what forced a fidelity judge on the derivative and what produces identical arcs across channels |
| **B.** Fully independent destination strategies over a shared core | Nothing but V-P03 holds the texts together. One signal can produce six unrelated stories, and planning cost is highest. Without shared leading material a reader who sees two posts cannot tell they are the same story |
| **C with exactly one leading item** (the map's literal wording) | Over-constrains short forms. On Ramp (walkthrough B), the article carries its argument on the payment timeline while a Threads post may carry it on the one figure. Forcing the same item on every destination reintroduces a soft parent |
| **Leading material must be the opening** | Merges two separate strategy fields and makes every destination open the same way. That is a hidden template, the failure the destination-strategy research was meant to remove |

**Rationale.** C is the only option in which consistency comes from the evidence layer (anchor, leading material) and variety comes from the decision layer (strategy). That is the split the map already makes in §7.4 and in the decision-vs-adaptation criterion. The walkthroughs B and D run cleanly under C. `K-PRC-03` (choose among whole variants) is satisfied per destination.

**What would reverse it.** Observation showing that V-P03 fails often under C (the destinations drift from the anchor), or that texts of one unit are near-identical despite separate strategies. Both are measurable from fingerprints. Moving toward B means relaxing a constraint, so the decision is cheap to revisit.

**What it does not decide.** How many model calls planning takes. C allows one planning call per unit that returns per-destination candidates, but call structure stays OPEN-06.

---

## AD-02 · OPEN-15: which destinations a unit gets — deterministic eligibility, exclusion only by recorded reason

**Decision.** S-07 is a **deterministic** step, not a model judgment.

1. **Eligible destinations** = destinations enabled in the Client Contract, minus those the contract excludes for this unit's topic or risk level (tier 2), minus those whose **hard platform policy** forbids the material (tier 1).
2. **Cadence.** Per-destination cadence and portfolio pressure can defer a destination for this unit. A deferral is recorded as `SKIP` with reason `cadence`.
3. **Mode: target capability versus rollout scope.** Two separate inputs decide the mode. They must never be confused.
   - **Destination capability (target architecture).** The target supports six sibling destinations: Wix, LinkedIn, Facebook, Instagram, Threads, Telegram. A destination is **capable** when it has a publisher, package, preflight, an idempotency authority (Step 3 §3.6) and a metrics collector.
   - **Rollout scope (migration compatibility, temporary).** A deployment setting listing which capable destinations are switched on for publishing. During migration and shadow it may be narrower. The current `R1_PUBLISH_CHANNELS` (Wix + LinkedIn) is an **AS-IS fact** about today's release, not a target constraint.
   - A destination is `publish` when the client contract enables it, it is capable, and the rollout scope includes it. Otherwise it is `generate_only`, **as a temporary migration state**. The finished canonical run publishes to all six (owner product frame, patch CANONICAL-SCOPE).
4. **Material fit is not a selection step.** A destination for which no admissible strategy exists fails at S-08/S-11 and ends in a destination-level `SKIP` with that reason. Fit emerges from planning. It is never predicted up front.
5. **Publication dependencies are recorded separately** from content. Example: the LinkedIn post links to the Wix article. If the target of a link is skipped, the linking plan drops the link in adaptation (`DEGRADE`). The dependency never makes one text the source of another (I-06).

**Alternatives considered**

| Option | Why rejected |
|---|---|
| Always all six destinations | Ignores contract exclusions, risk level, hard platform policy and cadence. It floods the calendar |
| The model chooses destinations "by material" | This is a hidden routing decision made before strategy, on something close to a label ("this is an Instagram story"). It cannot be verified. Afterwards "no strategy fits" cannot be told apart from "the model preferred not to try". It conflicts with I-10 and I-11 in spirit and weakens the skip-rate indicator (ARP §6.3) |

**Rationale.** A deterministic S-07 makes every exclusion explainable by one rule and one tier. It keeps the skip rate per destination and reason clean. It keeps the one real material judgment, "can this destination tell this anchor honestly", inside planning, where V-P checks exist. The extra cost of trying a destination is a planning call that fails at S-11 before any prose is written.

**Change to Canonical Map v1.** In the S-07 row, the decider changes from "Model + contract" to "Code (contract, platform policy, destination capability, rollout scope, cadence)". `K-DST-*` knowledge moves from S-07 to S-08 and S-10, where it already acts.

**What would reverse it.** A high, stable rate of destination `SKIP` at S-08 for one destination and one material pattern. That would show that an up-front filter pays for itself. The filter would then be added as a **recorded, rule-based** exclusion (a tier-2 contract rule or a tier-3 knowledge record), not as a free model choice.

---

## AD-03 · OPEN-18: when a signal is split into units, and how the calendar absorbs it

**Status: architecture resolved; production behavior disabled pending observation.** Until the cap is raised by an explicit decision, no second unit is created or deferred in production. Implementers must not build split execution as live behaviour on the strength of this record.

**Decision.** A signal is split into more than one Editorial Unit only when **all** of these hold:

1. **Independence.** The Interpretation Boundary contains at least two admissible interpretations, and neither depends on the other: one is not a premise, consequence or restatement of the other (field `depends_on` on E-08).
2. **Separate support.** Each candidate anchor rests on at least one evidence claim that the other does not use.
3. **Standalone viability.** Each unit passes S-06 on its own, with its own evidentiary asset. A unit that needs the other's asset is not a unit.
4. **Cap.** The number of units per signal has a configured maximum.
5. **Calendar.**
   - Only one unit per signal enters the current publication slot: the strongest anchor, chosen with the §7.3 tie-breakers.
   - Every other unit is stored as `deferred`, with an expiry derived from the freshness of its evidence.
   - Deferred units re-enter S-00 as selection candidates alongside new signals, under the same portfolio pressure.
   - An expired unit ends in `SKIP` with reason `expired`.

**Initial configuration.** The maximum starts at **1**. With cap = 1, S-05 evaluates rules 1–3 and records a `split_candidate` in the run trace, and nothing else: **no additional unit is created, stored or deferred**, and no deferred unit re-enters S-00. Splitting is observed before it is enabled. Enabling it later is a configuration change plus an explicit decision based on the traced split-candidate rate, not an architecture change.

**Alternatives considered**

| Option | Why rejected |
|---|---|
| A core with several anchors | Rejected in round 4. It breaks I-07 and makes V-P03 undefined |
| Never split | Loses real two-story signals (walkthrough D). It forces the anchor to choose and discards the second story silently |
| Split freely, publish all units at once | One rich signal fills the week with one topic. Thin units appear that each fail the anchor test on their own |

**Rationale.** The three safeguards from round 4 become testable conditions on typed fields. The calendar problem is solved at the only place that already sees the whole queue (S-00), not by a second scheduler. Starting at a maximum of 1 is consistent with how OPEN-P1 is handled: measure the real rate first.

**Consequence for Step 3.** An Editorial Unit can outlive the run that created it. Storage must be keyed by unit as well as by run and signal. A run can start from a deferred unit. If the unit's evidence has not expired, the run reuses the stored core and boundary. Otherwise it re-researches.

---

## AD-04 · OPEN-21: several signals into one unit — schema ready, behaviour deferred

**Decision.**

- **Schema: many-to-many.** An Evidence Core and an Editorial Unit reference a **list** of signal IDs (at least one). Every source observation keeps the signal it came from.
- **Behaviour now: one-to-many.** One signal can become one or more units. No component builds a core from several signals.
- **Future capability.** Merging (a roundup, "three reports on one mechanism this week") is a future S-00 capability. It would add a step that composes a core from several signals' research, followed by the normal flow from S-02.
- **Storage.** Run artifacts and units are keyed by `run_id` and `unit_id`. Signal IDs are attributes, not the only key.

**Alternatives considered**

| Option | Why rejected |
|---|---|
| Design merging now | There is no evidence yet that Never Blank needs roundups, and no content form for them is defined. It would add a new S-00 mode without a slice to prove it |
| Ignore merging | Storage is currently keyed by `signal_id` (`reports/content_packages/<signal_id>/runs/<run_id>/`). Keeping a single-signal key would make merging a data migration later |

**Rationale.** A list costs nothing now and keeps the door open. The behaviour stays out of scope until there is a reason to build it.

**Product note.** Whether Never Blank publishes roundups or trend pieces at all is a content-product question. It is **not** raised with the owner now, because nothing is blocked by it.

---

## Decisions made while writing Step 1

| ID | Decision | Alternatives | Rationale |
|---|---|---|---|
| **AD-05** | E-02, E-03 and E-04 **wrap** the existing research contract (`SupportReference`, `ExtractedEvidence`, `NormalizedResearchArtifact`). The field `ExtractedEvidence.claim` maps to `evidence_claim.statement`. The existing field is not renamed in place | Rebuild the evidence types; rename the field in place | The contract is immutable, typed, referentially checked and on the R1 path. Renaming a serialized field breaks stored artifacts. A mapping keeps the ontology clean without migrating data |
| **AD-06** | E-08 Interpretation and E-09 Interpretation Boundary are **new** entities that reference evidence by ID. `ModelInterpretation` is not extended | Add strength, admissibility and limits to `ModelInterpretation` | `ModelInterpretation` has no producer. It lives inside the research artifact, which is created before the enrichment loop. The boundary has to be versioned after enrichment. Overloading the research type would couple the two lifecycles |
| **AD-07** | Labels (`material_label`, strategy label, form label) live in a separate **label record**, written after the decision. It is never routed to S-00…S-13; `stage_routing` proves this per run. Label generation is **post-decision observability only**: it is not required for successful generation or publication, is not a synchronous step of the run, and may be code-based, batched, asynchronous, or absent when unavailable. A missing label never fails a run | Keep `material_label` inside E-05, as the map says | I-10 becomes a structural property that can be checked in the trace, instead of a promise |
| **AD-08** | `interpretation.audience_transfer` (`direct_audience` / `bounded_external_case`) is a first-class field of E-08. It reuses the meaning of #58 `EditorialClaimMode` | Leave transfer implicit in "consequence for the reader" | The current gate already makes this distinction, and it is exactly the error behind "you, the reader, bake at night" and "the business has more money" |
| **AD-09** | The #58 decision gate's `supported_editorial_angle` and `defensible_perspective` do not decide anything in the target. They may be recorded as hints. Its fit, relevance and claim-mode outputs feed S-00 and S-04. Final verdict in step 5 | Keep the gate as is; delete it | Two components must not decide the angle. The gate's stop semantics are compatible with I-01 and worth keeping |
| **AD-10** | Strength is a position on **one ordered ladder per run**: the client's declared ladder (`claim_strength_ceiling` values, as today) if one exists, otherwise a universal default ladder. Evidence claims and interpretations use the same ladder. The ceiling is a position on it | Separate scales for evidence and interpretation; numeric strength | Keeps the existing client-contract mechanism. It makes "thesis inherits the ceiling of the weakest interpretation" a simple minimum. The Never Blank Monday stream declares no ladder today, so the default is needed. The default's wording is a Step 4 item |

---

## Кратко по-русски (для Светы)

Четыре открытых архитектурных вопроса решены. К тебе ни один не идёт: это инженерные решения.

- **OPEN-19. Модель C.** Общие у всех площадок одной единицы: факты, граница интерпретаций, якорь и один-два «ведущих материала». Ведущий материал — главная опора текста, но не обязательно его начало: с чего начать, каждая площадка решает сама. Всё остальное площадка тоже выбирает сама. A отвергнута, потому что это скрытый «родитель», ровно как сейчас LinkedIn пересказывает статью Wix. B отвергнута, потому что это шесть несвязанных историй.
- **OPEN-15. Площадки выбирает не модель, а правила**: договор клиента, жёсткие правила площадки, частота публикаций, что разрешено публиковать. Если площадке нечего честно сказать, это выяснится при планировании, и она будет пропущена с записанной причиной.
- **OPEN-18. Сигнал делится на две единицы только при строгих условиях**: две независимые мысли, у каждой свои доказательства и свой актив. Вторая единица не публикуется сразу, а ждёт своей очереди, пока не устарела. **Статус: архитектура решена, в продакшене деление выключено до наблюдений.** Система только записывает, где могла бы делить; вторая единица не создаётся и не откладывается. Включим отдельным решением, когда увидим цифры.
- **OPEN-21. Объединение нескольких сигналов в одну историю** не делаем, но хранение устроено так, чтобы потом это можно было добавить без переделки.
- Ещё шесть решений по ходу (AD-05…AD-10). Главное: доказательства строим на уже существующем коде, а метки («Разбор», «Находка») хранятся отдельно, и планировщик их физически не видит.
