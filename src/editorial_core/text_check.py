"""S-13 · Text check: verify every text, and route each failure to the layer that decided it.

Issue #307, slice SL-6. §3: "Verify the text against the core, the boundary, the
plan and the contract. Route each failure to the layer that made the decision. It
must not rewrite."

Three routes, three different scopes — the whole difficulty
----------------------------------------------------------
S-13 is a **destination**-scoped stage, and not one of the counters it spends is
counted at its own scope (§0.3):

============================  ==============  =============  ==================
route                         counter         counter scope  scope key
============================  ==============  =============  ==================
S-13 → S-12 (text fault)      ``L_edit``      text           the **approved plan**
S-13 → S-08 (strategy fault)  ``L_strategy``  destination    unit + destination
S-13 → S-04 (boundary fault)  ``L_boundary``  unit           the unit
============================  ==============  =============  ==================

The ledger keys on ``(counter_id, scope_key)``, so the three cannot consume one
another. But it validates only that a key is a non-empty string, and nothing in
this repository compares :class:`~src.editorial_core.topology.CounterScope`
against a key — so the shape of each key is this module's to get right, and #304's
defect is what getting it wrong looks like.

Why ``L_edit`` is keyed on the approved plan and not on the text
---------------------------------------------------------------
§0.3's table reads ``L_edit | text | **1 per approved plan**``, and every route
row says the target is "S-12 edit, **same plan**". ``E-15.version`` is "+1 per
edit", so keying on ``text_ref`` would mint a fresh allowance with every edit —
an unbounded edit loop wearing a bound's clothes. Keying on
``plan.scope_key`` instead is the opposite error: that is ``L_strategy``'s
destination key, and a second approved plan for one destination would inherit the
first's spent allowance, silently making the limit "1 per destination".

So the key is the approved plan's own identity, which
:attr:`~src.editorial_core.writer.Text.plan_ref` carries as ``(plan_id, version)``
— stable across every edit of one text, and different for the genuinely new
approved plan a ``L_strategy`` replan produces. The bound composes:
``L_strategy`` 2 per destination × ``L_edit`` 1 per approved plan ⇒ at most two
edits per destination in a run.

What it must not do
-------------------
"It must not rewrite." Every failure here produces a route or a terminal outcome
and no prose. The Writer's edit entry point is
:func:`~src.editorial_core.writer.revise_prose`, which this stage calls nothing of
— it hands findings back and S-12 decides what they mean for the text.

V-S\\* never block (I-12): they are recorded as hints beside the verdict, and a
soft signal that could stop a publication would be a hard check with a soft
label.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Optional, Protocol, Sequence

from src.editorial_core.arp import (
    ArpOutcome,
    KnowledgeStatus,
    AttemptCounterLedger,
    KnowledgeRef,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.destinations import Destination, destination_scope_key
from src.editorial_core.evidence_core import EvidenceCore
from src.editorial_core.executable_plan import ExecutablePlan, ForbiddenItem
from src.editorial_core.interpretation_boundary import InterpretationBoundary
from src.editorial_core.plan_check import (
    CheckClass,
    CheckMethod,
    CheckOutcome,
    CheckResult,
    FaultOwner,
    Finding,
)
from src.editorial_core.writer import Text
from src.knowledge.loader import LoadedCheck

#: The stage this module is (§2.3).
STAGE: Final[str] = "S-13"

#: Counters, and the three causes the topology registry declares for this source.
EDIT_COUNTER: Final[str] = "L_edit"
STRATEGY_COUNTER: Final[str] = "L_strategy"
BOUNDARY_COUNTER: Final[str] = "L_boundary"

EDIT_CAUSE: Final[str] = "phrasing_or_removable_fact"
STRATEGY_CAUSE: Final[str] = "structural_or_load_bearing_fault"
BOUNDARY_CAUSE: Final[str] = "interpretation_inadmissible_or_unlisted"

#: The two model calls §3 allows per text version, in order.
TRUTH_CALL: Final[str] = "truth"
EXECUTION_CALL: Final[str] = "execution"
CALLS_PER_TEXT_VERSION: Final[int] = 2

#: Which check each call answers (§3, Decider).
TRUTH_CHECKS: Final[tuple[str, ...]] = ("V-T01", "V-T02", "V-T03")
EXECUTION_CHECKS: Final[tuple[str, ...]] = ("V-T06", "V-T07", "V-T08")

#: The checks that route by branch rather than by finding alone (patch R2).
BRANCHED_CHECKS: Final[tuple[str, ...]] = ("V-T01", "V-T08")


class TextCheckError(RuntimeError):
    """S-13 was asked to verify something it cannot honestly verify."""


class TextResult(str, Enum):
    """What the verdict decided (§3, Outputs)."""

    ACCEPTED = "accepted"
    EDIT = "edit"
    REPLAN = "replan"
    SKIP = "skip"


def edit_scope_key(plan_ref: tuple[str, int]) -> str:
    """The key ``L_edit`` is counted under: the **approved plan** (§0.3).

    ``<plan_id>/v<version>`` — stable across every edit of one text, because an
    edit is a new text version of the same plan, and different for the new
    approved plan a ``L_strategy`` replan produces. Never the text's own
    ``(text_id, version)``: that increments per edit and would hand out a fresh
    allowance each time.
    """

    plan_id, version = plan_ref
    if not str(plan_id).strip() or int(version) < 1:
        raise TextCheckError(
            f"an edit is counted against the approved plan, and {plan_ref!r} "
            "names none; §0.3 counts L_edit per approved plan"
        )
    return f"{plan_id}/v{int(version)}"


@dataclass(frozen=True, slots=True)
class PriorPublication:
    """A prior ``E-16`` as V-T05 and V-S05 count it (§3, Inputs).

    A **narrow view** of the fingerprint rather than the entity, for the reason
    S-00's, S-07's, S-09's and S-11's projections give — and here for one more:
    ``E-16`` carries ``label_ref``, and its own access rule is that "label records
    are never routed to S-00…S-13". A stage handed the whole fingerprint would
    route labels into a stage forbidden to see them (I-10), so the label is not a
    field of this view and cannot arrive by accident.
    """

    fingerprint_id: str
    destination: Destination
    content_digest: str
    #: The near-duplicate profile V-T05 compares — "shingles and n-grams". Empty
    #: means the digest is all this record can answer with.
    shingles: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.fingerprint_id.strip() or not self.content_digest.strip():
            raise TextCheckError(
                "a prior publication is identified by its fingerprint and the "
                "digest of what was published"
            )


@dataclass(frozen=True, slots=True)
class TextFingerprint:
    """A prior ``E-16`` as **V-S05** compares against it (§3, Inputs).

    A second narrow view beside :class:`PriorPublication`, and a second one
    deliberately: V-T05 asks whether this text has already been published here
    and needs the digest and the near-duplicate profile for that; V-S05 asks how
    close the text is to the portfolio and compares four other things. V-S05's
    own record draws the line — "Near-exact republication is not this check's
    business — that is V-T05" — so handing V-T05 these fields would give a hard,
    blocking check inputs its record says are not its question.

    One field per dimension the record reports, because it requires them
    "**each reported separately** so that a shared path and a shared phrasing are
    not added together into one number nobody can act on". Each is optional: a
    fingerprint written before a field existed answers about the fields it has,
    and forcing one would make the comparison invent what it did not read.

    These are the **normalized** forms, which is what E-16's ``strategy`` row
    says it stores ("snapshot of E-13 fields, normalized for comparison"). How a
    real fingerprint is projected into them is the harness's, like every other
    projection in this layer, and which fingerprints count as recent is a
    question about the day the run happens on — a scheduling input the core is
    handed rather than one it reads (CE-1).
    """

    fingerprint_id: str
    destination: Destination
    #: The ordered part names of the published text: its reader path as executed.
    reader_path: tuple[str, ...] = ()
    #: Its first sentence, normalized.
    opening: Optional[str] = None
    #: Its last sentence, normalized.
    ending: Optional[str] = None
    #: Its word shingles, the n-gram profile — the same form :func:`shingles`
    #: produces, so the two sides of the comparison are built the same way.
    shingles: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.fingerprint_id.strip():
            raise TextCheckError(
                "a portfolio text is identified by the fingerprint it came from"
            )


class TextCheckTransport(Protocol):
    """The two model calls S-13 makes, as one narrow boundary."""

    def complete(self, *, instructions: str, request: str) -> str: ...


@dataclass(frozen=True, slots=True)
class TextVerdict:
    """One text version, checked (Step 1 §4, fix F-2 — sole producer S-13).

    Status and check results live **here and not on E-15**: F-2 moved them off the
    entity so that a text is what was written and a verdict is what was decided
    about it. ``boundary_ref`` is recorded because the verdict is only true against
    the boundary version it was checked at.
    """

    verdict_id: str
    text_ref: tuple[str, int]
    plan_ref: tuple[str, int]
    boundary_ref: tuple[str, int]
    unit_id: str
    destination: Destination
    checks: tuple[CheckResult, ...]
    result: TextResult
    route: Optional[str] = None
    counter: Optional[str] = None
    outcome: Optional[OutcomeRecord] = None
    hints: tuple[CheckResult, ...] = ()
    calls: int = 0

    def __post_init__(self) -> None:
        if not self.verdict_id.strip() or not self.unit_id.strip():
            raise TextCheckError("a verdict is identified, and names its unit")
        if not self.checks:
            raise TextCheckError(
                f"{self.verdict_id} records no check; a verdict is what the checks "
                "decided, and one over none decided nothing"
            )
        accepted = self.result is TextResult.ACCEPTED
        failed = [item for item in self.checks if item.result is not CheckOutcome.PASS]
        if accepted and failed:
            raise TextCheckError(
                f"{self.verdict_id} is accepted with "
                + ", ".join(item.check_id for item in failed)
                + " unresolved; §3 lets only an accepted text reach S-14, and a "
                "text accepted over a failing hard check is the gate not holding"
            )
        if accepted and (self.route or self.counter or self.outcome):
            raise TextCheckError(
                f"{self.verdict_id} is accepted and also routed somewhere; an "
                "accepted text is where the checks ended"
            )
        if not accepted and not failed:
            raise TextCheckError(
                f"{self.verdict_id} is {self.result.value} with every check "
                "passing; a text is only sent back by a finding"
            )
        if any(item.check_class is CheckClass.SOFT for item in self.checks):
            raise TextCheckError(
                f"{self.verdict_id} records a soft check among the checks that "
                "decided it; V-S* never block (I-12) and belong in `hints`"
            )
        if any(item.check_class is not CheckClass.SOFT for item in self.hints):
            raise TextCheckError(
                f"{self.verdict_id} records a hard check as a hint; a hard check "
                "that found something routes"
            )

    @property
    def accepted(self) -> bool:
        """May this text reach S-14? §3: "Only accepted texts reach S-14"."""

        return self.result is TextResult.ACCEPTED

    def as_entity(self) -> dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "text_ref": list(self.text_ref),
            "plan_ref": list(self.plan_ref),
            "boundary_ref": list(self.boundary_ref),
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "result": self.result.value,
            "route": self.route,
            "counter": self.counter,
            "checks": [
                {
                    "check_id": item.check_id,
                    "result": item.result.value,
                    "route": item.route,
                    "fault_owner": None
                    if item.fault_owner is None
                    else item.fault_owner.value,
                    "branch": item.branch,
                    "criterion": item.criterion,
                }
                for item in self.checks
            ],
            "hints": [item.check_id for item in self.hints],
            "calls": self.calls,
        }


def verdict_id(text_ref: tuple[str, int]) -> str:
    """One verdict per text version (§2.5)."""

    return f"tv-{text_ref[0]}-v{int(text_ref[1])}"


# ===========================================================================
# The code half (§3, Decider: code)
# ===========================================================================

#: A figure as V-T01's code part recognises one: digits, optionally grouped or
#: decimal, optionally with a unit or a percent sign attached.
_FIGURE = re.compile(r"\d[\d,.]*\s*(?:%|percent|million|billion|bn|m|k)?", re.I)

#: A URL as V-T04 recognises one.
_URL = re.compile(r"https?://[^\s<>\")\]]+")

#: How many shingles two texts may share before V-T05 calls it a near-duplicate.
#: Not a threshold this module chose: the record says "the same claims in the
#: same order with the wording moved about", which is what a high overlap is.
NEAR_DUPLICATE_OVERLAP: Final[float] = 0.8


def shingles(text: str, *, width: int = 5) -> frozenset[str]:
    """The text's word shingles, as V-T05's near-duplicate profile (§3).

    Lower-cased and whitespace-normalised, because a republication with the
    casing changed is the same republication.
    """

    words = re.findall(r"[a-z0-9']+", text.lower())
    if len(words) < width:
        return frozenset([" ".join(words)]) if words else frozenset()
    return frozenset(
        " ".join(words[index : index + width]) for index in range(len(words) - width + 1)
    )


# V-S05 has **no** similarity threshold, and this is where one would have gone.
# Its own record states `threshold: none`, I-12 keeps a soft signal from becoming
# one without an owner decision, and OPEN-25 leaves the portfolio soft-pressure
# weights open as an implementation question nobody has answered. So any number
# here — including a small one chosen to look harmless — would be this layer
# deciding that some measured resemblance is too slight to tell anyone about.
# V-S05 reports what it measured. :data:`NEAR_DUPLICATE_OVERLAP` stays what it
# is: V-T05's hard threshold, which blocks, and which is a different question.


def normalized_sentence(value: str) -> str:
    """One sentence as both sides of a V-S05 comparison spell it.

    The same normalization :func:`shingles` applies, for the same reason: an
    opening repeated with the casing or the spacing changed is the same opening,
    and a comparison that missed it would report no resemblance where a reader
    sees one.
    """

    return " ".join(re.findall(r"[a-z0-9']+", value.lower()))


def text_opening(text: Text) -> Optional[str]:
    """The text's first sentence, normalized, or ``None`` when it has none."""

    return _edge_sentence(text, first=True)


