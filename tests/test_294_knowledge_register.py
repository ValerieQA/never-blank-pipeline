"""Issue #294: the knowledge register format, its vocabularies and its validator.

Step 4 §8 gives the register a validator and gives it one job: a person edits these
files by hand, so a hand edit must not be able to break a run quietly. The evidence
that it does that job is a corpus:

- **`tests/fixtures/knowledge_register/valid/`** — a record, a destination record, a
  probe family, a hard check, a soft check and a client ladder, laid over the
  repository's own register. All accepted.
- **`tests/fixtures/knowledge_register/invalid/rule_NN_…/`** — one file per rule of
  §8, each dropped into that same accepted register, each carrying exactly one
  defect. All rejected, each by its own rule and by no other.

The corpus is the test's data, not its code: a new rule is a new directory, and
`test_the_corpus_covers_every_numbered_rule` fails until one exists.

Running the CI script over the repository's real register is what puts all of this
in CI (`scripts/ci/check_knowledge_register.py`).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

import pytest
import yaml

from scripts.ci.check_knowledge_register import (
    DEFAULT_BASELINE_REF,
    EXIT_NO_BASELINE,
    build_baseline,
    client_rule_paths,
    main,
)
from src.knowledge.grammar import (
    Always,
    And,
    Atom,
    ConditionError,
    Or,
    parse_condition,
)
from src.knowledge.ladder import (
    CLIENT_LADDER_SLOT,
    UNIVERSAL_TOP_LEVEL,
    client_ladder_problems,
    level_names,
)
from src.knowledge.markdown import load_document
from src.knowledge.validator import (
    KR_APPROVAL,
    KR_CLIENT_LADDER,
    KR_CONDITION,
    KR_STRUCTURE,
    RULES,
    RecordBaseline,
    validate_register,
)
from src.knowledge.vocabulary import VocabularyError, load_vocabularies
from src.strategy.client_contracts import PLAN_SCALAR_SLOTS, load_stream_contract

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The register the repository ships, which CI validates on every change.
REGISTER = _REPO_ROOT / "knowledge"
CLIENTS = _REPO_ROOT / "clients"

CORPUS = _REPO_ROOT / "tests" / "fixtures" / "knowledge_register"
VALID = CORPUS / "valid"
INVALID = CORPUS / "invalid"

VOCABULARIES = load_vocabularies(REGISTER)


class Built(NamedTuple):
    """One assembled register, with the client rule files that go with it."""

    register: Path
    #: The directory to hand `--clients`, whose `*/streams/*.md` are the rule files.
    clients_root: Path
    client_paths: tuple[Path, ...]


def build_register(root: Path, overlay: Optional[Path] = None) -> Built:
    """The repository's register plus the valid corpus, then `overlay` over both.

    The valid corpus is deliberately laid over the **real** vocabularies and the
    **real** universal ladder rather than over copies of them: a fixture register
    with its own vocabularies would go on passing after the shipped ones stopped
    agreeing with the code that reads them.
    """

    register = root / "register"
    clients_root = root / "clients"
    client = clients_root / "client"
    shutil.copytree(REGISTER, register)
    shutil.copytree(VALID / "register", register, dirs_exist_ok=True)
    shutil.copytree(VALID / "client", client)
    if overlay is not None:
        for name, destination in (("register", register), ("client", client)):
            source = overlay / name
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
    return Built(
        register=register,
        clients_root=clients_root,
        client_paths=tuple(sorted((client / "streams").glob("*.md"))),
    )


def baseline_of(register: Path) -> dict[str, RecordBaseline]:
    """Every identified record of a register, as rule 7's second half reads it."""

    baseline: dict[str, RecordBaseline] = {}
    for path in (
        *sorted((register / "records").rglob("*.md")),
        *sorted((register / "ladders").glob("*.md")),
        *sorted((register / "checks").glob("*.md")),
    ):
        document = load_document(path)
        identity = document.field("id") or ""
        version = document.field("version") or ""
        baseline[identity] = RecordBaseline(
            version=int(version),
            version_surface_digest=document.version_surface_digest(),
        )
    return baseline


#: The one case only a caller with history can catch: rule 7's version half needs
#: the tree as it was. The CI script reads that from git, and a register assembled
#: in a temporary directory is in no git tree; the run-start gate does not read it
#: at all, because at run start there is no earlier tree.
CASES_NEEDING_A_BASELINE = frozenset({"rule_07_version_did_not_increase"})


