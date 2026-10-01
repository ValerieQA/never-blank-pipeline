"""Deterministic external boundaries for one canonical Golden Engine run (#351).

#351 has to prove that the thirteen canonical stages compose — that a signal
entering S-00 leaves S-13 as checked text — and a composition proof is only
worth something if the thing executing is the production chain. So the line
this module draws is a line about *who* is replaced:

* **external and nondeterministic** boundaries are supplied here. The research
  provider and the eleven model transports are the run's seams; production
  hands them in (``GoldenEngineSeams``) precisely so that a run can state where
  each came from. A test supplying them is using the seam, not bypassing it;
* **internal producers are never replaced.** No stage is mocked, no entity is
  hand-authored, and nothing writes into the run workspace except the engine.
  Every typed artifact a stage consumes was built by the stage that produces
  it, which is the only way the composition can be what is under test.

Every double here **answers the request it was given**. None returns a constant
payload: each parses the request the production stage composed and replies in
terms of the identifiers that request contains. That is what keeps the answers
from drifting out of agreement with each other — a claim ID the engine never
asked about cannot appear in an answer, and a renamed request field fails the
run instead of silently producing a stale reply. The shared identities (the
signal, the recorded artifact, the case) live in :data:`SCENARIO` so that the
eleven boundaries are answering about one and the same material.

The recorded research artifact is the repository's own (``evidence_core_299``),
retrieved from CNBC on 2026-06-22 and reused with this run's identity. Nothing
here reaches a network, a provider or a credential.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from src.editorial.decision_lens_evaluator import (
    DEFAULT_INSTRUCTIONS_PATH,
    DecisionLensEvaluator,
    DecisionLensInstructions,
)
from src.editorial.decision_lifecycle import RELEASE1_LENS_PROFILE
from src.editorial.editorial_role import resolve_editorial_role
from src.editorial_core.interpretation_boundary import (
    GENERATE_INSTRUCTIONS,
    PROBE_INSTRUCTIONS,
)
from src.editorial_core.material_features import MaterialFeature
from src.editorial_core.writer import (
    REVISION_INSTRUCTIONS,
    WRITER_INSTRUCTIONS,
)
from src.editorial_core.text_check import (
    EXECUTION_CHECKS,
    EXECUTION_INSTRUCTIONS,
    SIBLING_RECHECK_CHECKS,
    SIBLING_RECHECK_INSTRUCTIONS,
    TRUTH_CHECKS,
    TRUTH_INSTRUCTIONS,
)
from src.artifacts import resolve_run_dir
from src.intake.content_assignment import from_jsonl_signal
from src.research.lifecycle import build_research_request
from src.research.provider import (
    CompleteResearchResult,
    NormalizedResearchArtifact,
    ProviderAttribution,
    ProviderInvocation,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    RetrievalStatus,
    SourceOrigin,
    SourceRetrievalOutcome,
)

from src.run.call_budget import WEDNESDAY_MAX_CEILING, RunCallBudget
from src.run.call_budget_arp import ArpCallBudget
from src.run.golden_engine import (
    GoldenEngineConfiguration,
    GoldenEngineSeams,
    ResearchBinding,
    execute_canonical_topology,
    golden_engine_configuration,
)
from src.run.run_context import RunContext
from src.run.run_workspace import RunWorkspace
from src.run.transports import GoldenEngineTransports
from src.run.walking_skeleton import canonical_run_context
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext

#: The register and the client the canonical run reads. The repository's own, so
#: a contract that changes changes what this run executed against.
REGISTER_DIR = Path("knowledge")
CLIENT_DIR = Path("clients/never_blank")

#: The recorded case. ``ups_cold_chain_investment`` is the one of #299's three
#: whose evidence reaches ``ready``, which is the only state S-01 continues
#: from — the other two are that module's refusal cases.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evidence_core_299"
CASE = "ups_cold_chain_investment"

#: The production role, resolved rather than authored: ``wednesday-golden`` is
#: the declared role that states eligibility criteria, so S-00's eligibility
#: transport is exercised instead of skipped as "this role restricts nothing".
ROLE_ID = "never-blank-wednesday-golden"


def recorded_artifact() -> NormalizedResearchArtifact:
    """The artifact this repository recorded, loaded through its own type."""

    raw = (FIXTURES / f"{CASE}.artifact.json").read_text(encoding="utf-8")
    return NormalizedResearchArtifact.model_validate_json(raw)


@dataclass(frozen=True, slots=True)
class Scenario:
    """The identities every boundary answers about, derived from the artifact.

    Nothing here is a second source of truth: the evidence and source IDs are
    read off the recorded artifact, so an answer that cites them cites what the
    engine actually retrieved.
    """

    artifact: NormalizedResearchArtifact

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.artifact.evidence)

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.artifact.sources)


SCENARIO = Scenario(artifact=recorded_artifact())


@dataclass
class Ledger:
    """Which boundaries a run reached, in order, with the request each got.

    A composition proof needs this: "S-07 ran" is weak evidence next to "the
    strategy boundary was asked, once, about the anchor S-06 produced".
    """

    calls: list[tuple[str, str]] = field(default_factory=list)

    def record(self, name: str, request: str) -> None:
        self.calls.append((name, request))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.calls)

    def requests(self, name: str) -> tuple[str, ...]:
        return tuple(req for item, req in self.calls if item == name)

    def count(self, name: str) -> int:
        return len(self.requests(name))


class _Boundary:
    """A recorded boundary. Subclasses answer; this one only remembers."""

    name = "boundary"

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def complete(self, *, instructions: str, request: str) -> str:
        self.ledger.record(self.name, request)
        return self.answer(instructions=instructions, request=request)

    def answer(self, *, instructions: str, request: str) -> str:
        raise NotImplementedError


# ===========================================================================
# S-00 · source eligibility
# ===========================================================================


class Eligibility(_Boundary):
    """The role's criteria, met. The verdict schema is two fields and closed."""

    name = "eligibility"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        criteria = asked["eligibility_criteria"]
        return json.dumps({
            "eligible": True,
            "reason": (
                f"The case is a documented business event and satisfies all "
                f"{len(criteria)} declared criteria."
            ),
        })