def text_ending(text: Text) -> Optional[str]:
    """The text's last sentence, normalized, or ``None`` when it has none."""

    return _edge_sentence(text, first=False)


def text_reader_path(text: Text) -> tuple[str, ...]:
    """The text's reader path as it executes it: its part names, in order.

    The names are the plan's — the Writer returns one part per plan segment,
    named exactly as the plan names it — so two texts that walk the reader
    through the same shape share this tuple.
    """

    return tuple(normalized_sentence(item.name) for item in text.segments)


def _edge_sentence(text: Text, *, first: bool) -> Optional[str]:
    sentences = [
        part for part in re.split(r"(?<=[.!?])\s+", text.body.strip()) if part.strip()
    ]
    if not sentences:
        return None
    return normalized_sentence(sentences[0 if first else -1]) or None


def _v_s05(
    check: LoadedCheck,
    text: Text,
    portfolio: Sequence[TextFingerprint],
) -> CheckResult:
    """V-S05: how close this text is to the portfolio, recorded and never acted on.

    The soft half of map §10 — "memory presses, it does not forbid". Built as
    ``plan_check._v_p05`` is built, for the same reasons and with the same
    guarantees: the result is always a pass carrying hints, :class:`CheckResult`
    refuses to build a soft check that could be anything else, and
    :class:`TextVerdict` refuses a soft check among the checks that decided it.
    So this cannot become a threshold by somebody deciding to read it as one.

    The four dimensions are reported **separately**, which the record requires:
    a shared path and a shared phrasing are different facts about different
    decisions, and one number over both is a number nobody can act on. Near-exact
    republication is not asked about here — that is V-T05, which is hard and does
    block.

    **No threshold anywhere.** The record says ``threshold: none``, and the
    n-gram dimension therefore reports whatever overlap it measured rather than
    only the overlaps some number calls large enough. Deciding that a measured
    resemblance is too small to record would be exactly the soft-signal-turned-
    threshold I-12 forbids without an owner decision, and OPEN-25 leaves that
    decision open.

    An empty portfolio is answered rather than skipped. The hint then says the
    comparison was made and found nothing, which is the difference between a
    check that ran against nothing and a check nobody ran — the distinction every
    soft input in this layer turns on.
    """

    here = [item for item in portfolio if item.destination is text.destination]
    opening = text_opening(text)
    ending = text_ending(text)
    path = text_reader_path(text)
    profile = shingles(text.body)
    hints: list[Finding] = []
    for entry in here:
        if entry.reader_path and entry.reader_path == path:
            hints.append(
                _resembles(entry, text, "the reader path", str(len(path)) + " parts")
            )
        if entry.opening is not None and opening is not None and (
            entry.opening == opening
        ):
            hints.append(_resembles(entry, text, "the opening", entry.opening))
        if entry.ending is not None and ending is not None and (
            entry.ending == ending
        ):
            hints.append(_resembles(entry, text, "the ending", entry.ending))
        shared = profile & entry.shingles
        if shared:
            # Any shared n-gram is an observation; how much sharing matters is
            # not this layer's to say (`threshold: none`, I-12, OPEN-25). Zero
            # shared n-grams is the same state as an opening that does not match:
            # nothing found, so nothing to report about this dimension.
            overlap = _overlap(profile, entry.shingles)
            hints.append(
                _resembles(
                    entry,
                    text,
                    "n-gram overlap",
                    f"{len(shared)} shared of {len(profile)}, {overlap:.2f} of "
                    "the smaller profile",
                )
            )
    if not hints:
        hints.append(
            Finding(
                detail=(
                    f"no recent publication on {text.destination.value} shares "
                    "this text's reader path, opening, ending or n-grams; the "
                    f"comparison was made over {len(here)} prior publication(s) "
                    "and found nothing"
                ),
                refs=(text.text_id,),
            )
        )
    return _result(
        check, method=CheckMethod.CODE, outcome=CheckOutcome.PASS, findings=tuple(hints)
    )