def invalid_cases() -> list[Path]:
    """Every `rule_NN_…` directory of the corpus, one defect each."""

    return sorted(path for path in INVALID.iterdir() if path.is_dir())


def _rule_of(case: Path) -> str:
    """`rule_04_condition_uses_a_label` → `KR-04`."""

    return f"KR-{case.name.split('_')[1]}"


# ----------------------------------------------------------------------
# The register this repository ships
# ----------------------------------------------------------------------


def test_the_shipped_register_is_valid():
    findings = validate_register(
        REGISTER, client_rule_paths=client_rule_paths(CLIENTS)
    )
    assert [finding.render() for finding in findings] == []


def test_the_ci_script_accepts_the_shipped_register():
    # `--no-baseline` on purpose: this asserts the shipped tree satisfies the
    # rules, and rule 7's version-increase half needs an earlier tree, which a
    # working tree is not. Saying so is the point — it used to be the silent
    # default (#328 review). The half itself is proven against a real git
    # baseline below.
    assert (
        main(
            ["--register", str(REGISTER), "--clients", str(CLIENTS), "--no-baseline"]
        )
        == 0
    )


def test_the_shipped_vocabularies_mirror_the_code_that_reads_them():
    # Nothing to assert beyond loading: `load_vocabularies` refuses a register
    # whose stages or destinations have drifted from the registry and the
    # authorization boundary they mirror. It loaded at import time, so they agree.
    assert VOCABULARIES.get("stages").names[0] == "S-00"
    assert "wix" in VOCABULARIES.get("destinations").names


# ----------------------------------------------------------------------
# Acceptance evidence 1 and 2: the corpora
# ----------------------------------------------------------------------


def test_the_valid_corpus_is_accepted(tmp_path):
    built = build_register(tmp_path)
    findings = validate_register(
        built.register,
        client_rule_paths=built.client_paths,
        baseline=baseline_of(built.register),
    )
    assert [finding.render() for finding in findings] == []


@pytest.mark.parametrize("case", invalid_cases(), ids=lambda path: path.name)
def test_each_invalid_file_is_rejected_by_its_own_rule(case, tmp_path):
    baseline = baseline_of(build_register(tmp_path / "base").register)
    built = build_register(tmp_path / "case", overlay=case)

    findings = validate_register(
        built.register, client_rule_paths=built.client_paths, baseline=baseline
    )

    assert findings, f"{case.name} was accepted"
    # Its own rule and no other: a fixture that tripped two rules would prove
    # neither of them.
    assert {finding.rule for finding in findings} == {_rule_of(case)}


@pytest.mark.parametrize(
    "case",
    [case for case in invalid_cases() if case.name not in CASES_NEEDING_A_BASELINE],
    ids=lambda path: path.name,
)
def test_the_ci_script_refuses_each_invalid_file(case, tmp_path):
    built = build_register(tmp_path, overlay=case)
    assert (
        main(
            [
                "--register",
                str(built.register),
                "--clients",
                str(built.clients_root),
                "--no-baseline",
            ]
        )
        == 1
    )


def test_the_corpus_covers_every_numbered_rule():
    numbered = {rule for rule, _ in RULES} - {KR_STRUCTURE}
    assert {_rule_of(case) for case in invalid_cases()} == numbered


def test_a_file_that_is_not_a_record_at_all_is_refused(tmp_path):
    built = build_register(tmp_path)
    broken = built.register / "records" / "mat" / "K-MAT-02.md"
    broken.write_text(
        broken.read_text(encoding="utf-8").replace(
            "status: descriptive", "status: descriptive\nstatus: candidate", 1
        ),
        encoding="utf-8",
    )

    findings = validate_register(built.register, client_rule_paths=built.client_paths)

    assert [finding.rule for finding in findings] == [KR_STRUCTURE]
    assert "set twice" in findings[0].message


def test_a_vocabulary_that_has_drifted_from_the_code_refuses_the_register(tmp_path):
    built = build_register(tmp_path)
    stages = built.register / "vocab" / "stages.md"
    stages.write_text(
        "\n".join(
            line
            for line in stages.read_text(encoding="utf-8").splitlines()
            if not line.startswith("- `S-15`")
        ),
        encoding="utf-8",
    )

    findings = validate_register(built.register)

    assert [finding.rule for finding in findings] == [KR_STRUCTURE]
    assert "S-15" in findings[0].message


