"""The configuration producers: `ContractFitRules` and `DestinationRules` in production.

Issue #363, slice SL-6.45. Before it, two **required** stage inputs had no
producer at all: S-00's fit table and S-10/S-11's destination rules were built
by hand in three test files and nowhere else, and two of those hand-built rules
cited ``K-DST-LI-11`` — a record that has never existed. A green suite over
configuration nothing produces is the same defect #361 closed for the transport
Protocols, one layer up.

What these tests are for
------------------------
Each one runs the whole chain — **human-editable document → loader → typed
runtime value → the stage that declares it** — against the repository's *real*
configuration, and each is written so that a bypass fails it:

* hard-coding the tuple in ``src/`` fails the two that edit the document;
* an ``or default`` or a swallowed exception fails the refusal tests;
* deleting ``K-DST-TG-02`` fails telegram and nothing else;
* dropping one client rule fails that destination's one field and no other;
* substituting the legacy ``_WORD_RANGE`` fails LinkedIn's length;
* swapping a hand-built fixture back in fails the stage test.

What is deliberately not proven here
------------------------------------
**No end-to-end S-00 fit on a real signal.** ``FitRule.field`` is "the E-01
field the rule reads, spelled as the intake record spells it", and the real
intake record (``data/research/signals_active.jsonl``) carries 46 fields and
neither a domain field nor a risk field. Normalising a real signal into the
fields S-00 reads is seam 1, which #351 owns. So the binding is a required
argument here, the tests supply their own spelling, and nothing adds a synthetic
field to a real signal to make a fit pass. The gap is documented rather than
simulated — see :func:`test_the_field_binding_is_unresolved_and_structurally_so`.

**Nothing about whether the thirteen stage contracts compose.** That is #351's
own risk and is untouched.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.destinations import Destination
from src.editorial_core.executable_plan import (
    ClientRule,
    HashtagPolicy,
    LengthTarget,
    LengthUnit,
    PlanError,
    PlanFormat,
    PlatformRule,
)
from src.editorial_core.signal_selection import (
    SelectionCandidate,
    SignalFit,
    select_signal,
)
from src.knowledge.destination_rules import (
    CONTRACT_SECTION,
    DestinationRulesError,
    destination_rules,
    rule_catalogue,
)
from src.knowledge.markdown import load_document
from src.knowledge.records import parse_knowledge_record
from src.strategy.client_contract import CONTRACT_FILE, ClientConfigurationError
from src.strategy.contract_fit import (
    DOMAIN_SECTION,
    RISK_RULE_ID,
    RISK_SECTION,
    TOPIC_RULE_ID,
    contract_fit_rules,
)
from tests.test_298_signal_selection import _role
from tests.test_305_executable_plan_and_check import (
    _checked,
    _contract,
    _rules,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTER = _REPO_ROOT / "knowledge"
DESTINATION_RECORDS = REGISTER / "records" / "dst"
NEVER_BLANK = _REPO_ROOT / "clients" / "never_blank"
CONTRACT = NEVER_BLANK / CONTRACT_FILE

#: The two field names the tests bind the fit rules to. They are the *tests'*
#: spelling and not the engine's: #351 resolves the real one against the intake
#: adapter, and naming it here would let this slice design half of seam 1.
DOMAIN_FIELD = "TEST_DOMAIN"
RISK_FIELD = "TEST_RISK"

#: The owner's editorial domain (2026-09-28), in the contract's own spelling.
EXPECTED_DOMAIN = (
    "entrepreneurship_operations",
    "marketing_sales_cx",
    "ai_technology_automation",
    "productivity_process",
    "adjacent_business",
)

#: The rule that fixed each of the three values, named as `DestinationRules`
#: names it: the value is plural where the field is a policy over many tags and
#: the rule that fixed it is singular, so the two spellings do not derive from
#: one another.
RULE_ATTRIBUTE = {
    "format": "format_rule",
    "length": "length_rule",
    "hashtags": "hashtag_rule",
}

#: The 18/18 authority table of #363, row for row: which source fixes which
#: value for which destination. `None` for the rule id means "the client's own
#: rule", which is asserted by tier rather than by name.
AUTHORITY: dict[Destination, dict[str, tuple[KnowledgeTier, Any]]] = {
    Destination.WIX: {
        "format": (KnowledgeTier.APPROVED_CLIENT_RULE, PlanFormat.ARTICLE),
        "length": (
            KnowledgeTier.APPROVED_CLIENT_RULE,
            LengthTarget(minimum=400, maximum=600, unit=LengthUnit.WORDS),
        ),
        "hashtags": (KnowledgeTier.APPROVED_CLIENT_RULE, HashtagPolicy.FORBIDDEN),
    },
    Destination.LINKEDIN: {
        "format": (KnowledgeTier.PLATFORM_RANKING, PlanFormat.POST),
        "length": (
            KnowledgeTier.PLATFORM_RANKING,
            LengthTarget(minimum=250, maximum=400, unit=LengthUnit.WORDS),
        ),
        "hashtags": (KnowledgeTier.APPROVED_CLIENT_RULE, HashtagPolicy.REQUIRED),
    },
    Destination.FACEBOOK: {
        "format": (KnowledgeTier.PLATFORM_RANKING, PlanFormat.POST),
        "length": (
            KnowledgeTier.APPROVED_CLIENT_RULE,
            LengthTarget(minimum=350, maximum=600, unit=LengthUnit.WORDS),
        ),
        "hashtags": (KnowledgeTier.APPROVED_CLIENT_RULE, HashtagPolicy.REQUIRED),
    },
    Destination.INSTAGRAM: {
        "format": (KnowledgeTier.PLATFORM_RANKING, PlanFormat.CAROUSEL),
        "length": (
            KnowledgeTier.APPROVED_CLIENT_RULE,
            LengthTarget(minimum=80, maximum=150, unit=LengthUnit.WORDS),
        ),
        "hashtags": (KnowledgeTier.PLATFORM_RANKING, HashtagPolicy.ALLOWED),
    },
    Destination.THREADS: {
        "format": (KnowledgeTier.PLATFORM_RANKING, PlanFormat.POST),
        "length": (
            KnowledgeTier.APPROVED_CLIENT_RULE,
            LengthTarget(minimum=150, maximum=400, unit=LengthUnit.WORDS),
        ),
        "hashtags": (KnowledgeTier.APPROVED_CLIENT_RULE, HashtagPolicy.ALLOWED),
    },
    Destination.TELEGRAM: {
        "format": (KnowledgeTier.APPROVED_CLIENT_RULE, PlanFormat.CHANNEL_POST),
        "length": (
            KnowledgeTier.APPROVED_CLIENT_RULE,
            LengthTarget(minimum=180, maximum=300, unit=LengthUnit.WORDS),
        ),
        "hashtags": (KnowledgeTier.APPROVED_CLIENT_RULE, HashtagPolicy.FORBIDDEN),
    },
}


def _fit_rules(directory: Path = NEVER_BLANK):
    """The production fit table, bound to this test module's field spelling."""

    return contract_fit_rules(
        domain_field=DOMAIN_FIELD, risk_field=RISK_FIELD, directory=directory
    )


