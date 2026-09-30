"""The client contracts S-08…S-11 require, and the client-rule registry behind them.

Issue #368, slice SL-6.47. Two more **required** stage inputs had no producer:
``StrategyContract`` was built only in ``tests/test_304_…`` — sixteen of those as
a bare ``StrategyContract()`` — and ``AdaptationContract`` was built nowhere in
``src/`` or ``scripts/`` at all. These tests run the whole chain for both —
**human-editable document → loader → typed runtime value → the stage that
declares it** — against the repository's real configuration.

The one distinction these tests exist to hold
---------------------------------------------
All three ``StrategyContract`` fields used to default to ``()``, so
``StrategyContract()`` constructed silently. The three empties are not equally
harmful: an empty ``positions`` fails closed, an empty ``preferences`` is inert,
and an empty ``prohibitions`` is **permissive and silent** — S-09 has no other
source of ``CONTRACT_PROHIBITION``, so nothing is ever excluded and the trace
shows nothing was consulted. Never Blank's three sets *are* empty by owner
decision; the defect was that the absence of configuration looked exactly like
the decision.

So every test below is written so that a bypass fails it:

* restoring any ``= ()`` default fails :func:`test_the_type_refuses_an_unspoken_contract`;
* restoring a producer fallback to ``()`` for any of the three makes the
  *missing* case pass, and fails :func:`test_a_missing_declaration_raises_and_names_itself`
  and :func:`test_configured_empty_and_absent_differ_at_the_producer_boundary`;
* a literal ending mode in ``src/`` fails :func:`test_the_ending_mode_is_the_records_and_not_a_literal`;
* a producer that composed a contract with no fixed slot when ``K-NB-01`` states
  none fails :func:`test_the_record_losing_its_clause_is_refused_rather_than_unfixed`
  and :func:`test_the_authorized_record_being_absent_is_refused_too`;
* a producer that counted the slots ``K-NB-01`` states rather than checking which
  slot it fixed accepts a renamed one and a second record's own, and fails
  :func:`test_the_authorized_record_fixing_another_slot_instead_is_refused` and
  :func:`test_another_records_own_fixed_slot_is_refused_rather_than_carried`;
* dropping the produced slot removes the V-P04 Finding and fails
  :func:`test_v_p04_enforces_the_fixed_slot_end_to_end`;
* reverting the registry wiring lets the run start and fails
  :func:`test_an_unreadable_client_rule_stops_the_run` and
  :func:`test_a_refused_register_stops_the_run_before_the_producers_read_it`;
* an import of ``src/publishing/hashtags.py`` in the engine or either producer
  fails :func:`test_no_engine_or_producer_depends_on_publishing`;
* sourcing the hashtag *policy* from the new producer fails
  :func:`test_the_hashtag_policy_still_comes_from_the_rules_363_left`.

What is deliberately not proven here
------------------------------------
**Nothing about whether S-00…S-13 compose.** That is #351's, and this slice only
removes one of its blockers. The V-P04 test drafts its plan with #305's fixture
contract — a path that is already known to work — and checks it against the
**production** ``AdaptationContract``, because the seam under test is the one
between the producer and S-11 and not S-10's own drafting.

**Nothing about the company-mention obligation.** It is deferred: no ``K-DST``
record states mention or tag capability for any destination, so its condition has
no authority the runtime can lawfully evaluate. There is no ``K-NB`` record for
it, and this file does not pretend one is coming.
"""

from __future__ import annotations

import ast
import dataclasses
import subprocess
from pathlib import Path

