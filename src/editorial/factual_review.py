"""ENGINE: the Factual Reviewer — factual integrity, separated and fail-closed (#269).

One reviewer was being asked two questions at once. "Is every sentence true to
the evidence behind it?" and "is this the article the client wanted?" are
different questions with different authorities: the first is universal and the
Engine owns it, the second is editorial and the client owns it. Asked together
they trade against each other, and the trade always goes the same way — a
well-executed article with one invented number reads better than a dull honest
one, so the invented number survives as a note in the rationale.

So factual integrity is reviewed here, first, against the run's own
``EditorialPlan``: the authoritative claim, its strength ceiling on the
contract's own ladder, the evidence package including what the run may **not**
use, and the factual restrictions the contract attached. What this reviewer
finds is not an annotation. A finding means the article is not accepted as it
stands — it goes to the reviser as a specific finding, and an article that
still carries one after its single controlled revision does not publish.

It fails closed in the other direction too: a transport that fails, an answer
that is not readable as a verdict, or a finding of a kind the Engine does not
carry stops the run. An unreadable factual review is not a clean one.

What it enforces (``FACTUAL_FINDING_KINDS``) is the list in #269, and every
item on it is a way a sentence can fail the evidence behind it rather than an
editorial preference:

* an unsupported factual claim or inference;
* invented causality — a because the evidence never establishes;
* claim-strength escalation beyond the plan's ceiling, in scope, modality,
  direction or causality;
* an invented or misidentified entity;
* invented attribution — words or a position put in a source's mouth;
* a number that traces to nothing in the evidence package;
* a breach of a factual restriction the plan carries;
* a provenance breach — evidence used against what the run recorded about it.

Two of them are proven mechanically rather than asked about: the untraceable
figures and the shared machine tells, both from ``src.editorial.machine_tells``.
Presence of a number is not compliance, so the figures are checked whatever the
reviewer says about them.

Generic Engine behaviour: nothing here knows a client, a brand or an argument.
The reviewer is given the article, the plan's own values, and the run's
evidence — all of it the client's text or this run's findings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final, Protocol

from src.editorial.editorial_plan import EditorialPlan
from src.editorial.machine_tells import MachineTellList, MachineTellScan, scan

#: Every way a sentence can fail the evidence behind it. Universal, never
#: editorial: an article can be dull, off-brand and badly shaped without
#: raising one of these, and none of them is a matter of taste.
UNSUPPORTED_CLAIM: Final[str] = "unsupported_claim"
INVENTED_CAUSALITY: Final[str] = "invented_causality"
CLAIM_STRENGTH_ESCALATION: Final[str] = "claim_strength_escalation"
INVENTED_ENTITY: Final[str] = "invented_entity"
INVENTED_ATTRIBUTION: Final[str] = "invented_attribution"
UNTRACEABLE_NUMBER: Final[str] = "untraceable_number"
FACTUAL_RESTRICTION_BREACH: Final[str] = "factual_restriction_breach"
PROVENANCE_BREACH: Final[str] = "provenance_breach"

FACTUAL_FINDING_KINDS: Final[frozenset[str]] = frozenset({
    UNSUPPORTED_CLAIM, INVENTED_CAUSALITY, CLAIM_STRENGTH_ESCALATION,
    INVENTED_ENTITY, INVENTED_ATTRIBUTION, UNTRACEABLE_NUMBER,
    FACTUAL_RESTRICTION_BREACH, PROVENANCE_BREACH,
})

_MAX_DETAIL_LENGTH: Final[int] = 500


class FactualReviewError(RuntimeError):
    """The factual review cannot produce a trustworthy verdict — fail closed."""


class FactualReviewTransport(Protocol):
    """Narrow injectable boundary to the factual reviewer model."""

    def complete(self, *, instructions: str, request: str) -> str: ...


@dataclass(frozen=True, slots=True)
class FactualFinding:
    """One way the article is not true to the evidence behind it."""

    kind: str
    quote: str
    detail: str

    def as_evidence(self) -> dict[str, str]:
        return {"kind": self.kind, "quote": self.quote, "detail": self.detail}

    def as_guidance(self) -> str:
        return f"{self.kind}: {self.quote} — {self.detail}"


@dataclass(frozen=True, slots=True)
class FactualReview:
    """What the factual boundary found, and whether the article survives it."""

    findings: tuple[FactualFinding, ...] = ()
    mechanical: MachineTellScan = field(default_factory=MachineTellScan)
    #: The contract and lens digests the plan was built from, so a review is
    #: readable years later against the documents that governed it.
    lineage: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.findings and not self.mechanical.blocks

    def as_guidance(self) -> tuple[str, ...]:
        """The specific findings the reviser must resolve, as readable lines.

        Only what blocks: a warning, a suggestion and an owner-review note are
        recorded for people, never handed to a model as a correction to make.
        """
        return (
            *(finding.as_guidance() for finding in self.findings),
            *(f"{found.kind}: {found.quote} — {found.detail}"
              for found in self.mechanical.gated),
        )

    def as_evidence(self) -> dict:
        return {
            "passed": self.passed,
            "findings": [finding.as_evidence() for finding in self.findings],
            "mechanical": self.mechanical.as_evidence(),
            "plan_lineage": dict(self.lineage),
        }


@dataclass(frozen=True, slots=True)
class FactualGate:
    """Everything the factual boundary needs for one run.

    A run that built no ``EditorialPlan`` has no gate: there is no
    authoritative claim, ceiling or evidence package to review against, and
    inventing one would be the opposite of what this module is for.
    """

    plan: EditorialPlan
    reviewer: FactualReviewTransport
    #: The shared machine-tell list. ``None`` runs the claim review alone.
    machine_tells: MachineTellList | None = None


FACTUAL_REVIEW_INSTRUCTIONS = """You are a factual integrity reviewer. You receive one JSON request \
containing an ARTICLE, the run's authoritative editorial plan, and the evidence package that plan \
was built on.

