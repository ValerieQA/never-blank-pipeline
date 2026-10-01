# Engine / client boundary audit

Issue #255, the audit-first deliverables. Audited against `main` at
`2b28b5edc84750a86152ac0913aeb55db0189b07`.

**This document changes nothing.** No file was moved, renamed or deleted, no
behaviour altered, no Wednesday or Friday path touched. Every ambiguity is left in
the owner-decision queue (§5) rather than resolved by inference, as the issue's
decision gate requires.

## 0 · The headline

The **Golden Engine is already almost clean, and the legacy layers are where the
customer lives.** Applying the Replace-the-client test file by file:

| Namespace | Files | With client identity in executable lines |
|---|---|---|
| `src/knowledge` | 10 | **0** |
| `src/editorial_core` | 17 | **1** |
| `src/run` | 15 | 2 |
| `src/publishing` | 20 | 9 |
| `src/strategy` | 15 | 11 |
| `src/editorial` | 26 | **15** |
| `src/analytics` | 7 | 6 |
| `src/never_blank` | 19 | 19 — *correct, it is the client namespace* |

77 of 177 files under `src/` name the customer in a line that is not a comment.
The distribution is the finding: the canonical engine and the knowledge register
are essentially generic, while `src/editorial/`, `src/strategy/` and
`src/analytics/` — generic-sounding namespaces — hold Never Blank's business
meaning as executable text.

Method note, because it changes the numbers: comment and docstring-opening lines
were excluded. A file that only *mentions* the client in prose is not a leak; a
file that hard-codes the client in a constant, a prompt body, a path or a field
name is.

## 1 · Boundary map

### ENGINE — generic, reusable, replace-the-client safe
| Path | Evidence |
|---|---|
| `src/editorial_core/` | 16 of 17 files carry no client identity. The stages take contracts, knowledge and profiles as **typed injected inputs** — `AdaptationContract`, `VoiceBrief`, `ContractDestinations`, `ReferenceLibrary`, `KnowledgeBase` — and none of them is constructed inside the engine |
| `src/knowledge/` | 0 of 10. The register loader routes records by stage; the records themselves are data |
| `src/run/` | 13 of 15. Workspace, manifest, ledger, summary, budget — machinery about runs, not about a customer |
| `src/artifacts/`, `src/models.py` | 0 |

### CLIENT: NEVER_BLANK — correctly placed
| Path | What it holds |
|---|---|
| `clients/never_blank/` (22 files) | `contract.md` (enabled destinations, voice reference, forbidden reference), `rules/K-NB-01…06`, `lenses/*`, `lists/machine_tells.md`, `streams/monday.md`, `audience.md`, `editorial/reference/` with the library index and its exemplars |
| `src/never_blank/` (19 files) | The Wednesday-July isolated path. Its own header states it *"deliberately lives in the Never Blank product namespace"* — client code that knows it is client code |
| `config/prompts/decision_lens/never_blank.yaml`, `config/prompts/editorial_acceptance/never_blank*.yaml` | Client-named profile files selected by a generic loader. **This is the good legacy pattern** |

### MACHINE / RUNTIME DATA
`reports/` — **7,993 tracked files**, generated run output. `data/` (14),
`strategy/` (26, including `published_content_index.jsonl`). Together these are
the large majority of tracked files in the repository and none of them is either
Engine or client policy.