import pytest

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.candidate_strategies import StrategyContract
from src.editorial_core.destinations import Destination
from src.editorial_core.executable_plan import HashtagPolicy, PlanError
from src.editorial_core.plan_check import check_plan
from src.knowledge.client_rules import ClientRulesError, client_rules
from src.knowledge.destination_rules import destination_rules, rule_catalogue
from src.strategy.adaptation_contract import (
    FIXED_SLOTS_FIELD,
    HASHTAG_SECTION,
    AdaptationContractError,
    adaptation_contract,
    client_hashtags,
)
from src.strategy.client_contract import CONTRACT_FILE
from src.strategy.strategy_contract import (
    DECLARED_EMPTY,
    DECLARED_SECTIONS,
    PREFERENCES_SECTION,
    PROHIBITIONS_SECTION,
    StrategyContractError,
    strategy_contract,
)
from tests.test_305_executable_plan_and_check import (
    CHECKS,
    PASSING_CHECK,
    _contract,
    _core,
    _drafted,
    _ledger,
    _rules,
    _Transport,
    _two_readings,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTER = _REPO_ROOT / "knowledge"
NEVER_BLANK = _REPO_ROOT / "clients" / "never_blank"
CONTRACT = NEVER_BLANK / CONTRACT_FILE
CLIENT_RULES = NEVER_BLANK / "rules"

#: The record the owner authorized as the client authority for the ending mode,
#: and the slot it fixes. Named here because the *assertion* is about this pair;
#: the producer names neither, which is what makes editing the record change the
#: result.
ENDING_RECORD = "K-NB-01"
ENDING_SLOT = "ending_mode"
ENDING_VALUE = "kicker"

#: The static client-owned vocabulary, and the two tags that are deliberately
#: **not** in it: `#CompoundPresence` is conditional on the article naming it and
#: the industry tag is derived from the signal, so both are computations.
DECLARED_TAGS = ("#NeverBlank", "#CustomerTrust")
COMPUTED_TAG = "#CompoundPresence"

#: The two producers this slice adds, and the loader behind them.
PRODUCERS = (
    "src/strategy/strategy_contract.py",
    "src/strategy/adaptation_contract.py",
    "src/knowledge/client_rules.py",
)

#: The one of them that composes the slot, and so the only one the authorized
#: slot *name* belongs in — once, as the authorization itself.
ENDING_PRODUCER = "src/strategy/adaptation_contract.py"


def _produced(directory: Path = NEVER_BLANK, register: Path = REGISTER):
    """The production `AdaptationContract`, against a client directory on disk."""

    return adaptation_contract(
        directory=directory, register=register, root=_REPO_ROOT
    )


def _copied_client(tmp_path: Path) -> Path:
    """The real client directory, copied so a test may edit it."""

    target = tmp_path / "client"
    for path in sorted(NEVER_BLANK.rglob("*")):
        if not path.is_file():
            continue
        item = target / path.relative_to(NEVER_BLANK)
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(path.read_bytes())
    return target


def _edited(tmp_path: Path, relative: str, old: str, new: str) -> Path:
    """The real client directory with one exact substitution in one file."""

    directory = _copied_client(tmp_path)
    path = directory / relative
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} is not one place in {relative}"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return directory


def _with_section(tmp_path: Path, section: str, body: str) -> Path:
    """The real contract with one section's body replaced, whole.

    Replacing a body by line range rather than by string substitution, because a
    heading is also named in the prose of the section beside it — and a test that
    edited the wrong one of the two would be asserting something else.
    """

    directory = _copied_client(tmp_path)
    path = directory / CONTRACT_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"## {section}")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    replaced = [
        *lines[:start],
        f"## {section}",
        "",
        *body.splitlines(),
        "",
        *lines[end:],
    ]
    path.write_text("\n".join(replaced) + "\n", encoding="utf-8")
    return directory


def _renamed_section(tmp_path: Path, section: str) -> Path:
    """The real contract with one heading renamed: the declaration is now absent."""

    directory = _copied_client(tmp_path)
    path = directory / CONTRACT_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[lines.index(f"## {section}")] = f"## {section} (renamed by the test)"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory


def _copied_register(tmp_path: Path) -> Path:
    """The real register, copied so a test may break one record in it."""

    target = tmp_path / "knowledge"
    for path in sorted(REGISTER.rglob("*")):
        if not path.is_file():
            continue
        item = target / path.relative_to(REGISTER)
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(path.read_bytes())
    return target


def _code_outside_the_module_docstring(relative: str) -> str:
    """One module's text with its own docstring removed.

    The docstring is where a producer is allowed to *quote* a record's clause, as
    documentation. What must not carry a value is the code, so the check reads the
    code and leaves the prose alone.
    """

    text = (_REPO_ROOT / relative).read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(text))
    return text.replace(docstring, "") if docstring else text


def _imported(relative: str) -> set[str]:
    """Every module name this file imports, by either form."""

    text = (_REPO_ROOT / relative).read_text(encoding="utf-8")
    names: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def _git(*args: str) -> tuple[int, str]:
    done = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args], capture_output=True, text=True
    )
    return done.returncode, done.stdout.strip()


# ── 1 · declared empty is valid ────────────────────────────────────────────