def _copied(tmp_path: Path) -> Path:
    """The real contract, copied so a test may edit it and see the difference."""

    directory = tmp_path / "client"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CONTRACT_FILE).write_text(
        CONTRACT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


def _edited(tmp_path: Path, old: str, new: str) -> Path:
    """The real contract with one exact substitution, as a keeper would edit it."""

    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} is not one place in the contract"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return directory


# ── 1 · the rules come from the document ───────────────────────────────────


def test_the_fit_rules_are_the_contracts_and_not_a_literal_in_src():
    """artifact → loader → typed value, on the client's real contract."""

    rules = _fit_rules()

    assert tuple(rule.rule_id for rule in rules.rules) == (
        TOPIC_RULE_ID,
        RISK_RULE_ID,
    )
    topic, risk = rules.rules
    assert topic.fit is SignalFit.OUTSIDE_TOPICS
    assert topic.admits == EXPECTED_DOMAIN
    assert risk.fit is SignalFit.OUTSIDE_RISK_LEVEL
    assert risk.admits == ("low",)
    # Neither value is written in `src/`: the contract is the only place the
    # vocabulary appears, so editing it is the only way to change the table.
    assert EXPECTED_DOMAIN[0] in CONTRACT.read_text(encoding="utf-8")


def test_editing_the_admitted_domains_changes_what_the_producer_returns(tmp_path):
    """The mutation this test exists for: a tuple hard-coded in `src/` fails it."""

    directory = _edited(
        tmp_path, "- marketing_sales_cx\n", "- marketing_sales_cx\n- logistics\n"
    )
    topic, _ = _fit_rules(directory).rules

    assert topic.admits == (*EXPECTED_DOMAIN[:2], "logistics", *EXPECTED_DOMAIN[2:])
    assert topic.admits != _fit_rules().rules[0].admits


