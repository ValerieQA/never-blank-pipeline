"""ENGINE: the runtime object a run executes a client's editorial contract as.

A human-readable editorial contract is worth nothing until a run is *shaped* by
it. The failure this module exists to end is the one #264 names: documents that
exist and are never read — a policy written by people, approved, versioned, and
then absent from every message a model ever receives.

An ``EditorialPlan`` is the one object between the two. It is built from a
loaded contract snapshot plus what this run found, it is validated before
anything is written, it is rendered into the writing stage's model input, and it
is persisted beside the exact contract and lens digests it was built from. If
the plan is not built, the run does not carry the contract; if the plan carries
a value the contract does not permit, the run stops.

**The Engine holds the slots; the client holds every value.** ``ending_mode`` is
a slot. Which ending modes exist, which one this stream uses, and what any of
them means are the client's, written in ``## Plan`` in the stream contract
(``src/strategy/client_contracts.py``). There is deliberately no Python enum of
editorial choices: an editorial rotation must be a document edit, never a code
change. The Engine refuses a slot it does not carry and a value the contract
does not permit, and beyond that it does not know what it is carrying.

What the Engine *does* know, because it is universal rather than editorial:

* a claim may not cite evidence that does not exist, or evidence the run marked
  do-not-use;
* a claim may not be stated more strongly than the ceiling the contract set,
  compared on the ladder the contract declared;
* an entity or a number a claim names must appear in the evidence it cites;
* a string on a shared banned list may not appear in the output.

None of those are editorial opinions. They are what it means for a sentence to
be supported by the evidence behind it, and they hold for every client.

The plan is **not** a paragraph outline. It says what the article must be true
to, never what its third paragraph is.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from src.strategy.client_contracts import CONDITIONAL_STAGES, ClientContracts, Lens

if TYPE_CHECKING:
    from src.editorial.plan_decisions import PlanDecisions
    from src.research.evidence import NormalizedResearchArtifact

#: Evidence-integrity finding kinds. Universal, not editorial: each one names a
#: way a sentence can fail to be supported by the evidence it cites.
UNSUPPORTED_INFERENCE: Final[str] = "unsupported_inference"
CLAIM_STRENGTH_ESCALATION: Final[str] = "claim_strength_escalation"
INVENTED_ENTITY_ATTRIBUTION: Final[str] = "invented_entity_attribution"
UNTRACEABLE_NUMBER: Final[str] = "untraceable_number"
DO_NOT_USE_EVIDENCE: Final[str] = "do_not_use_evidence"

#: The stages a plan routes client lenses to (#267): every stage that runs after
#: research, so every stage a conditional lens can be activated for. One plan,
#: one activation decision per condition, however many of these stages a lens
#: names — the writing stage and the reviser never decide it twice.
PLAN_STAGES: Final[tuple[str, ...]] = CONDITIONAL_STAGES

#: The key the enriched signal carries the plan under, so every stage that
#: shapes the writing reads one authority (#263). The Engine writes the plan's
#: own text here and nothing else; a stage reads it through ``plan_block``.
PLAN_SIGNAL_KEY: Final[str] = "EDITORIAL_PLAN"


class EditorialPlanError(ValueError):
    """A plan cannot be built, or is not the plan the contract requires."""


def _normalised(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One thing the run may rely on — or may not, and then it says why."""

    item_id: str
    statement: str
    #: Where it came from: source ids, URLs, whatever the caller can prove.
    provenance: tuple[str, ...] = ()
    #: Verbatim support the statement rests on. Numbers and named entities are
    #: traced against this as well as against the statement.
    support: tuple[str, ...] = ()
    usable: bool = True
    #: Why the item may not be used. Required when ``usable`` is False: an item
    #: withdrawn without a reason cannot be reviewed.
    reason: str = ""

    @property
    def traceable_text(self) -> str:
        return " ".join((self.statement, *self.support, *self.provenance))