def _resembles(
    entry: TextFingerprint, text: Text, dimension: str, detail: str
) -> Finding:
    """One dimension, named, and never added to another."""

    return Finding(
        detail=(
            f"{entry.fingerprint_id} on {text.destination.value} shares "
            f"{dimension} with this text ({detail}); a hint, and never a reason "
            "to block, edit or replan anything"
        ),
        refs=(entry.fingerprint_id,),
    )


def _overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """What share of the smaller profile the two texts have in common."""

    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _figures(text: str) -> set[str]:
    return {
        match.group(0).strip().rstrip(".,").lower()
        for match in _FIGURE.finditer(text)
        if any(character.isdigit() for character in match.group(0))
    }


def check_links_resolve(text: Text, core: EvidenceCore) -> tuple[Finding, ...]:
    """V-T04 (code): every link and named source is one the core holds.

    "with the URL the core has" — so a link the core does not hold is a finding
    whether it works or not. I-03: the text may carry no source the core did not
    supply.
    """

    held = {
        str(source.locator.value).strip()
        for source in core.sources
        if source.locator is not None and source.locator.value
    }
    findings: list[Finding] = []
    for url in sorted(set(_URL.findall(text.body)) | set(text.links)):
        if url.strip() not in held:
            findings.append(
                Finding(
                    detail=(
                        f"the text carries {url!r}, which the Evidence Core does "
                        "not hold; a link the core did not supply is a source the "
                        "text invented (I-03)"
                    ),
                    refs=(url,),
                )
            )
    return tuple(findings)


