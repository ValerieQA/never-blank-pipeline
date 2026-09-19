"""ENGINE: the decisions a client's contract leaves to each run (#267).

A stream contract can leave two kinds of question open, and both have to be
answered before an ``EditorialPlan`` exists:

* **Which conditional lenses apply.** A lens with ``activates_on`` names the
  conditions under which it applies. Whether one holds is a fact about *this
  run's research evidence*, so it is decided from that evidence — never from
  the weekday, the topic, or any text the pipeline generated.
* **Which value a multi-value slot takes.** Where ``## Plan`` lists several
  values for a scalar slot, the contract has declared the options and left the
  choice to the run.

This module asks one decider both questions at once and holds the answer to
the contract. The decider sees the client's own text — the condition names, the
lenses that declare them, the permitted values verbatim — plus the run's
evidence package and central claim. It never sees an article: the plan is
decided before anything is written.

Nothing here knows any client. The conditions, the lens texts and the values
are passed through as the client wrote them, and the Engine checks only what is
universal:

* every open question is answered exactly once, and nothing else is;
* a condition is met only on evidence this run holds and may use — named by
  item id, so activation evidence cannot be invented;
* a chosen value is one the contract permits, verbatim;
* no answer, an unreadable answer or an ambiguous one stops the run. The first
  value is never a default, and an unanswered condition is never "inactive".

A contract that leaves nothing open costs no call and changes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from src.editorial.editorial_plan import (
    PLAN_STAGES,
    Claim,
    EditorialPlanError,
    EvidencePackage,
)
from src.strategy.client_contracts import PLAN_SCALAR_SLOTS, ClientContracts, Lens


class PlanDecider(Protocol):
    """Answers a plan-decision request; the Engine validates the answer."""

    #: Recorded in the plan as who made this run's decisions.
    identity: str

    def decide(self, request: Mapping[str, object]) -> str:
        """The decider's raw JSON answer to ``request``."""


PLAN_DECISION_INSTRUCTIONS: Final[
    str
] = """A client's editorial contract leaves some decisions to each run. Make them for THIS
run, from the RESEARCH EVIDENCE and the CENTRAL CLAIM supplied. You are given no article
and must not assume one.

CONDITIONS: each names a condition under which one or more of the client's lenses apply,
with the client's own lens text. Decide whether the condition is met by the evidence.
A condition is met only when evidence items supplied establish it; cite them by id. Do
not treat a condition as met because it would make a better story. Items marked
"usable": false may not be cited.

SLOTS: each lists the values the client's contract permits. Choose exactly one of them
per slot, copied verbatim, that fits this run's evidence and claim. If the evidence does
not let you choose exactly one, return an empty value: never default to the first.

Return ONLY valid JSON:
{"activations": [{"condition": "<condition>", "met": true|false,
                  "finding": "when met: what in the evidence meets it; otherwise empty",
                  "evidence_refs": ["<evidence id>", ...],
                  "reason": "one sentence"}],
 "selections": [{"slot": "<slot>", "value": "<one permitted value, verbatim, or empty>",
                 "evidence_refs": ["<evidence id>", ...],
                 "reason": "one sentence"}]}
Answer every condition and every slot supplied, exactly once, and nothing else."""


class ModelPlanDecider:
    """The production decider: one budget-charged model call per run.

    Called only when the contract leaves something open, so a client whose
    contract decides everything — or declares no plan — pays nothing.
    """

    #: The setting that names the model — recorded instead of the model value,
    #: which deployments keep as a secret.
    identity = "model:NB_ENRICH_MODEL"

    def decide(self, request: Mapping[str, object]) -> str:
        from src.utils.llm_client import chat, model_enrich

        return chat(
            system=PLAN_DECISION_INSTRUCTIONS,
            user=json.dumps(request, ensure_ascii=False),
            json_mode=True,
            model=model_enrich(),
        )


@dataclass(frozen=True, slots=True)
class ActivationDecision:
    condition: str
    met: bool
    #: What in the evidence meets the condition; empty when not met.
    finding: str
    evidence_refs: tuple[str, ...]
    reason: str
    #: The lens identities that name this condition.
    declared_by: tuple[str, ...]
    #: Every stage those lenses route to. One decision serves all of them: a
    #: lens named for writing and revision is never decided twice.
    stages: tuple[str, ...] = ()

    @property
    def proof(self) -> str:
        """The activation evidence a plan records and hands to the writer."""
        return f"{self.finding} [evidence: {', '.join(self.evidence_refs)}]"

    def as_evidence(self) -> dict:
        return {
            "condition": self.condition,
            "met": self.met,
            "finding": self.finding,
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
            "declared_by": list(self.declared_by),
            "stages": list(self.stages),
        }