def test_the_declared_empty_contract_is_valid_and_is_the_documents():
    """Acceptance 1: three empty tuples, and no error.

    The mutation this catches: a producer that treated an empty declaration as a
    configuration failure would refuse Never Blank's real contract.
    """

    contract = strategy_contract(directory=NEVER_BLANK)

    assert contract.positions == ()
    assert contract.prohibitions == ()
    assert contract.preferences == ()

    # Each of the three is a positive statement in the document, not an omission.
    text = CONTRACT.read_text(encoding="utf-8")
    for section in DECLARED_SECTIONS:
        assert f"## {section}" in text, section
    assert text.count(f"\n{DECLARED_EMPTY}\n") == len(DECLARED_SECTIONS)


def test_a_declared_prohibition_is_read_rather_than_assumed_absent(tmp_path):
    """The producer reads rows; it is not wired to return `()`.

    Without this, every assertion that Never Blank's sets are empty would also
    pass for a producer that returned `()` whatever the document said.
    """

    directory = _with_section(
        tmp_path,
        PROHIBITIONS_SECTION,
        "| rule_id | focal_subjects | reveals | statement |\n"
        "|---|---|---|---|\n"
        "| NB-NO-DELAY | — | delayed | This client does not hold the point back. |",
    )
    contract = strategy_contract(directory=directory)

    assert [rule.rule_id for rule in contract.prohibitions] == ["NB-NO-DELAY"]
    rule = contract.prohibitions[0]
    assert rule.tier is KnowledgeTier.APPROVED_CLIENT_RULE
    assert rule.focal_subjects == ()
    assert [kind.value for kind in rule.reveals] == ["delayed"]
    # And the real contract still declares none, so the row came from the edit.
    assert strategy_contract(directory=NEVER_BLANK).prohibitions == ()


# ── 2 · absent is not empty ────────────────────────────────────────────────


@pytest.mark.parametrize("section", DECLARED_SECTIONS)
def test_a_missing_declaration_raises_and_names_itself(tmp_path, section):
    """Acceptance 2, and the defect the slice exists to prevent.

    Removing one declaration must not produce a contract with that set empty.
    Restoring an `or ()` for any of the three makes this test pass silently,
    which is why the message is asserted to name the section a keeper must write.
    """

    with pytest.raises(StrategyContractError) as raised:
        strategy_contract(directory=_renamed_section(tmp_path, section))

    message = str(raised.value)
    assert section in message
    assert DECLARED_EMPTY in message


def test_a_missing_contract_raises_rather_than_an_empty_contract(tmp_path):
    with pytest.raises(StrategyContractError) as raised:
        strategy_contract(directory=tmp_path / "nowhere")

    assert "no contract" in str(raised.value)


def test_a_declaration_that_says_neither_none_nor_a_table_raises(tmp_path):
    """A section somebody emptied is not a section that declared nothing."""

    with pytest.raises(StrategyContractError) as raised:
        strategy_contract(directory=_with_section(tmp_path, PREFERENCES_SECTION, ""))

    message = str(raised.value)
    assert PREFERENCES_SECTION in message
    assert DECLARED_EMPTY in message


def test_a_declaration_cannot_say_none_and_list_rows_at_once(tmp_path):
    directory = _with_section(
        tmp_path,
        PROHIBITIONS_SECTION,
        "| rule_id | focal_subjects | reveals | statement |\n"
        "|---|---|---|---|\n"
        "| NB-BOTH | — | delayed | A table, and a `none` under it. |\n"
        f"\n{DECLARED_EMPTY}",
    )

    with pytest.raises(StrategyContractError) as raised:
        strategy_contract(directory=directory)

    assert "chooses between them" in str(raised.value)


# ── 3 · the type refuses an unspoken contract ──────────────────────────────


def test_the_type_refuses_an_unspoken_contract():
    """Acceptance 3. Restoring any `= ()` default fails this test.

    The signature is the refusal a caller cannot mistake for an empty contract:
    an explicit `()` is still an explicit answer, and no argument at all is not
    one.
    """

    with pytest.raises(TypeError):
        StrategyContract()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        StrategyContract(positions=())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        StrategyContract(prohibitions=(), preferences=())  # type: ignore[call-arg]

    stated = StrategyContract(positions=(), prohibitions=(), preferences=())
    assert (stated.positions, stated.prohibitions, stated.preferences) == ((), (), ())

    # The same fact read off the type, so that a default reintroduced with a
    # different spelling is caught too.
    declared = {
        item.name: item
        for item in dataclasses.fields(StrategyContract)
    }
    for name in ("positions", "prohibitions", "preferences"):
        field = declared[name]
        assert field.default is dataclasses.MISSING, name
        assert field.default_factory is dataclasses.MISSING, name


# ── 4 · configured empty vs absent, at the producer boundary ───────────────


