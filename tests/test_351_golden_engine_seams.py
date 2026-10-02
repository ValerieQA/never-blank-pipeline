"""Issue #351: the two seams of the executable Golden Engine, and the wall.

Seam 1 is "the only genuinely new translation layer" of the slice: the research
signal intake writes, as the typed input S-00 reads. Seam 11 is the
``expected_destinations`` authority #305 made a required argument of
``run_barrier`` and nothing supplied.

Both are tested against the real seam rather than a helper beside it: the fit
rules come from the real client contract through ``golden_engine_fit_rules``,
and the refusals are asserted as what ``select_signal`` records, not as what
the adapter thinks it would record.

The third group is the slice's import-direction criterion: "neither
``src/publishing/`` nor ``src/editorial/`` acquires an import of
``src/editorial_core/``". It carries its own planted violation, so a walker
that stopped finding modules cannot pass it by finding nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Optional

import pytest

import scripts.research.enrich as enrich
from src.editorial_core.arp import (
    ArpOutcome,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.destinations import (
    Destination,
    DestinationDecision,
    DestinationDecisionSet,
    DestinationMode,
    Eligibility,
    ExclusionRule,
    ModeRule,
    decision_id,
)
from src.editorial_core.signal_selection import (
    SignalFit,
    SignalSelection,
    select_signal,
)
from src.run.expected_destinations import (
    ExpectedDestinationsError,
    expected_destinations,
)
from src.run.signal_adapter import (
    DOMAIN_FIELD,
    RISK_FIELD,
    SIGNAL_ID_FIELD,
    SOURCE_URL_FIELD,
    SignalAdapterError,
    golden_engine_fit_rules,
    selection_candidate,
)
from src.strategy.business_config import EditorialRole
from src.strategy.contract_fit import RISK_RULE_ID, TOPIC_RULE_ID

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The real client contract, read through the production binding. One admitted
#: value of each vocabulary is taken from it rather than repeated here: a
#: literal would keep passing after the owner changed the client's domains.
FIT_RULES = golden_engine_fit_rules(
    directory=_REPO_ROOT / "clients" / "never_blank"
)
ADMITTED_DOMAIN = FIT_RULES.rules[0].admits[0]
ADMITTED_RISK = FIT_RULES.rules[1].admits[0]

SIGNAL = "sig-351-seam"
SOURCE = "https://example.test/item"

UNIT = "unit-351-seam"

#: Sentinel for "the record does not carry this key at all", which is a
#: different state from carrying it empty and is what #365 actually writes.
_ABSENT = object()


# ===========================================================================
# Fixtures
# ===========================================================================


def _record(**overrides: Any) -> dict[str, Any]:
    """One intake record, classified, as Stage 4 writes it (#365)."""

    record: dict[str, Any] = {
        SIGNAL_ID_FIELD: SIGNAL,
        "HEADLINE": "A vendor states the payment settles in minutes.",
        SOURCE_URL_FIELD: SOURCE,
        DOMAIN_FIELD: ADMITTED_DOMAIN,
        enrich.DOMAIN_OUTCOME_FIELD: enrich.ADMITTED,
        RISK_FIELD: ADMITTED_RISK,
        enrich.RISK_OUTCOME_FIELD: enrich.ADMITTED,
    }
    record.update(overrides)
    return {key: value for key, value in record.items() if value is not _ABSENT}


def _role() -> EditorialRole:
    """A role that restricts no source class, so S-00 makes no model call.

    ``eligibility_criteria`` empty is a declared state, not a missing one, and
    it keeps these tests on the seam: what is being asserted is which fit rule
    decided, and a judgment call in the middle would only add a second way for
    the same assertion to fail.
    """

    return EditorialRole(
        role_id="role-351",
        intent="Test the seam and nothing else.",
        structure=("one section",),
        forbidden=("hype",),
    )


class _RefusingTransport:
    """Anything that asks this for text has left the seam under test."""

    def complete(self, *, instructions: str, request: str) -> str:
        raise AssertionError(
            "S-00 made a source-eligibility call; the role under test declares "
            "no criteria, so the seam has grown a model call nobody asked for"
        )


def _select(record: dict[str, Any]) -> SignalSelection:
    return select_signal(
        selection_candidate(record),
        fit_rules=FIT_RULES,
        role=_role(),
        transport=_RefusingTransport(),
    )


# ===========================================================================
# Seam 1 · the record reaches S-00 as the record
# ===========================================================================


def test_the_adapter_binds_the_fields_the_intake_record_spells():
    """#363 left the binding to this seam; #365 writes those two names."""

    assert DOMAIN_FIELD == enrich.DOMAIN_FIELD
    assert RISK_FIELD == enrich.RISK_FIELD
    assert {rule.field for rule in FIT_RULES.rules} == {DOMAIN_FIELD, RISK_FIELD}


def test_a_classified_record_is_selected_by_the_real_contract():
    """The acceptance the whole seam exists for: a real record gets through."""

    selection = _select(_record())

    assert selection.selected is True
    assert selection.fit is SignalFit.FITS
    assert selection.outcome is None
    assert [result.rule_id for result in selection.fit_rules] == [
        TOPIC_RULE_ID,
        RISK_RULE_ID,
    ]
    assert all(result.passed for result in selection.fit_rules)


def test_an_unclassified_record_is_skipped_by_the_rule_that_refused_it():
    """S-00's refusal, not the adapter's: the trace names the rule."""

    selection = _select(_record(**{DOMAIN_FIELD: _ABSENT}))

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS
    assert selection.outcome is not None
    assert selection.outcome.outcome is ArpOutcome.SKIP
    assert selection.outcome.scope_key == SIGNAL
    refused = selection.fit_rules[0]
    assert refused.rule_id == TOPIC_RULE_ID
    assert refused.passed is False
    assert refused.stated == ()


def test_the_adapter_does_not_raise_on_an_unclassified_record():
    """Raising would take the refusal away from the rule that owns it.

    The 134 historical signals carry neither field, and a seam that refused
    them here would produce a stack trace where the run needs a recorded SKIP
    naming ``FIT-NB-TOPIC-01``.
    """

    candidate = selection_candidate(
        {SIGNAL_ID_FIELD: SIGNAL, "HEADLINE": "An unclassified historical signal."}
    )

    assert candidate.signal_id == SIGNAL
    assert DOMAIN_FIELD not in candidate.signal
    assert RISK_FIELD not in candidate.signal


def test_cannot_answer_is_carried_across_and_is_not_read_as_a_value():
    """A failed classification stays apart from an out-of-vocabulary one (#365).

    Both are the same ``SKIP`` at S-00 — the fit rule cannot tell them apart
    and does not need to — and the record must keep the difference, because a
    classifier that failed and a signal deliberately outside the vocabulary are
    two different facts about the run.
    """

    failed = _record(**{
        DOMAIN_FIELD: _ABSENT,
        enrich.DOMAIN_OUTCOME_FIELD: enrich.CANNOT_ANSWER,
    })
    outside = _record(**{
        DOMAIN_FIELD: _ABSENT,
        enrich.DOMAIN_OUTCOME_FIELD: enrich.OUTSIDE_ADMITTED,
    })

    for record, outcome_value in (
        (failed, enrich.CANNOT_ANSWER),
        (outside, enrich.OUTSIDE_ADMITTED),
    ):
        candidate = selection_candidate(record)
        assert candidate.signal[enrich.DOMAIN_OUTCOME_FIELD] == outcome_value
        assert DOMAIN_FIELD not in candidate.signal
        selection = select_signal(
            candidate,
            fit_rules=FIT_RULES,
            role=_role(),
            transport=_RefusingTransport(),
        )
        assert selection.fit is SignalFit.OUTSIDE_TOPICS


def test_the_record_reaches_the_stage_unchanged():
    """Seam 1 passes the record through: no key added, none dropped, none moved."""

    record = _record()
    candidate = selection_candidate(record)

    assert dict(candidate.signal) == record


def test_the_adapter_cannot_synthesise_a_classification():
    """Structural, not a promise: what S-00 reads is read-only.

    The slice's own rule is that this seam must not "populate, infer, default,
    append or synthesise" either field. A mapping nothing can write into is how
    that rule survives the next caller who is sure they have a better default.
    """

    candidate = selection_candidate(_record(**{DOMAIN_FIELD: _ABSENT}))

    with pytest.raises(TypeError):
        candidate.signal[DOMAIN_FIELD] = ADMITTED_DOMAIN  # type: ignore[index]


def test_a_later_edit_of_the_caller_s_record_does_not_reach_the_candidate():
    """What S-00 read is what S-00 read, whatever the caller does next."""

    record = _record()
    candidate = selection_candidate(record)
    record[DOMAIN_FIELD] = "something else entirely"

    assert candidate.signal[DOMAIN_FIELD] == ADMITTED_DOMAIN


@pytest.mark.parametrize("identity", [_ABSENT, "", "   ", 17, None])
def test_a_record_that_cannot_be_identified_is_refused(identity: Any):
    """The signal ID is the scope key every outcome of S-00 is recorded against."""

    with pytest.raises(SignalAdapterError) as raised:
        selection_candidate(_record(**{SIGNAL_ID_FIELD: identity}))

    assert SIGNAL_ID_FIELD in str(raised.value)


def test_the_two_facts_portfolio_pressure_compares_are_lifted():
    candidate = selection_candidate(_record())

    assert candidate.topic_key == ADMITTED_DOMAIN
    assert candidate.source_locators == (SOURCE,)


@pytest.mark.parametrize(
    "stated",
    [_ABSENT, "", "  ", ["a", "b"], [], 3, None],
    ids=["absent", "empty", "blank", "several", "none-listed", "number", "null"],
)
def test_a_record_that_states_no_single_topic_states_no_topic_key(stated: Any):
    """An exact match on a key nothing in the portfolio holds is not a match.

    A composite key made of two domains would look like a key that could match
    and would match nothing, which is worse evidence than the absence.
    """

    assert selection_candidate(_record(**{DOMAIN_FIELD: stated})).topic_key is None


def test_a_record_with_no_locator_claims_no_resemblance():
    candidate = selection_candidate(_record(**{SOURCE_URL_FIELD: _ABSENT}))

    assert candidate.source_locators == ()


# ===========================================================================
# Seam 11 · who is in the barrier round
# ===========================================================================


def _eligible(
    destination: Destination,
    *,
    mode: DestinationMode = DestinationMode.PUBLISH,
) -> DestinationDecision:
    return DestinationDecision(
        destination_decision_id=decision_id(UNIT, destination),
        unit_id=UNIT,
        destination=destination,
        eligibility=Eligibility.ELIGIBLE,
        rule_ref=f"CD-{destination.value}",
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        mode=mode,
        mode_rule=(
            ModeRule.PUBLISHES
            if mode is DestinationMode.PUBLISH
            else ModeRule.OUTSIDE_ROLLOUT_SCOPE
        ),
    )


def _excluded(destination: Destination) -> DestinationDecision:
    return DestinationDecision(
        destination_decision_id=decision_id(UNIT, destination),
        unit_id=UNIT,
        destination=destination,
        eligibility=Eligibility.EXCLUDED,
        rule_ref=f"CD-{destination.value}",
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        exclusion_rule=ExclusionRule.CONTRACT_DISABLED,
        outcome=OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.DESTINATION_OUTSIDE_CONTRACT,
            scope=OutcomeScope.DESTINATION,
            scope_key=f"{UNIT}/{destination.value}",
            reason="the contract does not enable this destination",
        ),
    )