@dataclass(frozen=True, slots=True)
class SlotSelection:
    slot: str
    value: str
    #: Every value the contract permits, in the contract's order.
    permitted: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str

    def as_evidence(self) -> dict:
        return {
            "slot": self.slot,
            "value": self.value,
            "position": self.permitted.index(self.value),
            "permitted": list(self.permitted),
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PlanDecisions:
    """What this run decided that the contract left open, and on what."""

    #: The stages these decisions route lenses to.
    stages: tuple[str, ...] = PLAN_STAGES
    #: The decider's identity; empty when nothing was left open.
    decided_by: str = ""
    #: The contract the options came from — identity and digest.
    contract: Mapping[str, str] | None = None
    activations: tuple[ActivationDecision, ...] = ()
    selections: tuple[SlotSelection, ...] = ()

    @property
    def activation_evidence(self) -> dict[str, str]:
        return {d.condition: d.proof for d in self.activations if d.met}

    @property
    def selected(self) -> dict[str, str]:
        return {s.slot: s.value for s in self.selections}

    def as_evidence(self) -> dict:
        return {
            "stages": list(self.stages),
            "decided_by": self.decided_by,
            "contract": dict(self.contract or {}),
            "activations": [d.as_evidence() for d in self.activations],
            "selections": [s.as_evidence() for s in self.selections],
        }


def _open_conditions(contracts: ClientContracts) -> dict[str, list[Lens]]:
    """Every condition a conditional lens names → the lenses naming it.

    Across every plan stage at once, so a condition is decided once per run
    whichever stages its lenses route to.
    """
    conditions: dict[str, list[Lens]] = {}
    for lens in contracts.lenses:
        if lens.is_standing or not set(lens.stages) & set(PLAN_STAGES):
            continue
        for condition in lens.activates_on:
            conditions.setdefault(condition, []).append(lens)
    return conditions


def _open_slots(contracts: ClientContracts) -> dict[str, tuple[str, ...]]:
    """Every scalar slot for which the contract permits more than one value."""
    return {
        slot: contracts.stream.plan_values(slot)
        for slot in PLAN_SCALAR_SLOTS
        if len(contracts.stream.plan_values(slot)) > 1
    }


def plan_decision_request(
    contracts: ClientContracts,
    *,
    central_claim: Claim,
    evidence: EvidencePackage,
) -> dict | None:
    """What the decider is asked, or ``None`` when the contract left nothing open."""
    conditions, slots = _open_conditions(contracts), _open_slots(contracts)
    if not conditions and not slots:
        return None
    return {
        "central_claim": central_claim.text,
        "conditions": [
            {
                "condition": condition,
                "lenses": [
                    {
                        "lens": lens.identity,
                        "stages": list(lens.stages),
                        "text": lens.text,
                    }
                    for lens in lenses
                ],
            }
            for condition, lenses in conditions.items()
        ],
        "slots": [
            {"slot": slot, "permitted": list(values)} for slot, values in slots.items()
        ],
        "evidence": [
            {
                "id": item.item_id,
                "statement": item.statement,
                "support": list(item.support),
                "usable": item.usable,
                **({"reason": item.reason} if not item.usable else {}),
            }
            for item in evidence.items
        ],
    }


def resolve_plan_decisions(
    contracts: ClientContracts,
    *,
    central_claim: Claim,
    evidence: EvidencePackage | None,
    decider: PlanDecider | None,
) -> PlanDecisions:
    """Decide what the contract left open for this run, or stop the run."""
    package = evidence if evidence is not None else EvidencePackage()
    request = plan_decision_request(
        contracts, central_claim=central_claim, evidence=package
    )
    if request is None:
        return PlanDecisions()
    if decider is None:
        raise EditorialPlanError(
            f"{contracts.stream.identity} leaves decisions to the run and no "
            "decider was given to make them"
        )
    raw = decider.decide(request)
    conditions, slots = _open_conditions(contracts), _open_slots(contracts)
    answer = _parse(raw)
    return PlanDecisions(
        decided_by=decider.identity,
        contract={
            "identity": contracts.stream.identity,
            "path": contracts.stream.path,
            "digest": contracts.stream.digest,
        },
        activations=_activations(answer["activations"], conditions, package),
        selections=_selections(answer["selections"], slots, package),
    )


# ── holding the answer to the contract ──────────────────────────────────────


def _parse(raw: str) -> dict[str, list]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise EditorialPlanError(f"plan decider returned invalid JSON: {exc}") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"activations", "selections"}
        or not all(isinstance(data[key], list) for key in ("activations", "selections"))
    ):
        raise EditorialPlanError(
            'plan decider answer must be {"activations": [...], "selections": [...]}'
        )
    return data