# ── 2 · `adjacent_business` is present, and why ────────────────────────────


def test_adjacent_business_is_admitted_so_adjacency_has_somewhere_to_land():
    """The owner's anti-narrow-allow-list instruction, as a value in the table.

    `FitRule.check` computes `passed = bool(stated) and all(value in admits)` —
    a strict allow-list over every value a signal states. The owner's decision
    is explicit that the domain is "not to be read as a narrow allow-list that
    rejects legitimate adjacent SMB material merely because its exact noun is
    absent", and this value is where that adjacency lands. Removing it converts
    the owner's decision into the thing the owner forbade, silently.
    """

    topic, _ = _fit_rules().rules
    assert "adjacent_business" in topic.admits

    adjacent = {DOMAIN_FIELD: "adjacent_business", RISK_FIELD: "low"}
    assert topic.check(adjacent).passed is True


def test_removing_adjacent_business_from_the_contract_changes_the_table(tmp_path):
    directory = _edited(tmp_path, "- adjacent_business\n", "")
    topic, _ = _fit_rules(directory).rules

    assert "adjacent_business" not in topic.admits
    assert topic.check({DOMAIN_FIELD: "adjacent_business"}).passed is False


# ── 3 · absent configuration raises ────────────────────────────────────────


def test_a_missing_contract_raises_rather_than_admitting_everything(tmp_path):
    with pytest.raises(ClientConfigurationError) as raised:
        _fit_rules(tmp_path / "nowhere")

    assert "no contract" in str(raised.value)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (f"## {DOMAIN_SECTION}", "## Something else", DOMAIN_SECTION),
        (f"## {RISK_SECTION}", "## Something else", RISK_SECTION),
    ],
    ids=["missing-domain-section", "missing-risk-section"],
)
def test_a_missing_section_raises(tmp_path, old, new, expected):
    """An `or default` anywhere on this path returns a table instead."""

    with pytest.raises(ClientConfigurationError) as raised:
        _fit_rules(_edited(tmp_path, old, new))

    assert expected in str(raised.value)


def test_an_empty_admits_list_raises(tmp_path):
    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    text = path.read_text(encoding="utf-8")
    for value in EXPECTED_DOMAIN:
        text = text.replace(f"- {value}\n", "")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ClientConfigurationError) as raised:
        _fit_rules(directory)

    assert "admits nothing" in str(raised.value)


def test_an_empty_risk_level_raises(tmp_path):
    with pytest.raises(ClientConfigurationError) as raised:
        _fit_rules(_edited(tmp_path, "- low\n", ""))

    assert "admits nothing" in str(raised.value)


def test_a_duplicated_admitted_value_raises(tmp_path):
    with pytest.raises(ClientConfigurationError) as raised:
        _fit_rules(_edited(tmp_path, "- low\n", "- low\n- low\n"))

    assert "twice" in str(raised.value)


def test_the_field_binding_is_unresolved_and_structurally_so():
    """The E-01 gap is a signature, not a placeholder string (#351 owns seam 1).

    A rule reading a field the intake record does not carry refuses every real
    signal, because `check` starts at `bool(stated)`. So the producer refuses to
    invent a spelling: called with no binding it raises from its own signature,
    which is the one refusal a caller cannot read as an empty table.
    """

    with pytest.raises(TypeError):
        contract_fit_rules()  # type: ignore[call-arg]

    with pytest.raises(ClientConfigurationError):
        contract_fit_rules(
            domain_field=" ", risk_field=RISK_FIELD, directory=NEVER_BLANK
        )
    with pytest.raises(ClientConfigurationError):
        contract_fit_rules(
            domain_field=DOMAIN_FIELD, risk_field="", directory=NEVER_BLANK
        )
    with pytest.raises(ClientConfigurationError):
        contract_fit_rules(
            domain_field="SAME", risk_field="SAME", directory=NEVER_BLANK
        )

    # The two spellings an earlier draft of the spec proposed stay withdrawn:
    # declaring them here would let this slice design half of seam 1.
    text = CONTRACT.read_text(encoding="utf-8")
    assert "editorial_domain" not in text
    assert "risk_level" not in text