def test_configured_empty_and_absent_differ_at_the_producer_boundary(tmp_path):
    """Acceptance test 4, on `prohibitions`: the one empty that is silent.

    No new stage or trace semantics are used for the proof. The producer is
    called twice on two documents that differ by one heading, and the two
    outcomes are a value and a refusal.
    """

    configured = strategy_contract(directory=NEVER_BLANK)
    assert configured.prohibitions == ()

    with pytest.raises(StrategyContractError) as raised:
        strategy_contract(
            directory=_renamed_section(tmp_path, PROHIBITIONS_SECTION)
        )

    assert PROHIBITIONS_SECTION in str(raised.value)


# ── 5 · the ending mode is K-NB-01's ───────────────────────────────────────


def test_the_produced_adaptation_contract_has_all_four_fields():
    """Acceptance 4: four fields, each from its own authority."""

    contract = _produced()

    assert contract.voice_brief_ref == "never-blank-voice v1"
    assert contract.forbidden, "the client's forbidden list reached the contract"
    assert {item.tier for item in contract.forbidden} == {
        KnowledgeTier.APPROVED_CLIENT_RULE
    }
    assert [
        (slot.name, slot.value, slot.rule_ref) for slot in contract.fixed_slots
    ] == [(ENDING_SLOT, ENDING_VALUE, ENDING_RECORD)]
    assert contract.hashtags == DECLARED_TAGS


def test_the_ending_mode_is_the_records_and_not_a_literal(tmp_path):
    """Acceptance 5. A literal ending mode in `src/` fails this test.

    The record is edited in a copied client directory and the produced slot
    follows it. The **value** is named nowhere in the producers, and the slot name
    only as the authorization decision 3 states — once, as a constant, never as a
    value composed into a slot. The check reads the code with the module docstring
    removed, because quoting the record's own clause as documentation is how a
    reader learns the grammar.
    """

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        f"[fixes: {ENDING_SLOT} = {ENDING_VALUE}]",
        f"[fixes: {ENDING_SLOT} = closing_question]",
    )

    edited = _produced(directory=directory)
    assert [slot.value for slot in edited.fixed_slots] == ["closing_question"]
    assert [slot.rule_ref for slot in edited.fixed_slots] == [ENDING_RECORD]
    assert edited.fixed_slots != _produced().fixed_slots

    for relative in PRODUCERS:
        code = _code_outside_the_module_docstring(relative)
        assert ENDING_VALUE not in code, relative
        named = 1 if relative == ENDING_PRODUCER else 0
        assert code.count(ENDING_SLOT) == named, (
            f"{relative}: the slot name belongs in a producer once, as the "
            "authorization, and nowhere else"
        )


def test_only_the_ending_slot_is_produced_and_nothing_is_invented():
    """Owner decision 3: "No other fixed slot is invented."

    The producer reads every loaded client rule, and against the real
    configuration exactly one record fixes a slot, so exactly one is produced.
    Both halves matter: a producer that never read the records would be the
    literal the test above refuses, and one that carried a second record's slot
    would be deciding client policy — which the two tests below refuse from
    either side.
    """

    rules = client_rules(directory=NEVER_BLANK, register=REGISTER)
    named = {loaded.identity for loaded in rules.records}

    assert ENDING_RECORD in named
    assert len(named) >= 6, "the whole K-NB set is loaded, not one record"
    assert [slot.name for slot in _produced().fixed_slots] == [ENDING_SLOT]


def test_the_record_losing_its_clause_is_refused_rather_than_unfixed(tmp_path):
    """Acceptance 4: the authorized slot is required, not read only if present.

    Deleting the clause leaves a record that still shapes `E-14.fixed_slots`,
    still reads as a normal record everywhere else, and fixes nothing. The
    mutation this catches is the producer that accepted it: an empty
    `fixed_slots()` composes a contract V-P04 can only pass — the same silence
    this slice closes one field along — and no plan checked against it shows that
    the rule had stopped being read.
    """

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        f" [fixes: {ENDING_SLOT} = {ENDING_VALUE}]",
        "",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    message = str(raised.value)
    assert ENDING_RECORD in message
    assert "fixes no slot" in message


def test_the_authorized_record_being_absent_is_refused_too(tmp_path):
    """The same refusal by the other route: the record never reaches the load.

    A deleted or retired record (§9.2) is not loaded at all, so a producer reading
    only what arrived would compose a contract whose one constraint had quietly
    left the run. The message distinguishes this from a record that is loaded and
    states no clause, because the two are different things for the keeper to do.
    """

    directory = _copied_client(tmp_path)
    (directory / "rules" / f"{ENDING_RECORD}.md").unlink()

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    message = str(raised.value)
    assert ENDING_RECORD in message
    assert "absent or retired" in message


