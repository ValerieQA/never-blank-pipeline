"""S-01 · the #58 evaluator as a relevance screen (Issue #299, slice SL-3).

The second half of S-01, and the one refinement R-1 moved. AD-09 placed the #58
outputs "before S-00 and S-04"; the evaluator needs the research artifact, so it
cannot run before research, and Step 2 §7 (R-1) puts it at the **end of S-01**
as an early screen — before any money is spent on enrichment.

What changes here is not the judgment but what is done with it (Step 5 §1.2):

- ``revise`` / ``hold`` are **not a wait**. The current engine stops the run
  there; a live Wednesday run was stopped exactly that way. I-01 makes it a
  ``REPLAN`` into S-03 with a ``reader_connection`` or ``evidence`` gap while
  ``L_enrich`` allows, and a ``SKIP`` once it does not;
- ``reject``, ``irrelevant`` and ``insufficient_evidence`` end the signal, each
  with its own recorded state so that a client reading the skip rate can tell
  "not for this audience" from "not enough evidence to tell";
- ``supported_editorial_angle`` and ``defensible_perspective`` are **hints**
  (AD-09). They are recorded and consumed by nothing, which is structural here
  rather than promised: :meth:`RelevanceAssessment.for_boundary` is the whole of
  what S-04 receives, and the hints are not in it. Two components must not
  decide the angle;
- what *does* feed the boundary is relevance plus claim mode. ``claim_mode``
  becomes E-08's ``audience_transfer`` (AD-08, which reuses the meaning of #58's
  ``EditorialClaimMode``), so the Lens no longer decides the story — it decides
  whether the material concerns this audience and how the article may speak
  about them.

The reconciled profile — ``never_blank_reconciled.yaml`` under
``config/prompts/decision_lens/``, instruction revision 1.3 — says the same four
things to the model, which is the #151 debt Step 5 §1.2 deferred and then
defined. It is a **second** artifact, selected by :func:`screen_instructions`
and only behind a flag that is off by default: its ``proceed`` no longer
requires an angle, and the live research Friday/Sunday path reads the maintained
``never_blank.yaml``, which still does. NB-03b is shadow only, and an edit to
that file is a change to what a live run decides whatever else it is. The
decision **contract** is untouched either way: ``decision.json`` keeps its
schema, so every artifact already written still validates and reuse through
``--from-package`` still works.

``require_proceed`` is replaced rather than called (§1, Seam): a disposition is
routed here, not raised. ``DecisionPolicyRecord`` is not consulted at all —
canonical runs carry a RelevanceAssessment, and Step 5 §1.2 keeps the policy
record for current paths only.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-01)
and §7 (R-1); ``docs/editorial/architecture/06_STEP5_MIGRATION_MAP.md`` §1.2;
``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md`` AD-08 and AD-09.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, Optional

from src.editorial.decision_contract import (
    AudienceRelevanceBasisType,
    BusinessAudienceRelevance,
    DecisionDisposition,
    DecisionEvidenceSufficiency,
    DecisionLensDecisionArtifact,
    DecisionLensJudgment,
    DecisionLensProfileIdentity,
    EditorialClaimMode,
    research_artifact_digest,
)
from src.editorial.decision_lens_evaluator import (
    DEFAULT_INSTRUCTIONS_PATH,
    DecisionLensEvaluator,
    DecisionLensInstructions,
)
from src.editorial.decision_lifecycle import (
    DecisionGateError,
    evaluate_and_persist_decision,
)
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.evidence_core import STAGE, EvidenceCore
from src.editorial_core.signal_selection import CallBudget
from src.research.evidence import NormalizedResearchArtifact
from src.strategy.execution_context import (
    AudienceSelection,
    ConfigurationIdentity,
    DecisionLensEditorialStrategyView,
)

#: The route this screen may take, exactly as the topology registry declares it
#: (Step 2 §5.3). Named here so the stage asks for a declared route rather than
#: describing one: an undeclared backward edge is a second engine.
ENRICHMENT_ROUTE_CAUSE: Final[str] = "relevance_revise_or_hold"

#: Where the enrichment REPLAN goes. Recorded for readers; the target itself
#: comes from the registry through :class:`AttemptCounterLedger`.
ENRICHMENT_ROUTE_TARGET: Final[str] = "S-03"

#: The reconciled instruction revision (Step 5 §1.2), as its own artifact beside
#: the maintained one. Separate rather than an edit because the maintained file
#: is what the live research path reads, and revision 1.3 drops the angle from
#: the ``proceed`` bar — on that path the reconciliation would be a change to
#: what a live run decides, which NB-03b's production-safety line forbids.
RECONCILED_INSTRUCTIONS_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "prompts"
    / "decision_lens"
    / "never_blank_reconciled.yaml"
)

#: What turns the reconciled revision on. Off unless the environment says
#: otherwise, and nothing in this repository says otherwise, so it is off in
#: production: a job that wants revision 1.3 sets it in its own environment.
RECONCILED_PROFILE_FLAG: Final[str] = "NB_RECONCILED_LENS_PROFILE"


class RelevanceScreenError(RuntimeError):
    """The screen was asked to judge something it cannot honestly judge."""


class AudienceTransfer(str, Enum):
    """E-08's ``audience_transfer`` vocabulary (AD-08).

    Declared here because S-01 is what produces the value and S-04 is what
    consumes it; AD-08 makes it a first-class field of E-08, and E-08 arrives
    with the stage that owns it.
    """

    DIRECT_AUDIENCE = "direct_audience"
    BOUNDED_EXTERNAL_CASE = "bounded_external_case"


#: AD-08: the transfer field "reuses the meaning of #58 ``EditorialClaimMode``".
#: A table rather than a branch, so that a claim mode without a transfer is a
#: missing row and not a silent default.
_TRANSFER_OF_CLAIM_MODE: Mapping[EditorialClaimMode, AudienceTransfer] = {
    EditorialClaimMode.DIRECT_AUDIENCE_CLAIM: AudienceTransfer.DIRECT_AUDIENCE,
    EditorialClaimMode.BOUNDED_EXTERNAL_CASE: AudienceTransfer.BOUNDED_EXTERNAL_CASE,
}


class RequestedGapKind(str, Enum):
    """The gap kinds S-01 may ask S-03 for (§1, ARP).

    Two of E-07's six, because §1 names exactly these two: the others describe
    material S-02 has not looked at yet. S-01 asks; S-03 is the sole producer of
    the E-07 the request becomes (fix F-3).
    """

    EVIDENCE = "evidence"
    READER_CONNECTION = "reader_connection"


#: The dispositions that end the signal, and the state each is recorded as.
#: Separate states because §3.3 carries the state code and not the disposition:
#: an audience the material does not concern and evidence too thin to tell are
#: two different things for a client to read in the skip rate.
_TERMINAL_STATES: Mapping[DecisionDisposition, StateCode] = {
    DecisionDisposition.REJECT: StateCode.SIGNAL_NOT_RELEVANT,
    DecisionDisposition.INSUFFICIENT_EVIDENCE: (
        StateCode.RELEVANCE_EVIDENCE_INSUFFICIENT
    ),
}

#: The two §1 routes into enrichment. Not a wait, and not a stop.
_ENRICHMENT_DISPOSITIONS = frozenset({
    DecisionDisposition.REVISE,
    DecisionDisposition.HOLD,
})


# ===========================================================================
# The RelevanceAssessment (§1, Outputs)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DecisionRef:
    """Where the legacy ``decision.json`` is, and what it said (§2.2).

    The canonical workspace references the artifacts the existing lifecycle
    writes rather than copying them — the wrap relationship from Step 0 — so
    this is a path and a digest, and ``decision.json`` stays the record.
    """

    path: str
    digest: str

    def as_entity(self) -> dict[str, str]:
        return {"path": self.path, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class RelevanceHints:
    """The two #58 fields that decide nothing (AD-09).

    Kept because the judgment is worth reading and because deleting them from
    the decision contract would invalidate every artifact already written. Not
    kept in :class:`BoundaryInput`, which is the whole of what S-04 receives.
    """

    supported_editorial_angle: str
    defensible_perspective: str

    def as_entity(self) -> dict[str, Any]:
        return {
            "supported_editorial_angle": self.supported_editorial_angle,
            "defensible_perspective": self.defensible_perspective,
            #: Written into the artifact rather than left to documentation: a
            #: reader of one relevance record can see that these two were
            #: recorded as hints, without having to know AD-09.
            "consumed_downstream": False,
        }


@dataclass(frozen=True, slots=True)
class RelevanceBasis:
    """Why the cited research concerns the configured audience (#58, restricted).

    The basis type and its references, and not the statement prose: what S-04
    needs is which claims carry the audience connection and on what kind of
    ground. ``analogy_only`` is a legitimate answer here, and the decision
    contract already refuses to let it alone produce a ``proceed``.
    """

    basis_type: AudienceRelevanceBasisType
    evidence_claim_refs: tuple[str, ...]
    source_refs: tuple[str, ...]

    def as_entity(self) -> dict[str, Any]:
        return {
            "basis_type": self.basis_type.value,
            "evidence_claim_refs": list(self.evidence_claim_refs),
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class BoundaryInput:
    """Exactly what the Interpretation Boundary receives from the screen.

    S-04's input list asks for the "RelevanceAssessment (claim mode and
    relevance bases)", and this is that list and nothing else. It is a type
    rather than a convention so that "the angle fields are not consumed
    downstream" is checkable: there is nowhere in here to put one.
    """

    relevance: BusinessAudienceRelevance
    audience_transfer: AudienceTransfer
    relevance_bases: tuple[RelevanceBasis, ...]

    def as_entity(self) -> dict[str, Any]:
        return {
            "relevance": self.relevance.value,
            "audience_transfer": self.audience_transfer.value,
            "relevance_bases": [basis.as_entity() for basis in self.relevance_bases],
        }


@dataclass(frozen=True, slots=True)
class RelevanceAssessment:
    """``RelevanceAssessment``: the #58 decision, restricted per AD-09."""

    signal_id: str
    core_ref: str
    decision: DecisionRef
    disposition: DecisionDisposition
    relevance: BusinessAudienceRelevance
    audience_transfer: AudienceTransfer
    evidence_sufficiency: DecisionEvidenceSufficiency
    relevance_bases: tuple[RelevanceBasis, ...]
    hints: RelevanceHints
    #: What the screen asks enrichment for. Empty unless the disposition routes
    #: into S-03: a gap is a request, and the other dispositions request nothing.
    requested_gaps: tuple[RequestedGapKind, ...] = ()

    def __post_init__(self) -> None:
        if not self.signal_id.strip() or not self.core_ref.strip():
            raise RelevanceScreenError(
                "a relevance assessment names the signal it judged and the core "
                "it judged it on"
            )
        if not self.relevance_bases:
            raise RelevanceScreenError(
                f"{self.signal_id} has a relevance assessment with no basis; #58 "
                "requires at least one, and a relevance nothing grounds is a "
                "relevance nobody can check"
            )
        if self.requested_gaps and self.disposition not in _ENRICHMENT_DISPOSITIONS:
            raise RelevanceScreenError(
                f"{self.signal_id} is {self.disposition.value} and requests an "
                "enrichment gap; only `revise` and `hold` route into S-03 "
                "(Step 2 §1), and a gap nothing will act on is a request made "
                "of nobody"
            )

    @property
    def assessment_id(self) -> str:
        return f"rel-{self.signal_id}"

    def for_boundary(self) -> BoundaryInput:
        """What S-04 consumes: relevance, claim mode as transfer, and bases."""

        return BoundaryInput(
            relevance=self.relevance,
            audience_transfer=self.audience_transfer,
            relevance_bases=self.relevance_bases,
        )

    def as_entity(self) -> dict[str, Any]:
        """The entity body written to ``signal/relevance.ref.json`` (§2.2)."""

        return {
            "entity_type": "E-04.relevance_ref",
            "entity_id": self.assessment_id,
            "signal_id": self.signal_id,
            "core_ref": self.core_ref,
            "decision": self.decision.as_entity(),
            "disposition": self.disposition.value,
            "evidence_sufficiency": self.evidence_sufficiency.value,
            "boundary_input": self.for_boundary().as_entity(),
            "requested_gaps": [gap.value for gap in self.requested_gaps],
            "hints": self.hints.as_entity(),
        }