# ===========================================================================
# S-01 · research retrieval, extended evidence assessment, relevance
# ===========================================================================


class Research:
    """The recorded artifact, re-identified for the run that asked for it.

    The evidence, sources, excerpts and readiness are the recorded ones and are
    not touched. What is replaced is identity and clock: a provider answers the
    request it was handed, and ``execute_and_persist_research`` checks exactly
    that — the artifact's run, assignment and signal must be the request's, its
    retrievals must match the outcomes reported beside them, and nothing may be
    timestamped before the invocation that produced it.
    """

    def __init__(self, ledger: Ledger, *, identity: Any) -> None:
        self.ledger = ledger
        self.identity = identity

    def research(self, request: ResearchProviderRequest) -> CompleteResearchResult:
        self.ledger.record("research", request.signal_id)
        artifact = recorded_artifact().model_copy(update={
            "run_id": request.run_id,
            "assignment_id": request.assignment_id,
            "signal_id": request.signal_id,
            "configuration_identity": self.identity,
            "created_at": request.requested_at,
            "sources": tuple(
                source.model_copy(update={"retrieved_at": request.requested_at})
                for source in recorded_artifact().sources
            ),
        })
        invocation = ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id="recorded-351",
                adapter_id="recorded-351",
                adapter_version="1.0",
                invocation_id="44444444-4444-4444-8444-444444444444",
            ),
            started_at=request.requested_at,
            completed_at=request.requested_at + timedelta(seconds=1),
            attempt_count=1,
        )
        outcomes = tuple(
            SourceRetrievalOutcome(
                retrieval_id=f"retrieval-{source.source_id}",
                origin=SourceOrigin.CLIENT_SUPPLIED,
                locator=source.locator.value,
                status=RetrievalStatus.RETRIEVED,
                attempted_at=request.requested_at,
                source_id=source.source_id,
                retrieved_at=request.requested_at,
            )
            for source in artifact.sources
        )
        return CompleteResearchResult(
            request_run_id=request.run_id,
            request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id,
            invocation=invocation,
            source_outcomes=outcomes,
            outcome=ResearchOperationOutcome.COMPLETE,
            artifact=artifact,
        )


class EvidenceJudgment(_Boundary):
    """The extended assessment this repository recorded for this case.

    Replayed rather than re-derived: #299 saved the answer beside the artifact
    it judges, so the strengths and dispositions S-01 builds the core from are
    the ones a reviewer can read in the fixture.
    """

    name = "evidence_judgment"

    def answer(self, *, instructions: str, request: str) -> str:
        return (FIXTURES / f"{CASE}.response.json").read_text(encoding="utf-8")