def test_the_authorized_record_fixing_a_second_slot_is_refused(tmp_path):
    """The other end of the same bound: one approval, one fixed value.

    Owner decision 3 authorized this record for the ending mode and no other
    slot. A second clause in it would be a constraint V-P04 enforces on the
    strength of an approval that was given to the first, so it is the keeper's
    decision on a record of its own rather than this producer's to extend.
    """

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        "- S-13 · `E-15.text`",
        f"- S-10 · `{FIXED_SLOTS_FIELD}` — a second value the record states. "
        "[fixes: opening_mode = anecdote]\n- S-13 · `E-15.text`",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    message = str(raised.value)
    assert ENDING_RECORD in message
    assert "one fixed value" in message


def test_the_authorized_record_fixing_another_slot_instead_is_refused(tmp_path):
    """Acceptance 4 names the slot as well as the record, and both are checked.

    The record keeps its clause, its stage, its field and its tier, and renames
    the slot. A producer that counted the clauses this record states would accept
    it: exactly one arrives, from the authorized record, and the contract then
    carries no `ending_mode` at all — a constraint V-P04 cannot compare a plan
    against, and one it was never approved to enforce, in a single edit.
    """

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        f"[fixes: {ENDING_SLOT} = {ENDING_VALUE}]",
        f"[fixes: closing_style = {ENDING_VALUE}]",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    message = str(raised.value)
    assert ENDING_RECORD in message
    assert ENDING_SLOT in message
    assert "closing_style" in message


def test_another_records_own_fixed_slot_is_refused_rather_than_carried(tmp_path):
    """Owner decision 3 from the other side: no second record fixes anything.

    `K-NB-02` is a loaded, approved, tier-2 client rule that already influences
    an `E-14` field at S-10, so a clause in it reads as legitimately as
    `K-NB-01`'s. It is still a constraint V-P04 would enforce on an approval
    given to one value in one record, and the same producer that counted only
    `K-NB-01`'s slots would compose a contract fixing two.
    """

    directory = _edited(
        tmp_path,
        "rules/K-NB-02.md",
        "- S-10 · `E-14.citations` — a derivative cites only what the core holds.",
        f"- S-10 · `{FIXED_SLOTS_FIELD}` — a second record's own slot. "
        "[fixes: opening_mode = anecdote]",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    message = str(raised.value)
    assert "K-NB-02" in message
    assert "opening_mode" in message
    assert "one fixed value" in message


def test_a_malformed_fixes_clause_raises_rather_than_being_completed(tmp_path):
    """A producer that guessed would hand V-P04 a constraint nobody wrote."""

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        f"[fixes: {ENDING_SLOT} = {ENDING_VALUE}]",
        "[fixes: end on the kicker, probably]",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    assert "<slot> = <value>" in str(raised.value)


def test_a_fixes_clause_on_another_field_is_refused(tmp_path):
    """The clause is read exactly: a value S-10 has nowhere to put is a refusal."""

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        f"- S-10 · `{FIXED_SLOTS_FIELD}` — the client's own ending mode",
        "- S-10 · `E-14.subheadings` — the client's own ending mode",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    assert "E-14.fixed_slots" in str(raised.value)


def test_a_fixes_clause_at_another_stage_is_refused_rather_than_unread(tmp_path):
    """A clause no producer reads is a rule the keeper believes is in force.

    The mutation this catches is the one that reads naturally: filtering the
    records to this stage first, so a clause written on an S-08 entry produces no
    slot and no error — invisible from both ends.
    """

    directory = _edited(
        tmp_path,
        f"rules/{ENDING_RECORD}.md",
        f"- S-10 · `{FIXED_SLOTS_FIELD}` — the client's own ending mode",
        f"- S-08 · `{FIXED_SLOTS_FIELD}` — the client's own ending mode",
    )

    with pytest.raises(AdaptationContractError) as raised:
        _produced(directory=directory)

    assert "S-08" in str(raised.value)


# ── 6 · V-P04 enforces the produced slot ───────────────────────────────────


def test_v_p04_enforces_the_fixed_slot_end_to_end():
    """Acceptance test 6: a plan without the fixed value is refused, citing K-NB-01.

    The plan is drafted against #305's fixture contract, which carries no fixed
    slot, and then checked against the **production** contract. The mutation this
    catches is the one the acceptance names: dropping the slot from the produced
    contract removes the Finding, which the second half asserts.
    """

    produced = _produced()
    snapshot = _two_readings()
    strategy, drafted = _drafted(boundary=snapshot, contract=_contract())
    assert drafted.plan is not None
    assert drafted.plan.fixed_slots == ()

    decision = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=snapshot,
        core=_core(),
        rules=_rules(),
        contract=produced,
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
    )

    assert decision.passed is False
    verdict = decision.verdict
    assert verdict is not None
    compliance = verdict.check("V-P04")
    assert compliance is not None
    cited = [
        finding
        for finding in compliance.findings
        if finding.rule_ref == ENDING_RECORD
    ]
    assert len(cited) == 1, [item.rule_ref for item in compliance.findings]
    assert cited[0].tier is KnowledgeTier.APPROVED_CLIENT_RULE
    assert ENDING_SLOT in cited[0].detail

    # The mutation guard: with the slot dropped, nothing cites the record.
    without = check_plan(
        plan=drafted.plan,
        strategy=strategy,
        boundary=snapshot,
        core=_core(),
        rules=_rules(),
        contract=dataclasses.replace(produced, fixed_slots=()),
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(PASSING_CHECK),
    )
    slotless = without.verdict.check("V-P04") if without.verdict else None
    assert slotless is None or not [
        finding
        for finding in slotless.findings
        if finding.rule_ref == ENDING_RECORD
    ]