# ── 4 · every destination resolves, at the authority the table says ────────


@pytest.mark.parametrize("destination", list(Destination), ids=lambda d: d.value)
def test_every_destination_resolves_at_the_declared_authority(destination):
    """The 18/18 table, row for row, from the configuration on disk.

    The mutation this catches: deleting `K-DST-TG-02` fails telegram, and
    dropping one client rule fails that destination's one field and no other.
    """

    rules = destination_rules(destination, register=REGISTER, contract=CONTRACT)
    expected = AUTHORITY[destination]

    assert rules.destination is destination
    assert set(expected) == set(RULE_ATTRIBUTE)
    for field, (tier, value) in expected.items():
        rule = getattr(rules, RULE_ATTRIBUTE[field])
        assert getattr(rules, field) == value, f"{destination.value}.{field}"
        assert rule.tier is tier, f"{destination.value}.{field} authority"
        if tier is KnowledgeTier.APPROVED_CLIENT_RULE:
            assert isinstance(rule, ClientRule)
        else:
            assert isinstance(rule, PlatformRule)
            assert rule.tier in (
                KnowledgeTier.HARD_PLATFORM_POLICY,
                KnowledgeTier.PLATFORM_RANKING,
            )


def test_deleting_the_telegram_ranking_record_leaves_telegram_constructible():
    """`K-DST-TG-02` fixes none of the three, so it is telegram's *other* rule.

    The owner's decision 2 was a separate tier-4 record rather than a promotion
    of `K-DST-TG-01`, and the point of it is that telegram has a ranking record
    at all. It reaches S-10 as a constraint, which is where a reader looks for
    it.
    """

    rules = destination_rules(
        Destination.TELEGRAM, register=REGISTER, contract=CONTRACT
    )
    named = {rule.rule_id for rule in rules.rules}

    assert "K-DST-TG-02" in named
    assert "K-DST-TG-01" not in named  # tier 3 is not a rule S-10 applies


def test_dropping_one_client_rule_fails_that_field_and_no_other(tmp_path):
    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    text = path.read_text(encoding="utf-8")
    row = next(
        line
        for line in text.splitlines()
        if line.startswith("| NB-DST-TG-LENGTH ")
    )
    path.write_text(text.replace(row + "\n", ""), encoding="utf-8")

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(
            Destination.TELEGRAM, register=REGISTER, contract=path
        )
    assert "E-14.length_target" in str(raised.value)

    # Every other destination is untouched by the missing row.
    for other in Destination:
        if other is Destination.TELEGRAM:
            continue
        assert destination_rules(other, register=REGISTER, contract=path)


# ── 5 · every cited id resolves to its declaring source ────────────────────


def test_every_cited_rule_id_resolves_to_the_file_that_declares_it():
    """A `K-DST-` id to a record on disk, a client id to the contract's own row.

    The mutation: reintroducing `K-DST-LI-11` anywhere fails, because no file
    under `knowledge/records/dst/` declares it; and a client rule carrying a
    `K-DST-` id fails on its own, because the contract does not own one.
    """

    catalogue = rule_catalogue(register=REGISTER, contract=CONTRACT)
    sources = catalogue.sources()
    contract_text = CONTRACT.read_text(encoding="utf-8")

    cited = set()
    for destination in Destination:
        for rule in destination_rules(
            destination, register=REGISTER, contract=CONTRACT
        ).rules:
            cited.add(rule.rule_id)

    assert cited
    for rule_id in sorted(cited):
        declaring = Path(sources[rule_id])
        assert declaring.is_file(), rule_id
        if rule_id.startswith("K-DST-"):
            assert declaring.parent == DESTINATION_RECORDS, rule_id
            assert parse_knowledge_record(
                load_document(declaring)
            ).record_id == rule_id
        else:
            assert declaring == CONTRACT, rule_id
            assert f"| {rule_id} |" in contract_text


def test_k_dst_li_11_is_declared_by_no_file_and_cited_by_no_test():
    """The id the two fixtures used to carry. It never named a record."""

    assert not (DESTINATION_RECORDS / "K-DST-LI-11.md").exists()
    for path in sorted((_REPO_ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name == Path(__file__).name:
            continue
        assert "K-DST-LI-11" not in text, path.name


def test_a_client_rule_may_not_carry_a_register_id(tmp_path):
    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "| NB-DST-WIX-FORMAT |", "| K-DST-WIX-09 |"
        ),
        encoding="utf-8",
    )

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(Destination.WIX, register=REGISTER, contract=path)

    assert "K-DST-" in str(raised.value)