def check_figures_quoted(text: Text, core: EvidenceCore) -> tuple[Finding, ...]:
    """V-T01, code part: every figure in the text is in the core, as the core has it.

    The model half judges whether a figure is *used* as the core supports it; this
    half answers the cheaper question first — whether the number appears in the
    core at all. A figure the core never states cannot be quoted correctly from it.
    """

    supplied = " ".join(
        [observation.excerpt for observation in core.observations]
        + [claim.statement for claim in core.evidence_claims]
    )
    known = _figures(supplied)
    findings: list[Finding] = []
    for figure in sorted(_figures(text.body)):
        if figure not in known and figure.rstrip("%") not in {
            item.rstrip("%") for item in known
        }:
            findings.append(
                Finding(
                    detail=(
                        f"the text states {figure!r} and the Evidence Core states "
                        "no such figure; a number the core does not hold is not a "
                        "number this text may assert"
                    ),
                    refs=(figure,),
                )
            )
    return tuple(findings)


def check_not_republished(
    text: Text, priors: Sequence[PriorPublication]
) -> tuple[Finding, ...]:
    """V-T05 (code): not a near-exact republication on this destination.

    Compared only against priors on **this** destination, as the record says.
    An empty prior set is the honest first-run answer: the check ran and found
    nothing to compare against, which is a pass and not an absence of a check.
    """

    here = [item for item in priors if item.destination is text.destination]
    if not here:
        return ()

    digest = text.content_digest
    for prior in here:
        if prior.content_digest == digest:
            return (
                Finding(
                    detail=(
                        f"the text's digest matches {prior.fingerprint_id}, already "
                        f"published on {text.destination.value}; a digest match is "
                        "a duplicate outright"
                    ),
                    refs=(prior.fingerprint_id,),
                ),
            )

    profile = shingles(text.body)
    if not profile:
        return ()
    for prior in here:
        if not prior.shingles:
            continue
        overlap = len(profile & prior.shingles) / len(profile)
        if overlap >= NEAR_DUPLICATE_OVERLAP:
            return (
                Finding(
                    detail=(
                        f"the text shares {overlap:.0%} of its shingles with "
                        f"{prior.fingerprint_id} on {text.destination.value}: the "
                        "same claims in the same order with the wording moved about"
                    ),
                    refs=(prior.fingerprint_id,),
                ),
            )
    return ()


def check_forbidden_phrases(
    text: Text, forbidden: Sequence[ForbiddenItem]
) -> tuple[Finding, ...]:
    """V-T06, code half: none of the phrases the Client Contract forbids.

    Phrases only. A construction type is not a string — the record's own criterion
    sends it to the model, "however it is worded" — so the execution call answers
    that half and this one does not guess at it.
    """

    findings: list[Finding] = []
    for item in forbidden:
        if item.kind.value != "phrase":
            continue
        if item.matches(text.body):
            findings.append(
                Finding(
                    detail=(
                        f"the text contains {item.value!r}, which "
                        f"{item.rule_ref} forbids"
                    ),
                    refs=(item.value,),
                    rule_ref=item.rule_ref,
                    tier=item.tier,
                )
            )
    return tuple(findings)


# ===========================================================================
# The model half: two calls per text version, and nothing else (§3, Calls)
# ===========================================================================

TRUTH_INSTRUCTIONS: Final[str] = """\
You judge one text against the evidence and the boundary it was written from.
Answer only the questions asked, against the criteria given, and nothing else.

V-T01 (truth): is every figure, name, date and link used as the Evidence Core
has it, and is no claim asserted more strongly than its evidence allows?
For each failure say whether the plan could still be executed without the
offending material:
  * `removable` — the thesis, the promise and every move still stand without it;
  * `load_bearing` — removing it leaves the thesis, a promise or a move
    unsupported, which means the plan required material the core does not hold.
When the evidence for the branch is thin, answer `load_bearing`: a decision error
must not be charged to the prose.

V-T02 (admissibility): does the text assert any reading the boundary recorded as
inadmissible, OR any reading the boundary never admitted at all? The recorded
inadmissible list is a detection aid and not the limit of the question.

V-T03 (chain): does thesis -> interpretation -> evidence claim -> observation
resolve at every link, with the text standing on that chain rather than beside it?

Return JSON only:
{"v_t01": {"holds": true, "findings": [{"detail": "...", "branch":
"removable|load_bearing"}]}, "v_t02": {"holds": true, "findings": [{"detail":
"...", "interpretation_ref": "..."}]}, "v_t03": {"holds": true, "findings":
[{"detail": "..."}]}}
"""

EXECUTION_INSTRUCTIONS: Final[str] = """\
You judge one text against the plan it was written from. Answer only what is
asked, against the criteria given.

V-T06 (constructions): does the text execute any construction type the contract
forbids, however it is worded? Phrases are matched by code and are not your
question.

V-T07 (execution): are the opening, the reader path and the concession of the
approved plan present in the text, doing what the plan said they would do?

V-T08 (ending): does the ending return to the image or fact the opening used and
leave it meaning something it did not mean at the start? An ending that restates
the opening, or restates the article, is a recap and fails. When it fails, say
which layer owns it:
  * `execution` — the approved ending_intention is a valid reframe and the text
    executed it as a recap;
  * `strategy` — the approved ending_intention, executed faithfully, would itself
    recap the opening.

Return JSON only:
{"v_t06": {"holds": true, "findings": [{"detail": "..."}]}, "v_t07": {"holds":
true, "findings": [{"detail": "..."}]}, "v_t08": {"holds": true, "findings":
[{"detail": "...", "branch": "execution|strategy"}]}}
"""

#: How a branch name maps to the layer that owns the fault (patch R2).
_OWNER_BY_BRANCH: Final[Mapping[str, FaultOwner]] = {
    "removable": FaultOwner.WRITER,
    "load_bearing": FaultOwner.PLAN,
    "execution": FaultOwner.WRITER,
    "strategy": FaultOwner.PLAN,
}

#: The branch each check defaults to when the answer does not name one. §3:
#: "default to the plan branch when uncertain".
_DEFAULT_BRANCH: Final[Mapping[str, str]] = {
    "V-T01": "load_bearing",
    "V-T08": "strategy",
}

#: The criterion each branch was decided against, recorded with the decision.
_CRITERION: Final[Mapping[str, str]] = {
    "removable": "the thesis, the promise and every move stand without it",
    "load_bearing": "removing it leaves a thesis, promise or move unsupported",
    "execution": "the approved ending_intention is a valid reframe, executed as a recap",
    "strategy": "the approved ending_intention would itself recap the opening",
}


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    """One call's answers, per check ID."""

    holds: Mapping[str, bool]
    findings: Mapping[str, tuple[dict[str, Any], ...]]

    def failed(self, check_id: str) -> bool:
        return not self.holds.get(check_id, True)


