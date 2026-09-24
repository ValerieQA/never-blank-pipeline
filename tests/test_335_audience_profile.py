"""Issue #335: the Audience Profile — typed entity, client artifact, loading.

S-04 lists the Audience Profile among its required inputs, because
`E-08.reader_connection` says how the material connects to a reader and may be
empty only together with a `SKIP` (Step 1 E-08). Step 1 §295 also says what does
*not* reach the boundary: the client's right to speak, its lens and its
portfolio. So the profile is the one context that enters, and everything here
follows from that.

Four claims, each of which has to be able to fail:

- **The vocabulary is the authority, not the profile.** Never Blank's profile
  states every attribute `knowledge/vocab/audience_attributes.md` declares, each
  with a value from that attribute's own declared set. These tests read both
  from the vocabulary artifact rather than restating them, so they keep holding
  when the vocabulary is versioned.
- **It is configuration**, the way a Client Contract is: a document in the
  active client's directory, and the output of no stage.
- **A condition evaluates against it.** `audience <attribute> is <value>` is
  true exactly where the loaded profile says so, and false where it does not.
- **Nothing else is readable through it.** Positions, lenses and portfolio have
  no attribute to arrive under, and a profile that invents one is refused.

No network, no model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.knowledge.grammar import parse_condition
from src.knowledge.loader import StageInputs, applies
from src.knowledge.vocabulary import Vocabularies, Vocabulary, load_vocabularies
from src.strategy.audience_profile import (
    PROFILE_FILE,
    READING_STAGES,
    AudienceProfile,
    AudienceProfileError,
    audience_profile,
    load_audience_profile,
)
from src.strategy.client_contracts import DEFAULT_CLIENT_DIR

_REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTER = _REPO_ROOT / "knowledge"
NEVER_BLANK = _REPO_ROOT / DEFAULT_CLIENT_DIR


@pytest.fixture(scope="module")
def vocabularies() -> Vocabularies:
    return load_vocabularies(REGISTER)


@pytest.fixture(scope="module")
def attributes(vocabularies: Vocabularies) -> Vocabulary:
    return vocabularies.get("audience_attributes")


@pytest.fixture(scope="module")
def never_blank(attributes: Vocabulary) -> AudienceProfile:
    return load_audience_profile(NEVER_BLANK / PROFILE_FILE, attributes)


def _rows(attributes: Vocabulary) -> list[tuple[str, str, str]]:
    """A valid profile's rows, taken from the vocabulary itself."""

    return [(term.name, term.values[0], "a reason") for term in attributes.terms]


def _write(directory: Path, rows: list[tuple[str, str, str]], **front: str) -> Path:
    fields = {"profile_id": "fixture", "version": "1", **front}
    lines = [
        "---",
        *(f"{key}: {value}" for key, value in fields.items()),
        "---",
        "",
        "## Attributes",
        "",
        "| Attribute | Value | Why |",
        "|---|---|---|",
        *(f"| {name} | {value} | {why} |" for name, value, why in rows),
    ]
    path = directory / PROFILE_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── the client artifact, against the vocabulary that governs it ─────────────


def test_never_blanks_profile_states_every_declared_attribute(
    never_blank: AudienceProfile, attributes: Vocabulary
):
    """Every attribute the vocabulary declares, with a value from its own set.

    Both halves are read from `audience_attributes.md`: nothing here restates
    which attributes exist or what they may say.
    """
    assert attributes.terms, "the vocabulary declares no attributes to check"
    assert tuple(name for name, _ in never_blank.attributes) == attributes.names
    for name, value in never_blank.attributes:
        term = attributes.term(name)
        assert term is not None
        assert value in term.values

    assert never_blank.identity == "never-blank-audience/1"
    assert never_blank.digest.startswith("sha256:")


def test_a_profile_that_omits_a_declared_attribute_is_refused(
    attributes: Vocabulary, tmp_path
):
    path = _write(tmp_path, _rows(attributes)[1:])
    with pytest.raises(AudienceProfileError, match=attributes.terms[0].name):
        load_audience_profile(path, attributes)


def test_a_value_outside_the_declared_set_is_refused(attributes: Vocabulary, tmp_path):
    term = attributes.terms[0]
    rows = [
        (term.name, "whatever_the_client_liked", "a reason"),
        *_rows(attributes)[1:],
    ]
    path = _write(tmp_path, rows)
    with pytest.raises(AudienceProfileError, match=" / ".join(term.values)):
        load_audience_profile(path, attributes)