def test_a_register_that_is_not_there_is_refused(tmp_path):
    findings = validate_register(tmp_path / "nothing-here")
    assert [finding.rule for finding in findings] == [KR_STRUCTURE]


# ----------------------------------------------------------------------
# Rule 3's other two arms (Q5, I-12, I-13)
# ----------------------------------------------------------------------

# The corpus proves rule 3 through an invariant nobody approved, which is one of
# its three arms. The other two are the two invariants this issue must preserve,
# and each is one edit to an already accepted check away.


def test_a_threshold_on_a_soft_check_needs_an_owner(tmp_path):
    """I-12: a soft signal acts on a number only where an owner approved one."""

    built = build_register(tmp_path)
    check = built.register / "checks" / "V-S10.md"
    check.write_text(
        check.read_text(encoding="utf-8").replace(
            "threshold: none", "threshold: 0.7", 1
        ),
        encoding="utf-8",
    )

    findings = validate_register(built.register, client_rule_paths=built.client_paths)

    assert [finding.rule for finding in findings] == [KR_APPROVAL]
    assert "I-12" in findings[0].message


def test_a_hard_check_drawn_from_research_needs_an_owner(tmp_path):
    """I-13: a research finding does not become a hard check on its own."""

    built = build_register(tmp_path)
    check = built.register / "checks" / "V-T01.md"
    # `approved-rule` rather than the invariant it is, so the one thing missing
    # approval is the research-sourced hard check itself.
    check.write_text(
        check.read_text(encoding="utf-8")
        .replace("rule_status: invariant", "rule_status: approved-rule", 1)
        .replace("evidence_class: REPO", "evidence_class: RES", 1)
        .replace("approved_by: owner, 2026-09-21 (I-03, Step 2 S-13)\n", "", 1),
        encoding="utf-8",
    )

    findings = validate_register(built.register, client_rule_paths=built.client_paths)

    assert [finding.rule for finding in findings] == [KR_APPROVAL]
    assert "I-13" in findings[0].message


# ----------------------------------------------------------------------
# Rule 7's second half, and the baseline it needs
# ----------------------------------------------------------------------


def test_an_unchanged_record_at_the_same_version_is_accepted(tmp_path):
    built = build_register(tmp_path)
    findings = validate_register(
        built.register,
        client_rule_paths=built.client_paths,
        baseline=baseline_of(built.register),
    )
    assert findings == ()


def test_a_check_may_reach_a_second_version(tmp_path):
    """A check's lineage is its change log: §3 gives it no `supersedes` to fill."""

    built = build_register(tmp_path)
    check = built.register / "checks" / "V-S10.md"
    check.write_text(
        check.read_text(encoding="utf-8")
        .replace("version: 1", "version: 2", 1)
        .replace(
            "## Change log\n",
            "## Change log\n- v2, 2026-09-22: the criterion was reworded.\n",
            1,
        ),
        encoding="utf-8",
    )

    findings = validate_register(built.register, client_rule_paths=built.client_paths)

    assert [finding.render() for finding in findings] == []


def test_without_a_baseline_the_version_half_is_not_invented(tmp_path):
    """A changed body at the same version passes only because nothing compared it."""

    baseline = baseline_of(build_register(tmp_path / "base").register)
    case = INVALID / "rule_07_version_did_not_increase"
    built = build_register(tmp_path / "case", overlay=case)

    assert validate_register(built.register, client_rule_paths=built.client_paths) == ()
    assert validate_register(
        built.register, client_rule_paths=built.client_paths, baseline=baseline
    )


def test_a_baseline_ref_git_cannot_read_fails_closed(capsys):
    """It used to say so on stderr and exit 0.

    Which means the documented invocation enforced nine and a half of the ten
    rules while reporting that it enforced ten, and a record could change
    without its version moving (#328 review). An unreadable ref is now an
    error of its own, told apart from a register the rules refused.
    """

    assert build_baseline("no-such-ref-for-issue-294", REGISTER) is None
    assert (
        main(
            [
                "--register",
                str(REGISTER),
                "--clients",
                str(CLIENTS),
                "--baseline-ref",
                "no-such-ref-for-issue-294",
            ]
        )
        == EXIT_NO_BASELINE
    )
    # One read: capsys clears the buffer, and the second call used to see "".
    stderr = capsys.readouterr().err
    assert "cannot be read here" in stderr
    assert "--no-baseline" in stderr, "the error has to say what the way out is"