def test_a_client_rule_cannot_be_constructed_outside_tier_2():
    """The type is the guarantee, not a convention (#363, owner boundary B)."""

    for tier in (
        KnowledgeTier.HARD_PLATFORM_POLICY,
        KnowledgeTier.PLATFORM_RANKING,
        KnowledgeTier.EDITORIAL,
    ):
        with pytest.raises(PlanError):
            ClientRule(rule_id="NB-X", text="something absolute", tier=tier)

    rule = ClientRule(
        rule_id="NB-X",
        text="something absolute",
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
    )
    assert rule.is_hard is False


# ── 6 · tier integrity ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("record_id", "tier"),
    [("K-DST-TG-01", "3"), ("K-DST-TG-02", "4")],
)
def test_telegram_keeps_its_tier_split(record_id, tier):
    """`K-DST-TG-01` is not promoted; the ranking record is a separate file."""

    record = parse_knowledge_record(
        load_document(DESTINATION_RECORDS / f"{record_id}.md")
    )
    assert record.tier == tier, record_id


def test_a_tier_3_record_is_not_a_rule_s10_applies():
    """Promoting `K-DST-TG-01` would put it in telegram's rules; it is not there."""

    catalogue = rule_catalogue(register=REGISTER, contract=CONTRACT)
    named = {item.rule.rule_id for item in catalogue.bound}

    assert "K-DST-TG-02" in named
    for tier_3 in ("K-DST-TG-01", "K-DST-WIX-01", "K-DST-LI-02"):
        assert tier_3 not in named, tier_3


def test_threads_02_is_absent_and_its_absence_is_documented():
    """The map routes it to the Client Contract, not to a production run."""

    assert not (DESTINATION_RECORDS / "K-DST-TH-02.md").exists()
    readme = (REGISTER / "README.md").read_text(encoding="utf-8")
    assert "K-DST-TH-02" in readme
    assert "Unavailable in an autonomous system" in readme


# ── 7 · the values are the register's, not a legacy constant's ─────────────


def test_linkedins_length_is_the_records_250_to_400_and_never_the_legacy_range():
    """Substituting `_WORD_RANGE`'s `(120, 220)` fails this test.

    The legacy constant is migration provenance for decisions already made and
    never a runtime dependency. LinkedIn in particular is why: promoting
    120–220 would have used precedence alone to replace the accepted canonical
    250–400, which the owner declined deliberately.
    """

    rules = destination_rules(
        Destination.LINKEDIN, register=REGISTER, contract=CONTRACT
    )

    assert rules.length == LengthTarget(
        minimum=250, maximum=400, unit=LengthUnit.WORDS
    )
    assert rules.length_rule.rule_id == "K-DST-LI-01"
    assert "250–400" in (
        DESTINATION_RECORDS / "K-DST-LI-01.md"
    ).read_text(encoding="utf-8")

    # No client rule competes for it, which is what makes the record govern.
    catalogue = rule_catalogue(register=REGISTER, contract=CONTRACT)
    client_lengths = [
        item
        for item in catalogue.for_destination(Destination.LINKEDIN)
        if isinstance(item.rule, ClientRule)
        and item.value_for("E-14.length_target") is not None
    ]
    assert client_lengths == []


def test_no_producer_imports_the_legacy_word_or_count_ranges():
    """Provenance, never a runtime dependency: no import and no subscript."""

    for module in (
        "src/knowledge/destination_rules.py",
        "src/strategy/contract_fit.py",
    ):
        text = (_REPO_ROOT / module).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not [name for name in imported if "platform_composer" in name], module
        assert not [name for name in imported if "hashtags" in name], module
        # Named in prose as provenance, and read nowhere: no subscript of either.
        assert "_WORD_RANGE[" not in text, module
        assert "_COUNT_RANGE[" not in text, module


def test_instagrams_hashtag_policy_is_the_records_and_not_the_legacy_count():
    """Option (b): `_COUNT_RANGE["instagram"]` of 3–6 is not promoted."""

    rules = destination_rules(
        Destination.INSTAGRAM, register=REGISTER, contract=CONTRACT
    )

    assert rules.hashtags is HashtagPolicy.ALLOWED
    assert rules.hashtag_rule.rule_id == "K-DST-IG-01"
    assert rules.hashtag_rule.tier is KnowledgeTier.PLATFORM_RANKING