You judge one thing: whether every factual statement in the ARTICLE is true to the evidence behind \
it. You do NOT judge writing, structure, paragraph order, voice, angle, interest, length or whether \
the article is any good. Those belong to a different reviewer. Never report a finding because a \
sentence is weak, generic or oddly placed.

Report a finding, quoting the ARTICLE exactly, whenever it contains:
- unsupported_claim: a factual claim or inference the evidence package does not support, including \
one that goes beyond what its evidence establishes;
- invented_causality: a cause, consequence or "because" the evidence does not establish — two facts \
appearing together is not a causal link;
- claim_strength_escalation: the central claim stated more strongly than the plan's \
claim_strength_ceiling, on the ladder the plan carries — in scope (more cases), modality (may \
becomes does), direction, or causality (correlation becomes cause);
- invented_entity: a company, product, person, institution, place or law the evidence does not \
name, or a real one misidentified;
- invented_attribution: words, a finding or a position attributed to a source that did not state it;
- untraceable_number: a figure, quantity, share, rate, currency amount or timeframe the evidence \
package does not contain. Stating a number is not the same as tracing one: a plausible figure in a \
sentence about consequences is still untraceable if nothing in the evidence carries it;
- factual_restriction_breach: a statement the plan's factual_restrictions forbid;
- provenance_breach: a use of evidence against what the run recorded about it — building on an item \
listed under do_not_use, or presenting one source's reporting as another's.

Report nothing else. An article that states only what its evidence supports has no findings, \
however plainly or oddly it is written.