@dataclass(frozen=True, slots=True)
class RelevanceScreen:
    """What the screen made of one core.

    A ``REPLAN`` carries an assessment: the gap S-03 is asked to close is in it,
    and a route with nothing to act on would be a loop. A screen that produced
    no judgment at all carries none.
    """

    signal_id: str
    assessment: Optional[RelevanceAssessment] = None
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if self.assessment is None and self.outcome is None:
            raise RelevanceScreenError(
                f"{self.signal_id} was screened and neither a relevance "
                "assessment nor an outcome was recorded"
            )
        if self.replans and self.assessment is None:
            raise RelevanceScreenError(
                f"{self.signal_id} routes into {ENRICHMENT_ROUTE_TARGET} with no "
                "assessment, so nothing says what enrichment is asked to close"
            )

    @property
    def continues(self) -> bool:
        """Did the screen let the signal go forward to S-02?"""

        return self.outcome is None

    @property
    def replans(self) -> bool:
        return self.outcome is not None and self.outcome.outcome is ArpOutcome.REPLAN


# ===========================================================================
# The screen
# ===========================================================================


def reconciled_profile_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Is instruction revision 1.3 turned on for this process?"""

    values: Mapping[str, str] = os.environ if env is None else env
    return values.get(RECONCILED_PROFILE_FLAG, "").strip().casefold() in {
        "1",
        "true",
        "yes",
    }


def screen_instructions(
    env: Optional[Mapping[str, str]] = None,
) -> DecisionLensInstructions:
    """Which instruction artifact this screen runs the #58 evaluator on.

    The maintained production artifact unless :data:`RECONCILED_PROFILE_FLAG`
    is on, which is how "current production behaviour is unchanged" holds while
    the reconciliation exists in the repository: the reconciled revision is a
    file production never reads and a flag production never sets. The profile
    identity is the same in both, so either one satisfies the Release 1 lens
    profile and the decision each writes records which revision judged it.
    """

    if reconciled_profile_enabled(env):
        return DecisionLensInstructions.load(RECONCILED_INSTRUCTIONS_PATH)
    return DecisionLensInstructions.load(DEFAULT_INSTRUCTIONS_PATH)


def screen_relevance(
    *,
    core: EvidenceCore,
    research: NormalizedResearchArtifact,
    evaluator: DecisionLensEvaluator,
    strategy_view: DecisionLensEditorialStrategyView,
    audience: AudienceSelection,
    identity: ConfigurationIdentity,
    lens_profile: DecisionLensProfileIdentity,
    run_id: str,
    assignment_id: str,
    signal_id: str,
    run_dir: Path,
    counters: AttemptCounterLedger,
    budget: Optional[CallBudget] = None,
) -> RelevanceScreen:
    """Screen the core for relevance, and route the disposition (§1, ARP).

    Returns a :class:`RelevanceScreen` in every case. The #58 evaluator is
    invoked exactly once, through the existing lifecycle, so ``decision.json``
    is written create-once, strict-reloaded and revalidated against this run's
    research exactly as it is in production. What this does not do is call
    ``require_proceed``: a non-``proceed`` disposition is a route, not a stop.
    """

    _judges_the_core_the_run_built(core, research)
    if budget is not None:
        refusal = budget.spend(scope=OutcomeScope.SIGNAL, scope_key=signal_id)
        if refusal is not None:
            return RelevanceScreen(signal_id=signal_id, outcome=refusal)

    try:
        decision = evaluate_and_persist_decision(
            evaluator,
            research=research,
            strategy_view=strategy_view,
            audience=audience,
            configuration_identity=identity,
            lens_profile=lens_profile,
            run_id=run_id,
            assignment_id=assignment_id,
            signal_id=signal_id,
            run_dir=run_dir,
        )
    except DecisionGateError as exc:
        # No decision artifact exists, so there is no judgment to route and
        # nothing about the audience has been said. The detail is the
        # evaluator's own bounded text — never provider output — and it stays in
        # the workspace, where free text belongs (§3.3).
        return RelevanceScreen(
            signal_id=signal_id,
            outcome=_skip(signal_id, StateCode.RELEVANCE_SCREEN_FAILED, str(exc)),
        )

    judgment = decision.judgment
    # Which route this takes is decided before the assessment is built, because
    # the gap it records is a request of enrichment and only one route makes
    # one: `irrelevant` is terminal whichever disposition carried it, so a
    # `revise` that is also irrelevant asks for nothing.
    irrelevant = judgment.relevance is BusinessAudienceRelevance.IRRELEVANT
    enriches = (
        decision.disposition in _ENRICHMENT_DISPOSITIONS and not irrelevant
    )
    assessment = _assessment(core, decision, run_dir, signal_id, enriches=enriches)

    if irrelevant:
        # §1 puts `irrelevant` in the terminal set beside `reject`, whatever
        # disposition carried it. Enrichment closes gaps in material that
        # concerns the audience; it does not make an audience concerned.
        return RelevanceScreen(
            signal_id=signal_id,
            assessment=assessment,
            outcome=_skip(
                signal_id,
                StateCode.SIGNAL_NOT_RELEVANT,
                "the relevance screen found the material irrelevant to "
                f"{audience.audience_id} (disposition "
                f"{decision.disposition.value})",
            ),
        )

    terminal = _TERMINAL_STATES.get(decision.disposition)
    if terminal is not None:
        return RelevanceScreen(
            signal_id=signal_id,
            assessment=assessment,
            outcome=_skip(
                signal_id,
                terminal,
                f"the relevance screen returned {decision.disposition.value} "
                f"(relevance {judgment.relevance.value}, evidence "
                f"{judgment.evidence_sufficiency.value})",
            ),
        )

    if enriches:
        # The ledger, not this stage, decides whether there is an attempt left
        # and what the route ends in when there is not: the contract is in the
        # registry and the accounting is in the ledger, so a stage cannot talk
        # either into a different answer.
        return RelevanceScreen(
            signal_id=signal_id,
            assessment=assessment,
            outcome=counters.route(
                source=STAGE,
                cause=ENRICHMENT_ROUTE_CAUSE,
                scope_key=signal_id,
                state_code=StateCode.RELEVANCE_NOT_ESTABLISHED,
                reason=(
                    "the relevance screen returned "
                    f"{decision.disposition.value}; enrichment is asked for "
                    + ", ".join(gap.value for gap in assessment.requested_gaps)
                ),
            ),
        )

    if decision.disposition is not DecisionDisposition.PROCEED:
        raise RelevanceScreenError(
            f"disposition {decision.disposition.value!r} has no route out of "
            f"{STAGE}; a disposition the screen cannot route is not one it may "
            "treat as proceed"
        )
    return RelevanceScreen(signal_id=signal_id, assessment=assessment)


# ===========================================================================
# Internals
# ===========================================================================


def _judges_the_core_the_run_built(
    core: EvidenceCore, research: NormalizedResearchArtifact
) -> None:
    """The screen judges the artifact the core wraps, and says so by digest."""

    digests = {digest for _, digest in core.research_artifact_refs}
    if research_artifact_digest(research) not in digests:
        raise RelevanceScreenError(
            f"core {core.core_id} wraps research artifact(s) "
            + ", ".join(sorted(artifact for artifact, _ in core.research_artifact_refs))
            + f", and the screen was handed {research.artifact_id}; the "
            "relevance of a core is judged on the evidence that core holds"
        )


def _assessment(
    core: EvidenceCore,
    decision: DecisionLensDecisionArtifact,
    run_dir: Path,
    signal_id: str,
    *,
    enriches: bool,
) -> RelevanceAssessment:
    judgment = decision.judgment
    transfer = _TRANSFER_OF_CLAIM_MODE.get(judgment.claim_mode)
    if transfer is None:  # pragma: no cover - the table is total over the enum
        raise RelevanceScreenError(
            f"claim mode {judgment.claim_mode.value!r} has no audience transfer; "
            "AD-08 maps the two, and an unmapped mode would reach S-04 as no "
            "transfer at all"
        )
    return RelevanceAssessment(
        signal_id=signal_id,
        core_ref=core.core_id,
        decision=_decision_ref(run_dir, decision),
        disposition=decision.disposition,
        relevance=judgment.relevance,
        audience_transfer=transfer,
        evidence_sufficiency=judgment.evidence_sufficiency,
        relevance_bases=tuple(
            RelevanceBasis(
                basis_type=basis.basis_type,
                evidence_claim_refs=tuple(basis.evidence_ids),
                source_refs=tuple(basis.source_ids),
            )
            for basis in judgment.relevance_bases
        ),
        hints=RelevanceHints(
            supported_editorial_angle=judgment.supported_editorial_angle,
            defensible_perspective=judgment.defensible_perspective,
        ),
        requested_gaps=_requested_gaps(judgment) if enriches else (),
    )


def _requested_gaps(judgment: DecisionLensJudgment) -> tuple[RequestedGapKind, ...]:
    """Which gap kind the screen asks enrichment for, decided by code.

    From the two facts the judgment states rather than from its prose: evidence
    that is not sufficient is an ``evidence`` gap, and a relevance that does not
    meet its own claim mode's bar is a ``reader_connection`` one. Both can hold
    at once. Neither holding is still a request — §1 routes ``revise``/``hold``
    into enrichment, S-03 opens only gaps that block a decision, and the
    evidence gap is the one that named the block.
    """

    kinds: list[RequestedGapKind] = []
    if judgment.evidence_sufficiency is not DecisionEvidenceSufficiency.SUFFICIENT:
        kinds.append(RequestedGapKind.EVIDENCE)
    if not _relevance_bar_met(judgment.claim_mode, judgment.relevance):
        kinds.append(RequestedGapKind.READER_CONNECTION)
    return tuple(kinds) or (RequestedGapKind.EVIDENCE,)


def _relevance_bar_met(
    claim_mode: EditorialClaimMode, relevance: BusinessAudienceRelevance
) -> bool:
    """Does this relevance meet the bar the declared claim mode sets?

    The decision contract's own rule, read rather than restated with different
    words: bounded external-case mode trades the direct bar for a promise about
    how the article will speak, and admits ``indirect``; direct-claim mode
    requires ``direct``.
    """

    if claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE:
        return relevance is not BusinessAudienceRelevance.IRRELEVANT
    return relevance is BusinessAudienceRelevance.DIRECT


def _decision_ref(
    run_dir: Path, decision: DecisionLensDecisionArtifact
) -> DecisionRef:
    """The legacy decision's path and digest (§2.2).

    The path is relative to the legacy package root — ``<signal>/runs/<run>`` —
    so the reference survives the workspace being read anywhere. The digest is
    taken over the artifact's canonical bytes, which the lifecycle has already
    proved identical to the file's: it strict-reloads what it wrote and refuses
    a non-canonical byte.
    """

    relative = Path(*run_dir.parts[-3:], "decision.json")
    digest = hashlib.sha256(decision.canonical_bytes()).hexdigest()
    return DecisionRef(path=relative.as_posix(), digest=f"sha256:{digest}")


def _skip(signal_id: str, state_code: StateCode, reason: str) -> OutcomeRecord:
    return OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=state_code,
        scope=OutcomeScope.SIGNAL,
        scope_key=signal_id,
        reason=reason,
    )