def _decisions(
    excluded: Optional[tuple[Destination, ...]] = None,
) -> DestinationDecisionSet:
    """The six, as S-07 leaves them for a unit the contract enables everywhere.

    Wix and LinkedIn publish; the other four generate only, because today's
    rollout scope does not include them (AD-02 §3).
    """

    turned_off = frozenset(excluded or ())
    return DestinationDecisionSet(
        unit_id=UNIT,
        decisions=tuple(
            _excluded(destination)
            if destination in turned_off
            else _eligible(
                destination,
                mode=(
                    DestinationMode.PUBLISH
                    if destination in (Destination.WIX, Destination.LINKEDIN)
                    else DestinationMode.GENERATE_ONLY
                ),
            )
            for destination in Destination
        ),
    )


def test_the_round_is_every_eligible_destination_of_the_unit():
    assert expected_destinations(_decisions()) == frozenset(Destination)


def test_a_generate_only_destination_is_in_the_round():
    """Principle B: it gets a plan, so B1 compares it against the anchor.

    A barrier that dropped it would compare a subset and still report that
    I-07 held for the unit.
    """

    round_one = expected_destinations(_decisions())

    assert Destination.TELEGRAM in round_one


def test_an_excluded_destination_is_not_in_the_round():
    decisions = _decisions(excluded=(Destination.TELEGRAM,))

    assert expected_destinations(decisions) == frozenset(Destination) - {
        Destination.TELEGRAM
    }


