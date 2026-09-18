"""#254 / #240 D12: the Engine executes a client's human-readable contracts.

The Engine loads a client's stream contract and 0..N lenses and routes each to
the stages it names; it knows nothing about any client. These tests pin the
loader's contract, prove Never Blank's current Monday documents are the one
authority for what they cover, and run the owner's **Replace-the-client test**
as code: a materially different client, supplied only as documents, reaches the
same stages with no change to the Engine.

No network, no model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.editorial.editorial_role import (
    STREAM_OWNED_INTENT_PREFIX,
    EditorialRoleError,
    render_editorial_role_rules,
    resolve_editorial_role,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.client_contracts import (
    DEFAULT_CLIENT_DIR,
    ClientContractError,
    client_dir,
    contracts_for_role,
    load_lens,
    load_stream_contract,
)

MONDAY_ROLE = "never-blank-monday-documented-case"
NEVER_BLANK = DEFAULT_CLIENT_DIR

STREAM = """---
stream_id: s
version: "1"
role_id: r
selection: first_valid
---

# A title for people

Guidance for people.

## Purpose

The purpose, in
two lines.

## Selection

### Any group name the client likes

- First rule.
- Second rule that
  continues here.

### Another group

- Third rule.
"""

LENS = """---
lens_id: l
version: "1"
applies_to: [s]
stages: [selection, writing]
---

# A lens