# ----------------------------------------------------------------------
# The `Applies when` grammar (§4)
# ----------------------------------------------------------------------


def _condition(line: str):
    return parse_condition(line, VOCABULARIES)


def test_always_is_a_condition_of_its_own():
    assert isinstance(_condition("always"), Always)


def test_always_cannot_be_joined_to_a_term():
    with pytest.raises(ConditionError, match="whole condition or none of it"):
        _condition("always and destination is wix")


def test_a_boundary_fact_can_be_present_or_counted():
    present = _condition("boundary has contested_assertion")
    assert isinstance(present, Atom)
    assert (present.name, present.minimum) == ("contested_assertion", None)

    counted = _condition("boundary has at least 2 admissible_interpretations")
    assert isinstance(counted, Atom)
    # The vocabulary declares the fact in the singular; a person counting them
    # writes the plural, and both spell the same term.
    assert (counted.name, counted.minimum) == ("admissible_interpretation", 2)


def test_a_fact_that_is_not_countable_cannot_be_counted():
    with pytest.raises(ConditionError, match="cannot be counted"):
        _condition("boundary has at least 2 contested_assertion")


def test_and_binds_tighter_than_or():
    condition = _condition(
        "destination is wix or destination is linkedin and format is post"
    )
    assert isinstance(condition, Or)
    assert len(condition.operands) == 2
    assert isinstance(condition.operands[1], And)


def test_parentheses_and_not_group_terms():
    condition = _condition(
        "feature documented_case is yes and not (destination is telegram)"
    )
    assert isinstance(condition, And)
    assert len(condition.atoms()) == 2


def test_a_value_the_vocabulary_does_not_declare_is_refused():
    with pytest.raises(ConditionError, match="figure_provenance"):
        _condition("feature figure_provenance is maybe")


def test_a_term_the_vocabulary_does_not_have_is_refused():
    with pytest.raises(ConditionError, match="ship together"):
        _condition("feature vibe is good")


def test_free_text_is_not_a_condition():
    with pytest.raises(ConditionError, match="not part of the condition grammar"):
        _condition("feature documented_case is yes; probably")


def test_a_label_is_refused_however_it_is_spelt():
    for spelling in (
        "material_label is Teardown",
        "Material Label is teardown",
        "strategy_label is Scene",
        "Frame and points is yes",
    ):
        with pytest.raises(ConditionError, match="I-10"):
            _condition(spelling)


def test_a_feature_that_merely_contains_a_label_word_is_not_a_label():
    # `Scene` is a path label; `real_scene` is a feature. The words have to stand
    # on their own for the label refusal to fire, or the grammar would lose a
    # term it needs.
    assert isinstance(_condition("feature real_scene is yes"), Atom)


def test_a_strategy_term_may_only_be_read_where_a_strategy_exists(tmp_path):
    built = build_register(tmp_path)
    (built.register / "records" / "mat" / "K-MAT-96.md").write_text(
        "\n".join(
            (
                "---",
                "id: K-MAT-96",
                "version: 1",
                "status: candidate",
                "tier: 3",
                "evidence_class: OBS",
                "confidence: low",
                "review_by: 2027-09-21",
                "---",
                "",
                "# A record reading a strategy before one is chosen",
                "",
                "## Statement",
                "It conditions on the reveal and influences S-04, where no",
                "strategy has been built yet.",
                "",
                "## Applies when",
                "strategy reveal is delayed",
                "",
                "## Influences",
                "- S-04 · `E-09.admissible` — which interpretations are admitted.",
                "",
                "## Conflicts",
                "None known.",
                "",
                "## Source",
                "A test for §4's restriction on strategy terms.",
                "",
                "## Change log",
                "- v1, 2026-09-21: written by the test.",
                "",
            )
        ),
        encoding="utf-8",
    )

    findings = validate_register(built.register, client_rule_paths=built.client_paths)

    assert [finding.rule for finding in findings] == [KR_CONDITION]
    assert "S-09" in findings[0].message


