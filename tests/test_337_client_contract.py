"""The Client Contract's configured inputs reach the stages that declare them.

Issue #337, slice SL-2. Three inputs the stage contracts name and nothing
loaded: S-07's enabled destinations, S-10's and S-12's voice brief, and the
``forbidden`` phrasing S-10 resolves into ``E-14``.

What these tests are for
------------------------
A file on disk is not an integration. Before this slice `config/brand_voice.md`
had **zero readers** in `src/` and the client's own forbidden list had a loader
and no consumer. So the tests that matter here run the whole chain —
**human-editable artifact → loader → typed runtime value → the stage that
declares it** — against the client's *real* configuration rather than a fixture,
and then prove the three things that must not be confused stay apart.

What is deliberately not proven here
------------------------------------
V-T06 end to end. Its record is `method: code+model`, and the model half plus the
finding it routes to S-12 on ``L_edit`` belong to S-13, which does not exist yet
(#307). What is proven is everything #337 can honestly supply: the typed
configuration, the deterministic phrase-matching seam, and the values S-13 will
consume. No test here claims a finished V-T06.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.destinations import Destination
from src.editorial_core.executable_plan import (
    AdaptationContract,
    ForbiddenItem,
    ForbiddenKind,
)
from src.knowledge.loader import load_register
from src.knowledge.vocabulary import load_vocabularies
from src.publishing.release_scope import R1_PUBLISH_CHANNELS
from src.editorial_core.destinations import (
    Eligibility,
    ExclusionRule,
    DestinationMode,
    ModeRule,
)
from src.strategy.client_contract import (
    CONTRACT_FILE,
    ClientConfigurationError,
    client_contract,
    contract_destinations,
    forbidden_from,
    load_voice_brief,
    voice_brief,
)
from src.strategy.client_contracts import load_shared_list

_REPO_ROOT = Path(__file__).resolve().parents[1]
NEVER_BLANK = _REPO_ROOT / "clients" / "never_blank"


@pytest.fixture(scope="module")
def contract():
    """The real client's contract, as a run would read it."""

    return client_contract(directory=NEVER_BLANK)