# ── 8 · the stages receive the produced objects ────────────────────────────


def test_s00_receives_the_contracts_own_fit_table():
    """S-00 is called with the producer's output, and records its rule ids.

    Swapping in a hand-built fixture fails this: the recorded rule ids and the
    admitted vocabulary are the contract's, and no fixture in this repository
    carries either.
    """

    rules = _fit_rules()
    candidate = SelectionCandidate(
        signal_id="sig-363",
        signal={DOMAIN_FIELD: "celebrity gossip", RISK_FIELD: "low"},
    )

    selection = select_signal(
        candidate,
        fit_rules=rules,
        role=_role(),
        transport=_UncalledTransport(),
    )

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS
    assert [result.rule_id for result in selection.fit_rules] == [
        TOPIC_RULE_ID,
        RISK_RULE_ID,
    ]
    refused = selection.fit_rules[0]
    assert refused.passed is False and refused.field == DOMAIN_FIELD
    assert selection.outcome is not None
    assert TOPIC_RULE_ID in (selection.outcome.reason or "")


def test_s10_and_s11_receive_the_production_destination_rules():
    """The plan is adapted to, and checked against, the rules on disk.

    Both stages are called for real. What the assertions look at is the object
    they received: the plan's own constraints cite `K-DST-LI-01`, which is a
    record under `knowledge/records/dst/`, and the length it carries is that
    record's 250–400 rather than any fixture's.
    """

    production = destination_rules(
        Destination.LINKEDIN, register=REGISTER, contract=CONTRACT
    )
    contract = _contract(hashtags=("#NeverBlank",))

    _, plan, decision = _checked(rules=production, contract=contract)

    assert plan.length_target == LengthTarget(
        minimum=250, maximum=400, unit=LengthUnit.WORDS
    )
    assert plan.format is PlanFormat.POST
    cited = {constraint.rule_ref for constraint in plan.constraints}
    assert "K-DST-LI-01" in cited
    for rule_ref in cited:
        if rule_ref.startswith("K-DST-"):
            assert (DESTINATION_RECORDS / f"{rule_ref}.md").is_file(), rule_ref
    # The client's own hashtag rule reached the plan at the contract's tier.
    assert production.hashtag_rule.tier is KnowledgeTier.APPROVED_CLIENT_RULE
    assert decision.verdict is not None


def test_the_fixture_rules_and_the_production_rules_are_not_the_same_thing():
    """The mutation guard for the test above: a fixture would carry 80–220."""

    fixture = _rules()
    production = destination_rules(
        Destination.LINKEDIN, register=REGISTER, contract=CONTRACT
    )

    assert fixture.length != production.length
    assert fixture.hashtags is not production.hashtags


# ── 9 · the stage-side change is exactly the carve-out ─────────────────────


def test_a_tier_2_rule_never_ends_a_destination_however_absolute_it_reads():
    """V-P04 ends a destination on a tier-1 *platform* rule and nothing else."""

    from src.editorial_core.plan_check import _ends_it

    client = ClientRule(
        rule_id="NB-DST-ABSOLUTE",
        text="This client never publishes anything at all, under any condition.",
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        compliant_variant=False,
    )
    assert _ends_it(client) is False

    hard = PlatformRule(
        rule_id="K-DST-WIX-03",
        text="Scaled unoriginal content is sanctioned.",
        tier=KnowledgeTier.HARD_PLATFORM_POLICY,
        compliant_variant=False,
    )
    assert _ends_it(hard) is True


def test_two_records_of_equal_rank_on_one_field_refuse(tmp_path):
    """Equal authority fixing one field fixes neither, and it fails loudly.

    Never Blank declares no competing pair — both places where one could have
    arisen were resolved by declining to write the client rule — so the
    field-aware precedence path is real machinery with no live input in this
    configuration. That is expected rather than dead code, and this is the
    constructed input that exercises it: a second tier-4 LinkedIn record
    fixing the format `K-DST-LI-01` already fixes.
    """

    register = tmp_path / "knowledge"
    _copy_register(register)
    (register / "records" / "dst" / "K-DST-LI-04.md").write_text(
        _RIVAL_RECORD, encoding="utf-8"
    )

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(
            Destination.LINKEDIN, register=register, contract=CONTRACT
        )

    message = str(raised.value)
    assert "K-DST-LI-01" in message and "K-DST-LI-04" in message
    assert "same authority" in message