### HISTORICAL / RETIRED
`src/never_blank/wednesday_july/` is a deliberate verbatim restoration (#207) and
is *not* stale — it is pinned on purpose. `docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`
is live authority (the K-family source). Nothing was found that is provably retired
and still registered; §3 lists what would have to be checked to claim otherwise.

## 2 · Client-policy leaks, concrete

### 2.1 In the Golden Engine — exactly one
`src/editorial_core/relevance_screen.py:110-116`

```python
RECONCILED_INSTRUCTIONS_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "config" / "prompts" / "decision_lens" / "never_blank_reconciled.yaml"
)
```

**Replace-the-client: NO.** Swap the customer and this constant still points at
Never Blank's file, so the Engine would need a code edit because the customer
changed. It is the only such line in `src/editorial_core/`, which makes it cheap
to fix and worth fixing before the pattern spreads: the neighbouring stages take
their profiles as injected values, and this one reaches out to a path instead.

### 2.2 Client prompts inside generic namespaces — 15 files
Each contains a system prompt whose body is Never Blank's business meaning, e.g.
`src/strategy/content_planner.py:44` — *"You are a content strategist for Never
Blank. Never Blank publishes evidence-led articles…"*.

`src/editorial/`: `decision_lens_lite.py`, `discovery_builder.py`, `hook_engine.py`,
`narrative_spine.py`, `never_blank_voice.py`, `pattern_extractor.py`,
`platform_composer.py`, `reader_context.py`, `story_assembly.py`, `vi_pipeline.py`.
`src/strategy/`: `content_planner.py`, `decision_engine.py`, `echo_memory.py`,
`pattern_extractor.py`. `src/publishing/`: `image_pipeline.py`.

**Replace-the-client: NO** for all fifteen. This is the largest category and the
one the canonical engine already solved by taking prompts as profile files.

### 2.3 Hard-coded brand constants in generic layers — 2
- `src/editorial/platform_composer.py:249` — `BRAND_ATTRIBUTION = "Never Blank"`
- `src/publishing/formatting.py:17` — `_SIGNATURE_PREFIX = "Never Blank"`

`src/publishing/` is otherwise the transport layer. A brand string there is the
customer's identity inside the mechanism that delivers it.

### 2.4 Client identity in a generic data model — 2 declarations
`src/lifecycle/signal_lifecycle.py:158` and `:541` — `never_blank_angle: str`, plus
`"NEVER_BLANK_ANGLE"` keys at `:233` and `:330`. A field named for the customer in
a lifecycle type means another customer inherits a column named after Never Blank.

### 2.5 Client visual policy in the publishing layer
`src/publishing/image_pipeline.py:147,152` — *"Never Blank grid requires dark
premium aesthetic"*, *"White backgrounds are rarely appropriate for Never Blank
covers"*. Editorial/brand judgement expressed as engine validation.

## 3 · Historical and stale references

`config/` carries client policy under **generic names** — `brand.yaml`,
`brand_voice.md`, `content_matrix.yaml`, `intelligence.yaml` — alongside genuinely
generic settings. 22 of 45 files under `config/` mention the customer.

**There are three client homes**, which is the legibility problem in one line:

1. `clients/never_blank/` — the canonical one, human-readable and externally editable
2. `config/never_blank/wednesday_golden.yaml` — a second, one file deep
3. `config/prompts/*/never_blank*.yaml` — a third, as client-named profiles

Nothing here is *stale* in the sense of retired-but-registered; it is **scattered**,
which is a different defect and the one §4 addresses. One real duplication was
already recorded separately in #337: `config/machine_tells/shared.yaml`
(`engine-machine-tells`, tier `directional`, 8 entries) and
`clients/never_blank/lists/machine_tells.md` (`never-blank-machine-tells`, 30
entries) are two different lists, not two copies, and three of the engine list's
five literal texts have a client counterpart that is the shorter core of the same
phrase.

## 4 · Proposed minimal organization

Smallest coherent scheme, no new layer invented — it is what `clients/never_blank/`
and `src/editorial_core/` already do, applied to the rest:

```
src/            ENGINE only. No customer name in an executable line.
src/<client>/   client code that knows it is client code (today: src/never_blank/)
clients/<id>/   the one home for a customer's human-readable contracts:
                  contract.md, rules/, lenses/, lists/, streams/,
                  editorial/reference/, audience.md, voice/
config/         engine settings that are not any customer's policy
reports/, data/, strategy/   runtime and generated state
```

Two rules make it checkable, and both already hold for the canonical engine:

1. **A generic module never names a client.** Client content arrives as a typed
   injected value or a profile selected by identifier.
2. **A client's policy has one home.** `clients/<id>/`. A client-named file
   anywhere else is either moved there or explained.

A future customer then needs a new `clients/<id>/` and no fork of `src/`.

## 5 · Owner-decision queue

The issue's gate says ambiguous ownership stops at a Product Owner decision. Five
genuine ambiguities, each with the competing readings:

| # | Subject | Engine capability | Client policy | Configurable mechanism |
|---|---|---|---|---|
| 1 | `config/prompts/blog_post.yaml`, `linkedin_post.yaml`, `telegram_post.yaml`, … (generic names, client content) | per-destination prompt shape is an Engine capability | the wording is Never Blank's editorial voice | Engine owns the slot, client supplies the body — needs one `clients/<id>/` home |
| 2 | `config/brand.yaml`, `content_matrix.yaml`, `intelligence.yaml` | scoring/matrix machinery is generic | the values are this customer's strategy | probably (3), but which keys are which is the decision |
| 3 | `src/analytics/` (6 of 7 files name the client) | analytics is generic | the metrics encode Never Blank's definition of performance | not audited deeply enough to propose — flagged |
| 4 | `reports/` — 7,993 tracked generated files | — | — | is generated output tracked on purpose, or is this accumulated state? Affects portability and repo size, and is not mine to decide |
| 5 | `src/never_blank/wednesday_july/` | — | pinned verbatim restoration (#207) | when Wednesday is re-expressed as contracts on the shared Engine, does this tree retire? #255 records that intent; the timing is the owner's |

Not in the queue, because the evidence answers them: §2.1–2.5 are leaks by the
Replace-the-client test with no competing reading.

## 6 · Migration slices, ordered so nothing working breaks

1. **`relevance_screen.py`'s path constant** — inject the profile path instead of
   naming the file. One constant, one call site, the Golden Engine becomes clean.
   Smallest possible first slice and it proves the pattern.
2. **`never_blank_angle` → a neutral field name** in `src/lifecycle/`, with the
   serialized key preserved for compatibility. Mechanical, no behaviour change.
3. **The two brand constants** (§2.3) become client-supplied values through the
   contract that #337 already loads.
4. **One client home** — move `config/never_blank/` and the client-named prompt
   profiles under `clients/never_blank/`, leaving loaders pointing at the new
   location. Touches no prompt text.
5. **The 15 embedded prompts** (§2.2) become profile files. Largest slice, and it
   must come last because it is also the one that changes what live prompts say if
   done carelessly — each file needs its own bounded change with the prompt body
   moved verbatim.

Slices 1–4 are mechanical and provable. Slice 5 is not one slice; it is fifteen,
and it should not start before the owner answers queue item 1.

## 7 · Enforceable checks

Two tests would hold the boundary without further judgement:

1. **No client name in an Engine executable line.** Scan `src/`, excluding
   `src/<client>/` namespaces, for customer identity outside comments and
   docstrings. It would fail today on the 77 files in §0 — so it lands last, or
   lands now with an explicit allowlist that shrinks as slices complete. The
   allowlist is the migration's progress bar.
2. **One client home.** No client-named file outside `clients/<id>/` and
   `src/<client>/`. Fails today on §3's three homes; passes after slice 4.

A narrower version of (1) is available immediately and worth having on its own:
**`src/editorial_core/` and `src/knowledge/` must contain no client name at all.**
That is true today for 26 of 27 files, and slice 1 makes it true for all of them —
a check that starts green and stays green protects the engine that matters most.

## 8 · Not done here

No migration, no move, no rename, no deletion. No Wednesday or Friday behaviour
touched. No client knowledge decided. No paid or live call. Implementation of any
slice above remains separately bounded, as the issue requires.