def _parse(raw: str, expected: Sequence[str]) -> Optional[ModelAnswer]:
    """Read one call's answer, or ``None`` when it cannot be read.

    ``None`` is not a pass. The caller turns it into ``NOT_ANSWERED`` and the
    publication is skipped: a check nobody ran is not a check that passed, and
    §3 lets only an accepted text reach S-14.
    """

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    holds: dict[str, bool] = {}
    findings: dict[str, tuple[dict[str, Any], ...]] = {}
    for check_id in expected:
        entry = payload.get(check_id.lower().replace("-", "_"))
        if not isinstance(entry, dict) or not isinstance(entry.get("holds"), bool):
            return None
        holds[check_id] = entry["holds"]
        raw_findings = entry.get("findings") or []
        if not isinstance(raw_findings, list):
            return None
        rows = tuple(item for item in raw_findings if isinstance(item, dict))
        if not entry["holds"] and not rows:
            return None
        findings[check_id] = rows
    return ModelAnswer(holds=holds, findings=findings)


def _ask(
    transport: TextCheckTransport, *, instructions: str, request: str, expected: Sequence[str]
) -> Optional[ModelAnswer]:
    try:
        raw = transport.complete(instructions=instructions, request=request)
    except Exception:  # noqa: BLE001 — a provider failure is a state, not a crash
        return None
    return _parse(raw, expected)


# ===========================================================================
# Routing: one route per verdict, and the replan class outranks the edit class
# ===========================================================================

#: Which cause each check's failure routes by, and on which counter. V-T01 and
#: V-T08 are absent because their route is decided by the branch, not the check.
_ROUTE_BY_CHECK: Final[Mapping[str, tuple[str, str]]] = {
    "V-T02": (BOUNDARY_CAUSE, BOUNDARY_COUNTER),
    "V-T03": (STRATEGY_CAUSE, STRATEGY_COUNTER),
    "V-T04": (EDIT_CAUSE, EDIT_COUNTER),
    "V-T06": (EDIT_CAUSE, EDIT_COUNTER),
    "V-T07": (STRATEGY_CAUSE, STRATEGY_COUNTER),
}

#: The state each route records.
_STATE_BY_COUNTER: Final[Mapping[str, StateCode]] = {
    EDIT_COUNTER: StateCode.TEXT_REQUIRES_EDIT,
    STRATEGY_COUNTER: StateCode.STRUCTURAL_TEXT_FAILURE,
    BOUNDARY_COUNTER: StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
}

#: Rank of each counter when a text carries findings of more than one class.
#: §3: "A text with both an edit-class and a replan-class finding follows the
#: replan route: a decision error outranks phrasing." The boundary route outranks
#: both — a text asserting an inadmissible reading is not repaired by a new
#: strategy over the same boundary.
_PRECEDENCE: Final[Mapping[str, int]] = {
    BOUNDARY_COUNTER: 0,
    STRATEGY_COUNTER: 1,
    EDIT_COUNTER: 2,
}


def _scope_key_for(counter: str, text: Text) -> str:
    """The key each counter is counted under — three scopes, three shapes (§0.3).

    This is the function #304's defect was an instance of getting wrong. Nothing
    below the stage boundary checks it: the ledger keys on
    ``(counter_id, scope_key)`` and validates only that the key is a non-empty
    string, so a key of the wrong shape is spent silently.
    """

    if counter == EDIT_COUNTER:
        return edit_scope_key(text.plan_ref)
    if counter == STRATEGY_COUNTER:
        return destination_scope_key(text.unit_id, text.destination)
    if counter == BOUNDARY_COUNTER:
        return text.unit_id
    raise TextCheckError(
        f"{STAGE} was asked for the scope of {counter!r}, which it does not spend"
    )


def _branched(check_id: str, row: Mapping[str, Any]) -> tuple[FaultOwner, str, str]:
    """The owner, the branch and the criterion for a branched check (patch R2)."""

    named = str(row.get("branch") or "").strip().lower()
    if named not in _OWNER_BY_BRANCH:
        named = _DEFAULT_BRANCH[check_id]
    return _OWNER_BY_BRANCH[named], named, _CRITERION[named]


def _result(
    check: LoadedCheck,
    *,
    method: CheckMethod,
    outcome: CheckOutcome,
    findings: tuple[Finding, ...],
    route: Optional[str] = None,
    owner: Optional[FaultOwner] = None,
    branch: Optional[str] = None,
    criterion: Optional[str] = None,
) -> CheckResult:
    record = check.check
    if record.check_class is None or record.rule_status is None:
        raise TextCheckError(
            f"{check.identity} states no class or no rule status; a CheckResult "
            "records both at the time of the run, and a check whose own record "
            "does not say what it is cannot be applied"
        )
    return CheckResult(
        check_id=check.identity,
        check_class=CheckClass(record.check_class),
        rule_status=KnowledgeStatus(record.rule_status),
        method=method,
        result=outcome,
        findings=findings,
        route=route,
        fault_owner=owner,
        branch=branch,
        criterion=criterion,
    )


@dataclass(frozen=True, slots=True)
class TextDecision:
    """What S-13 decided, with the verdict it wrote."""

    verdict: TextVerdict

    @property
    def accepted(self) -> bool:
        return self.verdict.accepted