Anything at all, delivered verbatim.
"""


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _configuration():
    return load_business_strategy_configuration(Path("strategy/current/business_strategy.json"))


# ── the stream contract ─────────────────────────────────────────────────────


def test_a_stream_contract_is_read_exactly(tmp_path):
    stream = load_stream_contract(_write(tmp_path, "streams/s.md", STREAM))

    assert stream.identity == "s/1"
    assert stream.role_id == "r"
    assert stream.purpose == "The purpose, in two lines."
    assert stream.requirements == ("First rule.", "Second rule that continues here.", "Third rule.")
    assert stream.digest.startswith("sha256:")


@pytest.mark.parametrize("mutation", [
    ("## Purpose", "## Aim"),
    ("## Selection", "## Signals"),
    ("## Purpose", "## Purpose\n\n## Extra"),
    ("# A title for people", "# A title for people\n\n### Stray"),
])
def test_an_unknown_missing_or_misplaced_heading_fails(tmp_path, mutation):
    """A typo stops the run instead of silently dropping a rule (#233 F-03)."""
    with pytest.raises(ClientContractError):
        load_stream_contract(_write(tmp_path, "streams/s.md", STREAM.replace(*mutation, 1)))


@pytest.mark.parametrize("mutation, message", [
    (("selection: first_valid\n", ""), "missing front-matter"),
    (("selection: first_valid", "selection: best_of_batch"), "not implemented"),
    (("role_id: r\n", "role_id: r\nclient: x\n"), "unknown front-matter"),
    (('version: "1"', "version: 1"), "non-empty string"),
])
def test_stream_front_matter_is_exact(tmp_path, mutation, message):
    with pytest.raises(ClientContractError, match=message):
        load_stream_contract(_write(tmp_path, "streams/s.md", STREAM.replace(*mutation, 1)))


def test_a_selection_line_that_is_not_a_rule_fails(tmp_path):
    text = STREAM.replace("- Third rule.", "Third rule without a bullet.")

    with pytest.raises(ClientContractError, match="must be a `###` group heading"):
        load_stream_contract(_write(tmp_path, "streams/s.md", text))


# ── the lens ────────────────────────────────────────────────────────────────


def test_a_lens_is_delivered_verbatim(tmp_path):
    lens = load_lens(_write(tmp_path, "lenses/l.md", LENS))

    assert lens.identity == "l/1"
    assert lens.stages == ("selection", "writing")
    assert lens.text == "# A lens\n\nAnything at all, delivered verbatim."


@pytest.mark.parametrize("mutation, message", [
    (("stages: [selection, writing]", "stages: [selection, marketing]"), "unknown stage"),
    (("stages: [selection, writing]", "stages: []"), "non-empty list"),
    (("applies_to: [s]", "applies_to: s"), "non-empty list"),
    (("stages: [selection, writing]", "stages: [writing, writing]"), "distinct"),
])
def test_lens_front_matter_is_exact(tmp_path, mutation, message):
    with pytest.raises(ClientContractError, match=message):
        load_lens(_write(tmp_path, "lenses/l.md", LENS.replace(*mutation, 1)))


# ── routing ─────────────────────────────────────────────────────────────────


def test_lenses_reach_exactly_the_stages_they_name(tmp_path):
    _write(tmp_path, "streams/s.md", STREAM)
    _write(tmp_path, "lenses/l.md", LENS)
    _write(tmp_path, "lenses/r.md", LENS.replace("lens_id: l", "lens_id: r")
           .replace("stages: [selection, writing]", "stages: [revision]")
           .replace("Anything at all", "Revision only"))

    contracts = contracts_for_role("r", tmp_path)

    assert contracts.selection_requirements[-1].endswith("Anything at all, delivered verbatim.")
    assert contracts.for_stage("writing") == ("# A lens\n\nAnything at all, delivered verbatim.",)
    assert contracts.for_stage("revision") == ("# A lens\n\nRevision only, delivered verbatim.",)


def test_a_lens_for_another_stream_is_not_applied(tmp_path):
    _write(tmp_path, "streams/s.md", STREAM)
    _write(tmp_path, "lenses/l.md", LENS.replace("applies_to: [s]", "applies_to: [other]"))

    contracts = contracts_for_role("r", tmp_path)

    assert contracts.lenses == ()
    assert contracts.selection_requirements == contracts.stream.requirements


def test_zero_lenses_is_valid(tmp_path):
    _write(tmp_path, "streams/s.md", STREAM)

    contracts = contracts_for_role("r", tmp_path)

    assert contracts.lenses == ()
    for stage in ("selection", "writing", "revision"):
        assert contracts.for_stage(stage) == ()


def test_a_client_that_supplies_nothing_is_valid(tmp_path):
    assert contracts_for_role("r", tmp_path) is None


@pytest.mark.parametrize("setup, message", [
    (lambda root: (_write(root, "streams/a.md", STREAM),
                   _write(root, "streams/b.md", STREAM.replace("stream_id: s", "stream_id: t"))),
     "more than one stream contract"),
    (lambda root: (_write(root, "streams/s.md", STREAM),
                   _write(root, "lenses/a.md", LENS), _write(root, "lenses/b.md", LENS)),
     "declared twice"),
    (lambda root: (_write(root, "streams/s.md", STREAM),
                   _write(root, "streams/broken.md", STREAM.replace("## Purpose", "## Aim"))),
     "headings"),
])
def test_ambiguity_or_breakage_anywhere_fails_the_run(tmp_path, setup, message):
    setup(tmp_path)

    with pytest.raises(ClientContractError, match=message):
        contracts_for_role("r", tmp_path)


def test_the_active_client_is_deployment_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("NB_CLIENT_DIR", raising=False)
    assert client_dir() == DEFAULT_CLIENT_DIR

    monkeypatch.setenv("NB_CLIENT_DIR", str(tmp_path))
    assert client_dir() == tmp_path


# ── Replace-the-client test (#240 D12 addendum), as code ────────────────────


def test_a_different_client_runs_through_the_same_engine_by_documents_alone(
    tmp_path, monkeypatch
):
    """A bakery-supply newsletter, supplied only as documents, reaches the same
    stages Never Blank's documents reach — topic, sourcing policy and revision
    method all changed, and no Engine code did."""
    _write(tmp_path, "streams/weekly.md", """---
stream_id: bakery-weekly
version: "3"
role_id: never-blank-monday-documented-case
selection: first_valid
---

## Purpose

Help independent bakers price flour and butter against seasonal swings.

## Selection

### Relevant

- The signal concerns ingredient prices, supply or kitchen equipment.
""")
    _write(tmp_path, "lenses/tone.md", """---
lens_id: bakery-tone
version: "1"
applies_to: [bakery-weekly]
stages: [writing, revision]
---

Warm, practical, never alarmist. No sourcing requirement.
""")
    monkeypatch.setenv("NB_CLIENT_DIR", str(tmp_path))

    _, role = resolve_editorial_role(_configuration(), MONDAY_ROLE)
    contracts = contracts_for_role(MONDAY_ROLE)
    rendered = render_editorial_role_rules(
        role, surface="wix", lenses=contracts.for_stage("writing")
    )

    assert role.intent == "Help independent bakers price flour and butter against seasonal swings."
    assert role.eligibility_criteria == (
        "The signal concerns ingredient prices, supply or kitchen equipment.",
    )
    assert "Warm, practical, never alarmist." in rendered
    assert contracts.for_stage("revision") == (
        "Warm, practical, never alarmist. No sourcing requirement.",
    )
    # nothing of the replaced client leaks through
    assert "small business" not in role.intent + " ".join(role.eligibility_criteria)
    assert "primary authority" not in rendered


# ── CLIENT: NEVER_BLANK's current documents ─────────────────────────────────


def test_never_blank_monday_is_governed_by_its_contract_and_two_lenses():
    contracts = contracts_for_role(MONDAY_ROLE, NEVER_BLANK)

    assert contracts.stream.identity == "never-blank-monday/1"
    assert contracts.stream.selection == "first_valid"
    assert sorted(lens.lens_id for lens in contracts.lenses) == [
        "never-blank-evidence", "never-blank-revision",
    ]


def test_never_blank_evidence_policy_is_a_client_lens_for_selection_and_writing():
    contracts = contracts_for_role(MONDAY_ROLE, NEVER_BLANK)
    evidence = next(l for l in contracts.lenses if l.lens_id == "never-blank-evidence")

    assert set(evidence.stages) == {"selection", "writing"}
    assert evidence.text in contracts.selection_requirements
    assert evidence.text in contracts.for_stage("writing")
    assert "primary authority" in evidence.text


def test_the_monday_role_takes_purpose_and_selection_from_the_client():
    contracts = contracts_for_role(MONDAY_ROLE, NEVER_BLANK)
    _, role = resolve_editorial_role(_configuration(), MONDAY_ROLE)

    assert role.intent == contracts.stream.purpose
    assert role.eligibility_criteria == contracts.selection_requirements


def test_the_json_copy_is_a_pointer_that_never_reaches_a_prompt():
    raw = json.loads(Path("strategy/current/business_strategy.json").read_text())
    monday = next(r for r in raw["editorial_roles"] if r["role_id"] == MONDAY_ROLE)
    _, role = resolve_editorial_role(_configuration(), MONDAY_ROLE)

    assert monday["intent"].startswith(STREAM_OWNED_INTENT_PREFIX)
    assert "eligibility_criteria" not in monday, "one authority per rule"
    assert monday["intent"] not in render_editorial_role_rules(role, surface="wix")


def test_a_pointer_without_its_contract_fails_closed(tmp_path):
    with pytest.raises(EditorialRoleError, match="no stream contract governs it"):
        resolve_editorial_role(_configuration(), MONDAY_ROLE, client_dir=tmp_path)


def test_a_role_the_client_does_not_govern_is_unchanged(tmp_path):
    configuration = _configuration()
    other = next(r for r in configuration.editorial_roles if r.role_id != MONDAY_ROLE)

    _, role = resolve_editorial_role(configuration, other.role_id, client_dir=tmp_path)

    assert role == other


def test_retired_historical_documents_are_not_registered_as_prompt_rules():
    """#240 D12: historical editorial documents are not current authority."""
    raw = json.loads(Path("strategy/current/business_strategy.json").read_text())
    registered = {r["path"] for r in raw["prompt_rule_references"]}

    for retired in ("config/brand_voice.md", "docs/PLATFORM_AND_VISUAL_STRATEGY.md",
                    "strategy/methodology/strategy_methodology.md",
                    "strategy/methodology/editorial_strategy.md",
                    "strategy/methodology/platform_strategy.md"):
        assert retired not in registered


def test_no_client_document_is_loaded_from_outside_the_client_directory():
    contracts = contracts_for_role(MONDAY_ROLE, NEVER_BLANK)
    paths = [contracts.stream.path, *(lens.path for lens in contracts.lenses)]

    assert all(Path(p).is_relative_to(NEVER_BLANK) for p in paths)


def test_a_note_for_people_is_never_delivered_to_a_model(tmp_path):
    _write(tmp_path, "streams/s.md", STREAM.replace(
        "## Purpose\n", "## Purpose\n\n<!-- Internal: ask Sveta before changing. -->\n"))
    _write(tmp_path, "lenses/l.md", LENS.replace(
        "# A lens", "<!-- Owner note, #999. -->\n\n# A lens"))

    contracts = contracts_for_role("r", tmp_path)

    delivered = contracts.stream.purpose + " ".join(contracts.for_stage("writing"))
    assert "Sveta" not in delivered and "#999" not in delivered
    assert contracts.for_stage("writing") == ("# A lens\n\nAnything at all, delivered verbatim.",)


def test_never_blank_notes_stay_with_people():
    contracts = contracts_for_role(MONDAY_ROLE, NEVER_BLANK)

    for text in (contracts.stream.purpose, *contracts.for_stage("selection"),
                 *contracts.for_stage("writing"), *contracts.for_stage("revision")):
        assert "<!--" not in text and "#240" not in text and "#254" not in text
