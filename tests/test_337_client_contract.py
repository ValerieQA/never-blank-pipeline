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
from src.publishing.release_scope import R1_PUBLISH_CHANNELS
from src.strategy.client_contract import (
    CONTRACT_FILE,
    ClientConfigurationError,
    client_contract,
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

    assert enabled == {item.value for item in Destination}
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