class Lens(_Boundary):
    """A ``proceed`` relevance judgment, stated about this artifact's IDs."""

    name = "lens"

    def answer(self, *, instructions: str, request: str) -> str:
        evidence = list(SCENARIO.evidence_ids)
        sources = list(SCENARIO.source_ids)
        return json.dumps({
            "disposition": "proceed",
            "relevance": "direct",
            "evidence_sufficiency": "sufficient",
            "why_signal_matters": (
                "It changes a capacity decision the audience is making now."
            ),
            "business_value_connection": (
                "The investment reprices the service the audience buys."
            ),
            "audience_problem_or_opportunity": (
                "Decide whether to commit to cold-chain capacity this year."
            ),
            "defensible_perspective": (
                "Capacity commitments are a commercial choice, not a trend."
            ),
            "supported_editorial_angle": (
                "What a carrier's capacity bet tells a small operator."
            ),
            "source_ids": sources,
            "evidence_ids": evidence,
            "relevance_bases": [{
                "basis_type": "direct_audience_evidence",
                "statement": "The cited evidence states the capacity change directly.",
                "evidence_ids": evidence,
                "source_ids": sources,
                "documented_direct_consequence": None,
            }],
            "criterion_results": [{
                "criterion_id": "nb-supported-mechanism",
                "assessment": "satisfied",
                "conclusion": "The evidence exposes a real operating decision.",
                "evidence_ids": evidence,
                "source_ids": sources,
                "restrictions": [],
            }],
            "research_condition_handling": [],
            "restrictions": ["Do not generalize beyond the cited carrier."],
            "disposition_reasons": [
                "Current-run evidence directly supports the angle."
            ],
        })


# ===========================================================================
# S-02 · material features
# ===========================================================================


class Material(_Boundary):
    """One answer per feature, cited to a claim the request actually carries.

    E-05 requires an entry for every member of the closed feature list, so the
    answer is built by walking the enum rather than by listing names: a feature
    added to the vocabulary makes this answer incomplete loudly instead of
    leaving a later condition to read "absent" where nothing was asked.
    """

    name = "material"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        usable = [
            item["evidence_claim_id"]
            for item in asked["claims"]
            if item["verdict"] in {"accepted", "qualified"}
        ]
        cited = usable[:1]
        values: list[dict[str, Any]] = []
        for feature in MaterialFeature:
            if feature is MaterialFeature.FIGURE_PROVENANCE:
                value: Any = "third_party"
                positive = True
            elif feature is MaterialFeature.FRESHNESS:
                value = "high"
                positive = True
            else:
                value = feature in _PRESENT
                positive = bool(value)
            values.append({
                "feature": feature.value,
                "value": value,
                "confidence": "medium",
                "rationale": "Read off the cited excerpt.",
                "evidence_refs": cited if positive else [],
            })
        return json.dumps({"features": values, "assets": [], "notes": []})


#: Which features the recorded case carries. A documented, named-company
#: investment with a stated mechanism — and not a first-person scene.
_PRESENT = frozenset({
    MaterialFeature.DOCUMENTED_CASE,
    MaterialFeature.NAMED_COMPANY,
    MaterialFeature.METHOD_KNOWN,
    MaterialFeature.MECHANISM_PRESENT,
    MaterialFeature.FAILURE_COST,
})


# ===========================================================================
# S-04 · the interpretation boundary (two calls, routed by instructions)
# ===========================================================================


class Boundary(_Boundary):
    """S-04's generate and probe calls, each answered from its own request.

    Routed by ``instructions`` and never by call order, for the reason #301's
    own double gives: what separates the two calls is the instructions each
    carries, so a double that answered by position would pass a stage that made
    one call twice.

    The readings are built out of the claims the request carries — their IDs,
    their verdicts and their recorded ceiling — so that nothing is cited that
    the core does not hold and no reading is stronger than the evidence under
    it. The audience transfer is the one the relevance screen already recorded;
    choosing a different one here would be this double overruling S-01.
    """

    name = "boundary"

    def answer(self, *, instructions: str, request: str) -> str:
        if instructions == GENERATE_INSTRUCTIONS:
            return self._generate(request)
        if instructions == PROBE_INSTRUCTIONS:
            return self._probe(request)
        return self._test(request)

    # -- the generate call ------------------------------------------------

    def _generate(self, request: str) -> str:
        asked = json.loads(request)
        claims = [item for item in asked["core"]["claims"] if item["usable"]]
        refs = [item["evidence_claim_id"] for item in claims]
        level = min(item["ceiling"]["level"] for item in claims)
        transfer = asked["relevance"]["audience_transfer"]
        return json.dumps({
            "interpretations": [
                {
                    "statement": (
                        "The carrier is buying capacity ahead of the demand it "
                        "expects, which is what the reported investment is for."
                    ),
                    "kind": "mechanism",
                    "support_refs": refs,
                    "counter_refs": [],
                    "depends_on": [],
                    "audience_transfer": transfer,
                    "strength_level": level,
                    "limits": [{
                        "text": (
                            "One reported investment by one carrier; nothing "
                            "here shows the timing holds elsewhere."
                        ),
                        "refs": refs[:1],
                    }],
                    "rationale": (
                        "The reported investment and the reported reason for it "
                        "are what the reading rests on."
                    ),
                    "rationale_refs": refs,
                },
                {
                    "statement": (
                        "A buyer of cold-chain capacity faces the timing "
                        "question this investment was made to answer."
                    ),
                    "kind": "consequence_for_reader",
                    "support_refs": refs,
                    "counter_refs": [],
                    "depends_on": [1],
                    "audience_transfer": transfer,
                    "strength_level": level,
                    "limits": [],
                    "rationale": (
                        "The recorded demand growth is what makes the timing "
                        "question the reader's as well."
                    ),
                    "rationale_refs": refs,
                },
            ],
            "limits": [{
                "text": "A single reported case, read only as far as it is reported.",
                "refs": refs[:1],
            }],
            "ambiguities": [],
            "reader_connection": {
                "text": (
                    "Capacity bought early is capacity priced before it is needed."
                ),
                "refs": refs,
            },
        })

    # -- the probe call ---------------------------------------------------

    def _probe(self, request: str) -> str:
        asked = json.loads(request)
        return json.dumps({
            "families": [
                {
                    "record_id": family["record_id"],
                    "finding": (
                        "Nothing among the proposed readings reaches past the "
                        f"recorded case in the way {family['record_id']} names."
                    ),
                    "tempting": None,
                }
                for family in asked["probe_families"]
            ],
            "verdicts": [
                {
                    "index": item["index"],
                    "admissibility": "admissible",
                    "finding": (
                        "Every reference the reading cites is a claim the core "
                        "records, and it claims nothing beyond them."
                    ),
                    "reason": None,
                    "temptation_note": None,
                }
                for item in asked["interpretations"]
            ],
        })

    # -- the re-entry test call -------------------------------------------

    def _test(self, request: str) -> str:
        asked = json.loads(request)
        return json.dumps({
            "reason": "unsupported",
            "temptation_note": (
                "It reads like the next sentence, which is why a writer adds it."
            ),
            "finding": (
                "The detected statement rests on nothing the core records."
            ),
            "matches": None,
            "statement": asked["detected"]["statement"],
            "kind": "other",
            "support_refs": [],
            "rationale": "No claim in the core carries it.",
            "rationale_refs": [],
        })