def test_a_later_round_is_the_shorter_set():
    """§0.2: "if B1 can never pass … B1 re-evaluates without it"."""

    decisions = _decisions()

    assert expected_destinations(
        decisions, skipped=(Destination.INSTAGRAM, Destination.THREADS)
    ) == frozenset(Destination) - {Destination.INSTAGRAM, Destination.THREADS}


def test_a_skip_of_a_destination_the_unit_never_had_is_refused():
    """The one thing a caller uses this to be sure of is that the two agree."""

    decisions = _decisions(excluded=(Destination.TELEGRAM,))

    with pytest.raises(ExpectedDestinationsError) as raised:
        expected_destinations(decisions, skipped=(Destination.TELEGRAM,))

    assert Destination.TELEGRAM.value in str(raised.value)


def test_a_round_with_nobody_left_is_refused_here_rather_than_at_the_barrier():
    """A unit with nowhere left to go is skipped as a unit before B1."""

    decisions = _decisions()

    with pytest.raises(ExpectedDestinationsError) as raised:
        expected_destinations(decisions, skipped=tuple(Destination))

    assert UNIT in str(raised.value)


# ===========================================================================
# The wall: the legacy path never learns about the canonical core
# ===========================================================================

_WALLED = ("publishing", "editorial")

_PLANTED = "from src.editorial_core.topology import CANONICAL_TOPOLOGY\n"


