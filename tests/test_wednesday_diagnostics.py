"""Issue #215: what the second Wednesday CONTROLLED_LIVE run exposed.

Run 33283836847 got further than any Wednesday run before it. July's selector
chose 11 of 30 candidates, ten were scored and enriched, Goodyear won, direct
retrieval succeeded, the evidence gate returned READY, and the whole restored
July pipeline produced a complete article across five surfaces.

Then it stopped at editorial acceptance with:

    editorial reviewer output contains unknown fields: verdict

Not an editorial rejection — an underspecified contract. The parser accepts
exactly four keys; Monday's rubric prints that JSON schema literally, and
Wednesday's said only *"Return only the strict JSON verdict required by the
existing editorial acceptance contract"*, which is what produced a key called
``verdict``.

And because the canonical ``generated.json`` is written long after the gate
that blocked it, the article the run had already produced was lost. A blocked
run is the one whose output most needs reading.

Two fixes, both narrow:

1. the Wednesday rubric states the canonical schema explicitly — the parser is
   **not** loosened and ``verdict`` still fails closed;
2. two diagnostic artifacts are written at the production seam **before**
   acceptance, marked so they can never be mistaken for product.

No paid calls and no network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.artifacts import (
    DIAGNOSTIC_MARKERS,
    ArtifactCollisionError,
    load_run_generated,
    write_generated_pre_acceptance_json,
    write_signal_snapshot_json,
)
from src.editorial.editorial_acceptance import (
    EditorialAcceptanceError,
    EditorialAcceptanceRubric,
)
from src.never_blank.wednesday_routing import WEDNESDAY_ROLE_ID
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_monday_stream import MONDAY_ROLE, WEDNESDAY_SUPPLY
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_wednesday_wiring import _wednesday_article

WEDNESDAY_RUBRIC = Path(
    "config/prompts/editorial_acceptance/never_blank_golden_wednesday.yaml"
)
MONDAY_RUBRIC = Path("config/prompts/editorial_acceptance/never_blank.yaml")

#: The complete Goodyear-shaped article, long enough that a truncated capture
#: is obvious. Run 33283836847's own article is unrecoverable, so this stands
#: in for one of the same shape.
LONG_BODY = (
    "Everyone is watching Goodyear's losses. Nobody is asking what it means "
    "that management extended the turnaround timeline while the cash burn "
    "continued. " + ("The mechanism is capacity, not demand. " * 60)
    + "Source: Verified report (https://source.example/report)."
)


# ===========================================================================
# Fix 1 — the reviewer output contract, stated
# ===========================================================================


def test_the_wednesday_rubric_states_the_canonical_acceptance_schema():
    """The exact gap that stopped run 33283836847."""
    from src.editorial.editorial_acceptance import _ALLOWED_REVIEW_KEYS

    instructions = yaml.safe_load(WEDNESDAY_RUBRIC.read_text())["instructions"]

    for key in _ALLOWED_REVIEW_KEYS:
        assert f'"{key}"' in instructions, f"rubric never names {key}"
    for value in ("accept", "revise", "reject"):
        assert value in instructions
    # and it names the failure that actually happened, so the model is told
    # what not to do rather than only what to do
    assert "verdict" in instructions


def test_the_wednesday_rubric_names_no_key_the_parser_would_refuse():
    """A rubric that asks for a fifth key would fail closed on every run."""
    import re

    from src.editorial.editorial_acceptance import _ALLOWED_REVIEW_KEYS

    instructions = yaml.safe_load(WEDNESDAY_RUBRIC.read_text())["instructions"]
    schema = instructions[instructions.index("{"):instructions.index("}") + 1]
    quoted = set(re.findall(r'"([a-z_]+)":', schema))
    assert quoted == set(_ALLOWED_REVIEW_KEYS), (
        f"the rubric's schema block does not match the parser: {quoted}"
    )


def test_the_schema_matches_the_one_monday_already_proves_safe():
    monday = yaml.safe_load(MONDAY_RUBRIC.read_text())["instructions"]
    wednesday = yaml.safe_load(WEDNESDAY_RUBRIC.read_text())["instructions"]

    def schema_of(text):
        return " ".join(text[text.index("{"):text.index("}") + 1].split())

    assert schema_of(wednesday) == schema_of(monday)


def test_the_rubric_version_was_bumped_with_its_content():
    """Identity is a content contract; changing text under 1.0 is drift."""
    rubric = EditorialAcceptanceRubric.load(WEDNESDAY_RUBRIC)
    assert rubric.identity == "never-blank-golden-wednesday-acceptance/1.1"

    role = yaml.safe_load(Path("config/never_blank/wednesday_golden.yaml").read_text())
    assert role["acceptance_rubric_identity"] == rubric.identity

    business = json.loads(Path("strategy/current/business_strategy.json").read_text())
    wednesday = next(
        r for r in business["editorial_roles"]
        if r["role_id"] == WEDNESDAY_ROLE_ID
    )
    assert wednesday["acceptance_rubric_identity"] == rubric.identity


def test_monday_s_rubric_is_untouched():
    monday = yaml.safe_load(MONDAY_RUBRIC.read_text())
    assert monday["version"] == "1.0"
    business = json.loads(Path("strategy/current/business_strategy.json").read_text())
    pinned = [
        r.get("acceptance_rubric_identity")
        for r in business["editorial_roles"]
        if r["role_id"] != WEDNESDAY_ROLE_ID
    ]
    assert all(p is None or "golden-wednesday" not in p for p in pinned)


# ── the parser itself is NOT loosened ──────────────────────────────────────


def _review(payload: dict):
    """Run the real acceptance parser over one reviewer response."""
    from src.editorial.editorial_acceptance import _review_article

    class _Reviewer:
        def complete(self, *, instructions, request):
            return json.dumps(payload)

    return _review_article(
        _Reviewer(),
        EditorialAcceptanceRubric.load(WEDNESDAY_RUBRIC),
        article_body="A documented case with one mechanism.",
        research=ReadyProvider().research(_acceptance_request()).artifact,
        run_id="00000000-0000-4000-8000-000000000001",
    )


def _acceptance_request():
    """A real provider request, so the review sees a real evidence artifact."""
    from datetime import datetime, timezone

    from src.intake import from_jsonl_signal
    from src.research.lifecycle import build_research_request
    from src.run import ExecutionMode, RunContext
    from src.strategy.business_config import load_business_strategy_configuration
    from src.strategy.execution_context import StrategyExecutionContext

    strategy = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    assignment = from_jsonl_signal(
        dict(WEDNESDAY_SUPPLY), strategy_ref="2026-07-presence-debt-campaign-1",
        strategy_version="1", submitted_at=datetime.now(timezone.utc),
    )
    run = RunContext.from_assignment(
        assignment, ExecutionMode.DRY_RUN, configuration_identity=strategy.identity
    )
    return build_research_request(
        run, assignment, dict(WEDNESDAY_SUPPLY), strategy.research,
        now=datetime.now(timezone.utc),
    )


def test_the_canonical_shape_parses_normally():
    result = _review({
        "disposition": "accept",
        "failed_criterion_ids": [],
        "rationale": "Every criterion passes on the accepted evidence.",
        "revision_guidance": "",
    })
    assert result.disposition.value == "accept"


def test_a_verdict_key_still_fails_closed():
    """The contract is stated, not relaxed. `verdict` is still refused."""
    with pytest.raises(EditorialAcceptanceError, match="unknown fields: verdict"):
        _review({
            "verdict": "accept",
            "failed_criterion_ids": [],
            "rationale": "…",
            "revision_guidance": "",
        })


def test_an_extra_key_alongside_the_canonical_ones_still_fails_closed():
    with pytest.raises(EditorialAcceptanceError, match="unknown fields"):
        _review({
            "disposition": "accept", "failed_criterion_ids": [],
            "rationale": "…", "revision_guidance": "", "confidence": "high",
        })


# ===========================================================================
# Fix 2 — the article that was blocked can now be read
# ===========================================================================


def _article_with_stages() -> dict:
    article = _wednesday_article()
    article["platforms"]["long"]["body"] = LONG_BODY
    article["platforms"]["long"]["title"] = "What Goodyear's extended timeline admits"
    article["hook"] = {"selected_hook": "Everyone is watching the losses."}
    article["reader_context"] = {"context": "Goodyear manufactures tires."}
    article["discovery"] = {"puzzle": "Management stood by the plan."}
    article["story_assembly"] = {"surviving_explanation": "Deliberate cash burn."}
    article["never_blank_voice"] = {"checklist_pass": True}
    return article


def _run(tmp_path, *, reviewer_payload=None, role=WEDNESDAY_ROLE_ID,
         signal=None, dry_run=False, article=None):
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    if role:
        argv = argv + ["--editorial-role", role]
    supplied = dict(signal or WEDNESDAY_SUPPLY)
    argv = [supplied["SIGNAL_ID"] if i == 2 else part for i, part in enumerate(argv)]
    patches["supply_wednesday_signal"] = mock.MagicMock(return_value=supplied)
    patches["_load_signal"] = mock.MagicMock(return_value=supplied)
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=article or _article_with_stages()
    )
    patches["generate_article"] = mock.MagicMock(
        return_value={**(article or _article_with_stages()), "pattern": {}}
    )
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)

    if reviewer_payload is not None:
        # The REAL acceptance stage must run: the contract under test is what
        # the parser does with a reviewer's output, and the harness normally
        # stands the whole stage in for.
        del patches["run_editorial_acceptance"]

        class _Reviewer:
            def complete(self, *, instructions, request):
                return json.dumps(reviewer_payload)
        reviewer = _Reviewer()
    else:
        reviewer = None

    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=reviewer)
    return code, patches


def _run_dir(tmp_path):
    dirs = list(tmp_path.glob("*/runs/*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def test_a_blocked_article_still_leaves_both_diagnostics(tmp_path):
    """Run 33283836847, replayed: blocked at acceptance, evidence preserved."""
    code, patches = _run(tmp_path, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })

    assert code == 1                                   # still blocked
    run_dir = _run_dir(tmp_path)
    assert (run_dir / "signal_snapshot.json").exists()
    assert (run_dir / "generated_pre_acceptance.json").exists()
    # …and the canonical artifact was NOT written
    assert not (run_dir / "generated.json").exists()


def test_the_preserved_article_is_complete_not_a_log_rendering(tmp_path):
    """The whole point: the body must be readable in full afterwards."""
    _code, _patches = _run(tmp_path, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })
    data = json.loads((_run_dir(tmp_path) / "generated_pre_acceptance.json").read_text())

    assert data["platforms"]["long"]["body"] == LONG_BODY      # byte-for-byte
    assert len(data["platforms"]["long"]["body"]) > 2000       # not truncated
    assert "…" not in data["platforms"]["long"]["body"]
    assert data["title"] == "What Goodyear's extended timeline admits"
    assert data["platforms"]["medium"]["body"]                 # the social draft
    assert data["echo_line"]
    assert data["structured_article"]["signature"]


def test_the_preserved_article_carries_the_pipeline_stage_outputs(tmp_path):
    _code, _patches = _run(tmp_path, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })
    stages = json.loads(
        (_run_dir(tmp_path) / "generated_pre_acceptance.json").read_text()
    )["stages"]

    for name in ("decision_lens", "narrative_spine", "hook", "reader_context",
                 "discovery", "story_assembly", "never_blank_voice"):
        assert name in stages, f"{name} was not preserved"


def test_the_signal_snapshot_is_the_object_generation_consumed(tmp_path):
    """Persisted as production held it — nothing recomputed or filled in."""
    signal = {**WEDNESDAY_SUPPLY,
              "CORE_TENSION": "Cash burn against a survival bet.",
              "POTENTIAL_HOOK": "Everyone is watching the losses.",
              "NEVER_BLANK_ANGLE": "The timeline is the admission.",
              "BLOG_ANGLE": "Signal, case, outcome, lesson.",
              "score_reason": "documented case with a real company"}
    _code, _patches = _run(tmp_path, signal=signal, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })
    snapshot = json.loads((_run_dir(tmp_path) / "signal_snapshot.json").read_text())

    assert snapshot["signal"] == signal          # exactly, field for field


def test_the_diagnostics_are_marked_non_canonical_and_unpublishable(tmp_path):
    _code, _patches = _run(tmp_path, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })
    run_dir = _run_dir(tmp_path)
    for name in ("signal_snapshot.json", "generated_pre_acceptance.json"):
        data = json.loads((run_dir / name).read_text())
        assert data["canonical"] is False, name
        assert data["publishable"] is False, name
        assert data["stage"] == "pre_acceptance", name


def test_a_payload_cannot_declare_itself_canonical(tmp_path):
    """The markers overwrite; they do not defer to the content."""
    write_generated_pre_acceptance_json(
        tmp_path, {"canonical": True, "publishable": True, "stage": "published"}
    )
    data = json.loads((tmp_path / "generated_pre_acceptance.json").read_text())
    assert data["canonical"] is False
    assert data["publishable"] is False
    assert data["stage"] == "pre_acceptance"


def test_the_blocked_diagnostic_cannot_be_republished(tmp_path):
    """--from-package requires generated.json, which a blocked run never wrote."""
    code, _patches = _run(tmp_path, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })
    assert code == 1
    run_dir = _run_dir(tmp_path)
    signal_id, source_run_id = run_dir.parent.parent.name, run_dir.name

    with pytest.raises(FileNotFoundError, match="generated.json"):
        load_run_generated(tmp_path, signal_id, source_run_id)


def test_a_blocked_run_publishes_nothing_and_consumes_nothing(tmp_path):
    code, patches = _run(tmp_path, reviewer_payload={
        "verdict": "accept", "failed_criterion_ids": [],
        "rationale": "…", "revision_guidance": "",
    })

    assert code == 1
    assert not patches["WixPublisher"].return_value.publish.called
    assert not patches["LinkedInPublisher"].return_value.publish.called
    assert not patches["append_published_entry"].called     # no consumption
    assert not list(tmp_path.glob("*/runs/*/publication_results.json"))


def test_diagnostics_never_authorize_publication_on_their_own(tmp_path):
    """No production code reads them back — asserted structurally."""
    import ast

    for path in ("scripts/generate_and_publish.py",
                 "src/publishing/package.py",
                 "src/lifecycle/signal_lifecycle.py"):
        tree = ast.parse(Path(path).read_text())
        names = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute))
        }
        assert "load_signal_snapshot_json" not in names
        assert "load_generated_pre_acceptance_json" not in names

    # and no loader for them exists at all
    artifacts = Path("src/artifacts/__init__.py").read_text()
    assert "def load_generated_pre_acceptance" not in artifacts
    assert "def load_signal_snapshot" not in artifacts


# ===========================================================================
# The accepted path, from-package, and Monday are unchanged
# ===========================================================================


def test_an_accepted_run_still_writes_the_canonical_package(tmp_path):
    code, patches = _run(tmp_path, reviewer_payload={
        "disposition": "accept", "failed_criterion_ids": [],
        "rationale": "Every criterion passes.", "revision_guidance": "",
    })

    assert code == 0
    run_dir = _run_dir(tmp_path)
    assert (run_dir / "generated.json").exists()         # canonical, as before
    assert (run_dir / "generated_pre_acceptance.json").exists()   # and evidence
    assert patches["WixPublisher"].return_value.publish.called


def test_the_diagnostic_and_the_canonical_package_are_different_files(tmp_path):
    _code, _patches = _run(tmp_path, reviewer_payload={
        "disposition": "accept", "failed_criterion_ids": [],
        "rationale": "Every criterion passes.", "revision_guidance": "",
    })
    run_dir = _run_dir(tmp_path)
    canonical = json.loads((run_dir / "generated.json").read_text())
    diagnostic = json.loads((run_dir / "generated_pre_acceptance.json").read_text())

    assert canonical != diagnostic
    assert "canonical" not in canonical or canonical.get("canonical") is not False
    assert diagnostic["canonical"] is False


def test_monday_writes_neither_diagnostic(tmp_path):
    """Two new files in a Monday run would be a change to Monday.

    The diagnostics explain the restored Wednesday path, and the seam is
    gated on the same role predicate that routes generation there. An earlier
    revision of this change wrote them for every role on the reasoning that
    recording decides nothing — but the file appearing at all is the change.
    """
    code, patches = _run(tmp_path, role=MONDAY_ROLE, reviewer_payload={
        "disposition": "accept", "failed_criterion_ids": [],
        "rationale": "Every criterion passes.", "revision_guidance": "",
    })

    assert code == 0
    assert patches["generate_article"].called            # Monday's own engine
    assert not patches["generate_for_wednesday"].called

    run_dir = _run_dir(tmp_path)
    assert not (run_dir / "signal_snapshot.json").exists()
    assert not (run_dir / "generated_pre_acceptance.json").exists()
    # …and Monday's own artifacts are exactly as before
    assert (run_dir / "generated.json").exists()
    assert patches["WixPublisher"].return_value.publish.called


def test_a_roleless_run_writes_neither_diagnostic(tmp_path):
    code, patches = _run(tmp_path, role="", reviewer_payload={
        "disposition": "accept", "failed_criterion_ids": [],
        "rationale": "Every criterion passes.", "revision_guidance": "",
    })

    assert code == 0
    run_dir = _run_dir(tmp_path)
    assert not (run_dir / "signal_snapshot.json").exists()
    assert not (run_dir / "generated_pre_acceptance.json").exists()
    assert (run_dir / "generated.json").exists()


def test_a_monday_run_writes_exactly_the_artifacts_it_wrote_before(tmp_path):
    """Named explicitly, so a future diagnostic cannot leak in unnoticed."""
    _code, _patches = _run(tmp_path, role=MONDAY_ROLE, reviewer_payload={
        "disposition": "accept", "failed_criterion_ids": [],
        "rationale": "Every criterion passes.", "revision_guidance": "",
    })
    written = {path.name for path in _run_dir(tmp_path).iterdir()}

    assert not (written & {"signal_snapshot.json", "generated_pre_acceptance.json"})


def test_the_diagnostic_gate_is_the_routing_predicate(tmp_path):
    """One predicate decides both, so they cannot drift apart."""
    import ast

    tree = ast.parse(Path("scripts/generate_and_publish.py").read_text())
    guards = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and getattr(node.test.func, "id", "") == "is_wednesday_role"
    ]
    # one guards generation routing, one guards the diagnostics
    assert len(guards) >= 2
    bodies = [ast.dump(node) for node in guards]
    assert any("generate_for_wednesday" in body for body in bodies)
    assert any("write_signal_snapshot_json" in body for body in bodies)


def test_a_failure_to_write_diagnostics_never_stops_a_run(tmp_path):
    """Evidence, not product: recording must not be able to break publishing."""
    with mock.patch.object(
        gap, "write_signal_snapshot_json", side_effect=OSError("disk full")
    ):
        code, patches = _run(tmp_path, reviewer_payload={
            "disposition": "accept", "failed_criterion_ids": [],
            "rationale": "Every criterion passes.", "revision_guidance": "",
        })
    assert code == 0
    assert patches["WixPublisher"].return_value.publish.called


def test_the_diagnostics_are_create_once_like_every_other_artifact(tmp_path):
    write_signal_snapshot_json(tmp_path, {"SIGNAL_ID": "x"})
    with pytest.raises(ArtifactCollisionError):
        write_signal_snapshot_json(tmp_path, {"SIGNAL_ID": "x"})


def test_the_markers_are_a_single_shared_definition():
    assert DIAGNOSTIC_MARKERS == {
        "canonical": False, "publishable": False, "stage": "pre_acceptance",
    }


# ===========================================================================
# Restored July modules unchanged
# ===========================================================================


FIXTURES = Path("tests/fixtures/wednesday_july")

_RESTORED = [
    ("src/never_blank/wednesday_july/research/discover.py",
     "july_research_originals/discover.py.txt"),
    ("src/never_blank/wednesday_july/research/enrich.py",
     "july_research_originals/enrich.py.txt"),
    ("src/never_blank/wednesday_july/research/score.py",
     "july_research_originals/score.py.txt"),
    ("src/never_blank/wednesday_july/research/angles.py",
     "july_research_originals/angles.py.txt"),
    ("src/never_blank/wednesday_july/decision_lens_lite.py",
     "july_originals/decision_lens_lite.py.txt"),
    ("src/never_blank/wednesday_july/narrative_spine.py",
     "july_originals/narrative_spine.py.txt"),
    ("src/never_blank/wednesday_july/hook_engine.py",
     "july_originals/hook_engine.py.txt"),
    ("src/never_blank/wednesday_july/discovery_builder.py",
     "july_originals/discovery_builder.py.txt"),
    ("src/never_blank/wednesday_july/story_assembly.py",
     "july_originals/story_assembly.py.txt"),
    ("src/never_blank/wednesday_july/never_blank_voice.py",
     "july_originals/never_blank_voice.py.txt"),
    ("src/never_blank/wednesday_july/platform_composer.py",
     "july_originals/platform_composer.py.txt"),
]


@pytest.mark.parametrize("path,original", _RESTORED)
def test_the_restored_july_modules_still_carry_every_july_line(path, original):
    ported = Path(path).read_text()
    for line in (FIXTURES / original).read_text().splitlines():
        if 'SOURCES_CONFIG = Path("config/research_sources.yaml")' in line:
            continue
        if "parents[2]" in line:
            continue
        if line.strip().startswith("from src.editorial."):
            continue
        assert line in ported, f"{path}: lost July line {line!r}"


def test_no_july_prompt_was_touched_to_produce_the_artifact():
    """The capture is at the seam; the pipeline was not asked to report more."""
    for module in ("decision_lens_lite", "narrative_spine", "hook_engine",
                   "discovery_builder", "story_assembly", "never_blank_voice",
                   "platform_composer"):
        source = Path(f"src/never_blank/wednesday_july/{module}.py").read_text()
        assert "pre_acceptance" not in source
        assert "generated_pre_acceptance" not in source
        assert "signal_snapshot" not in source