# ── 7 · the vocabulary is declared, and publishing consumes it ─────────────


def test_the_hashtag_vocabulary_is_exactly_the_two_static_values():
    """Acceptance 6: the declaration, and neither computed tag."""

    assert client_hashtags(directory=NEVER_BLANK) == DECLARED_TAGS
    assert _produced().hashtags == DECLARED_TAGS
    assert COMPUTED_TAG not in _produced().hashtags
    # The words are the document's: they appear in the contract and the producer
    # reads them from there. The computed tag is *named* there, in the note that
    # says why it is not declared, and it is not declared.
    text = CONTRACT.read_text(encoding="utf-8")
    for tag in DECLARED_TAGS:
        assert f"- {tag}" in text, tag
    assert f"- {COMPUTED_TAG}" not in text


def test_editing_the_declared_vocabulary_changes_what_publishing_emits(tmp_path):
    """The mutation: a tuple hard-coded in either module fails this test."""

    directory = _with_section(
        tmp_path,
        HASHTAG_SECTION,
        "\n".join(f"- {tag}" for tag in (*DECLARED_TAGS, "#QuietProof")),
    )

    assert client_hashtags(directory=directory) == (*DECLARED_TAGS, "#QuietProof")
    assert _produced(directory=directory).hashtags == (
        *DECLARED_TAGS, "#QuietProof",
    )

    for relative in PRODUCERS + ("src/publishing/hashtags.py",):
        code = _code_outside_the_module_docstring(relative)
        for tag in DECLARED_TAGS:
            assert tag not in code, f"{relative} writes {tag} rather than reading it"


def test_publishing_is_a_consumer_of_the_declared_vocabulary():
    """The direction that leaves one authority for the client's own words."""

    from src.publishing.hashtags import branded_hashtags, generate_hashtags

    assert branded_hashtags() == DECLARED_TAGS
    tags = generate_hashtags(
        {"INDUSTRY": "retail"}, "linkedin", article_text="The queue."
    )
    assert tags[: len(DECLARED_TAGS)] == list(DECLARED_TAGS)


@pytest.mark.parametrize(
    "body",
    ["- NeverBlank", "- #Never Blank", "- #NeverBlank\n- #NeverBlank", "nothing", ""],
    ids=["no-hash", "two-words", "declared-twice", "not-a-bullet", "emptied"],
)
def test_a_vocabulary_that_cannot_be_read_exactly_raises(tmp_path, body):
    with pytest.raises(AdaptationContractError):
        client_hashtags(directory=_with_section(tmp_path, HASHTAG_SECTION, body))


def test_a_missing_vocabulary_section_raises(tmp_path):
    with pytest.raises(AdaptationContractError) as raised:
        client_hashtags(directory=_renamed_section(tmp_path, HASHTAG_SECTION))

    assert HASHTAG_SECTION in str(raised.value)