def _core_imports(source: str, where: str) -> list[str]:
    """Every import of the editorial core this module makes.

    All four shapes, absolute and relative: a wall that only knew
    ``from src.editorial_core import x`` would be walked around by
    ``from ..editorial_core import x`` without anybody meaning to.
    """

    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=where)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if _is_core(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and _is_core(node.module):
                found.append(("." * node.level) + node.module)
            elif node.level:
                found += [
                    ("." * node.level) + alias.name
                    for alias in node.names
                    if _is_core(alias.name)
                ]
    return found


def _is_core(module: str) -> bool:
    """Does this dotted name reach ``src/editorial_core/``?

    The trailing dot matters: ``editorial_core_helpers`` is a module nobody has
    written, and a prefix match without it would refuse one on sight.
    """

    return any(
        module == name or module.startswith(name + ".")
        for name in ("src.editorial_core", "editorial_core")
    )


def test_the_import_direction_detector_sees_a_violation():
    """The walled test below cannot pass by finding nothing."""

    assert _core_imports(_PLANTED, "<planted>") == ["src.editorial_core.topology"]
    assert _core_imports("import src.editorial_core\n", "<planted>") == [
        "src.editorial_core"
    ]
    assert _core_imports(
        "from ..editorial_core.arp import ArpOutcome\n", "<planted>"
    ) == ["..editorial_core.arp"]
    assert _core_imports("from .. import editorial_core\n", "<planted>") == [
        "..editorial_core"
    ]
    assert _core_imports("from src.editorial import machine_tells\n", "<ok>") == []


@pytest.mark.parametrize("package", _WALLED)
def test_the_legacy_layer_does_not_import_the_editorial_core(package: str):
    """AD-05's allowed direction is one way: the core is never a dependency.

    The canonical engine wraps the existing pipeline, so ``src/run/`` and
    ``src/editorial_core/`` may reach into ``src/editorial/``. The reverse is
    what would make the legacy path depend on an engine it does not run, and
    would end the OFF path's independence.
    """

    modules = sorted((_REPO_ROOT / "src" / package).rglob("*.py"))
    assert modules, f"src/{package}/ holds no module; this test checked nothing"

    offenders = {
        str(path.relative_to(_REPO_ROOT)): imported
        for path in modules
        if (
            imported := _core_imports(
                path.read_text(encoding="utf-8"),
                str(path.relative_to(_REPO_ROOT)),
            )
        )
    }
    assert offenders == {}