# ===========================================================================
# S-06 · the anchor
# ===========================================================================


class Anchor(_Boundary):
    """Chooses among the candidate readings the request offers, and says why.

    The index chosen is the first candidate the request carries rather than a
    constant: a stage that offered a different set would be answered about that
    set. The strength is the chosen candidate's own recorded level, so the
    anchor never claims more than the reading it is built on, and the leading
    material is cited from that candidate's own support.
    """

    name = "anchor"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        candidates = asked["candidates"]
        chosen = candidates[0]
        return json.dumps({
            "chosen_index": chosen["index"],
            "strength_level": chosen["strength_level"],
            "leading_material": list(chosen["support_refs"]),
            "candidates": [
                {
                    "index": item["index"],
                    "reason": (
                        "It is the reading closest to the recorded mechanism."
                        if item["index"] == chosen["index"]
                        else "It depends on the chosen reading rather than leading."
                    ),
                }
                for item in candidates
            ],
        })


# ===========================================================================
# S-08 · the candidate strategies
# ===========================================================================


class Strategy(_Boundary):
    """Two whole strategies per destination, both built from the request.

    §1 asks for two to four, and the two here differ in the one dimension a
    destination can legitimately change — where the reveal sits — so that S-09
    has something to rank rather than a duplicate. Every reference is taken from
    the request: the thesis cites the anchor's own reading, the leading material
    is the anchor's, and ``knowledge_used`` names only records the register
    actually routed to this stage, which for this run is none.
    """

    name = "strategy"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        anchor = asked["anchor"]
        leading = [item["ref"] for item in anchor["leading_material"]]
        admissible = [item["interpretation_id"] for item in asked["boundary"]["admissible"]]
        routed = [item["record_id"] for item in asked["knowledge"]]
        # A concession cites a limitation by its *text*: Step 1 gives a
        # Limitation no ID of its own, so the boundary's own wording is the
        # reference, carried across unchanged.
        limits = [item["text"] for item in asked["boundary"]["limits"]] + [
            limit["text"]
            for member in asked["boundary"]["admissible"]
            for limit in member["limits"]
        ]
        thesis_refs = [anchor["interpretation_id"]]
        second = next((item for item in admissible if item not in thesis_refs), None)
        return json.dumps({"candidates": [
            self._candidate(
                reveal="immediate",
                until_move=None,
                leading=leading,
                thesis_refs=thesis_refs,
                second=second,
                routed=routed,
                limitation=limits[0],
            ),
            self._candidate(
                reveal="delayed",
                until_move=2,
                leading=leading,
                thesis_refs=thesis_refs,
                second=second,
                routed=routed,
                limitation=limits[0],
            ),
        ]})

    def _candidate(
        self,
        *,
        reveal: str,
        until_move: Optional[int],
        leading: list[str],
        thesis_refs: list[str],
        second: Optional[str],
        routed: list[str],
        limitation: str,
    ) -> dict[str, Any]:
        decided = {
            "editorial_job": (
                "Show what buying capacity early does to the price of it."
            ),
            "angle": (
                "The carrier's investment read as a timing decision, not news."
            ),
            "editorial_thesis": (
                "Capacity bought before demand arrives is capacity priced "
                "before the buyer can negotiate."
            ),
            "focal_subject": "The carrier making the recorded investment.",
            "leading_material_ref": (
                "It is the claim the whole reading rests on."
            ),
            "reader_path": (
                "The recorded investment first, then what it does to a buyer."
            ),
            "opening": (
                "The reported figure opens; the consequence is held back."
            ),
            "reveal": f"A {reveal} reveal suits this destination's reading pace.",
            "concession": "The single-case limit is stated rather than buried.",
            "ending_intention": (
                "Leave the reader with the timing question, unanswered."
            ),
        }
        if second is not None:
            # An optional field is justified only when it was stated: a field a
            # candidate left out was not decided, and justifying it would be
            # the answer claiming a decision it did not make.
            decided["second_interpretation_ref"] = (
                "The reader's own consequence is a second reading, so it is "
                "named rather than folded into the thesis."
            )
        return {
            "editorial_job": decided["editorial_job"],
            "angle": decided["angle"],
            "thesis": decided["editorial_thesis"],
            "thesis_interpretation_refs": thesis_refs,
            "focal_subject_kind": "company",
            "focal_subject": decided["focal_subject"],
            "focal_subject_refs": leading[:1],
            "leading_material_ref": leading[0],
            "reader_path": [
                {
                    "text": "What the carrier bought, as reported.",
                    "purpose": "Put the recorded fact in front of the reader.",
                    "refs": leading[:1],
                },
                {
                    "text": "What early capacity does to a later buyer.",
                    "purpose": "Carry the mechanism to the reader's own decision.",
                    "refs": leading,
                },
            ],
            "opening": {
                "text": "A carrier committed to cold-chain capacity it does not yet need.",
                "held_back": "What that does to the price a buyer pays later.",
                "refs": leading[:1],
            },
            "reveal": reveal,
            "until_move": until_move,
            "concession": {
                "present": True,
                "limitation_ref": limitation,
                "move_index": 2,
            },
            "ending_intention": decided["ending_intention"],
            "second_interpretation_ref": second,
            "client_position_ref": None,
            "justifications": [
                {"field_name": name, "text": text, "refs": leading[:1]}
                for name, text in decided.items()
            ],
            "knowledge_used": routed,
        }


