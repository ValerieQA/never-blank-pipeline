"""S-00 · Signal selection: fit, eligibility, pressure (Issue #298, slice SL-3).

The first stage of the canonical engine, and the narrowest. Step 2 §1 gives it
one authority: decide whether **this** signal is worth a run for this client.
It decides fit and relevance only, and it "must not decide an angle, a story or
a destination" — so nothing here reads the material, and nothing here produces
anything a later stage could mistake for an editorial decision.

What it does, in the order it does it
-------------------------------------
1. **Contract fit, by rule.** The contract's topics and risk level arrive as
   :class:`ContractFitRules` — a table the client owns, each row carrying its
   own ``rule_id``. Every row is evaluated and every result is recorded, so the
   trace can say which rules were read and not only which one refused. The
   first row that refuses decides the recorded ``fit``, and a signal that does
   not fit is a ``SKIP`` — never a hold (I-01).
2. **Portfolio pressure, by code.** What the portfolio already carries that
   this candidate resembles. Soft by contract: in assigned mode it never skips
   on its own, it is recorded. It is computed before the model call because it
   costs nothing and a skipped signal's resemblance is still worth knowing.
3. **Source eligibility, by model.** One call, the stage's only one, wrapping
   ``src/editorial/source_eligibility.py``. That module fails closed — a
   malformed verdict, a transport failure or an uncertain answer is never an
   eligible candidate — and this stage keeps that posture: a failed judgment
   is recorded as a ``SKIP``, not as a verdict and not as a reason to retry.

**Assigned mode only.** The run starts with one signal and S-00 accepts or
skips it, which is also how the current engine starts runs. Queue mode and the
deferred units that compete in it are U-2's, and U-2 is dormant while the split
cap is 1 (AD-03): :func:`select_from_queue` is the interface, fixed now so that
raising the cap needs no redesign, and it refuses to pretend it has a queue.

**Relevance is deliberately absent.** Step 2's Post column asks S-00 for
``selected = true`` with relevance recorded, and refinement R-1 (§7) then moved
the #58 relevance evaluation to the end of S-01, "because it needs the research
artifact". There is no research artifact at S-00, so this stage records no
relevance and no relevance basis; the fields of ``E-01.selection`` that hold
them belong to the stage that fills them.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-00),
§4 U-2 and §7 (R-1); ``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md``
§2, E-01 and SignalSelection; ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md``
§6.2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional, Protocol
from urllib.parse import urlsplit, urlunsplit

from src.editorial.source_eligibility import (
    SourceEligibilityError,
    SourceEligibilityTransport,
    judge_source_eligibility,
)
from src.editorial_core.arp import (
    ArpOutcome,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.strategy.business_config import EditorialRole

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-00"

#: AD-03: the number of units one signal may be split into. While it is 1 no
#: deferred unit is ever created, so no deferred unit can compete for a run and
#: U-2 has nothing to rank. Raising it is an owner decision, not a parameter a
#: caller passes in.
SPLIT_CAP: Final[int] = 1


class SignalSelectionError(RuntimeError):
    """S-00 was asked for a selection its contract cannot honestly make."""


# ===========================================================================
# The vocabularies (Step 1 §2, E-01)
# ===========================================================================


class CandidateKind(str, Enum):
    """What competed for this run (AD-03).

    ``DEFERRED_UNIT`` exists because the schema is fixed now and the behaviour
    is not: while the split cap is 1 only ``SIGNAL`` occurs, in production and
    everywhere else.
    """

    SIGNAL = "signal"
    DEFERRED_UNIT = "deferred_unit"


class SignalFit(str, Enum):
    """How the contract answered. Anything other than ``FITS`` is a ``SKIP``."""

    FITS = "fits"
    OUTSIDE_CONTRACT = "outside_contract"
    OUTSIDE_TOPICS = "outside_topics"
    OUTSIDE_RISK_LEVEL = "outside_risk_level"


#: What each refusal is recorded as in the durable ledger. Two state codes,
#: because the map §6.2 gives the risk level a row of its own ("High stakes
#: outside the contract's risk level") beside the row that covers contract and
#: topics. Step 2's ARP column groups all three as one terminal `SKIP` of the
#: signal, which both codes are; what the split buys is that a client reading
#: the skip rate can tell a topic it does not cover from a risk it will not
#: take, without the free text that the ledger does not carry (Step 3 §3.3).
_FIT_STATE_CODES: Mapping[SignalFit, StateCode] = {
    SignalFit.OUTSIDE_CONTRACT: StateCode.SIGNAL_OUTSIDE_CONTRACT,
    SignalFit.OUTSIDE_TOPICS: StateCode.SIGNAL_OUTSIDE_CONTRACT,
    SignalFit.OUTSIDE_RISK_LEVEL: StateCode.HIGH_STAKES_OUTSIDE_RISK_LEVEL,
}


class SimilarityKind(str, Enum):
    """How a candidate resembles something Portfolio Memory already holds.

    Only what a signal has before any research: the topic it is about and the
    sources it points at. Resemblance between *texts* is V-S05's question, and
    there is no text at S-00 to ask it of.

    Both are exact matches on normalized values. There is no score and no
    threshold: a soft signal acquires a threshold only with the owner's
    approval (I-12), and "similar enough" is exactly such a threshold.
    """

    SAME_TOPIC = "same_topic"
    SAME_SOURCE = "same_source"


# ===========================================================================
# Contract fit rules, as data
# ===========================================================================


@dataclass(frozen=True, slots=True)
class FitRule:
    """One rule of the Client Contract, carrying the ID the trace records.

    A rule reads one field of the signal and admits a listed set of values.
    That is the whole grammar, and it is deliberately smaller than a condition
    language: S-00 decides fit, and a rule that needed more than "is what the
    signal says in what the contract allows" would be deciding something else.
    """

    rule_id: str
    #: What a signal this rule turns away is recorded as. Never ``FITS``: a
    #: rule states what it refuses, and fitting is what is left over.
    fit: SignalFit
    #: The E-01 field the rule reads, spelled as the intake record spells it.
    field: str
    #: The values the contract admits, in the client's own spelling.
    admits: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise SignalSelectionError(
                "a fit rule is named by its rule ID, which is what a SKIP for "
                "it is recorded with"
            )
        if self.fit is SignalFit.FITS:
            raise SignalSelectionError(
                f"{self.rule_id} declares {SignalFit.FITS.value!r} as its "
                "verdict; a rule says what it refuses, and a signal fits when "
                "no rule refused it"
            )
        if not self.field.strip():
            raise SignalSelectionError(f"{self.rule_id} reads no field")
        if not self.admits:
            raise SignalSelectionError(
                f"{self.rule_id} admits nothing, so it refuses every signal; "
                "a contract that takes no topic at all is not a fit rule"
            )

    def check(self, signal: Mapping[str, Any]) -> "FitRuleResult":
        """Apply this rule to one signal.

        A signal that states nothing for the field does not pass. Silence is
        not admission: the contract listed what it takes, and a signal that
        does not say which of them it is has not been shown to be one.
        """

        stated = _stated_values(signal.get(self.field))
        admitted = {_normalized(value) for value in self.admits}
        return FitRuleResult(
            rule_id=self.rule_id,
            fit=self.fit,
            field=self.field,
            stated=stated,
            passed=bool(stated) and all(value in admitted for value in stated),
        )


@dataclass(frozen=True, slots=True)
class FitRuleResult:
    """One fit rule applied, as the trace records it (Step 2 §1, Trace)."""

    rule_id: str
    fit: SignalFit
    field: str
    #: What the signal stated for the field, normalized. Empty means it stated
    #: nothing at all.
    stated: tuple[str, ...]
    passed: bool

    def as_entity(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "field": self.field,
            "stated": list(self.stated),
            "passed": self.passed,
            "refuses_as": self.fit.value,
        }


@dataclass(frozen=True, slots=True)
class ContractFitRules:
    """The contract's topic and risk rules, as data rather than as branches.

    Required input (Step 2 §1): a run with no fit rules would select every
    signal it was handed and record that the contract agreed, which is the one
    answer S-00 must never be able to give by omission.
    """

    rules: tuple[FitRule, ...]

    def __post_init__(self) -> None:
        if not self.rules:
            raise SignalSelectionError(
                "the Client Contract's fit rules are a required input of S-00; "
                "an empty table admits every signal and records that as a fit"
            )
        identities = [rule.rule_id for rule in self.rules]
        duplicated = sorted({
            identity for identity in identities if identities.count(identity) > 1
        })
        if duplicated:
            raise SignalSelectionError(
                "fit rule ID(s) declared twice: "
                + ", ".join(duplicated)
                + "; a SKIP names the rule that decided it, and a name two "
                "rules answer to names neither"
            )

    def evaluate(self, signal: Mapping[str, Any]) -> tuple[FitRuleResult, ...]:
        """Every rule applied, in the contract's own order.

        All of them, not up to the first refusal: §1's Trace column asks for
        "fit rule results with rule IDs", and a reader who sees only the rule
        that refused cannot tell which of the others were even consulted.
        """

        return tuple(rule.check(signal) for rule in self.rules)


# ===========================================================================
# Portfolio pressure (tier 5, soft)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class PortfolioFingerprint:
    """A prior E-16 as S-00 compares against it.

    A narrow view of the fingerprint rather than the entity itself: the two
    facts below are the only ones a signal can be compared on before research,
    and a stage that took the whole of E-16 would be claiming to read fields it
    has nothing to match them against.
    """

    fingerprint_id: str
    topic_key: Optional[str] = None
    source_locators: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioPressure:
    """One resemblance S-00 found and recorded (Step 1 §2, SignalSelection)."""

    fingerprint_id: str
    kind: SimilarityKind

    def as_entity(self) -> dict[str, str]:
        return {
            "fingerprint_ref": self.fingerprint_id,
            "similarity_kind": self.kind.value,
        }


# ===========================================================================
# The candidate and the seams
# ===========================================================================


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    """One candidate as S-00 reads it.

    ``signal`` is the intake record itself, spelled as intake spells it: the
    contract's fit rules name its fields, and ``judge_source_eligibility``
    reads it directly. ``topic_key`` and ``source_locators`` are lifted out
    beside it because portfolio pressure compares exactly those two (U-2 rule
    4.2) and neither has one fixed spelling in the record.
    """

    signal_id: str
    signal: Mapping[str, Any]
    kind: CandidateKind = CandidateKind.SIGNAL
    topic_key: Optional[str] = None
    source_locators: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise SignalSelectionError(
                "a candidate is identified by its signal ID, which is the "
                "scope key every outcome of this stage is recorded against"
            )


class CallBudget(Protocol):
    """The run's spend limit, as S-00 uses it (Step 2 §0.4, refinement R-3).

    A protocol rather than an import, for the reason ``TracedStageExecution``
    in :mod:`src.editorial_core.arp` is one: ``ArpCallBudget`` lives with the
    run harness and already depends on this package's ARP records. The core
    states what it needs of a budget; the harness supplies it.

    ``None`` from :meth:`spend` means the call is paid for and may be made. An
    OutcomeRecord means it was refused before any transport was invoked, and is
    the ``SKIP`` of the work that needed it.
    """

    def spend(
        self, *, scope: OutcomeScope, scope_key: str
    ) -> Optional[OutcomeRecord]: ...


@dataclass(frozen=True, slots=True)
class EligibilityRecord:
    """The source-class verdict, as the trace records it.

    ``reason`` is free text and therefore workspace-only (Step 3 §3.3): the
    durable RunSummary carries the state code and its category instead.
    """

    role_id: str
    eligible: bool
    reason: str
    #: True when the judgment could not be made and fail-closed ineligibility
    #: stood in for a verdict. The distinction is the trace's: "the role's
    #: criteria turned this source away" and "nobody could tell" are different
    #: facts, and both are ``SKIP``.
    failed_closed: bool = False

    def as_entity(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "eligible": self.eligible,
            "reason": self.reason,
            "failed_closed": self.failed_closed,
        }


# ===========================================================================
# E-01.selection
# ===========================================================================


@dataclass(frozen=True, slots=True)
class SignalSelection:
    """``E-01.selection``: what S-00 made of one candidate (Step 1 §2, E-01)."""

    signal_id: str
    candidate_kind: CandidateKind
    fit: SignalFit
    fit_rules: tuple[FitRuleResult, ...]
    portfolio_pressure: tuple[PortfolioPressure, ...]
    selected: bool
    #: Absent when no judgment was asked for: the fit rules ended the selection
    #: before the call, or the role declares no source-class criteria.
    eligibility: Optional[EligibilityRecord] = None
    #: The ``SKIP``, when there is one. A selected signal has no outcome —
    #: nothing was left unresolved.
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if self.selected:
            if self.outcome is not None:
                raise SignalSelectionError(
                    f"{self.signal_id} is selected and carries a "
                    f"{self.outcome.outcome.value}; an outcome records a state "
                    "the stage could not resolve, and selecting the signal "
                    "resolved it"
                )
            if self.fit is not SignalFit.FITS:
                raise SignalSelectionError(
                    f"{self.signal_id} is selected with fit "
                    f"{self.fit.value!r}; anything other than "
                    f"{SignalFit.FITS.value!r} is a SKIP (Step 1 §2, E-01)"
                )
            return
        if self.outcome is None:
            raise SignalSelectionError(
                f"{self.signal_id} is not selected and records no outcome; "
                "every state the engine does not resolve is recorded with its "
                "reason, and a signal left without one is a run that waits"
            )
        if self.outcome.outcome is not ArpOutcome.SKIP:
            raise SignalSelectionError(
                f"{self.signal_id} is not selected and records a "
                f"{self.outcome.outcome.value}; S-00's outcomes are terminal "
                "(Step 2 §1, ARP)"
            )

    def as_entity(self) -> dict[str, Any]:
        """The entity body written to ``signal/selection.json`` (§2.2, §2.3)."""

        return {
            "entity_type": "E-01.selection",
            "entity_id": self.signal_id,
            "candidate_kind": self.candidate_kind.value,
            "fit": self.fit.value,
            "fit_rules": [result.as_entity() for result in self.fit_rules],
            "eligibility": (
                None if self.eligibility is None else self.eligibility.as_entity()
            ),
            "portfolio_pressure": [
                pressure.as_entity() for pressure in self.portfolio_pressure
            ],
            "selected": self.selected,
            "outcome": (
                None if self.outcome is None else self.outcome.model_dump(mode="json")
            ),
        }


# ===========================================================================
# The stage
# ===========================================================================


def select_signal(
    candidate: SelectionCandidate,
    *,
    fit_rules: ContractFitRules,
    role: EditorialRole,
    transport: SourceEligibilityTransport,
    portfolio: Sequence[PortfolioFingerprint] = (),
    budget: Optional[CallBudget] = None,
) -> SignalSelection:
    """Assigned mode: accept or skip the one signal the run started with.

    Returns a :class:`SignalSelection` either way. A refusal is a value, not an
    exception: I-01 makes a non-fit signal a recorded ``SKIP``, and a caller
    that had to catch an error to find that out would have nothing to write
    into the trace.

    ``budget`` is optional because only the eligibility judgment spends
    anything, and a run that hands one over gets the R-3 behaviour: the call
    that would exceed the ceiling is not made, and the signal is skipped with
    ``budget_exhausted``.
    """

    if candidate.kind is not CandidateKind.SIGNAL:
        raise SignalSelectionError(
            f"{candidate.signal_id} is a {candidate.kind.value}, and assigned "
            "mode evaluates the one given signal (U-2 rule 1). Deferred units "
            f"compete in queue mode, which is dormant at split cap {SPLIT_CAP}"
        )

    pressure = _portfolio_pressure(candidate, portfolio)
    results = fit_rules.evaluate(candidate.signal)
    refused = next((result for result in results if not result.passed), None)
    if refused is not None:
        stated = ", ".join(refused.stated) if refused.stated else "not stated"
        return _skipped(
            candidate,
            fit=refused.fit,
            fit_rules=results,
            pressure=pressure,
            eligibility=None,
            outcome=OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=_FIT_STATE_CODES[refused.fit],
                scope=OutcomeScope.SIGNAL,
                scope_key=candidate.signal_id,
                reason=(
                    f"fit rule {refused.rule_id} refused the signal: "
                    f"{refused.field} is {stated}"
                ),
            ),
        )

    if not role.eligibility_criteria:
        # The role imposes no source-class restriction, which is a declared
        # state and not a missing one. `judge_source_eligibility` refuses a
        # role that declares no criteria — rightly, since it would have nothing
        # to judge against — and turning that refusal into a SKIP would read
        # "this role restricts no source" as "no source passes".
        return _selected(candidate, results, pressure, eligibility=None)

    if budget is not None:
        refusal = budget.spend(
            scope=OutcomeScope.SIGNAL, scope_key=candidate.signal_id
        )
        if refusal is not None:
            return _skipped(
                candidate,
                fit=SignalFit.FITS,
                fit_rules=results,
                pressure=pressure,
                eligibility=None,
                outcome=refusal,
            )

    eligibility = _judge(candidate, role, transport)
    if not eligibility.eligible:
        return _skipped(
            candidate,
            fit=SignalFit.FITS,
            fit_rules=results,
            pressure=pressure,
            eligibility=eligibility,
            outcome=OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=StateCode.SOURCE_NOT_ELIGIBLE,
                scope=OutcomeScope.SIGNAL,
                scope_key=candidate.signal_id,
                reason=eligibility.reason,
            ),
        )
    return _selected(candidate, results, pressure, eligibility=eligibility)


def select_from_queue(
    candidates: Sequence[SelectionCandidate],
    *,
    split_cap: int = SPLIT_CAP,
) -> SignalSelection:
    """Queue mode (U-2): pick one candidate from signals and deferred units.

    Dormant, and says so. U-2 fixes the contract now — expiry as a hard
    boundary, fit re-checked against the current contract, ranking by
    relevance then portfolio pressure then age, no starvation boost — so that
    raising the split cap needs no redesign. What it does not do is let a
    caller execute it: at cap 1 no unit is ever deferred, so the queue this
    would rank has exactly the assigned signal in it, and ranking a list of one
    is :func:`select_signal` wearing a second name.

    Always raises :class:`SignalSelectionError` while ``split_cap`` is 1.
    """

    if split_cap <= SPLIT_CAP:
        raise SignalSelectionError(
            f"queue mode is dormant at split cap {split_cap}: no unit is ever "
            "deferred, so the queue holds only the assigned signal and U-2 has "
            f"nothing to rank ({len(candidates)} candidate(s) offered). "
            "Assigned mode is select_signal"
        )
    raise SignalSelectionError(
        f"split cap {split_cap} enables deferred units, and executing U-2's "
        "ranking is out of scope for this slice: deferred-unit execution "
        "arrives with the cap that needs it"
    )


# ===========================================================================
# Internals
# ===========================================================================


def _judge(
    candidate: SelectionCandidate,
    role: EditorialRole,
    transport: SourceEligibilityTransport,
) -> EligibilityRecord:
    """The stage's one model call, with the boundary's posture kept.

    ``source_eligibility`` never turns a failed judgment into a verdict, so
    neither does this: a transport failure, a malformed answer or a missing
    identity is recorded as ineligible and flagged as the failure it was. It is
    not retried — S-00 has no attempt counter (§1, Limits: "None (single
    pass)"), and a fail-closed judgment asked twice fails closed twice.
    """

    try:
        verdict = judge_source_eligibility(dict(candidate.signal), role, transport)
    except SourceEligibilityError as exc:
        return EligibilityRecord(
            role_id=role.role_id,
            eligible=False,
            # The boundary builds its messages from exception type names and
            # its own normalized reasons, never from provider prose, so this
            # carries no material the artifact should not hold.
            reason=f"the eligibility judgment failed closed: {exc}",
            failed_closed=True,
        )
    return EligibilityRecord(
        role_id=verdict.role_id,
        eligible=verdict.eligible,
        reason=verdict.reason,
    )


def _portfolio_pressure(
    candidate: SelectionCandidate,
    portfolio: Sequence[PortfolioFingerprint],
) -> tuple[PortfolioPressure, ...]:
    """What this candidate resembles, in the order the portfolio was given.

    Soft, and recorded whatever the selection decides: a signal skipped for
    contract fit that is also the fourth of its topic this month is two facts
    about the queue, and the second one does not stop being true because the
    first ended the run.
    """

    topic = _normalized(candidate.topic_key or "")
    sources = {_normalized_locator(locator) for locator in candidate.source_locators}
    sources.discard("")
    found: list[PortfolioPressure] = []
    for entry in portfolio:
        if topic and _normalized(entry.topic_key or "") == topic:
            found.append(
                PortfolioPressure(entry.fingerprint_id, SimilarityKind.SAME_TOPIC)
            )
        if sources and any(
            _normalized_locator(locator) in sources for locator in entry.source_locators
        ):
            found.append(
                PortfolioPressure(entry.fingerprint_id, SimilarityKind.SAME_SOURCE)
            )
    return tuple(found)


def _selected(
    candidate: SelectionCandidate,
    fit_rules: tuple[FitRuleResult, ...],
    pressure: tuple[PortfolioPressure, ...],
    *,
    eligibility: Optional[EligibilityRecord],
) -> SignalSelection:
    return SignalSelection(
        signal_id=candidate.signal_id,
        candidate_kind=candidate.kind,
        fit=SignalFit.FITS,
        fit_rules=fit_rules,
        portfolio_pressure=pressure,
        selected=True,
        eligibility=eligibility,
    )


def _skipped(
    candidate: SelectionCandidate,
    *,
    fit: SignalFit,
    fit_rules: tuple[FitRuleResult, ...],
    pressure: tuple[PortfolioPressure, ...],
    eligibility: Optional[EligibilityRecord],
    outcome: OutcomeRecord,
) -> SignalSelection:
    return SignalSelection(
        signal_id=candidate.signal_id,
        candidate_kind=candidate.kind,
        fit=fit,
        fit_rules=fit_rules,
        portfolio_pressure=pressure,
        selected=False,
        eligibility=eligibility,
        outcome=outcome,
    )


def _stated_values(raw: Any) -> tuple[str, ...]:
    """What a signal states for one field, normalized, once each.

    A field may hold one value or several — a signal about two topics states
    two — and a rule passes only when the contract admits every one of them.
    Anything that is not a string or a sequence of strings states nothing: the
    rule then refuses, which is the fail-closed direction. A sequence holding
    one member this cannot read states nothing either, rather than stating the
    members it can: dropping the unreadable one would let the rule pass on a
    field whose fit the signal never established in full.
    """

    if isinstance(raw, str):
        values: list[str] = [raw]
    elif isinstance(raw, Sequence) and all(isinstance(item, str) for item in raw):
        values = list(raw)
    else:
        return ()
    normalized = [_normalized(value) for value in values]
    return tuple(dict.fromkeys(value for value in normalized if value))


def _normalized(value: str) -> str:
    """One comparable spelling: whitespace collapsed, case folded."""

    return " ".join(value.split()).casefold()


def _normalized_locator(value: str) -> str:
    """One comparable spelling for a source locator, case kept where it counts.

    Whitespace is collapsed as everywhere else, but only what a URL declares
    case-insensitive is folded: the scheme and the host. A path and a query are
    the origin server's to spell, so ``/Case`` and ``/case`` are two sources
    until that server says otherwise, and a locator this cannot read as a URL
    is compared exactly as it was given.
    """

    collapsed = " ".join(value.split())
    try:
        parsed = urlsplit(collapsed)
    except ValueError:
        return collapsed
    if not parsed.scheme or not parsed.netloc:
        return collapsed
    userinfo, at, host = parsed.netloc.rpartition("@")
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            f"{userinfo}{at}{host.casefold()}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