def _written(directory: Path, body: str, **fields: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    front = "".join(f"{name}: {value}\n" for name, value in fields.items())
    path = directory / CONTRACT_FILE
    path.write_text(f"---\n{front}---\n\n# Contract\n\n{body}", encoding="utf-8")
    return path


def _lists(directory: Path, *, list_id: str = "fixture-forbidden") -> Path:
    lists = directory / "lists"
    lists.mkdir(parents=True, exist_ok=True)
    (lists / "forbidden.md").write_text(
        f'---\nlist_id: {list_id}\nversion: "1"\napplies_to: [x]\n---\n\n'
        "# Forbidden\n\n- game changer\n- at the end of the day\n",
        encoding="utf-8",
    )
    return lists


# ── the chain runs on the client's real configuration ──────────────────────


def test_the_client_contract_is_a_loaded_input_and_not_a_file_on_disk(contract):
    """artifact → loader → typed value, with the identity of what was read."""

    assert contract.contract_id == "never-blank"
    assert contract.version
    assert contract.digest.startswith("sha256:")
    assert contract.enabled
    assert contract.forbidden


def test_the_voice_document_is_referenced_and_typed_not_embedded(contract):
    """S-12's input, from the artifact the contract points at (#337).

    The document stays human-editable prose where it is; what becomes typed is
    its identity and its text. `E-14.voice_brief_ref` is a reference to a
    *version*, which is why the artifact had to declare one.
    """

    brief = voice_brief(contract, root=_REPO_ROOT)

    assert brief.brief_ref == "never-blank-voice v1"
    assert "Never Blank" in brief.text
    # referenced, not copied into the contract
    assert brief.text not in Path(contract.path).read_text(encoding="utf-8")
    assert contract.voice_ref == "config/brand_voice.md"


def test_the_forbidden_list_reaches_s10_as_e14_forbidden_entries(contract):
    """S-10's input: every entry carries the rule that imposed it and its tier."""

    assert contract.forbidden
    for item in contract.forbidden:
        assert item.kind is ForbiddenKind.PHRASE
        assert item.tier is KnowledgeTier.APPROVED_CLIENT_RULE
        assert item.rule_ref.startswith("never-blank-machine-tells v")
        assert item.value.strip()

    # the value S-10 is handed, in the shape S-10 already accepts
    adaptation = AdaptationContract(
        voice_brief_ref=voice_brief(contract, root=_REPO_ROOT).brief_ref,
        forbidden=contract.forbidden,
    )
    assert adaptation.forbidden == contract.forbidden


def test_the_matching_seam_v_t06_will_use_is_deterministic(contract):
    """V-T06's code half. The model half needs S-13 (#307) and is not faked."""

    item = next(
        entry for entry in contract.phrases() if entry.value == "game changer"
    )

    assert item.matches("this is a GAME   CHANGER for us")
    assert not item.matches("this changes the game")


def test_only_phrases_are_matched_by_code(contract):
    """A construction type is not a string, so code does not pretend to match it.

    `ForbiddenItem.matches` says so itself, and V-T06 sends constructions to the
    model "however it is worded". The client's list is all phrases today, so the
    construction half is empty — an honest state, not a gap.
    """

    assert contract.phrases()
    assert contract.constructions() == ()
    assert len(contract.phrases()) == len(contract.forbidden)


# ── the stages that declare these inputs actually receive them ────────────


def test_s10_adapts_under_the_client_s_own_forbidden_list(contract):
    """Real S-10 consumption: the loaded entries reach `adapt_strategy`.

    Not a fixture contract — the plan is adapted under the 30 phrases this client
    actually authored, and the plan records them as the constraints it was built
    against.
    """

    from tests.test_305_executable_plan_and_check import _contract, _drafted

    adaptation = _contract(forbidden=contract.forbidden)
    _, decision = _drafted(contract=adaptation)

    assert decision.plan is not None
    assert decision.plan.forbidden == contract.forbidden
    assert len(decision.plan.forbidden) == 30


def test_s10_adapts_under_the_client_s_own_voice_document(contract):
    """Real S-10 consumption of the voice brief (#337 acceptance).

    The other half of the acceptance: the typed voice value has to reach S-10 as
    well as S-12. S-10 does not read the prose — the Writer does — but it records
    which voice the plan was adapted under, and that reference is what S-12 later
    refuses a mismatch against. So the value proven here is the *loaded* one, from
    `config/brand_voice.md` through `voice_brief()`, not a fixture default.

    S-10's interface already supports this; nothing in the stage changed.
    """

    from src.editorial_core.executable_plan import AdaptationContract
    from tests.test_305_executable_plan_and_check import _drafted

    brief = voice_brief(contract, root=_REPO_ROOT)
    adaptation = AdaptationContract(
        voice_brief_ref=brief.brief_ref, forbidden=contract.forbidden
    )
    _, decision = _drafted(contract=adaptation)

    assert decision.plan is not None
    assert decision.plan.voice_brief_ref == brief.brief_ref == "never-blank-voice v1"

    # the approved version carries it too, which is what S-12 compares against
    approved = decision.plan.approved_with(())
    assert approved.voice_brief_ref == brief.brief_ref


def test_s12_receives_the_loaded_brief_and_compares_it_with_the_plan(contract):
    """Real S-12 consumption: the loaded `VoiceBrief` reaches `write_prose`.

    S-12 compares the brief it is handed against `E-14.voice_brief_ref` before the
    call — "the plan was approved against one version of the voice, and writing
    against another is a voice nobody approved reaching prose". Handing it this
    client's real brief against a plan approved for a different voice version is
    refused, which is what proves the loaded value is the one being compared
    rather than something the stage ignores.
    """

    from src.editorial_core.writer import WriterError
    from tests.test_306_writer import _prose, _write, _Transport

    brief = voice_brief(contract, root=_REPO_ROOT)
    transport = _Transport(_prose())

    with pytest.raises(WriterError, match="never-blank-voice v1"):
        _write(transport=transport, brief=brief)

    # refused before the call, so nothing was paid for the comparison
    assert transport.calls == 0


def _permitted_destination_names() -> set[str]:
    """The permitted destination names, from the register's own vocabulary.

    `knowledge/vocab/destinations.md` is the authority (#337 acceptance): derived
    through `load_vocabularies`, never restated as a list in test code, so a
    surface added or renamed there is a surface these tests see.
    """

    return set(load_vocabularies(_REPO_ROOT / "knowledge").get("destinations").names)


def test_the_configured_destinations_come_from_the_register_vocabulary(contract):
    """#337 acceptance: the permitted names are the register's, not the enum's.

    The enum agreeing with the vocabulary is checked by the register validator's
    own mirror rule; what this asserts is the **client configuration** against the
    vocabulary that governs it, so a contract naming a surface the register does
    not define fails here rather than at the first run that meets it.
    """

    permitted = _permitted_destination_names()

    assert permitted
    assert {item.value for item in contract.enabled} <= permitted
    # nothing this client configured is outside the register's vocabulary
    assert not {item.value for item in contract.enabled} - permitted


def test_a_configured_destination_outside_the_vocabulary_is_refused(tmp_path: Path):
    """The same authority, from the failing side."""

    permitted = _permitted_destination_names()
    outside = "mastodon"
    assert outside not in permitted

    _lists(tmp_path)
    _written(
        tmp_path,
        f"## Enabled destinations\n\n- wix\n- {outside}\n",
        contract_id="c",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )

    with pytest.raises(ClientConfigurationError, match=outside):
        client_contract(directory=tmp_path)


def test_the_contract_reaches_s07_and_decides_all_six_destinations(contract):
    """Real S-07 consumption: `contract.md` → loader → producer → `decide_destinations`.

    The claim this slice makes, end to end and on the client's own file. Without
    the producer the chain stopped at a typed value S-07 does not accept.
    """

    from tests.test_303_anchor_and_destinations import _decided, _unit

    unit = _unit()
    decided = _decided(unit, contract=contract_destinations(contract))

    # every one of the six is decided, and none is reported as unknown
    assert [item.destination for item in decided.decisions] == list(Destination)
    assert decided.undeclared == ()
    for decision in decided.decisions:
        assert decision.eligibility is Eligibility.ELIGIBLE
        assert decision.rule_ref.startswith("never-blank-destination-")


def test_publish_versus_generate_only_comes_from_capability_and_rollout(contract):
    """Today's Wix/LinkedIn split is not the Client Contract's doing.

    All six are enabled by the client, so if the remaining four are
    `generate_only` that can only have come from capability and the rollout
    scope — which is the separation AD-02 §3 asks to be kept, made checkable.
    """

    from tests.test_303_anchor_and_destinations import _decided, _unit

    decided = _decided(_unit(), contract=contract_destinations(contract))
    modes = {item.destination: item for item in decided.decisions}

    publishing = {
        item.destination.value
        for item in decided.decisions
        if item.mode is DestinationMode.PUBLISH
    }
    assert publishing == {"wix", "linkedin"}

    for name in ("facebook", "instagram", "threads", "telegram"):
        decision = modes[Destination(name)]
        assert decision.mode is DestinationMode.GENERATE_ONLY
        # the reason is the engine's, never the contract's
        assert decision.mode_rule is not ModeRule.CONTRACT_GENERATE_ONLY

    # and the contract said yes to all six
    assert all(row.enabled for row in contract_destinations(contract).rows)


def test_a_destination_the_client_turned_off_is_disabled_not_undeclared(
    tmp_path: Path,
):
    """The collapse this producer exists to avoid.

    `ContractDestinations` keeps the two apart on purpose — the destinations it
    does not declare "are not excluded: they are unknown to the contract … so a
    reader can tell a destination the client turned off from one it never
    mentioned". A destination left out of the *enabled* list is the first of
    those: the client wrote a contract covering its surfaces and said no to this
    one. Dropping the row would report that choice as an oversight.
    """

    from tests.test_303_anchor_and_destinations import _decided, _unit

    _lists(tmp_path)
    _written(
        tmp_path,
        "## Enabled destinations\n\n- wix\n- linkedin\n",
        contract_id="partial",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )
    partial = client_contract(directory=tmp_path)
    rows = contract_destinations(partial)

    # still six rows: four of them switched off, none of them missing
    assert len(rows.rows) == len(list(Destination))
    off = {row.destination.value for row in rows.rows if not row.enabled}
    assert off == {"facebook", "instagram", "threads", "telegram"}

    decided = _decided(_unit(), contract=rows)
    assert decided.undeclared == ()
    excluded = {
        item.destination.value: item
        for item in decided.decisions
        if item.eligibility is Eligibility.EXCLUDED
    }
    assert set(excluded) == off
    for name, decision in excluded.items():
        assert decision.exclusion_rule is ExclusionRule.CONTRACT_DISABLED
        assert decision.rule_ref == f"partial-destination-{name} v1"


def test_every_row_cites_its_own_rule(contract):
    """§1 Post: one decision, one rule. Two rows sharing an ID name neither."""

    rows = contract_destinations(contract).rows
    ids = [row.rule_id for row in rows]

    assert len(set(ids)) == len(ids)
    assert all(row.rule_id.endswith(f"v{contract.version}") for row in rows)


# ── the three things that are not each other (AD-02 §3) ────────────────────


def test_enabled_destinations_are_not_the_rollout_scope(contract):
    """The distinction S-07 keeps, now provable from the client's own answer.

    Enabled is what the client switched on; the rollout scope is what today's
    deployment publishes. A destination enabled and outside the scope is
    `generate_only`, not an error — which is only checkable because the two sets
    differ.
    """

    enabled = {item.value for item in contract.enabled}
    rollout = set(R1_PUBLISH_CHANNELS)

    assert enabled == _permitted_destination_names()
    assert rollout < enabled
    assert enabled - rollout == {"facebook", "instagram", "threads", "telegram"}


def test_the_contract_reads_no_rollout_scope_and_decides_no_mode():
    """#337 supplies the client's half only (AD-02 §3)."""

    import ast

    tree = ast.parse(
        (_REPO_ROOT / "src" / "strategy" / "client_contract.py").read_text(
            encoding="utf-8"
        )
    )
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        name.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for name in node.names
    }
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert not any("release_scope" in item for item in imported)
    assert "R1_PUBLISH_CHANNELS" not in imported | names
    assert "DestinationMode" not in imported | names