Return ONLY valid JSON, no text outside it:
{"findings": [{"kind": "<one of the kinds above>", "quote": "exact words from the ARTICLE", \
"detail": "one sentence naming what the evidence does or does not contain"}]}
Use an empty list when the article is true to its evidence."""


def factual_review_request(plan: EditorialPlan, *, article_body: str, run_id: str) -> str:
    """The reviewer's request: the article, the plan's values, the evidence.

    Every value here is the client's own text or this run's own findings. The
    Engine adds the field names and the note, and nothing else.
    """
    return json.dumps(
        {
            "run_id": run_id,
            "article": article_body,
            "central_claim": {
                "text": plan.central_claim.text,
                "strength": plan.central_claim.strength,
                "evidence_refs": list(plan.central_claim.evidence_refs),
            },
            "claim_strength_ceiling": plan.claim_strength_ceiling,
            "claim_strength_ladder": list(plan.strength_ladder),
            "factual_restrictions": list(plan.factual_restrictions),
            "acknowledged_limits": list(plan.acknowledged_limits),
            "evidence_package": [
                {"evidence_id": item.item_id, "statement": item.statement,
                 "support": list(item.support), "provenance": list(item.provenance)}
                for item in plan.evidence.usable
            ],
            "do_not_use": [
                {"evidence_id": item.item_id, "statement": item.statement,
                 "reason": item.reason}
                for item in plan.evidence.do_not_use
            ],
            "note": (
                "The evidence package is the only support that exists for this "
                "article. Nothing outside it counts, including anything you "
                "happen to know. Reject what the evidence does not carry; never "
                "supply support for it."
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def run_factual_review(
    gate: FactualGate, *, article_body: str, run_id: str
) -> FactualReview:
    """Review one article's factual integrity against the run's plan.

    Raises ``FactualReviewError`` for transport failures and unreadable
    verdicts: an unreadable review is not a clean one. A readable review with
    findings returns normally — the findings are the caller's to act on, and
    the caller does not publish an article that carries any.
    """
    mechanical = scan(
        article_body,
        tells=gate.machine_tells,
        client_entries=gate.plan.banned,
        traceable=" ".join(
            item.traceable_text for item in gate.plan.evidence.usable
        ),
    )
    try:
        raw = gate.reviewer.complete(
            instructions=FACTUAL_REVIEW_INSTRUCTIONS,
            request=factual_review_request(
                gate.plan, article_body=article_body, run_id=run_id
            ),
        )
    except Exception as exc:  # noqa: BLE001 — boundary normalizes transport errors
        raise FactualReviewError(
            f"factual reviewer transport failed ({type(exc).__name__})"
        ) from exc
    return FactualReview(
        findings=parse_factual_findings(raw),
        mechanical=mechanical,
        lineage=dict(gate.plan.lineage),
    )


def parse_factual_findings(raw: str) -> tuple[FactualFinding, ...]:
    """The reviewer's answer, strictly: findings of known kinds, or an error."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise FactualReviewError(
            "factual reviewer output is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise FactualReviewError("factual reviewer output is not a JSON object")
    items = data.get("findings")
    if not isinstance(items, list):
        raise FactualReviewError(
            'factual reviewer answer must be {"findings": [items]}'
        )
    findings: list[FactualFinding] = []
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("kind") not in FACTUAL_FINDING_KINDS
            or not isinstance(item.get("quote"), str)
            or not item["quote"].strip()
            or not isinstance(item.get("detail", ""), str)
        ):
            raise FactualReviewError(
                "every factual finding must be {kind, quote, detail} with kind one "
                "of " + ", ".join(sorted(FACTUAL_FINDING_KINDS))
            )
        findings.append(FactualFinding(
            kind=item["kind"],
            quote=item["quote"].strip()[:_MAX_DETAIL_LENGTH],
            detail=item.get("detail", "").strip()[:_MAX_DETAIL_LENGTH],
        ))
    return tuple(findings)


class LlmChatFactualReviewTransport:
    """Production factual reviewer transport backed by the repository LLM client."""

    def complete(self, *, instructions: str, request: str) -> str:
        from src.utils.llm_client import chat, model_enrich

        return chat(system=instructions, user=request, json_mode=True, model=model_enrich())