def test_a_lapsed_record_does_not_break_a_tie_inside_its_tier(tmp_path):
    """Review freshness is not a second precedence dimension (#363 repair).

    `_authority()` briefly returned `(tier_rank, 1 if weak else 0)`, which made
    a current rule outrank a lapsed one at the same tier. That is an ordering
    #363 does not authorize: `tier_rank()` is the only one, and equal rank on
    one field fails closed. The defect was invisible from the outside — the
    field still resolved, to the fresher rule — so the regression is the pair
    that must refuse rather than resolve.

    Reverting the repair makes `destination_rules()` return LinkedIn's format
    from `K-DST-LI-01` and this test fails on the missing refusal.
    """

    register = tmp_path / "knowledge"
    _copy_register(register)
    (register / "records" / "dst" / "K-DST-LI-05.md").write_text(
        _LAPSED_RIVAL_RECORD, encoding="utf-8"
    )

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(
            Destination.LINKEDIN, register=register, contract=CONTRACT
        )

    message = str(raised.value)
    assert "K-DST-LI-01" in message and "K-DST-LI-05" in message
    assert "same authority" in message


def test_two_client_rows_fixing_one_field_refuse(tmp_path):
    """The contract's own half of the same rule, refused where the field is known."""

    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    text = path.read_text(encoding="utf-8")
    row = next(
        line for line in text.splitlines() if line.startswith("| NB-DST-TG-LENGTH ")
    )
    twin = row.replace("NB-DST-TG-LENGTH", "NB-DST-TG-LENGTH-2").replace(
        "180–300", "200–320"
    )
    path.write_text(text.replace(row, f"{row}\n{twin}"), encoding="utf-8")

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(Destination.TELEGRAM, register=REGISTER, contract=path)

    message = str(raised.value)
    assert "NB-DST-TG-LENGTH" in message and "NB-DST-TG-LENGTH-2" in message


def test_a_stronger_rule_wins_the_field_and_the_loser_is_kept(tmp_path):
    """tier 1 > tier 2 > tier 4 by the existing ladder, and nothing is dropped.

    The loser stays in `other_rules` rather than being merged away, so the
    trace shows both rules and which one governed.
    """

    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    text = path.read_text(encoding="utf-8")
    row = next(
        line for line in text.splitlines() if line.startswith("| NB-DST-TG-FORMAT ")
    )
    # A client rule fixing LinkedIn's format, which `K-DST-LI-01` fixes at
    # tier 4: the approved client rule outranks reach advice.
    rival = (
        "| NB-DST-LI-FORMAT | linkedin | E-14.format | article | "
        "This client writes LinkedIn as an article. |"
    )
    path.write_text(text.replace(row, f"{row}\n{rival}"), encoding="utf-8")

    rules = destination_rules(
        Destination.LINKEDIN, register=REGISTER, contract=path
    )

    assert rules.format is PlanFormat.ARTICLE
    assert rules.format_rule.rule_id == "NB-DST-LI-FORMAT"
    assert rules.format_rule.tier is KnowledgeTier.APPROVED_CLIENT_RULE
    # The record that lost the format still fixed the length, and is still here.
    assert "K-DST-LI-01" in {rule.rule_id for rule in rules.rules}
    assert rules.length_rule.rule_id == "K-DST-LI-01"


def test_destination_rules_still_only_refuses_one_id_naming_two_rules():
    """`__post_init__` gained nothing, and the one check it had still holds.

    Precedence is field-aware, and only the producer still knows which field a
    rule competed for: once a losing rule sits in `other_rules` that provenance
    is gone. So the equal-rank refusal lives there, and this type keeps exactly
    the check it can still make on its own.
    """

    from src.editorial_core import executable_plan

    with pytest.raises(PlanError):
        executable_plan.DestinationRules(
            destination=Destination.WIX,
            format=PlanFormat.ARTICLE,
            format_rule=PlatformRule(
                rule_id="K-DST-WIX-02",
                text="one",
                tier=KnowledgeTier.PLATFORM_RANKING,
            ),
            length=LengthTarget(minimum=1, maximum=2, unit=LengthUnit.WORDS),
            length_rule=PlatformRule(
                rule_id="K-DST-WIX-02",
                text="another",
                tier=KnowledgeTier.PLATFORM_RANKING,
            ),
            hashtags=HashtagPolicy.FORBIDDEN,
            hashtag_rule=ClientRule(
                rule_id="NB-DST-WIX-HASHTAGS",
                text="no tags",
                tier=KnowledgeTier.APPROVED_CLIENT_RULE,
            ),
        )