def check_text(
    *,
    text: Text,
    plan: ExecutablePlan,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    forbidden: Sequence[ForbiddenItem],
    checks: Mapping[str, LoadedCheck],
    counters: AttemptCounterLedger,
    transport: TextCheckTransport,
    priors: Sequence[PriorPublication] = (),
    portfolio: Sequence[TextFingerprint] = (),
    soft_hints: Sequence[CheckResult] = (),
) -> TextDecision:
    """Verify one text version and route its failure to the layer that decided it.

    Two model calls and no more (§3, Calls: 2 per text version), made only once
    the code checks have run: a text a deterministic check already refused is not
    worth asking a model about, and §0.4 asks the cheap question first.

    It rewrites nothing. A failure becomes a route with its counter spent at the
    right scope, or — for V-T05 — a terminal skip of the publication with no
    counter at all, because that finding is not about this text but about what is
    already on the surface.
    """

    _precondition(text=text, plan=plan, boundary=boundary)

    # V-S05 before anything else can return. It is `code` and costs no model
    # call, it blocks nothing, and it is evaluated **unconditionally** so that
    # every verdict this stage writes carries it — including the ones that stop
    # at V-T05 or at an unreadable answer. A soft check evaluated only on the
    # paths that happen to reach the end is a soft check whose absence means two
    # different things.
    hints = (
        *soft_hints,
        _v_s05(checks[SOFT_CHECKS[0]], text, portfolio),
    )

    results: list[CheckResult] = []
    routed: list[tuple[str, str, CheckResult]] = []  # (counter, cause, result)

    def record(
        check_id: str,
        findings: tuple[Finding, ...],
        *,
        method: CheckMethod,
        row: Optional[Mapping[str, Any]] = None,
    ) -> None:
        check = checks[check_id]
        if not findings:
            results.append(
                _result(check, method=method, outcome=CheckOutcome.PASS, findings=())
            )
            return
        if check_id in BRANCHED_CHECKS:
            owner, branch, criterion = _branched(check_id, row or {})
            counter = (
                EDIT_COUNTER if owner is FaultOwner.WRITER else STRATEGY_COUNTER
            )
            cause = EDIT_CAUSE if counter == EDIT_COUNTER else STRATEGY_CAUSE
            item = _result(
                check,
                method=method,
                outcome=CheckOutcome.FAIL,
                findings=findings,
                route=cause,
                owner=owner,
                branch=branch,
                criterion=criterion,
            )
        else:
            cause, counter = _ROUTE_BY_CHECK[check_id]
            item = _result(
                check,
                method=method,
                outcome=CheckOutcome.FAIL,
                findings=findings,
                route=cause,
            )
        results.append(item)
        routed.append((counter, cause, item))

    # -- V-T05 first: terminal, no counter, and it makes the calls pointless ----
    republication = check_not_republished(text, priors)
    if republication:
        results.append(
            _result(
                checks["V-T05"],
                method=CheckMethod.CODE,
                outcome=CheckOutcome.FAIL,
                findings=republication,
            )
        )
        return TextDecision(
            verdict=_verdict(
                text,
                boundary,
                tuple(results),
                TextResult.SKIP,
                outcome=OutcomeRecord(
                    outcome=ArpOutcome.SKIP,
                    state_code=StateCode.NEAR_EXACT_REPUBLICATION,
                    scope=OutcomeScope.PUBLICATION,
                    scope_key=f"{text.text_id}/v{text.version}",
                    reason=(
                        "the text is a near-exact republication on this "
                        "destination; terminal by V-T05's own route table, and "
                        "S-14's idempotency authority says the same from the "
                        "other side"
                    ),
                ),
                hints=hints,
            )
        )
    results.append(
        _result(checks["V-T05"], method=CheckMethod.CODE, outcome=CheckOutcome.PASS, findings=())
    )

    # -- the rest of the code half ---------------------------------------------
    record("V-T04", check_links_resolve(text, core), method=CheckMethod.CODE)
    phrases = check_forbidden_phrases(text, forbidden)
    figures = check_figures_quoted(text, core)

    # -- the two calls ---------------------------------------------------------
    request = _request(text, plan, boundary, core)
    truth = _ask(
        transport,
        instructions=TRUTH_INSTRUCTIONS,
        request=request,
        expected=TRUTH_CHECKS,
    )
    execution = _ask(
        transport,
        instructions=EXECUTION_INSTRUCTIONS,
        request=request,
        expected=EXECUTION_CHECKS,
    )
    calls = CALLS_PER_TEXT_VERSION

    if truth is None or execution is None:
        unread = [
            check_id
            for check_id, answer in (("truth", truth), ("execution", execution))
            if answer is None
        ]
        for check_id in TRUTH_CHECKS if truth is None else ():
            results.append(
                _result(
                    checks[check_id],
                    method=CheckMethod.MODEL_EXPLICIT_CRITERION,
                    outcome=CheckOutcome.NOT_ANSWERED,
                    findings=(
                        Finding(
                            detail=(
                                f"the {unread[0]} call produced no answer this stage "
                                "may read; a check nobody ran is not a check that "
                                "passed"
                            ),
                            refs=(text.text_id,),
                        ),
                    ),
                )
            )
        for check_id in EXECUTION_CHECKS if execution is None else ():
            results.append(
                _result(
                    checks[check_id],
                    method=CheckMethod.MODEL_EXPLICIT_CRITERION,
                    outcome=CheckOutcome.NOT_ANSWERED,
                    findings=(
                        Finding(
                            detail=(
                                "the execution call produced no answer this stage "
                                "may read; a check nobody ran is not a check that "
                                "passed"
                            ),
                            refs=(text.text_id,),
                        ),
                    ),
                )
            )
        return TextDecision(
            verdict=_verdict(
                text,
                boundary,
                tuple(results),
                TextResult.SKIP,
                outcome=OutcomeRecord(
                    outcome=ArpOutcome.SKIP,
                    state_code=StateCode.TEXT_CHECK_UNAVAILABLE,
                    scope=OutcomeScope.PUBLICATION,
                    scope_key=f"{text.text_id}/v{text.version}",
                    reason=(
                        "a hard text check produced no answer, so this text is not "
                        "a checked text and may not reach S-14"
                    ),
                ),
                hints=hints,
                calls=calls,
            )
        )

    # -- V-T01: the code part and the model part are one check -----------------
    truth_rows = truth.findings.get("V-T01", ())
    v_t01_findings = figures + tuple(
        Finding(detail=str(row.get("detail") or "a figure is not used as the core has it"))
        for row in truth_rows
    )
    record(
        "V-T01",
        v_t01_findings,
        method=CheckMethod.CODE_AND_MODEL,
        row=truth_rows[0] if truth_rows else {},
    )

    record(
        "V-T02",
        tuple(
            Finding(
                detail=str(row.get("detail") or "the text asserts a reading the boundary does not admit"),
                refs=tuple(
                    item for item in (row.get("interpretation_ref"),) if isinstance(item, str)
                ),
            )
            for row in truth.findings.get("V-T02", ())
        ),
        method=CheckMethod.MODEL_EXPLICIT_CRITERION,
    )
    record(
        "V-T03",
        tuple(
            Finding(detail=str(row.get("detail") or "the chain does not resolve"))
            for row in truth.findings.get("V-T03", ())
        ),
        method=CheckMethod.CODE_AND_MODEL,
    )

    constructions = tuple(
        Finding(detail=str(row.get("detail") or "the text executes a forbidden construction"))
        for row in execution.findings.get("V-T06", ())
    )
    record("V-T06", phrases + constructions, method=CheckMethod.CODE_AND_MODEL)
    record(
        "V-T07",
        tuple(
            Finding(detail=str(row.get("detail") or "the plan is not executed in the text"))
            for row in execution.findings.get("V-T07", ())
        ),
        method=CheckMethod.MODEL_EXPLICIT_CRITERION,
    )
    rows_08 = execution.findings.get("V-T08", ())
    record(
        "V-T08",
        tuple(
            Finding(detail=str(row.get("detail") or "the ending recaps rather than reframes"))
            for row in rows_08
        ),
        method=CheckMethod.MODEL_EXPLICIT_CRITERION,
        row=rows_08[0] if rows_08 else {},
    )

    if not routed:
        return TextDecision(
            verdict=_verdict(
                text, boundary, tuple(results), TextResult.ACCEPTED,
                hints=hints, calls=calls,
            )
        )

    # -- one route per verdict, by precedence ----------------------------------
    counter, cause, _ = min(routed, key=lambda row: _PRECEDENCE[row[0]])
    outcome = counters.route(
        source=STAGE,
        cause=cause,
        scope_key=_scope_key_for(counter, text),
        state_code=_STATE_BY_COUNTER[counter],
        reason=(
            f"{text.text_id} v{text.version} failed "
            + ", ".join(
                item.check_id for item in results if item.result is CheckOutcome.FAIL
            )
            + f"; routed by {cause}"
        ),
    )
    decided = (
        TextResult.EDIT
        if counter == EDIT_COUNTER and outcome.outcome is ArpOutcome.REPLAN
        else TextResult.REPLAN
        if outcome.outcome is ArpOutcome.REPLAN
        else TextResult.SKIP
    )
    return TextDecision(
        verdict=_verdict(
            text, boundary, tuple(results), decided,
            route=cause, counter=counter, outcome=outcome,
            hints=hints, calls=calls,
        )
    )