def _text(entry: dict, key: str, what: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        raise EditorialPlanError(f"{what}: `{key}` must be a string, got {value!r}")
    return value.strip()


def _refs(entry: dict, what: str, package: EvidencePackage) -> tuple[str, ...]:
    refs = entry.get("evidence_refs")
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise EditorialPlanError(f"{what}: `evidence_refs` must be a list of ids")
    for ref in refs:
        item = package.item(ref)
        if item is None:
            raise EditorialPlanError(
                f"{what}: cites evidence {ref!r} this run does not hold"
            )
        if not item.usable:
            raise EditorialPlanError(
                f"{what}: cites evidence {ref!r} this run may not use ({item.reason})"
            )
    return tuple(refs)


def _answered_once(
    entries: list, key: str, asked: Mapping, what: str
) -> dict[str, dict]:
    answered: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise EditorialPlanError(
                f"a {what} answer must be an object, got {entry!r}"
            )
        name = _text(entry, key, what)
        if name not in asked:
            raise EditorialPlanError(f"answered a {what} nobody asked: {name!r}")
        if name in answered:
            raise EditorialPlanError(f"answered the {what} {name!r} twice")
        answered[name] = entry
    unanswered = [name for name in asked if name not in answered]
    if unanswered:
        raise EditorialPlanError(
            f"the plan decider left the {what}(s) undecided: {', '.join(unanswered)}"
        )
    return answered


def _activations(
    entries: list, conditions: Mapping[str, list[Lens]], package: EvidencePackage
) -> tuple[ActivationDecision, ...]:
    answered = _answered_once(entries, "condition", conditions, "condition")
    decisions = []
    for condition, lenses in conditions.items():
        entry, what = answered[condition], f"condition {condition!r}"
        met = entry.get("met")
        if not isinstance(met, bool):
            raise EditorialPlanError(
                f"{what}: `met` must be true or false, got {met!r}"
            )
        finding, refs = _text(entry, "finding", what), _refs(entry, what, package)
        if met and (not finding or not refs):
            raise EditorialPlanError(
                f"{what} was met without a finding and the evidence ids that "
                "establish it; a lens is applied on evidence or not at all"
            )
        decisions.append(
            ActivationDecision(
                condition=condition,
                met=met,
                finding=finding if met else "",
                evidence_refs=refs,
                reason=_text(entry, "reason", what),
                declared_by=tuple(lens.identity for lens in lenses),
                stages=tuple(
                    stage
                    for stage in PLAN_STAGES
                    if any(stage in lens.stages for lens in lenses)
                ),
            )
        )
    return tuple(decisions)


def _selections(
    entries: list, slots: Mapping[str, tuple[str, ...]], package: EvidencePackage
) -> tuple[SlotSelection, ...]:
    answered = _answered_once(entries, "slot", slots, "slot")
    selections = []
    for slot, permitted in slots.items():
        entry, what = answered[slot], f"slot `{slot}`"
        chosen = _text(entry, "value", what)
        if not chosen:
            raise EditorialPlanError(
                f"{what}: the plan decider could not choose one of the "
                f"{len(permitted)} permitted values, and the run will not pick one for it"
            )
        matches = [
            v for v in permitted if " ".join(v.split()) == " ".join(chosen.split())
        ]
        if len(matches) != 1:
            raise EditorialPlanError(
                f"{what}: {chosen!r} is not a value the contract permits "
                f"({'; '.join(permitted)})"
            )
        selections.append(
            SlotSelection(
                slot=slot,
                value=matches[0],
                permitted=permitted,
                evidence_refs=_refs(entry, what, package),
                reason=_text(entry, "reason", what),
            )
        )
    return tuple(selections)