@dataclass(frozen=True, slots=True)
class EvidencePackage:
    """Everything this run may draw on, including what it may not."""

    items: tuple[EvidenceItem, ...] = ()

    def __post_init__(self) -> None:
        ids = [item.item_id for item in self.items]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise EditorialPlanError(
                f"evidence item id(s) used twice: {', '.join(duplicated)}"
            )
        for item in self.items:
            if not item.item_id.strip() or not item.statement.strip():
                raise EditorialPlanError("an evidence item needs an id and a statement")
            if not item.usable and not item.reason.strip():
                raise EditorialPlanError(
                    f"evidence item {item.item_id!r} may not be used and says no reason"
                )

    def item(self, item_id: str) -> EvidenceItem | None:
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    @property
    def usable(self) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.usable)

    @property
    def do_not_use(self) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if not item.usable)


@dataclass(frozen=True, slots=True)
class Claim:
    """A statement, and what the run says supports it."""

    text: str
    #: A value on the contract's strength ladder; empty when unstated.
    strength: str = ""
    evidence_refs: tuple[str, ...] = ()
    #: Entities and figures the statement names, each of which must appear in
    #: the evidence it cites. Supplied by the caller: the Engine reads a claim
    #: record, it does not parse prose.
    entities: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IntegrityFinding:
    """One way a claim is not supported by the evidence it cites."""

    kind: str
    claim: str
    detail: str
    evidence_ref: str = ""


@dataclass(frozen=True, slots=True)
class ActiveLens:
    """A client obligation this run carries, and what put it there."""

    lens_id: str
    version: str
    digest: str
    stages: tuple[str, ...]
    text: str
    #: The condition that activated a conditional lens; empty for a standing
    #: obligation, which needs none.
    activation: str = ""
    #: What made that condition true, preserved so the decision is reviewable.
    activation_evidence: str = ""

    @property
    def identity(self) -> str:
        return f"{self.lens_id}/{self.version}"

    @property
    def is_standing(self) -> bool:
        return not self.activation

    def as_evidence(self) -> dict:
        return {"identity": self.identity, "digest": self.digest,
                "stages": list(self.stages), "activation": self.activation,
                "activation_evidence": self.activation_evidence}