def _verdict(
    text: Text,
    boundary: InterpretationBoundary,
    results: tuple[CheckResult, ...],
    decided: TextResult,
    *,
    route: Optional[str] = None,
    counter: Optional[str] = None,
    outcome: Optional[OutcomeRecord] = None,
    hints: tuple[CheckResult, ...] = (),
    calls: int = 0,
) -> TextVerdict:
    return TextVerdict(
        verdict_id=verdict_id(text.text_ref),
        text_ref=text.text_ref,
        plan_ref=text.plan_ref,
        boundary_ref=(boundary.boundary_id, boundary.version),
        unit_id=text.unit_id,
        destination=text.destination,
        checks=results,
        result=decided,
        route=route,
        counter=counter,
        outcome=outcome,
        hints=hints,
        calls=calls,
    )


def _precondition(
    *, text: Text, plan: ExecutablePlan, boundary: InterpretationBoundary
) -> None:
    """§3's Pre: the text exists with ``plan_holds = true``.

    The first half of that Pre needs no check here, and deliberately has none:
    :class:`~src.editorial_core.writer.Text` refuses to exist with
    ``plan_holds = false`` at all, so a refused plan produces no E-15 for this
    stage to receive. A guard here could never fire, and one that cannot fire
    reads as protection where there is none. What is checked is the half the type
    cannot: that the text and the plan in front of this stage are the same pair.
    """

    if text.plan_ref != (plan.plan_id, plan.version):
        raise TextCheckError(
            f"{text.text_id} was written from {text.plan_ref!r} and {plan.plan_id} "
            f"v{plan.version} reached {STAGE}; a text is checked against the plan it "
            "executes"
        )
    if text.unit_id != plan.unit_id or text.destination is not plan.destination:
        raise TextCheckError(
            f"{text.text_id} and {plan.plan_id} do not name one unit and one "
            "destination"
        )


def _request(
    text: Text, plan: ExecutablePlan, boundary: InterpretationBoundary, core: EvidenceCore
) -> str:
    """What the two calls are shown. No sibling text, no label, no raw research."""

    return json.dumps(
        {
            "text": {"body": text.body, "title": text.title, "dek": text.dek},
            "plan": {
                "thesis_opening": plan.first_line_mechanics,
                "segments": [item.as_entity() for item in plan.segments],
                "citations": list(plan.citations),
            },
            "boundary": {
                "boundary_ref": [boundary.boundary_id, boundary.version],
                "admissible": [
                    member.interpretation_id
                    for member in boundary.members
                    if member.admissible
                ],
                "inadmissible": [
                    member.interpretation_id
                    for member in boundary.members
                    if not member.admissible
                ],
            },
            "core": {
                "observations": [item.excerpt for item in core.observations],
                "claims": [item.statement for item in core.usable_claims],
                "sources": [
                    str(item.locator.value) for item in core.sources if item.locator
                ],
            },
        },
        ensure_ascii=False,
    )


#: The soft check records S-13 applies. One, and it is loaded exactly as S-11
#: loads V-P05 among its own five (``plan_check.PLAN_CHECKS``): a stage that is
#: not handed its soft check's record cannot apply it, and until this existed
#: every canonical TextVerdict carried no hint at all.
SOFT_CHECKS: Final[tuple[str, ...]] = ("V-S05",)

#: The eight hard check records S-13 applies (§3, Knowledge / config).
REQUIRED_CHECKS: Final[tuple[str, ...]] = (
    "V-T01",
    "V-T02",
    "V-T03",
    "V-T04",
    "V-T05",
    "V-T06",
    "V-T07",
    "V-T08",
)


def text_check_records(knowledge: Any) -> Mapping[str, LoadedCheck]:
    """The eight V-T records, by ID, read from the register at run time.

    Read rather than written down here for the reason S-11's equivalent gives: a
    CheckResult records the rule status and class **at the time of the run**, so a
    stage carrying its own copy would keep reporting ``candidate`` after a keeper
    approved the rule.

    A missing record is a refusal. A text accepted without V-T02 having been
    applied is not a checked text, and continuing with seven checks because the
    eighth file was absent is the fail-open the register exists to prevent.
    """

    applied = (*REQUIRED_CHECKS, *SOFT_CHECKS)
    loaded = {check.identity: check for check in knowledge.checks}
    missing = sorted(set(applied) - set(loaded))
    if missing:
        raise TextCheckError(
            "the register holds no check record for "
            + ", ".join(missing)
            + f"; {STAGE} applies V-T01…V-T08 and {', '.join(SOFT_CHECKS)} and "
            "cannot accept a text against fewer"
        )
    return {check_id: loaded[check_id] for check_id in applied}


# ===========================================================================
# F-4: the boundary moved, and the siblings were accepted under the old one
# ===========================================================================

#: The one check a sibling re-check asks about. Not the whole truth call's set:
#: §5.4 asks for "a targeted re-run of the S-13 **truth** call", and what a new
#: boundary version can change is admissibility.
SIBLING_RECHECK_CHECKS: Final[tuple[str, ...]] = ("V-T02",)

#: One call per affected sibling (§5.4), not S-13's usual two. The execution call
#: is not re-run because nothing about the plan's execution changed — the boundary
#: did.
CALLS_PER_SIBLING_RECHECK: Final[int] = 1

