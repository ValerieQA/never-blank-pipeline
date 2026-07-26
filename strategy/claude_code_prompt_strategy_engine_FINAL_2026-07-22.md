# Strategy Engine — Final prompt for Claude Code (2026-07-22)

**Use `strategy/claude_code_prompt_strategy_engine_gpt_2026-07-22.md` as the
base spec — follow it in full.** The four overrides below replace specific
parts of that document where it conflicted with decisions made after it was
drafted. `strategy/claude_code_prompt_strategy_engine_2026-07-22.md` (the
earlier draft) is superseded except where quoted explicitly in an override
below — don't follow it beyond that.

## Override 1 — Pattern Extractor: build the real module now, not a stub

The base spec says: *"Если полноценная реализация сейчас слишком рискованна
для production pipeline, создай минимальную рабочую версию без
переусложнения."* Replace that with: **implement it now as a real module**,
not a placeholder or minimal stand-in. It answers, for every candidate
signal: what mechanism was found; what typical business-owner situation
maps to it; whether the signal fits Never Blank's territory at all (hard
reject if not); what the commercial consequence is; and, if a company
appears in the signal, why it's evidence rather than the article's subject
(decisions 24, 28 in `decision_log.md`). This has been an open architecture
item since Часть 4 — build it properly this time.

## Override 2 — Echo: large majority, not literal 100%

The base spec says: *"Echo обязателен. Если Echo отсутствует, материал не
должен считаться готовым."* Replace with: **Echo should be present in the
large majority of articles — treat its absence as a rare exception, not a
routine outcome. The quality bar does not drop to hit that rate.** Keep
generating multiple Echo candidates internally; keep refusing to insert a
generic or unearned one. If candidate generation is frequently producing
weak Echoes, that's a signal the generation prompt needs work — not a
reason to force a bad one through, and not a reason to lower how often a
real one is expected either.

## Override 3 — Article arc: run the new arc in production now, keep the existing arc in code

Two different article structures now exist:

- **Existing, already implemented** in `config/prompts/linkedin_post.yaml`
  and decisions 16–19 in `decision_log.md`: Hook → Observation → Recognition
  → Explanation → Reframe → Echo → CTA (optional).
- **New, from the base spec's Editorial Strategy section**: Hook →
  Recognition → Tension → Market Observation → Investigation → Mechanism →
  Business Consequence → Reframe → Compound Presence Connection → Echo →
  Soft CTA.

**Decision: the new 11-step arc is what generates production content
starting with this build.** Do not delete or overwrite the existing
9-step arc's code or prompt — keep it in the codebase as-is. Note
explicitly in whatever documentation you produce (the human-readable
strategy doc and/or `decision_log.md`) that the existing arc still exists
and still needs its own testing/evaluation — this is not a decision that
the old arc is wrong, only that the new one is what ships now. If it's
straightforward to keep both accessible (e.g., behind a config flag or as
two named prompt variants) rather than the old one becoming dead code, do
that — but don't over-engineer a full switching mechanism if it's not a
natural fit; a clear, documented, non-deleted old version is the minimum
bar.

## Override 4 — Two naming/scope corrections (not a disagreement between the two drafts, just gaps in the base spec)

- **`cta_intent` vs the existing `cta_mode`.** The repository already has a
  working `CTAMode` enum and `cta_mode` field wired through `models.py`,
  `config/content_matrix.yaml`, `generator.py`, and `pipeline.py` (values:
  `none` / `reflection` / `diagnostic` / `example_request` /
  `direct_conversation` — decision 18). Use that existing field everywhere
  the base spec's JSON examples show `cta_intent`. Do not create a second,
  parallel field. If a genuinely different concept is needed beyond the
  five existing modes, extend `CTAMode`'s values — don't fork a new one.
- **Target audience.** Wherever the base spec's examples show
  `"target_audience": "small business owners"`, use the actual segment from
  decision 34 instead: small B2B service businesses with a single
  decision-maker — agencies (digital/web/dev/creative), consultants, MSPs.
  Not small business in general.

## Everything else

Follow `strategy/claude_code_prompt_strategy_engine_gpt_2026-07-22.md`
exactly as written — weekly/monthly review logic, CONTINUE / ADJUST_EXECUTION
/ REVIEW_STRATEGY decisions, the JSON schemas, the `strategy/current/` and
`strategy/history/` folder layout, the CSV columns, the phased MVP boundary
(Phase 1–4), validation rules, fail-closed publishing gate, and the test/
fixture requirements all stand unchanged.