# ----------------------------------------------------------------------
# Ladders (§7)
# ----------------------------------------------------------------------


def test_the_engine_carries_the_level_a_person_reads():
    contract = load_stream_contract(VALID / "client" / "streams" / "weekly.md")

    assert CLIENT_LADDER_SLOT in PLAN_SCALAR_SLOTS
    assert contract.plan_values(CLIENT_LADDER_SLOT) == (
        "observed on one shop floor",
        "confirmed by the manufacturer",
        "established across the trade",
    )
    # The mapping is a declaration about the level, and the validator reads it
    # from the line as the keeper wrote it.
    declared = dict(contract.plan_slots)[CLIENT_LADDER_SLOT]
    assert declared[0].endswith("→ universal level 2")


def test_an_unannotated_ladder_passes_through_untouched():
    values = ("weak", "middling", "strong")
    assert level_names(values) == values


def test_a_sound_client_ladder_has_no_problems():
    assert (
        client_ladder_problems(
            ("observed once → universal level 2", "measured twice → universal level 3"),
            path="contract.md",
        )
        == ()
    )


@pytest.mark.parametrize(
    "values, expected",
    [
        (
            ("observed once → universal level 2", "measured twice"),
            "declares no universal level",
        ),
        (
            ("observed once → universal level 3", "measured twice → universal level 2"),
            "not above 3",
        ),
        (
            ("observed once → universal level 2", "measured twice → universal level 9"),
            "never reach past it",
        ),
        (
            ("said once → universal level 0", "observed once → universal level 1"),
            "starts at 1",
        ),
        (("observed once → universal level 2",), "at least 2"),
    ],
)
def test_a_client_ladder_the_validator_refuses(values, expected):
    problems = client_ladder_problems(values, path="contract.md")
    assert problems
    assert any(expected in problem for problem in problems)


def test_a_client_ladder_cannot_have_more_levels_than_the_universal_one():
    values = tuple(
        f"level {number} → universal level {number}"
        for number in range(1, UNIVERSAL_TOP_LEVEL + 2)
    )
    problems = client_ladder_problems(values, path="contract.md")
    assert any("never add one" in problem for problem in problems)


def test_the_universal_ladder_is_the_authority_a_client_is_measured_against(tmp_path):
    """Drop the ladder's top level, and a client level mapping to it is refused."""

    built = build_register(tmp_path)
    ladder = built.register / "ladders" / "default.md"
    ladder.write_text(
        "\n".join(
            line
            for line in ladder.read_text(encoding="utf-8").splitlines()
            if not line.startswith("| 4 |")
        ),
        encoding="utf-8",
    )

    findings = validate_register(built.register, client_rule_paths=built.client_paths)

    # The ladder itself is refused for disagreeing with the code that reads it,
    # and the client ladder is refused for reaching past what it now allows.
    assert {finding.rule for finding in findings} == {KR_STRUCTURE, KR_CLIENT_LADDER}


# ----------------------------------------------------------------------
# Vocabularies
# ----------------------------------------------------------------------


def test_a_vocabulary_declares_its_values_as_machine_tokens(tmp_path):
    path = tmp_path / "features.md"
    path.write_text(
        "---\nvocab_id: features\nversion: 1\n---\n\n# Features\n\n"
        "## Terms\n\n- `documented_case`: Yes indeed — prose\n",
        encoding="utf-8",
    )
    with pytest.raises(VocabularyError, match="machine tokens"):
        load_vocabularies(_register_with(tmp_path, path))


def _register_with(root: Path, replacement: Path) -> Path:
    """The shipped vocabularies with one file replaced."""

    register = root / "register"
    shutil.copytree(REGISTER, register)
    shutil.copy(replacement, register / "vocab" / replacement.name)
    return register


# ----------------------------------------------------------------------
# Rule 7's version-increase half, against a real git baseline (#328 review)
# ----------------------------------------------------------------------
#
# This half needs the tree as it was, so it was the one the CI script could
# silently skip: `--baseline-ref` defaulted to nothing, an unreadable ref also
# passed, and the corpus case for it was excluded from the CI-script test for
# want of a baseline. These build one in a real repository, so the negative and
# the positive are both proven rather than asserted about the code that would
# have done it.


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True, capture_output=True, text=True,
    )