SIBLING_RECHECK_INSTRUCTIONS: Final[str] = """\
A text was accepted against an earlier version of the interpretation boundary, and
the boundary has since changed. Re-answer one question against the NEW boundary
only.

V-T02 (admissibility): does the text assert any reading the new boundary records as
inadmissible, OR any reading it never admitted at all? The recorded inadmissible
list is a detection aid and not the limit of the question. A reading that was
admissible under the old version and is not under the new one is a failure now.

Return JSON only:
{"v_t02": {"holds": true, "findings": [{"detail": "...", "interpretation_ref":
"..."}]}}
"""


def affected_siblings(
    verdicts: Sequence[TextVerdict], boundary: InterpretationBoundary
) -> tuple[TextVerdict, ...]:
    """The accepted verdicts a boundary commit put in question (§5.4, F-4).

    Accepted, and checked against an **older** version of this boundary. A verdict
    already at the current version needs nothing: it was judged against what is
    now true. A verdict against a *different* boundary is not this unit's business
    and is left alone.
    """

    current = (boundary.boundary_id, boundary.version)
    return tuple(
        verdict
        for verdict in verdicts
        if verdict.accepted
        and verdict.boundary_ref[0] == current[0]
        and verdict.boundary_ref[1] < current[1]
    )


def recheck_siblings_after_boundary_commit(
    *,
    boundary: InterpretationBoundary,
    accepted: Sequence[tuple[Text, TextVerdict]],
    core: EvidenceCore,
    plans: Mapping[Destination, ExecutablePlan],
    checks: Mapping[str, LoadedCheck],
    counters: AttemptCounterLedger,
    transport: TextCheckTransport,
) -> tuple[TextDecision, ...]:
    """Re-check every sibling text an S-04 re-entry left judged against an old boundary.

    §5.4, defect **F-4**, the half this stage owns: "Texts already accepted for
    sibling destinations get a targeted re-run of the S-13 **truth** call (1 call
    each) before S-14."

    Why it is needed at all: one destination can discover an inadmissible reading,
    route to S-04, and leave the boundary at a new version — while the sibling that
    was accepted ten minutes earlier is still accepted **against the version that
    no longer holds**. Nothing else would catch it. S-11's code checks re-run on
    the plans, and the S-12 precondition compares versions, but a text that already
    passed S-13 has no reason to be looked at again unless this does it.

    One call per sibling, and only V-T02. Re-running the execution call would pay
    for an answer that cannot have changed: the plan's execution is what it was, and
    what moved is which readings the boundary admits.

    On failure the route is taken through the ledger rather than chosen here, and
    that is the point: V-T02's declared route is S-04 on ``L_boundary``, which the
    re-entry that produced this new version has already spent. So the ledger returns
    that route's own ``on_exhaustion`` — the destination is skipped — without this
    function deciding anything. A second boundary test would be re-testing the
    boundary that was just committed.

    Returns one decision per affected sibling, in the order given. A sibling whose
    re-check passes is returned re-accepted **at the new version**, so that the
    verdict a later reader finds says which boundary it was judged against.
    """

    decisions: list[TextDecision] = []
    for text, previous in accepted:
        if previous not in affected_siblings([previous], boundary):
            continue
        plan = plans.get(text.destination)
        if plan is None or plan.plan_ref != text.plan_ref:
            raise TextCheckError(
                f"{text.text_id} is being re-checked without the approved plan it "
                "executes; a re-check that cannot see the plan cannot say what the "
                "text was allowed to assert"
            )

        answer = _ask(
            transport,
            instructions=SIBLING_RECHECK_INSTRUCTIONS,
            request=_request(text, plan, boundary, core),
            expected=SIBLING_RECHECK_CHECKS,
        )
        if answer is None:
            results = (
                _result(
                    checks["V-T02"],
                    method=CheckMethod.MODEL_EXPLICIT_CRITERION,
                    outcome=CheckOutcome.NOT_ANSWERED,
                    findings=(
                        Finding(
                            detail=(
                                "the sibling truth re-check produced no answer, so "
                                "this text is not known to hold against the new "
                                "boundary version and may not reach S-14"
                            ),
                            refs=(text.text_id,),
                        ),
                    ),
                ),
            )
            decisions.append(
                TextDecision(
                    verdict=_verdict(
                        text,
                        boundary,
                        results,
                        TextResult.SKIP,
                        outcome=OutcomeRecord(
                            outcome=ArpOutcome.SKIP,
                            state_code=StateCode.TEXT_CHECK_UNAVAILABLE,
                            scope=OutcomeScope.PUBLICATION,
                            scope_key=f"{text.text_id}/v{text.version}",
                            reason=(
                                "the targeted truth re-check after a boundary "
                                "commit produced no answer"
                            ),
                        ),
                        calls=CALLS_PER_SIBLING_RECHECK,
                    )
                )
            )
            continue

        rows = answer.findings.get("V-T02", ())
        if not rows:
            decisions.append(
                TextDecision(
                    verdict=_verdict(
                        text,
                        boundary,
                        (
                            _result(
                                checks["V-T02"],
                                method=CheckMethod.MODEL_EXPLICIT_CRITERION,
                                outcome=CheckOutcome.PASS,
                                findings=(),
                            ),
                        ),
                        TextResult.ACCEPTED,
                        calls=CALLS_PER_SIBLING_RECHECK,
                    )
                )
            )
            continue

        findings = tuple(
            Finding(
                detail=str(
                    row.get("detail")
                    or "the text asserts a reading the new boundary does not admit"
                ),
                refs=tuple(
                    item
                    for item in (row.get("interpretation_ref"),)
                    if isinstance(item, str)
                ),
            )
            for row in rows
        )
        failed = _result(
            checks["V-T02"],
            method=CheckMethod.MODEL_EXPLICIT_CRITERION,
            outcome=CheckOutcome.FAIL,
            findings=findings,
            route=BOUNDARY_CAUSE,
        )
        outcome = counters.route(
            source=STAGE,
            cause=BOUNDARY_CAUSE,
            scope_key=text.unit_id,
            state_code=StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
            reason=(
                f"{text.text_id} v{text.version} was accepted against "
                f"{previous.boundary_ref[0]} v{previous.boundary_ref[1]} and asserts "
                f"a reading v{boundary.version} does not admit"
            ),
        )
        decisions.append(
            TextDecision(
                verdict=_verdict(
                    text,
                    boundary,
                    (failed,),
                    TextResult.REPLAN
                    if outcome.outcome is ArpOutcome.REPLAN
                    else TextResult.SKIP,
                    route=BOUNDARY_CAUSE,
                    counter=BOUNDARY_COUNTER,
                    outcome=outcome,
                    calls=CALLS_PER_SIBLING_RECHECK,
                )
            )
        )
    return tuple(decisions)