def test_client_forbidden_wording_is_not_the_label_vocabulary(contract):
    """`KnowledgeBase.forbidden_terms` is a different mechanism entirely.

    It is the label vocabulary, which every S-00…S-13 stage declares forbidden to
    its own *requests* (Step 2 §0.7, AD-07) — an I-10 hygiene rule. Wiring it here
    would enforce no client prohibition and would push label vocabulary into an
    editorial constraint, while still passing a test that only checked that
    something was loaded.
    """

    knowledge = load_register(_REPO_ROOT / "knowledge")
    labels = {term.strip().lower() for term in knowledge.forbidden_terms}
    client = {item.value.strip().lower() for item in contract.forbidden}

    assert labels
    assert client
    assert labels.isdisjoint(client)


def test_the_legacy_engine_list_is_not_a_source_of_e14_forbidden(contract):
    """`config/machine_tells/shared.yaml` stays the pre-canonical path's.

    Every one of its entries is `tier: directional` — advisory, in the legacy
    machine-tells vocabulary — and tier 1 in the register means hard *platform*
    policy. It also holds regex patterns and lede moves, which are not phrases.
    So it is neither tier this contract resolves, and the OFF path keeps reading
    it untouched.
    """

    import yaml

    engine = yaml.safe_load(
        (_REPO_ROOT / "config" / "machine_tells" / "shared.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert {entry["tier"] for entry in engine["entries"]} == {"directional"}

    rules = {item.rule_ref for item in contract.forbidden}
    assert rules == {"never-blank-machine-tells v1"}
    assert not any(engine["list_id"] in rule for rule in rules)


# ── refusals: a configured input is missing, or is wrong ───────────────────


def test_a_client_with_no_contract_is_refused_and_does_not_degrade(tmp_path: Path):
    """A hard input: there is no honest default for what to write for."""

    with pytest.raises(ClientConfigurationError, match="no contract"):
        client_contract(directory=tmp_path)


def test_a_destination_the_engine_does_not_have_is_refused(tmp_path: Path):
    _lists(tmp_path)
    _written(
        tmp_path,
        "## Enabled destinations\n\n- wix\n- mastodon\n",
        contract_id="c",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )

    with pytest.raises(ClientConfigurationError, match="mastodon"):
        client_contract(directory=tmp_path)


def test_a_contract_enabling_nothing_is_refused(tmp_path: Path):
    _lists(tmp_path)
    _written(
        tmp_path,
        "## Enabled destinations\n\n",
        contract_id="c",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )

    with pytest.raises(ClientConfigurationError, match="enables no destination"):
        client_contract(directory=tmp_path)


def test_a_contract_naming_a_list_nobody_declares_is_refused(tmp_path: Path):
    _lists(tmp_path)
    _written(
        tmp_path,
        "## Enabled destinations\n\n- wix\n",
        contract_id="c",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="not-a-list",
    )

    with pytest.raises(ClientConfigurationError, match="not-a-list"):
        client_contract(directory=tmp_path)


def test_front_matter_the_contract_does_not_declare_is_refused(tmp_path: Path):
    _lists(tmp_path)
    _written(
        tmp_path,
        "## Enabled destinations\n\n- wix\n",
        contract_id="c",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="fixture-forbidden",
        rollout="wix",
    )

    with pytest.raises(ClientConfigurationError, match="no field rollout"):
        client_contract(directory=tmp_path)


def test_a_voice_document_without_a_version_cannot_be_referenced(tmp_path: Path):
    path = tmp_path / "voice.md"
    path.write_text(
        "---\nversion: 1\n---\n\n# A voice\n\nprose with no identity\n",
        encoding="utf-8",
    )

    with pytest.raises(ClientConfigurationError, match="voice_id"):
        load_voice_brief(path)


def test_a_referenced_voice_document_that_is_not_there_is_refused(
    contract, tmp_path: Path
):
    with pytest.raises(ClientConfigurationError, match="not"):
        voice_brief(contract, root=tmp_path)


def test_a_list_read_twice_under_one_id_is_refused(tmp_path: Path):
    lists = _lists(tmp_path)
    (lists / "second.md").write_text(
        '---\nlist_id: fixture-forbidden\nversion: "2"\napplies_to: [x]\n---\n\n'
        "# Forbidden\n\n- something else\n",
        encoding="utf-8",
    )
    _written(
        tmp_path,
        "## Enabled destinations\n\n- wix\n",
        contract_id="c",
        version="1",
        voice_ref="config/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )

    with pytest.raises(ClientConfigurationError, match="one `list_id` names one"):
        client_contract(directory=tmp_path)


def test_a_rule_ref_names_the_list_and_its_version_not_the_entry(tmp_path: Path):
    """V-P04's route is decided by the tier of the rule broken (§3)."""

    shared = load_shared_list(_lists(tmp_path) / "forbidden.md")
    items = forbidden_from(shared)

    assert items
    assert {item.rule_ref for item in items} == {"fixture-forbidden v1"}
    assert {item.value for item in items} == {"game changer", "at the end of the day"}


# ── the chain #337 could not prove until S-13 existed (#307) ───────────────


def _chain_fixtures(contract):
    """The producers, and an approved plan carrying them. One fixture family."""

    from src.editorial_core.executable_plan import AdaptationContract
    from tests.test_306_writer import _approved, _two_readings

    brief = voice_brief(contract, root=_REPO_ROOT)
    boundary = _two_readings()
    adaptation = AdaptationContract(
        voice_brief_ref=brief.brief_ref, forbidden=contract.forbidden
    )
    strategy, approved, verdict = _approved(boundary=boundary, contract=adaptation)
    return brief, boundary, strategy, approved, verdict


def _write_body(text_body, *, brief, boundary, strategy, approved, verdict):
    from tests.test_306_writer import (
        SEGMENT_NAMES,
        _barrier,
        _core as _core_306,
        _ledger,
        _prose,
        _Transport as _WriterTransport,
    )
    from src.editorial_core.writer import write_prose

    return write_prose(
        plan=approved,
        verdict=verdict,
        barrier=_barrier([approved], [verdict], boundary=boundary),
        strategy=strategy,
        boundary=boundary,
        core=_core_306(),
        brief=brief,
        counters=_ledger(),
        transport=_WriterTransport(
            _prose(
                parts=[
                    {"name": SEGMENT_NAMES[0], "text": text_body},
                    {"name": SEGMENT_NAMES[1], "text": "The wait is the cost."},
                ]
            )
        ),
    )


def _check(text, *, approved, boundary, forbidden, counters=None):
    from src.editorial_core.text_check import check_text, text_check_records
    from src.knowledge.loader import load_register
    from tests.test_306_writer import _core as _core_306, _ledger

    return check_text(
        text=text,
        plan=approved,
        boundary=boundary,
        core=_core_306(),
        forbidden=forbidden,
        checks=text_check_records(load_register(_REPO_ROOT / "knowledge")),
        counters=counters if counters is not None else _ledger(),
        transport=_TextTransport(),
    )


def test_the_client_contract_reaches_v_t06_and_routes_an_edit(contract):
    """The whole chain, on the client's real configuration.

    client config → `VoiceBrief` + `forbidden` + `AdaptationContract`
    → `write_prose` → `check_text` / V-T06 → `L_edit` → `revise_prose`

    This is the half of #337's acceptance that was impossible before #307: V-T06
    belongs to S-13, and S-13 did not exist. Nothing here is a fixture contract —
    the phrase the text trips over is one of the thirty this client actually
    authored, and the voice reference is the one its own document declares.
    """

    from src.editorial_core.plan_check import CheckOutcome
    from src.editorial_core.text_check import EDIT_COUNTER, TextResult, edit_scope_key
    from src.editorial_core.writer import revise_prose
    from tests.test_306_writer import (
        SEGMENT_NAMES,
        _barrier,
        _core as _core_306,
        _ledger,
        _prose,
        _Transport as _WriterTransport,
    )

    # 1 · the producers, from the client's own files
    brief, boundary, strategy, approved, verdict = _chain_fixtures(contract)
    forbidden = contract.phrases()
    assert forbidden and brief.brief_ref == "never-blank-voice v1"
    tripped = next(item for item in forbidden if item.value == "game changer")

    # 2 · the approved plan carries the real voice reference and the real rules
    assert approved.voice_brief_ref == brief.brief_ref
    assert tripped in approved.forbidden

    # 3 · S-12 writes prose that breaks the client's rule, under the real brief
    offending = f"This is a {tripped.value} for small operators."
    written = _write_body(
        offending, brief=brief, boundary=boundary, strategy=strategy,
        approved=approved, verdict=verdict,
    )
    text = written.text
    assert text is not None
    assert tripped.value in text.body
    assert text.inputs.voice_brief_ref == brief.brief_ref

    # 4 · S-13: V-T06 consumes the produced rules and fails on the real phrase
    counters = _ledger()
    decision = _check(
        text, approved=approved, boundary=boundary,
        forbidden=forbidden, counters=counters,
    )
    v_t06 = next(item for item in decision.verdict.checks if item.check_id == "V-T06")
    assert v_t06.result is CheckOutcome.FAIL
    # the finding cites the client's own rule, by its list and version
    assert any(finding.rule_ref == tripped.rule_ref for finding in v_t06.findings)

    # 5 · the route is L_edit, at the approved plan's key
    assert decision.verdict.result is TextResult.EDIT
    assert decision.verdict.counter == EDIT_COUNTER
    assert decision.verdict.outcome is not None
    assert decision.verdict.outcome.route_target == "S-12"
    assert decision.verdict.outcome.scope_key == edit_scope_key(approved.plan_ref)
    assert counters.used(EDIT_COUNTER, edit_scope_key(approved.plan_ref)) == 1

    # 6 · revise_prose: same approved plan, next version
    repaired = revise_prose(
        prior=text,
        findings=tuple(finding.detail for finding in v_t06.findings),
        plan=approved,
        verdict=verdict,
        barrier=_barrier([approved], [verdict], boundary=boundary),
        strategy=strategy,
        boundary=boundary,
        core=_core_306(),
        brief=brief,
        counters=_ledger(),
        transport=_WriterTransport(
            _prose(
                parts=[
                    {"name": SEGMENT_NAMES[0], "text": "A shift for small operators."},
                    {"name": SEGMENT_NAMES[1], "text": "The wait is the cost."},
                ]
            )
        ),
    )
    assert repaired.text is not None
    assert repaired.text.plan_ref == approved.plan_ref
    assert repaired.text.text_id == text.text_id
    assert repaired.text.version == text.version + 1
    assert repaired.text.supersedes == text.text_ref
    assert tripped.value not in repaired.text.body
    assert repaired.calls == 1


def test_a_phrase_this_client_does_not_forbid_does_not_route_an_edit(contract):
    """The other direction: V-T06 fires on the client's list, not on prose it dislikes."""

    from src.editorial_core.text_check import TextResult

    brief, boundary, strategy, approved, verdict = _chain_fixtures(contract)
    clean = "The settlement network is named in the filing."
    assert not any(item.matches(clean) for item in contract.phrases())

    written = _write_body(
        clean, brief=brief, boundary=boundary, strategy=strategy,
        approved=approved, verdict=verdict,
    )
    decision = _check(
        written.text, approved=approved, boundary=boundary,
        forbidden=contract.phrases(),
    )

    assert decision.verdict.result is TextResult.ACCEPTED


class _TextTransport:
    """Both S-13 model calls answering "nothing found"."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        import json

        self.calls += 1
        if self.calls == 1:
            return json.dumps({
                "v_t01": {"holds": True, "findings": []},
                "v_t02": {"holds": True, "findings": []},
                "v_t03": {"holds": True, "findings": []},
            })
        return json.dumps({
            "v_t06": {"holds": True, "findings": []},
            "v_t07": {"holds": True, "findings": []},
            "v_t08": {"holds": True, "findings": []},
        })


# ── the artifact on disk is what the stage receives ────────────────────────


def _voice_document(path: Path, *, version: int, text: str) -> None:
    """Write the referenced voice artifact, as a person editing it would."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nvoice_id: fixture-voice\nversion: {version}\n---\n\n"
        f"# A voice\n\n{text}\n",
        encoding="utf-8",
    )


def _received_voice(root: Path, client: Path):
    """Load through the production path and run S-12. Returns (ref, request).

    The request is what the stage was actually handed — `_request` puts the brief
    in as ``{"voice_brief": {"ref": ..., "text": ...}}`` — so asserting on it is
    asserting on the stage's input rather than on what the loader returned.
    """

    from src.editorial_core.executable_plan import AdaptationContract
    from src.editorial_core.writer import write_prose
    from tests.test_306_writer import (
        SEGMENT_NAMES,
        _approved,
        _barrier,
        _core as _core_306,
        _ledger,
        _prose,
        _Transport as _WriterTransport,
        _two_readings,
    )

    contract = client_contract(directory=client)
    brief = voice_brief(contract, root=root)

    boundary = _two_readings()
    strategy, approved, verdict = _approved(
        boundary=boundary,
        contract=AdaptationContract(
            voice_brief_ref=brief.brief_ref, forbidden=contract.forbidden
        ),
    )
    transport = _WriterTransport(
        _prose(
            parts=[
                {"name": SEGMENT_NAMES[0], "text": "The filing names the network."},
                {"name": SEGMENT_NAMES[1], "text": "The wait is the cost."},
            ]
        )
    )
    written = write_prose(
        plan=approved,
        verdict=verdict,
        barrier=_barrier([approved], [verdict], boundary=boundary),
        strategy=strategy,
        boundary=boundary,
        core=_core_306(),
        brief=brief,
        counters=_ledger(),
        transport=transport,
    )
    assert written.text is not None
    assert transport.requests, "the stage made no call, so it received nothing"
    return brief.brief_ref, transport.requests[0], written.text


def test_editing_the_voice_artifact_changes_what_the_stage_receives(tmp_path: Path):
    """#337's last acceptance item, and the only one a loader test cannot cover.

    The chain is only real if the **document on disk** is what the stage ends up
    with. A test that asserted on `voice_brief()`'s return value would pass with a
    loader that read the right file once and cached it, or with one whose value
    never left the producer — so this one edits the artifact between two runs and
    looks at what S-12 was handed, not at what the loader said.

    `_request` puts the brief into the call as
    ``{"voice_brief": {"ref": ..., "text": ...}}``, so the captured request is the
    stage's own input.
    """

    client = tmp_path / "client"
    voice = tmp_path / "voice" / "brand_voice.md"
    _lists(client)
    _written(
        client,
        "## Enabled destinations\n\n- wix\n- linkedin\n",
        contract_id="fixture",
        version="1",
        voice_ref="voice/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )

    first = "Plain sentences. Name the mechanism before the benefit."
    _voice_document(voice, version=1, text=first)
    ref_one, request_one, text_one = _received_voice(tmp_path, client)

    assert ref_one == "fixture-voice v1"
    assert first in request_one
    assert text_one.inputs.voice_brief_ref == "fixture-voice v1"

    # a person edits the referenced artifact: new wording, next version
    second = "Short lines. No metaphor, and no adjective that does no work."
    _voice_document(voice, version=2, text=second)

    ref_two, request_two, text_two = _received_voice(tmp_path, client)

    # the stage now receives the edited document
    assert ref_two == "fixture-voice v2"
    assert second in request_two
    # and the wording that was replaced is gone from the stage's input
    assert first not in request_two
    assert text_two.inputs.voice_brief_ref == "fixture-voice v2"

    # the two runs really were different inputs, not one cached value
    assert request_one != request_two
    assert ref_one != ref_two


def test_the_stage_receives_the_referenced_document_and_not_another(tmp_path: Path):
    """`voice_ref` selects the artifact: a second document beside it is not read."""

    client = tmp_path / "client"
    _lists(client)
    _written(
        client,
        "## Enabled destinations\n\n- wix\n",
        contract_id="fixture",
        version="1",
        voice_ref="voice/brand_voice.md",
        forbidden_ref="fixture-forbidden",
    )
    _voice_document(
        tmp_path / "voice" / "brand_voice.md", version=1, text="The referenced voice."
    )
    _voice_document(
        tmp_path / "voice" / "other_voice.md", version=9, text="The wrong voice entirely."
    )

    _, request, _ = _received_voice(tmp_path, client)

    assert "The referenced voice." in request
    assert "The wrong voice entirely." not in request