@dataclass(frozen=True, slots=True)
class PortableNoun:
    """A name the article proposes to make portable, and what was decided."""

    noun: str
    decision: str
    rationale: str = ""

    def as_evidence(self) -> dict[str, str]:
        return {"noun": self.noun, "decision": self.decision, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class RegularityObservation:
    """How often one value has already occurred across a portfolio of runs.

    Portfolio-level regularity is evidence, never a rule: the Engine counts, and
    what a count means — a signature worth keeping, a rut worth breaking — is
    the client's to decide in its own documents.
    """

    slot: str
    value: str
    occurrences: int
    runs: tuple[str, ...] = ()

    def as_evidence(self) -> dict:
        return {"slot": self.slot, "value": self.value,
                "occurrences": self.occurrences, "runs": list(self.runs)}


@dataclass(frozen=True, slots=True)
class EditorialPlan:
    """What this run must be true to, and where every part of it came from."""

    central_claim: Claim
    evidence: EvidencePackage
    active_lenses: tuple[ActiveLens, ...]
    #: The exact contract and lens identities, paths and digests this plan was
    #: built from — the same snapshot record the run's evidence carries.
    lineage: Mapping[str, object]
    claim_strength_ceiling: str = ""
    #: The contract's ladder, weakest first. Empty when the client declared none,
    #: and then no strength can be compared and none is.
    strength_ladder: tuple[str, ...] = ()
    reader_verifiable_artifact: str = ""
    ending_mode: str = ""
    audience_currency: str = ""
    factual_restrictions: tuple[str, ...] = ()
    acknowledged_limits: tuple[str, ...] = ()
    portable_noun: PortableNoun | None = None
    banned: tuple[tuple[str, str], ...] = ()
    regularity: tuple[RegularityObservation, ...] = ()
    #: What this run decided that the contract left open — activations and
    #: slot choices, each with the evidence and the decider behind it
    #: (``src.editorial.plan_decisions``). Empty when nothing was left open.
    run_decisions: Mapping[str, object] = field(default_factory=dict)

    # ── what the plan can answer about a claim ──────────────────────────────

    def check(self, claims: Sequence[Claim]) -> tuple[IntegrityFinding, ...]:
        return check_claims(
            claims, evidence=self.evidence, ceiling=self.claim_strength_ceiling,
            strength_ladder=self.strength_ladder,
        )

    def forbidden_in(self, text: str) -> tuple[tuple[str, str], ...]:
        """Every banned entry the text contains, with the list it came from."""
        haystack = _normalised(text)
        return tuple(
            (entry, source) for entry, source in self.banned
            if _normalised(entry) and _normalised(entry) in haystack
        )

    # ── what the plan hands on ──────────────────────────────────────────────

    def lenses_for(self, stage: str) -> tuple[ActiveLens, ...]:
        """Every lens this run carries to ``stage``, standing and activated."""
        if stage not in PLAN_STAGES:
            raise EditorialPlanError(
                f"a plan routes lenses to {', '.join(PLAN_STAGES)}, not {stage!r}"
            )
        return tuple(lens for lens in self.active_lenses if stage in lens.stages)

    def activated_lens_texts(self, stage: str) -> tuple[str, ...]:
        """The conditional lenses this run activated for ``stage``, each with
        what activated it — the only route a conditional lens has to a stage.

        Standing lenses are not here: they already travel to every stage with
        the role's rules (``ClientContracts.for_stage``).
        """
        return tuple(
            f"{lens.text}\n\nWhat activated it in this run's evidence "
            f"({lens.activation}): {lens.activation_evidence}"
            for lens in self.lenses_for(stage)
            if not lens.is_standing
        )

    def as_prompt_text(self) -> str:
        """The plan as deterministic model input.

        Every line is the client's text or this run's evidence. The Engine adds
        labels for its own slots and nothing else — no arc, no section order, no
        editorial instruction of its own.
        """
        lines = [
            "",
            "EDITORIAL PLAN — what this article must be true to. Every line below "
            "comes from the client's approved editorial contract or from this "
            "run's own evidence. Follow it; it is not a paragraph outline and "
            "says nothing about where anything goes.",
            "",
            f"Central claim: {self.central_claim.text}",
        ]
        for label, value in (
            ("Claim strength ceiling — never state the claim more strongly than this",
             self.claim_strength_ceiling),
            ("Reader-verifiable artifact", self.reader_verifiable_artifact),
            ("Ending mode", self.ending_mode),
            ("Audience currency", self.audience_currency),
        ):
            if value:
                lines.append(f"{label}: {value}")
        if self.portable_noun is not None:
            lines.append(
                f"Portable noun — {self.portable_noun.decision}: "
                f"{self.portable_noun.noun}"
            )
        lines.extend(_block("Factual restrictions", self.factual_restrictions))
        lines.extend(_block("Acknowledged limits", self.acknowledged_limits))
        lines.extend(_block(
            "Evidence you may rely on",
            tuple(f"[{item.item_id}] {item.statement}" for item in self.evidence.usable),
        ))
        lines.extend(_block(
            "Evidence you may NOT use, whatever it appears to support",
            tuple(f"[{item.item_id}] {item.statement} — {item.reason}"
                  for item in self.evidence.do_not_use),
        ))
        lines.extend(_block(
            "Never write any of these, in any form",
            tuple(entry for entry, _ in self.banned),
        ))
        # Standing obligations already travel with the role's rules; a
        # conditional one reaches a model only here, and only once this run
        # recorded what activated it. This text is the writing stage's input,
        # so it carries the lenses routed to writing and no others.
        for lens in self.lenses_for("writing"):
            if lens.is_standing:
                continue
            lines.extend(["", f"Client lens, active for this article ({lens.activation}):",
                          lens.text,
                          ("What activated it in this run's evidence: "
                           f"{lens.activation_evidence}")])
        lines.append("")
        return "\n".join(lines)

    def as_review_text(self) -> str:
        """The projection an editorial reviewer judges execution against (#269).

        The same authority the article was written under — one plan per run —
        reduced to what a reviewer may hold an article to: the claim it had to
        be true to, the ceiling it could not exceed, the ending and artifact
        its contract decided, the restrictions and limits it accepted, and the
        client obligations that were active for this run. The activated
        conditional lenses matter most here: nothing else would tell the
        reviewer that a lens governed this article's writing.

        It is not the writing projection. The evidence package belongs to the
        factual boundary, and the banned list is matched mechanically — a
        reviewer asked to re-run either would be re-deciding what has already
        been decided.

        What this text is *not* is a checklist. It says what the article was
        asked to do; whether each obligation was owed at all is stated by the
        client's own lenses, and what a reviewer may never fail an article on
        is stated in its own request.
        """
        lines = [
            "",
            "EDITORIAL PLAN — the authority this article was written under. "
            "Judge whether the article does what this asked of it. Do not "
            "check it off: an obligation the client's own lens states as "
            "optional is not a defect when the article does without it.",
            "",
            f"Central claim: {self.central_claim.text}",
        ]
        for label, value in (
            ("Claim strength ceiling — the article may not state the claim more "
             "strongly than this", self.claim_strength_ceiling),
            ("Ending mode", self.ending_mode),
            ("Reader-verifiable artifact", self.reader_verifiable_artifact),
            ("Audience currency", self.audience_currency),
        ):
            if value:
                lines.append(f"{label}: {value}")
        if self.portable_noun is not None:
            lines.append(
                f"Portable noun — {self.portable_noun.decision}: "
                f"{self.portable_noun.noun}"
            )
        lines.extend(_block("Factual restrictions", self.factual_restrictions))
        lines.extend(_block("Acknowledged limits", self.acknowledged_limits))
        for lens in self.lenses_for("writing"):
            if lens.is_standing:
                lines.extend(["", "Client obligation, standing for every article "
                              "of this stream:", lens.text])
            else:
                lines.extend([
                    "",
                    f"Client obligation, active for THIS article ({lens.activation}) "
                    "— it governed the writing and you are judging whether the "
                    "article did what it asks:",
                    lens.text,
                    f"What activated it in this run's evidence: "
                    f"{lens.activation_evidence}",
                ])
        lines.append("")
        return "\n".join(lines)

    def as_evidence(self) -> dict:
        """What the run persists: the plan, and the exact documents behind it."""
        return {
            "central_claim": {
                "text": self.central_claim.text,
                "strength": self.central_claim.strength,
                "evidence_refs": list(self.central_claim.evidence_refs),
            },
            "claim_strength_ceiling": self.claim_strength_ceiling,
            "strength_ladder": list(self.strength_ladder),
            "reader_verifiable_artifact": self.reader_verifiable_artifact,
            "ending_mode": self.ending_mode,
            "audience_currency": self.audience_currency,
            "factual_restrictions": list(self.factual_restrictions),
            "acknowledged_limits": list(self.acknowledged_limits),
            "portable_noun": (
                None if self.portable_noun is None else self.portable_noun.as_evidence()
            ),
            "evidence_package": [
                {"item_id": item.item_id, "statement": item.statement,
                 "provenance": list(item.provenance), "usable": item.usable,
                 "reason": item.reason}
                for item in self.evidence.items
            ],
            "active_lenses": [lens.as_evidence() for lens in self.active_lenses],
            # which of them reached which stage, and on what
            "active_by_stage": {
                stage: [{"identity": lens.identity, "activation": lens.activation}
                        for lens in self.lenses_for(stage)]
                for stage in PLAN_STAGES
            },
            "banned": [{"entry": entry, "list": source} for entry, source in self.banned],
            "regularity": [item.as_evidence() for item in self.regularity],
            "lineage": dict(self.lineage),
            "run_decisions": dict(self.run_decisions),
        }


def plan_block(signal: Mapping[str, object]) -> str:
    """The plan a writing stage appends to its prompt, or ``""`` when none.

    The route by which an ``EditorialPlan`` reaches the stages that BUILD the
    argument — the spine, the hook, the voice — rather than only the composer
    that dresses it. An obligation delivered after the article is shaped is
    applied cosmetically, which is the failure #263 reports from a live run.

    Generic: the Engine knows no client, no condition and no lens. Whatever a
    contract routes to ``writing`` travels this one way, and a run with no
    plan changes nothing.
    """
    plan = signal.get(PLAN_SIGNAL_KEY) or ""
    if not isinstance(plan, str) or not plan.strip():
        return ""
    return ("\n\nThe plan below is this run's editorial contract, already "
            "validated against the evidence. Build what you write from it — it "
            "binds this stage as much as the final composition:\n"
            + plan.strip() + "\n")


def _block(label: str, values: Sequence[str]) -> list[str]:
    if not values:
        return []
    return ["", f"{label}:", *(f"- {value}" for value in values)]


# ── building a plan from a contract snapshot ────────────────────────────────


def _scalar(contracts: ClientContracts, slot: str, supplied: str) -> str:
    """One scalar slot, resolved against what the contract permits.

    Three refusals, one shape: a value the contract does not permit, a choice
    the contract requires and the run did not make, and — through the loader —
    a slot the Engine does not carry. All three are the same disease: contract
    semantics that were written down and then lost.
    """
    permitted = contracts.stream.plan_values(slot)
    value = supplied.strip()
    if not permitted:
        return value
    if not value:
        if len(permitted) == 1:
            # the contract permits exactly one value, so it decided this slot
            return permitted[0]
        raise EditorialPlanError(
            f"{contracts.stream.identity} permits {len(permitted)} values for "
            f"`{slot}` and this run chose none: {', '.join(permitted)}"
        )
    if value not in permitted:
        raise EditorialPlanError(
            f"{value!r} is not a `{slot}` {contracts.stream.identity} permits "
            f"({', '.join(permitted)})"
        )
    return value


def _listed(contracts: ClientContracts, slot: str, supplied: Sequence[str]) -> tuple[str, ...]:
    """A list slot: everything the contract states, then what the run adds."""
    values = list(contracts.stream.plan_values(slot))
    for extra in supplied:
        cleaned = extra.strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return tuple(values)


def _activated(
    contracts: ClientContracts, activation_evidence: Mapping[str, str]
) -> tuple[ActiveLens, ...]:
    """Every lens routed to a plan stage: standing obligations, and each
    conditional lens this run activated — once, for every stage it names."""
    declared = set(contracts.activation_conditions)
    unknown = sorted(set(activation_evidence) - declared)
    if unknown:
        raise EditorialPlanError(
            "activation evidence for condition(s) no lens declares: "
            + ", ".join(unknown)
        )
    for condition, proof in activation_evidence.items():
        if not str(proof).strip():
            raise EditorialPlanError(
                f"condition {condition!r} was activated with no evidence; a lens is "
                "applied on evidence or not at all"
            )
    active: list[ActiveLens] = []
    for lens in contracts.lenses:
        if not set(lens.stages) & set(PLAN_STAGES):
            continue
        if lens.is_standing:
            active.append(_active_lens(lens))
            continue
        condition = next(
            (c for c in lens.activates_on if str(activation_evidence.get(c, "")).strip()),
            "",
        )
        if condition:
            active.append(_active_lens(
                lens, condition, str(activation_evidence[condition]).strip()
            ))
    return tuple(active)


def _active_lens(lens: Lens, condition: str = "", evidence: str = "") -> ActiveLens:
    return ActiveLens(
        lens_id=lens.lens_id, version=lens.version, digest=lens.digest,
        stages=lens.stages, text=lens.text,
        activation=condition, activation_evidence=evidence,
    )


def build_editorial_plan(
    contracts: ClientContracts,
    *,
    central_claim: Claim,
    evidence: EvidencePackage | None = None,
    activation_evidence: Mapping[str, str] | None = None,
    claim_strength_ceiling: str = "",
    reader_verifiable_artifact: str = "",
    ending_mode: str = "",
    audience_currency: str = "",
    factual_restrictions: Sequence[str] = (),
    acknowledged_limits: Sequence[str] = (),
    portable_noun: PortableNoun | None = None,
    regularity: Sequence[RegularityObservation] = (),
    decisions: PlanDecisions | None = None,
) -> EditorialPlan:
    """Create and validate the plan this run executes the contract as.

    Fails closed rather than producing a plan that is quietly less than the
    contract: a value the contract does not permit, a choice it requires and the
    run did not make, a lens activated without evidence, or a central claim that
    cites evidence which does not exist or which this run may not use.

    A central claim that cites no evidence at all is *not* refused here — a run
    may legitimately be built on its own premise, and the plan records that it
    is unsupported and carries the restriction into the writing stage rather
    than pretending otherwise. ``check`` reports it as an unsupported inference
    for any caller that must treat it as a defect.

    ``decisions`` is what this run decided that the contract left open
    (``resolve_plan_decisions``): its activations and slot choices are applied
    and recorded. A value supplied both there and directly is refused — one
    authority per decision.
    """
    if not central_claim.text.strip():
        raise EditorialPlanError("a plan needs the central claim the run is built on")
    package = evidence if evidence is not None else EvidencePackage()
    supplied_values = {
        "claim_strength_ceiling": claim_strength_ceiling,
        "reader_verifiable_artifact": reader_verifiable_artifact,
        "ending_mode": ending_mode,
        "audience_currency": audience_currency,
    }
    if decisions is not None:
        twice = sorted(
            slot for slot in decisions.selected if supplied_values.get(slot, "").strip()
        )
        if twice or (activation_evidence and decisions.activation_evidence):
            raise EditorialPlanError(
                "a decision was supplied twice — directly and by the run's plan "
                f"decisions: {', '.join(twice) or 'activation evidence'}"
            )
        supplied_values.update(decisions.selected)
        activation_evidence = activation_evidence or decisions.activation_evidence
    resolved = {
        slot: _scalar(contracts, slot, supplied)
        for slot, supplied in supplied_values.items()
    }
    plan = EditorialPlan(
        central_claim=central_claim,
        evidence=package,
        active_lenses=_activated(contracts, activation_evidence or {}),
        lineage=contracts.provenance,
        claim_strength_ceiling=resolved["claim_strength_ceiling"],
        strength_ladder=contracts.stream.plan_values("claim_strength_ceiling"),
        reader_verifiable_artifact=resolved["reader_verifiable_artifact"],
        ending_mode=resolved["ending_mode"],
        audience_currency=resolved["audience_currency"],
        factual_restrictions=_listed(contracts, "factual_restrictions", factual_restrictions),
        acknowledged_limits=_listed(contracts, "acknowledged_limits", acknowledged_limits),
        portable_noun=portable_noun,
        banned=contracts.banned_entries,
        regularity=tuple(regularity),
        run_decisions=decisions.as_evidence() if decisions is not None else {},
    )
    breaches = [f for f in plan.check((central_claim,)) if f.kind != UNSUPPORTED_INFERENCE]
    if breaches:
        raise EditorialPlanError(
            "the central claim does not survive its own evidence: "
            + "; ".join(f"{f.kind} — {f.detail}" for f in breaches)
        )
    return plan


# ── evidence integrity, which is universal and never editorial ──────────────


def check_claims(
    claims: Sequence[Claim],
    *,
    evidence: EvidencePackage,
    ceiling: str = "",
    strength_ladder: Sequence[str] = (),
) -> tuple[IntegrityFinding, ...]:
    """Every way these claims are not supported by the evidence they cite.

    Reports rather than raises: which findings are fatal is the caller's
    decision. A strength that is not on the contract's ladder is the one
    exception — it cannot be compared with anything, so it is malformed input
    and raises.
    """
    ladder = tuple(strength_ladder)
    findings: list[IntegrityFinding] = []
    for claim in claims:
        cited: list[EvidenceItem] = []
        if not claim.evidence_refs:
            findings.append(IntegrityFinding(
                UNSUPPORTED_INFERENCE, claim.text,
                "the claim cites no evidence at all",
            ))
        for ref in claim.evidence_refs:
            item = evidence.item(ref)
            if item is None:
                findings.append(IntegrityFinding(
                    UNSUPPORTED_INFERENCE, claim.text,
                    f"cites {ref!r}, which the evidence package does not contain", ref,
                ))
                continue
            if not item.usable:
                findings.append(IntegrityFinding(
                    DO_NOT_USE_EVIDENCE, claim.text,
                    f"cites {ref!r}, which this run may not use: {item.reason}", ref,
                ))
                continue
            cited.append(item)
        findings.extend(_strength_findings(claim, ceiling, ladder))
        findings.extend(_traceability_findings(claim, cited))
    return tuple(findings)


def _strength_findings(
    claim: Claim, ceiling: str, ladder: tuple[str, ...]
) -> list[IntegrityFinding]:
    if not ladder or not ceiling or not claim.strength:
        return []
    for value, label in ((claim.strength, "claim"), (ceiling, "ceiling")):
        if value not in ladder:
            raise EditorialPlanError(
                f"{label} strength {value!r} is not on the contract's ladder "
                f"({', '.join(ladder)})"
            )
    if ladder.index(claim.strength) <= ladder.index(ceiling):
        return []
    return [IntegrityFinding(
        CLAIM_STRENGTH_ESCALATION, claim.text,
        f"stated as {claim.strength!r}, above the ceiling {ceiling!r} the contract set",
    )]


def _traceability_findings(
    claim: Claim, cited: Sequence[EvidenceItem]
) -> list[IntegrityFinding]:
    traceable = _normalised(" ".join(item.traceable_text for item in cited))
    findings: list[IntegrityFinding] = []
    for entity in claim.entities:
        if _normalised(entity) and _normalised(entity) not in traceable:
            findings.append(IntegrityFinding(
                INVENTED_ENTITY_ATTRIBUTION, claim.text,
                f"names {entity!r}, which the evidence it cites does not",
            ))
    for number in claim.numbers:
        if _normalised(number) and _normalised(number) not in traceable:
            findings.append(IntegrityFinding(
                UNTRACEABLE_NUMBER, claim.text,
                f"states {number!r}, which the evidence it cites does not",
            ))
    return findings


# ── portfolio-level regularity ──────────────────────────────────────────────


def portfolio_regularity(
    records: Sequence[Mapping[str, object]], slot: str
) -> tuple[RegularityObservation, ...]:
    """How often each value of ``slot`` occurs across persisted plan records.

    ``records`` are ``as_evidence()`` dicts, each optionally carrying the
    ``run_id`` it was written for. Counting is all the Engine does: no threshold,
    no verdict, nothing about what a repeated value says about the portfolio.
    """
    counts: dict[str, list[str]] = {}
    for record in records:
        raw = record.get(slot)
        values: list[str] = []
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list):
            values = [item for item in raw if isinstance(item, str)]
        run_id = str(record.get("run_id", "") or "")
        for value in values:
            if not value.strip():
                continue
            runs = counts.setdefault(value, [])
            if run_id:
                runs.append(run_id)
            else:
                # an unattributed record still counts; only its run is unknown
                runs.append("")
    return tuple(
        RegularityObservation(
            slot=slot, value=value, occurrences=len(runs),
            runs=tuple(run for run in runs if run),
        )
        for value, runs in sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )


# ── adapters ────────────────────────────────────────────────────────────────

#: Dispositions a run may build on. Everything else — rejected, conflicting, or
#: never assessed — becomes a do-not-use item carrying its own reason, so the
#: writing stage is told what it may not use instead of never hearing of it.
_USABLE_DISPOSITIONS: Final[frozenset[str]] = frozenset({"accepted", "qualified"})


def evidence_package_from_artifact(
    artifact: "NormalizedResearchArtifact",
) -> EvidencePackage:
    """The run's normalized research artifact as an evidence package."""
    items: list[EvidenceItem] = []
    for extracted in artifact.evidence:
        disposition = getattr(extracted.disposition, "value", str(extracted.disposition))
        usable = disposition in _USABLE_DISPOSITIONS
        items.append(EvidenceItem(
            item_id=extracted.evidence_id,
            statement=extracted.claim,
            provenance=tuple(extracted.source_ids),
            support=tuple(support.excerpt for support in extracted.support),
            usable=usable,
            reason=(
                "" if usable
                else (extracted.assessment_rationale
                      or f"evidence disposition: {disposition}")
            ),
        ))
    return EvidencePackage(tuple(items))