def test_no_engine_or_producer_depends_on_publishing():
    """Acceptance 6, second half: adding one import fails this test.

    `src/publishing/release_scope.py` is a different matter and is deliberately
    not what is asserted: the engine already reads the publish channels from it.
    What must stay out is the hashtag module, because that is where a second
    policy authority would appear.
    """

    engine = sorted((_REPO_ROOT / "src" / "editorial_core").glob("*.py"))
    assert engine, "no engine modules were scanned"
    scanned = [
        str(path.relative_to(_REPO_ROOT)) for path in engine
    ] + list(PRODUCERS)

    for relative in scanned:
        imported = _imported(relative)
        assert not [
            name for name in imported if "publishing.hashtags" in name
        ], relative
        assert "src.publishing.hashtags" not in _code_outside_the_module_docstring(
            relative
        ), relative


# ── 8 · the hashtag policy stays where #363 left it ────────────────────────


def test_the_hashtag_policy_still_comes_from_the_rules_363_left():
    """Acceptance 7 and 8: policy is the destination's, vocabulary is the client's.

    Sourcing the policy from the new producer fails this: the rule that fixed it
    is the contract's own `## Destination rules` row, and the file that declares
    it is the contract.
    """

    rules = destination_rules(
        Destination.LINKEDIN, register=REGISTER, contract=CONTRACT
    )

    assert rules.hashtags is HashtagPolicy.REQUIRED
    assert rules.hashtag_rule.rule_id == "NB-DST-LI-HASHTAGS"
    assert rules.hashtag_rule.tier is KnowledgeTier.APPROVED_CLIENT_RULE
    sources = rule_catalogue(register=REGISTER, contract=CONTRACT).sources()
    assert sources["NB-DST-LI-HASHTAGS"] == str(CONTRACT)

    # Instagram's policy is still the record's, unchanged by this slice.
    instagram = destination_rules(
        Destination.INSTAGRAM, register=REGISTER, contract=CONTRACT
    )
    assert instagram.hashtags is HashtagPolicy.ALLOWED
    assert instagram.hashtag_rule.rule_id == "K-DST-IG-01"

    # And neither new producer knows what a policy is.
    for relative in PRODUCERS:
        code = _code_outside_the_module_docstring(relative)
        assert "HashtagPolicy" not in code, relative
        assert "DestinationRules" not in code, relative


def test_the_destination_rule_rows_are_the_twelve_363_wrote():
    """The contract gained sections and lost no row."""

    text = CONTRACT.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| NB-DST-")]

    assert len(rows) == 12
    assert "| NB-DST-LI-HASHTAGS | linkedin | E-14.hashtags | required |" in text


# ── 9 · the registry is read, and a broken one stops the run ──────────────


def test_an_unreadable_client_rule_stops_the_run(tmp_path):
    """Acceptance test 9: the path is live rather than defaulting to `()`.

    Reverting the wiring lets the run start on a client folder holding a file
    nobody can read, which is the state this slice found: the records were
    validated in CI and never loaded.
    """

    directory = _copied_client(tmp_path)
    (directory / "rules" / "K-NB-09.md").write_text(
        "this file has no front matter and is not a record\n", encoding="utf-8"
    )

    with pytest.raises(ClientRulesError) as raised:
        _produced(directory=directory)

    assert "K-NB-09.md" in str(raised.value)


def test_the_rules_readme_is_the_only_file_that_is_not_a_rule(tmp_path):
    """The folder's documentation is not a rule written in it — and it is named.

    The exception is a name, not a shape, so it cannot widen into "skip whatever
    does not parse": a second unreadable file in the same directory is still the
    refusal the test above asserts.
    """

    assert (CLIENT_RULES / "README.md").is_file()
    rules = client_rules(directory=NEVER_BLANK, register=REGISTER)
    assert "README.md" not in [
        Path(loaded.record.path).name for loaded in rules.records
    ]

    directory = _copied_client(tmp_path)
    (directory / "rules" / "NOTES.md").write_text(
        "a note somebody left beside the rules, in no format at all\n",
        encoding="utf-8",
    )
    with pytest.raises(ClientRulesError) as raised:
        client_rules(directory=directory, register=REGISTER)

    assert "NOTES.md" in str(raised.value)


def test_a_client_rule_may_not_claim_an_authority_the_client_does_not_own(tmp_path):
    """§2.3: tier 1 is hard platform policy, and a client does not write one."""

    directory = _edited(
        tmp_path, f"rules/{ENDING_RECORD}.md", "tier: 2", "tier: 1"
    )

    with pytest.raises(ClientRulesError) as raised:
        _produced(directory=directory)

    assert ENDING_RECORD in str(raised.value)