# ===========================================================================
# S-09 · the ranking that selects one strategy per destination
# ===========================================================================


class Ranking(_Boundary):
    """One ranking per candidate the request offers, never per candidate it has.

    The first candidate is rated higher on both axes so that the selection has
    a winner without a tie-break; the second is rated lower rather than absent,
    because a missing ranking is a candidate the stage was never told about and
    is a different fact from a candidate judged weaker.
    """

    name = "ranking"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        return json.dumps({"rankings": [
            {
                "index": item["index"],
                "evidence_fit": 4 if position == 0 else 3,
                "destination_fit": 4 if position == 0 else 2,
                "reason": (
                    "The reader path is carried by the cited claims and the "
                    "reveal suits this destination."
                    if position == 0
                    else "It holds the reveal back further than this "
                         "destination rewards."
                ),
            }
            for position, item in enumerate(asked["candidates"])
        ]})


# ===========================================================================
# S-10 · the segmentation that turns one strategy into one executable plan
# ===========================================================================


class Segmentation(_Boundary):
    """Cuts the given reader path into this destination's format.

    The two rules the instructions state are what this double honours, and it
    honours them from the request rather than by construction: every move the
    request carries is carried by a segment, and the segment count stays inside
    the capacity the request states when it states one. ``subheadings`` is a
    plan when the format takes them and ``None`` when it does not, because a
    format that takes them and was given nothing is a plan that was not made.
    """

    name = "segmentation"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        moves = [move["index"] for move in asked["strategy"]["reader_path"]]
        capacity = asked.get("segment_capacity")
        segments: list[dict[str, Any]] = [
            {
                "name": f"segment {position}",
                "purpose": "Carry this move on this surface.",
                "moves": [index],
            }
            for position, index in enumerate(moves, 1)
        ]
        if capacity is not None and len(segments) > capacity:
            # Every move must still be carried, so the moves that do not fit as
            # segments of their own are folded into the last segment rather than
            # dropped.
            head, tail = segments[: capacity - 1], segments[capacity - 1 :]
            folded = [index for item in tail for index in item["moves"]]
            segments = head + [{
                "name": f"segment {capacity}",
                "purpose": "Carry the remaining moves together.",
                "moves": folded,
            }]
        return json.dumps({
            "segments": segments,
            "first_line_mechanics": (
                "The first line stands before the reader expands the text, so "
                "it carries the recorded figure and nothing that depends on "
                "what follows."
            ),
            "subheadings": (
                "No subheadings; the segments run on."
                if asked["takes_subheadings"]
                else None
            ),
        })