# ── the unbound records, and the keeper question they are ──────────────────


def test_the_meta_records_without_a_binding_reach_no_destination():
    """A destination is never inferred from a record's prefix."""

    catalogue = rule_catalogue(register=REGISTER, contract=CONTRACT)

    assert "K-DST-META-02" in catalogue.unbound
    assert "K-DST-META-03" in catalogue.unbound
    named = {item.rule.rule_id for item in catalogue.bound}
    assert "K-DST-META-02" not in named
    assert "K-DST-META-03" not in named
    # The one that *is* bound is bound because the map's own row names it.
    instagram = {
        item.rule.rule_id
        for item in catalogue.for_destination(Destination.INSTAGRAM)
    }
    assert "K-DST-META-01" in instagram

    readme = (REGISTER / "README.md").read_text(encoding="utf-8")
    assert "open keeper question" in readme


def test_a_malformed_fixes_clause_raises_rather_than_being_interpolated(tmp_path):
    """Risk 1: a parser that guessed would produce a wrong value silently."""

    register = tmp_path / "knowledge"
    _copy_register(register)
    record = register / "records" / "dst" / "K-DST-LI-01.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "[fixes: 250–400 words]", "[fixes: about 250 words or so]"
        ),
        encoding="utf-8",
    )

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(
            Destination.LINKEDIN, register=register, contract=CONTRACT
        )

    assert "a length target is a range and a unit" in str(raised.value)


def test_a_contract_with_no_destination_rules_section_raises(tmp_path):
    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"## {CONTRACT_SECTION}", "## Something else"
        ),
        encoding="utf-8",
    )

    with pytest.raises(DestinationRulesError) as raised:
        destination_rules(Destination.WIX, register=REGISTER, contract=path)

    assert CONTRACT_SECTION in str(raised.value)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


#: A second tier-4 LinkedIn record fixing the format `K-DST-LI-01` fixes. It
#: exists only inside a copied register, for the one test that needs two equal
#: authorities on one field — which Never Blank's own configuration has none of.
_LAPSED_RIVAL_RECORD = """---
id: K-DST-LI-05
version: 1
status: descriptive
tier: 4
evidence_class: VEND
confidence: low
verified_on: 2024-01-10
review_by: 2024-06-30
---

# A constructed rival to K-DST-LI-01 whose review has lapsed

## Statement
A fixture record at the same tier as `K-DST-LI-01`, with a `review_by` in the
past so the loader demotes it. It exists to prove that being stale does not
make it lose a field it has equal authority over.

## Applies when
destination is linkedin

## Influences
- S-10 · `E-14.format` — the article as the form. [fixes: article]

## Conflicts
It disagrees with `K-DST-LI-01` on purpose, at the same tier.

## Source
Written by `tests/test_363_configuration_producers.py`; never shipped.

## Change log
- v1, 2026-09-29: created as a test fixture (#363 repair).
"""


_RIVAL_RECORD = """---
id: K-DST-LI-04
version: 1
status: descriptive
tier: 4
evidence_class: VEND
confidence: low
verified_on: 2026-09-21
review_by: 2026-12-20
---

# A constructed rival to K-DST-LI-01, for the equal-rank refusal

## Statement
A fixture record. It exists to give one field two authorities of equal rank, so
that the refusal that follows can be exercised on something other than prose.

## Applies when
destination is linkedin

## Influences
- S-10 · `E-14.format` — the article as the form. [fixes: article]

## Conflicts
It disagrees with `K-DST-LI-01` on purpose, at the same tier.

## Source
Written by `tests/test_363_configuration_producers.py`; never shipped.

## Change log
- v1, 2026-09-29: created as a test fixture (#363).
"""


class _UncalledTransport:
    """A source-eligibility transport the fit rules never get past."""

    def complete(self, *, instructions: str, request: str) -> str:
        raise AssertionError(
            "the fit rules refused the signal, so no judgment was to be paid for"
        )


def _copy_register(destination: Path) -> None:
    """The real register, copied so a test may break one record in it."""

    for path in sorted(REGISTER.rglob("*")):
        if not path.is_file():
            continue
        target = destination / path.relative_to(REGISTER)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