def _committed_register(tmp_path: Path) -> Path:
    """A repository whose HEAD holds a valid register."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@e"),
                       ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    built = build_register(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the register as it was")
    return built.register


def _edit_body(record: Path) -> None:
    """Change the surface a version bump has to cover, and nothing else."""

    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "## Change log", "An extra sentence below the front matter.\n\n## Change log", 1
        ),
        encoding="utf-8",
    )


def test_a_changed_record_without_a_version_bump_is_refused(tmp_path, monkeypatch):
    register = _committed_register(tmp_path)
    _edit_body(register / "records" / "mat" / "K-MAT-02.md")
    monkeypatch.chdir(register.parent)

    assert main(["--register", str(register), "--baseline-ref", "HEAD"]) == 1


def test_the_same_change_passes_once_the_version_moves(tmp_path, monkeypatch):
    register = _committed_register(tmp_path)
    record = register / "records" / "mat" / "K-MAT-02.md"
    _edit_body(record)
    text = record.read_text(encoding="utf-8")
    version = int(re.search(r"^version: (\d+)$", text, re.M).group(1))
    # A material record at version 2 states what it supersedes; only check
    # records are exempt, because a check's lineage is its change log alone.
    text = text.replace(
        f"version: {version}",
        f"version: {version + 1}\nsupersedes: K-MAT-02 v{version}",
        1,
    )
    text = text.replace(
        "## Change log\n",
        f"## Change log\n- v{version + 1}, 2026-09-23: reworded the body.\n", 1,
    )
    record.write_text(text, encoding="utf-8")
    monkeypatch.chdir(register.parent)

    assert main(["--register", str(register), "--baseline-ref", "HEAD"]) == 0


def test_an_unchanged_register_passes_against_its_own_baseline(tmp_path, monkeypatch):
    """The half must be quiet when nothing moved, or it is not usable in CI."""

    register = _committed_register(tmp_path)
    monkeypatch.chdir(register.parent)

    assert main(["--register", str(register), "--baseline-ref", "HEAD"]) == 0


def test_the_baseline_is_required_unless_a_caller_says_otherwise(tmp_path, monkeypatch):
    """No baseline argument at all must not mean "skip rule 7 quietly"."""

    register = _committed_register(tmp_path)
    _edit_body(register / "records" / "mat" / "K-MAT-02.md")
    monkeypatch.chdir(register.parent)

    # The default ref does not exist in this throwaway repository, so the run
    # stops rather than reporting a register it did not fully check.
    assert DEFAULT_BASELINE_REF == "origin/main"
    assert main(["--register", str(register)]) == EXIT_NO_BASELINE


def test_only_an_explicit_no_baseline_skips_the_half(tmp_path, monkeypatch, capsys):
    register = _committed_register(tmp_path)
    _edit_body(register / "records" / "mat" / "K-MAT-02.md")
    monkeypatch.chdir(register.parent)

    # The unbumped change goes unnoticed — which is exactly why saying so out
    # loud is the only way to get here.
    assert main(["--register", str(register), "--no-baseline"]) == 0
    assert "NOT checked" in capsys.readouterr().err


def test_ci_runs_the_register_check_against_the_base_ref():
    """The enforcement lives in the workflow, so the workflow is the evidence.

    Everything above proves the script refuses what it should. This proves CI
    actually asks it, against a real base ref rather than the nothing a
    shallow checkout would give it.
    """

    workflow = yaml.safe_load(
        Path(".github/workflows/pr_tests.yml").read_text(encoding="utf-8")
    )
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]

    checkout = next(s for s in steps if "actions/checkout" in str(s.get("uses", "")))
    assert (checkout.get("with") or {}).get("fetch-depth") == 0, (
        "rule 7 needs the tree as it was; a shallow checkout has no base ref"
    )

    check = next(
        s for s in steps if "check_knowledge_register.py" in str(s.get("run", ""))
    )
    assert "--baseline-ref" in str(check["run"]), "the version half needs a baseline"
    assert "--no-baseline" not in str(check["run"]), "CI must not skip the half"
    assert (check.get("env") or {}).get("PYTHONPATH") == ".", (
        "a script run by path does not put the repository root on sys.path (#274)"
    )