# ===========================================================================
# S-11 · the per-destination plan check and the unit barrier B1
# ===========================================================================


class PlanCheck(_Boundary):
    """The two questions S-11 asks of one plan, answered as asked.

    Both answers are the "nothing wrong" ones, and both are the *shape* the
    stage parses rather than a bare ``true``: the conflict is ``None`` because
    no two fields were found to collide, and no forbidden construction is
    reported because the plan executes none. What makes this a usable double
    rather than a rubber stamp is that the deterministic half of V-P — the
    phrase matching, the slot checks, the length arithmetic — is code's and runs
    regardless of what this says.
    """

    name = "plan_check"

    def answer(self, *, instructions: str, request: str) -> str:
        return json.dumps({
            "fields_hold": True,
            "conflict": None,
            "forbidden_constructions": [],
        })


class Barrier(_Boundary):
    """B1: one judgment per destination in the request, and no contradiction.

    The judgments are built by walking the request's own plans, because the
    barrier requires an answer for every destination "exactly once each" — a
    double that listed destinations of its own would pass a barrier that was
    asked about a different set.
    """

    name = "barrier"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        return json.dumps({
            "plans": [
                {
                    "destination": plan["destination"],
                    "carries_anchor": True,
                    "detail": None,
                }
                for plan in asked["plans"]
            ],
            "contradictions": [],
        })


# ===========================================================================
# S-12 · the writer
# ===========================================================================


class Writer(_Boundary):
    """S-12's two calls: the write, and the edit that answers S-13's findings.

    One part per plan segment, named exactly as the plan names it. The prose is
    assembled out of the request — the claim statements as the core writes them,
    the move the segment carries as the plan states it, and nothing else. That is
    deliberately not "realistic writing"; it is the one kind of text a double can
    produce that S-13 can honestly check, because every sentence in it traces to
    a claim the core holds, and a forbidden phrase could only appear here if the
    plan or the core had put it there.

    The edit call is routed by instructions and answered over the request's own
    ``original_request``, as the next version of the same text: it repairs by
    closing differently, so the produced body differs from its predecessor, which
    is what makes "this is a new version" visible rather than asserted.

    ``title`` and ``dek`` follow the request's own ``takes_title_and_dek`` rather
    than a guess about the format, and a plan that asks for neither gets neither.
    """

    name = "writer"

    def answer(self, *, instructions: str, request: str) -> str:
        asked = json.loads(request)
        if instructions == REVISION_INSTRUCTIONS:
            return self._text(asked["original_request"], closing=_REPAIRED_CLOSING)
        if instructions == WRITER_INSTRUCTIONS:
            return self._text(asked, closing=_FIRST_CLOSING)
        raise AssertionError(  # pragma: no cover - the stage declares two calls
            "S-12 asked a question this double does not know; it answers the "
            "write and the edit, and must not guess at a third"
        )

    def _text(self, asked: dict[str, Any], *, closing: str) -> str:
        plan = asked["plan"]
        strategy = asked["strategy"]
        moves = {move["index"]: move for move in strategy["reader_path"]}
        claims = {
            claim["evidence_claim_id"]: claim
            for claim in asked["core_items"]["claims"]
        }
        segments = []
        for segment in plan["segments"]:
            carried = [moves[index] for index in segment["moves"] if index in moves]
            stated = [
                claims[ref]["statement"]
                for move in carried
                for ref in move.get("refs", ())
                if ref in claims
            ]
            sentences = [strategy["opening"]["text"]] if not segments else []
            sentences.extend(dict.fromkeys(stated))
            sentences.append(closing)
            segments.append({"name": segment["name"], "text": " ".join(sentences)})
        titled = plan["takes_title_and_dek"]
        return json.dumps({
            "plan_holds": True,
            "reason": None,
            "title": strategy["angle"] if titled else None,
            "dek": strategy["editorial_job"] if titled else None,
            "segments": segments,
        })


#: How the first write closes, and how an edit closes instead. Two wordings and
#: not one, so that "the edit produced the next version" is readable in the text
#: rather than taken on trust.
_FIRST_CLOSING = "Within the reported case, that is as far as the material goes."
_REPAIRED_CLOSING = (
    "The reported case carries this and no more, which is where it stops."
)


# ===========================================================================
# S-13 · the three model calls of the text check
# ===========================================================================