def test_a_value_stated_without_a_reason_is_refused(attributes: Vocabulary, tmp_path):
    rows = [(name, value, "") for name, value, _ in _rows(attributes)]
    path = _write(tmp_path, rows)
    with pytest.raises(AudienceProfileError, match="for no stated reason"):
        load_audience_profile(path, attributes)


def test_front_matter_is_the_identity_and_nothing_else(
    attributes: Vocabulary, tmp_path
):
    path = _write(tmp_path, _rows(attributes), english_level="native")
    with pytest.raises(AudienceProfileError, match="front matter has no field"):
        load_audience_profile(path, attributes)


# ── configuration, the way the Client Contract is ───────────────────────────


def test_the_profile_is_read_from_the_active_client_directory(
    attributes: Vocabulary, tmp_path, monkeypatch
):
    """Another client is another directory; no Engine code changes with it."""
    monkeypatch.delenv("NB_CLIENT_DIR", raising=False)
    loaded = audience_profile(REGISTER, directory=NEVER_BLANK)
    assert loaded.profile_id == "never-blank-audience"

    rows = [
        (term.name, term.values[-1], "the bakery reads it so")
        for term in attributes.terms
    ]
    _write(tmp_path, rows, profile_id="bakery-weekly-audience")
    monkeypatch.setenv("NB_CLIENT_DIR", str(tmp_path))
    replaced = audience_profile(REGISTER)

    assert replaced.profile_id == "bakery-weekly-audience"
    assert replaced.attributes == tuple(
        (term.name, term.values[-1]) for term in attributes.terms
    )


def test_a_client_without_a_profile_cannot_run(tmp_path):
    with pytest.raises(AudienceProfileError, match="has no Audience Profile"):
        audience_profile(REGISTER, directory=tmp_path)


# ── the condition the profile answers (Step 4 §4) ───────────────────────────


def test_an_audience_condition_evaluates_against_the_loaded_profile(
    never_blank: AudienceProfile, attributes: Vocabulary, vocabularies: Vocabularies
):
    """Every `audience <attribute> is <value>` the vocabulary permits, at S-04.

    True exactly where the profile says that value, false where it says another
    one — so a condition nobody could have got wrong is not what passes.
    """
    inputs = StageInputs(audience=never_blank.for_stage("S-04"))
    checked = 0
    for term in attributes.terms:
        for value in term.values:
            condition = parse_condition(
                f"audience {term.name} is {value}", vocabularies
            )
            expected = never_blank.value(term.name) == value
            assert applies(condition, inputs) is expected
            checked += 1
    assert checked > len(attributes.terms), "no attribute had an alternative value"


def test_only_the_stages_step_2_names_are_given_the_profile(
    never_blank: AudienceProfile
):
    assert READING_STAGES == ("S-04", "S-08")
    for stage in READING_STAGES:
        assert stage in CANONICAL_TOPOLOGY.stage_ids
        assert never_blank.for_stage(stage) == dict(never_blank.attributes)

    with pytest.raises(AudienceProfileError, match="is not given the Audience"):
        never_blank.for_stage("S-12")


# ── §295: the audience enters the boundary, and nothing else does ───────────


def test_no_other_client_context_is_readable_through_the_profile(
    never_blank: AudienceProfile, attributes: Vocabulary
):
    """The profile answers the vocabulary's attributes and holds nothing else.

    Never Blank's positions, its lenses and its portfolio memory are real
    documents in the same client directory; none of them is reachable from here,
    because the profile has nowhere to put them.
    """
    readable = never_blank.for_stage("S-04")
    assert set(readable) == set(attributes.names)
    for excluded in ("positions", "lens", "portfolio"):
        assert excluded not in readable
        with pytest.raises(AudienceProfileError, match="says nothing about"):
            never_blank.value(excluded)


def test_a_profile_that_smuggles_in_other_context_is_refused(
    attributes: Vocabulary, tmp_path
):
    for smuggled in ("client_positions", "lens", "portfolio"):
        rows = [*_rows(attributes), (smuggled, "yes", "we would like it at S-04")]
        path = _write(tmp_path, rows)
        with pytest.raises(AudienceProfileError, match="is not an audience attribute"):
            load_audience_profile(path, attributes)