def test_a_refused_register_stops_the_run_before_the_producers_read_it(tmp_path):
    """The run-start validator's other half: it now has a caller.

    `validate_at_run_start` had none at all, so §8's ten rules ran in CI and
    never again — and CI checks the tree at the time of a commit, not the working
    tree a run reads. Deleting the call makes this test pass a broken register.
    """

    register = _copied_register(tmp_path)
    (register / "records" / "dst" / "K-DST-LI-09.md").write_text(
        _UNAPPROVED_HARD_RECORD, encoding="utf-8"
    )

    with pytest.raises(ClientRulesError) as raised:
        _produced(register=register)

    message = str(raised.value)
    assert "does not start" in message
    assert "knowledge_register_invalid" in message


def test_the_accepted_register_and_client_rules_start_a_run():
    """The gate is a gate and not a wall: today's configuration passes it."""

    rules = client_rules(directory=NEVER_BLANK, register=REGISTER)

    assert rules.path == str(CLIENT_RULES)
    assert {loaded.tier for loaded in rules.records} == {
        KnowledgeTier.APPROVED_CLIENT_RULE
    }
    assert rules.record(ENDING_RECORD).identity == ENDING_RECORD
    with pytest.raises(ClientRulesError):
        rules.record("K-NB-99")


# ── E-14's citation invariant, untouched ───────────────────────────────────


def test_the_citation_invariant_is_unchanged_and_still_raises():
    """Acceptance 8: source attribution stays with the evidence machinery.

    Owner decision 6: no `StrategyContract` rule is added for it, because E-14's
    `citations` is already mandatory and non-empty and is computed by code. The
    contract declares no rule of any kind, so nothing was smuggled in.
    """

    _, drafted = _drafted(contract=_contract())
    assert drafted.plan is not None
    assert drafted.plan.citations

    with pytest.raises(PlanError) as raised:
        dataclasses.replace(drafted.plan, citations=())

    assert "cites no source" in str(raised.value)

    contract = strategy_contract(directory=NEVER_BLANK)
    assert contract.prohibitions == () and contract.preferences == ()


# ── 10 · containment ───────────────────────────────────────────────────────


def test_this_branch_changes_nothing_the_slice_declared_out_of_scope():
    """Acceptance 9 and 10: the diff is the evidence, so the diff is asserted.

    Gated on the branch touching the producer, so that later work elsewhere is
    not held hostage by a check about #368.
    """

    if _git("rev-parse", "--git-dir")[0] != 0:
        pytest.skip("not a git checkout")

    base = ""
    for ref in ("origin/main", "main"):
        status, resolved = _git("merge-base", ref, "HEAD")
        if status == 0 and resolved:
            base = resolved
            break
    assert base, "no base revision to compare against; main is unreachable"

    status, listed = _git("diff", "--name-only", base)
    assert status == 0, "the diff against the base revision could not be read"
    changed = [line for line in listed.splitlines() if line]

    if "src/strategy/adaptation_contract.py" not in changed:
        return

    assert not [
        line for line in changed if line.startswith("src/never_blank/wednesday_july/")
    ], "July is out of scope"
    core = [line for line in changed if line.startswith("src/editorial_core/")]
    assert core in ([], ["src/editorial_core/candidate_strategies.py"]), core
    # #363's own files, byte-identical: the policy is not touched by a slice that
    # only supplies the vocabulary.
    for untouched in (
        "src/knowledge/destination_rules.py",
        "src/strategy/contract_fit.py",
    ):
        assert untouched not in changed, untouched


# ----------------------------------------------------------------------
# Fixtures written only inside a copied register
# ----------------------------------------------------------------------


#: A tier-1 approved rule with no `approved_by`, which §8 rule 3 refuses, and no
#: `verified_on`, which rule 8 refuses for a `K-DST-*` record. It exists so that
#: one test can prove the run-start gate is called at all.
_UNAPPROVED_HARD_RECORD = """---
id: K-DST-LI-09
version: 1
status: approved-rule
tier: 1
evidence_class: PLAT
confidence: high
review_by: 2027-06-30
---

# A hard platform rule nobody approved

## Statement
A fixture record. It is a tier-1 approved rule with no `approved_by`, which the
register validator refuses, so a run that reads this register does not start.

## Applies when
destination is linkedin

## Influences
- S-10 · `E-14.format` — the form this fixture claims to fix.

## Conflicts
None; it is never loaded, because the register carrying it is refused.

## Source
Written by `tests/test_368_client_contracts.py`; never shipped.

## Change log
- v1, 2026-09-30: created as a test fixture (#368).
"""