#: The three call kinds S-13 declares, each with the checks it answers. Keyed by
#: the production instruction text so that a renamed group is a failed run and
#: never a question answered by accident.
_TEXT_CHECK_CALLS: Mapping[str, tuple[str, ...]] = {
    TRUTH_INSTRUCTIONS: TRUTH_CHECKS,
    EXECUTION_INSTRUCTIONS: EXECUTION_CHECKS,
    SIBLING_RECHECK_INSTRUCTIONS: SIBLING_RECHECK_CHECKS,
}

#: The extra field each branched check's finding carries, and the branch this
#: double names. Stated rather than defaulted: §3 defaults an unnamed branch to
#: the plan, and a double that relied on the default would be testing the
#: default instead of the route.
_BRANCH_FIELD: Mapping[str, tuple[str, str]] = {
    "V-T01": ("branch", "load_bearing"),
    "V-T08": ("branch", "strategy"),
}


class TextCheck(_Boundary):
    """S-13's truth, execution and sibling-re-check calls.

    Routed by instructions, like S-04's two calls, and answered per check ID from
    the production constants rather than from a literal list — so a check added
    to a group is answered, and a renamed group fails the run loudly instead of
    going silently unanswered.

    ``fails`` makes one named check fail, which is how the routes are proved: a
    V-T06 failure is the edit class and sends the text back to S-12, a V-T03
    failure is the replan class and sends the destination back to S-08, and a
    V-T02 failure is the boundary class and re-enters S-04. ``from_call`` limits
    the failure to the Nth invocation of the call kind that owns the failing
    check, which is how a scenario can let five siblings be accepted before the
    sixth text discovers an inadmissible reading.

    What no setting here can do is pass S-13's code half: V-T04's link
    resolution, V-T05, the forbidden-phrase match and the figure check are never
    asked of a transport and run on the real text whatever this answers.
    """

    name = "text_check"

    def __init__(
        self,
        ledger: Ledger,
        *,
        fails: Optional[str] = None,
        detail: str = "the text does not hold against this criterion",
        from_call: Optional[int] = None,
    ) -> None:
        super().__init__(ledger)
        self.fails = fails
        self.detail = detail
        self.from_call = from_call
        self.answered: Counter[str] = Counter()

    def answer(self, *, instructions: str, request: str) -> str:
        expected = _TEXT_CHECK_CALLS.get(instructions)
        if expected is None:  # pragma: no cover - the stage declares three
            raise AssertionError(
                "S-13 asked a question this double does not know; it answers the "
                "three calls the stage declares and must not guess at a fourth"
            )
        self.answered[instructions] += 1
        failing = self.fails in expected and (
            self.from_call is None or self.answered[instructions] == self.from_call
        )
        return json.dumps({
            check_id.lower().replace("-", "_"): self._entry(check_id, failing)
            for check_id in expected
        })

    def _entry(self, check_id: str, failing: bool) -> dict[str, Any]:
        if not (failing and check_id == self.fails):
            return {"holds": True, "findings": []}
        finding: dict[str, Any] = {"detail": self.detail}
        if check_id == "V-T02":
            # The re-entry is given the reading the text expressed, and a V-T02
            # finding that could not say what it was would ask S-04 about
            # nothing.
            finding["interpretation_ref"] = None
        field = _BRANCH_FIELD.get(check_id)
        if field is not None:
            finding[field[0]] = field[1]
        return {"holds": False, "findings": [finding]}


# ===========================================================================
# The run, assembled from production producers only
# ===========================================================================


@dataclass(frozen=True, slots=True)
class CanonicalRun:
    """Everything one canonical run needs, and where each part came from."""

    seams: GoldenEngineSeams
    configuration: GoldenEngineConfiguration
    signal: dict[str, Any]
    binding: ResearchBinding
    run_context: RunContext
    runs_root: Path
    packages_dir: Path
    ledger: Ledger
    now: datetime


#: The run's clock. Handed in, never read: CE-1 makes every timestamp the
#: harness's, and a test that read the wall clock could not compare two runs.
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def canonical_run(
    tmp_path: Path,
    *,
    text_check: Optional[TextCheck] = None,
    barrier: Optional[Barrier] = None,
    signal_id: str = "sig-351-exec",
) -> CanonicalRun:
    """Assemble one canonical run: production configuration, authored answers.

    Every input below has exactly one producer, and it is the production one:

    * the role comes from ``resolve_editorial_role`` over the declared business
      strategy configuration — not an authored ``EditorialRole``;
    * the twelve authorities come from ``golden_engine_configuration`` over the
      real register and the real client directory;
    * the signal's two editorial classifications are taken from the client
      contract's own fit rules, so the intake record states values the contract
      admits rather than strings chosen here;
    * the assignment comes from ``from_jsonl_signal``, the research request from
      ``build_research_request``, the Decision-Lens inputs from
      ``StrategyExecutionContext``, and the legacy run directory from
      ``resolve_run_dir``.

    What is authored is the eleven external answers and the intake record itself.
    """

    configuration = load_business_strategy_configuration()
    _, role = resolve_editorial_role(configuration, ROLE_ID)
    golden = golden_engine_configuration(
        register_dir=REGISTER_DIR, client_dir=CLIENT_DIR, role=role
    )
    context = StrategyExecutionContext.from_configuration(configuration)
    strategy_view = context.decision_lens_editorial
    signal = {
        "SIGNAL_ID": signal_id,
        "HEADLINE": "A carrier invests in cold-chain capacity",
        "SOURCE_URL": "https://example.test/cold-chain-capacity",
        "CORE_FACT": "A carrier invested in cold-chain logistics capacity.",
        "TARGET_AUDIENCE": "small-b2b-agencies",
        # Admitted values, read off the contract's own fit rules (#365/#368).
        "EDITORIAL_DOMAIN": golden.fit_rules.rules[0].admits[0],
        "EDITORIAL_DOMAIN_OUTCOME": "admitted",
        "EDITORIAL_RISK": golden.fit_rules.rules[1].admits[0],
        "EDITORIAL_RISK_OUTCOME": "admitted",
    }
    run_context = canonical_run_context(signal_id, NOW)
    assignment = from_jsonl_signal(
        signal,
        strategy_ref=run_context.strategy_ref,
        strategy_version=run_context.strategy_version,
    )
    request = build_research_request(
        run_context, assignment, signal, context.research, now=NOW
    )
    packages_dir = tmp_path / "content_packages"
    legacy_run_dir = resolve_run_dir(packages_dir, signal_id, run_context.run_id)
    legacy_run_dir.mkdir(parents=True)
    binding = ResearchBinding(
        request=request,
        identity=strategy_view.identity,
        strategy_view=strategy_view,
        audience_selection=strategy_view.select_audience(None),
        lens_profile=RELEASE1_LENS_PROFILE,
        assignment_id=assignment.assignment_id,
        run_dir=legacy_run_dir,
        run_started_at=NOW,
    )
    ledger = Ledger()
    bound = {
        "material": Material(ledger),
        "boundary": Boundary(ledger),
        "anchor": Anchor(ledger),
        "strategy": Strategy(ledger),
        "ranking": Ranking(ledger),
        "segmentation": Segmentation(ledger),
        "plan_check": PlanCheck(ledger),
        "barrier": barrier or Barrier(ledger),
        "writer": Writer(ledger),
        "text_check": text_check or TextCheck(ledger),
    }
    for double in bound.values():
        double.ledger = ledger
    missing = sorted(set(GoldenEngineTransports.__dataclass_fields__) - set(bound))
    if missing:  # pragma: no cover - a new transport must be answered, not skipped
        raise AssertionError(
            "the transport bundle declares " + ", ".join(missing) + ", which this "
            "scenario supplies no answer for; an unanswered boundary would make a "
            "stage fail for want of a double rather than for want of a contract"
        )
    seams = GoldenEngineSeams(
        transports=GoldenEngineTransports(**bound),
        research=Research(ledger, identity=strategy_view.identity),
        eligibility=Eligibility(ledger),
        evidence_judgment=EvidenceJudgment(ledger),
        relevance=DecisionLensEvaluator(
            Lens(ledger),
            DecisionLensInstructions.load(DEFAULT_INSTRUCTIONS_PATH),
        ),
    )
    return CanonicalRun(
        seams=seams,
        configuration=golden,
        signal=signal,
        binding=binding,
        run_context=run_context,
        runs_root=tmp_path / "editorial_runs",
        packages_dir=packages_dir,
        ledger=ledger,
        now=NOW,
    )


def execute(run: CanonicalRun, *, limit: int = WEDNESDAY_MAX_CEILING):
    """Execute the canonical topology over ``run``, and return its result.

    The call budget is the production one and is charged by the stages through
    the production wrap; ``limit`` is a ceiling and never a target. It is the
    Wednesday role's declared ceiling because that is the role this scenario
    resolves, and because the canonical six-destination topology costs more
    logical calls than ``R1_MAX_CEILING`` admits — see the module note in
    ``tests/test_351_golden_engine_execution.py``.
    """

    workspace = RunWorkspace.create(run.runs_root, run.run_context.run_id)
    budget = ArpCallBudget(RunCallBudget(limit, hard_max=WEDNESDAY_MAX_CEILING))
    execution = execute_canonical_topology(
        workspace=workspace,
        run_context=run.run_context,
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        budget=budget,
        now=run.now,
    )
    return execution, workspace, budget
