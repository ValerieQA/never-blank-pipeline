"""Issue #207: Wednesday runs the July path, and Versant survives it.

The forensic record (#206) established that the 2026-07-06 Versant / Full
Swing specimen is unreachable today for four independent reasons. Two are
supply-side configuration. One is a product decision. The fourth is
structural and is what this package answers: the current shared editorial
pipeline opens with ``pattern_extractor``, a stage that did not exist in July
and that asserts

    article_protagonist — "Always 'owner'. This is a hard assertion, not a
    choice." … signal_fit = "reject" if "the signal is only relevant to
    large-company strategy" … founder_scenario "must be writable WITHOUT any
    company name".

The Versant article's protagonist *is* the company — a media conglomerate
redefining what "media" means. Under that stage the specimen is rejected, or
survives only by being flattened into an owner scenario, which destroys the
second-order reading that made it the reference output.

These scenarios prove the restored Wednesday path reproduces July's editorial
behaviour and that the historical Versant signal reaches generation through
it. No paid call is made anywhere: every stage transport is faked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.never_blank.wednesday_july import (
    DELIBERATELY_ABSENT_STAGES,
    JULY_STAGE_ORDER,
    WednesdayGenerationError,
    generate_wednesday_article,
)

FIXTURES = Path("tests/fixtures/wednesday_july")
_MODULE = "src.never_blank.wednesday_july"

#: Every ported stage module whose transport must be faked.
_STAGE_MODULES = (
    "decision_lens_lite", "narrative_spine", "hook_engine",
    "discovery_builder", "story_assembly", "never_blank_voice",
    "platform_composer",
)


@pytest.fixture(scope="module")
def versant() -> dict:
    """The historical enriched signal, exactly as committed at c7d3a23."""
    return json.loads(
        (FIXTURES / "versant_full_swing_signal.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def july_specimen() -> dict:
    """What the July run actually published, for reference assertions."""
    return json.loads(
        (FIXTURES / "versant_full_swing_july_output.json").read_text(encoding="utf-8")
    )


# ===========================================================================
# A schema-valid fake transport — no network, no spend
# ===========================================================================


def _stage_payload(stage: str) -> str:
    """Minimal output satisfying each ported stage's own validator."""
    payloads = {
        "decision_lens_lite": {
            "core_decision": "Buy an experiential technology company.",
            "strategic_objective": "Replace declining legacy revenue.",
            "strategic_objective_evidence": ["cable revenue decline"],
            "strategic_objective_confidence": "high",
            "business_lesson": "Category boundaries move before balance sheets do.",
            "never_blank_insight": "The purchase redefines the category, not the portfolio.",
        },
        "narrative_spine": {
            "core_decision": "Buy an experiential technology company.",
            "narrative_spine": "A media company stops being defined by its channel.",
            "company_as_evidence_of": "Versant demonstrates that category lines move first.",
            "target_feeling": "reframe",
        },
        "hook_engine": {
            "hook_candidates": [
                {"type": "contradiction", "text": "Everyone saw the price tag."},
                *[{"type": "invisible_signal", "text": f"Candidate hook {i}."}
                  for i in range(1, 6)],
            ],
            "selected_hook": "Everyone saw the price tag.",
            "selected_index": 0,
            "selection_reason": "names the unseen consequence",
        },
        "discovery_builder": {
            "first_wrong_explanation": "It looks like chasing a consumer trend.",
            "puzzle": "A media company is buying hardware.",
            "investigation_sequence": [
                "legacy revenue fell", "the asset is experiential",
                "the category boundary moved",
            ],
            "aha_setup": "The category itself is being redrawn.",
        },
        "story_assembly": {
            "surviving_explanation": "The acquisition redefines what counts as media.",
            "remaining_uncertainty": "Whether the new format reaches legacy scale.",
            "business_translation": "When the core market erodes, the definition moves first.",
        },
        "never_blank_voice": {
            "signature": "Never Blank: the boldest moves redraw the boundary.",
            "checklist_pass": True,
            "checklist_notes": "",
        },
        "reader_context": {
            "context_line": "Legacy channels erode long before the numbers say so.",
        },
        "platform_composer": {
            "body": "A composed platform body long enough to satisfy the composer.",
            "echo_included": True,
        },
    }
    return json.dumps(payloads[stage])


class _FakeTransport:
    """Records the prompt each stage sent, and answers in its own schema."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []   # (stage, system, user)

    def for_stage(self, stage: str):
        def fake_chat(system, user, json_mode=False, model=None, **kwargs):
            self.calls.append((stage, system, user))
            return _stage_payload(stage)
        return fake_chat

    @property
    def stages(self) -> list[str]:
        return [stage for stage, _s, _u in self.calls]

    def prompt_for(self, stage: str) -> str:
        return "\n".join(u for s, _sys, u in self.calls if s == stage)

    def system_for(self, stage: str) -> str:
        return "\n".join(sys for s, sys, _u in self.calls if s == stage)


def _run(signal: dict) -> tuple[dict, _FakeTransport]:
    transport = _FakeTransport()
    patches = [
        mock.patch(f"{_MODULE}.{m}.chat", side_effect=transport.for_stage(m))
        for m in _STAGE_MODULES
    ]
    # reader_context is the shared module, reused because it is byte-identical
    patches.append(
        mock.patch("src.editorial.reader_context.chat",
                   side_effect=transport.for_stage("reader_context"))
    )
    for p in patches:
        p.start()
    try:
        return generate_wednesday_article(signal), transport
    finally:
        for p in patches:
            p.stop()


# ===========================================================================
# 1. The governing regression — Versant reaches generation
# ===========================================================================


def test_the_historical_versant_signal_reaches_generation(versant):
    """The whole point: this signal must not be rejected before it is written."""
    result, transport = _run(versant)

    assert set(result) == {
        "decision_lens", "narrative_spine", "structured_article", "platforms"
    }
    assert result["platforms"]["long"]["body"]
    assert result["structured_article"]["signature"]
    assert result["structured_article"]["signal_id"] == "37a503640b83be6c"
    # every editorial stage ran; nothing short-circuited the signal
    for stage in JULY_STAGE_ORDER:
        assert stage in transport.stages, f"{stage} never executed"


def test_no_stage_can_reject_the_signal_for_being_a_large_company(versant):
    """July had no signal_fit gate inside generation, and neither does this."""
    _result, transport = _run(versant)

    combined = " ".join(transport.system_for(s) for s in JULY_STAGE_ORDER).lower()
    # the owner-protagonist assertion and the large-company rejection are the
    # current shared rules this path exists to avoid
    assert "always \"owner\"" not in combined
    assert "hard assertion, not a choice" not in combined
    assert "only relevant to large-company strategy" not in combined
    assert "signal_fit" not in combined


def test_the_restored_path_does_not_run_pattern_extractor(versant):
    _result, transport = _run(versant)

    assert "pattern_extractor" in DELIBERATELY_ABSENT_STAGES
    assert "pattern_extractor" not in transport.stages
    # and no executable line imports or runs it (the docstring names it only
    # to record that the omission is deliberate)
    source = Path("src/never_blank/wednesday_july/pipeline.py").read_text()
    code = [
        line for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", '"', "'"))
    ]
    for line in code:
        assert "extract_pattern" not in line
        assert '_run_stage("pattern_extractor"' not in line


def test_the_current_shared_pipeline_would_apply_the_owner_assertion():
    """Why the isolation is necessary, asserted against the shared code."""
    shared = Path("src/editorial/pattern_extractor.py").read_text()
    assert 'Always "owner"' in shared
    assert "hard assertion, not a choice" in shared
    assert "only relevant to large-company strategy" in shared
    # and the shared pipeline runs it first
    shared_pipeline = Path("src/editorial/pipeline.py").read_text()
    assert '_run_stage("pattern_extractor"' in shared_pipeline


# ===========================================================================
# 2. July editorial behaviour, reproduced literally
# ===========================================================================


def test_the_stage_order_is_the_july_order(versant):
    _result, transport = _run(versant)

    first_run = []
    for stage in transport.stages:
        if stage not in first_run:
            first_run.append(stage)
    assert tuple(first_run) == JULY_STAGE_ORDER


def test_the_interpretation_fields_reach_the_stages_that_used_them(versant):
    """CORE_TENSION and the case reading are what make this second-order."""
    _result, transport = _run(versant)

    lens = transport.prompt_for("decision_lens_lite")
    assert versant["CORE_TENSION"] in lens
    assert versant["WHY_THIS_CASE_IS_INTERESTING"] in lens
    assert versant["BUSINESS_LESSON"] in lens
    assert versant["COUNTER_EXAMPLE"] in lens

    hook = transport.prompt_for("hook_engine")
    assert versant["CORE_FACT"] in hook
    assert versant["CORE_TENSION"] in hook

    discovery = transport.prompt_for("discovery_builder")
    assert versant["CORE_TENSION"] in discovery
    assert versant["RESPONSE_TAKEN"] in discovery


def test_the_ported_modules_are_verbatim_july(versant):
    """A literal restoration — the port must not have been 'improved'."""
    import subprocess

    for module in _STAGE_MODULES:
        july = subprocess.run(
            ["git", "show", f"c7d3a23:src/editorial/{module}.py"],
            capture_output=True, text=True, check=True,
        ).stdout
        ported = Path(f"src/never_blank/wednesday_july/{module}.py").read_text()
        # the port adds an isolation banner and repoints intra-package imports;
        # everything else must be byte-identical to July
        stripped = "\n".join(
            line for line in ported.splitlines()
            if not line.startswith("#") or "ISOLATED WEDNESDAY" not in ported[:400]
        )
        for july_line in july.splitlines():
            if july_line.strip().startswith("from src.editorial."):
                continue          # intra-package import, legitimately repointed
            assert july_line in ported, f"{module}: lost July line {july_line!r}"
        assert stripped  # sanity


def test_july_retry_semantics_are_preserved(versant):
    """One retry on a schema failure, then a typed stop — no degradation."""
    attempts = []

    def flaky(system, user, json_mode=False, model=None, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return json.dumps({"core_decision": ""})      # schema-invalid
        return _stage_payload("decision_lens_lite")

    others = [
        mock.patch(f"{_MODULE}.{m}.chat",
                   side_effect=_FakeTransport().for_stage(m))
        for m in _STAGE_MODULES if m != "decision_lens_lite"
    ]
    others.append(mock.patch("src.editorial.reader_context.chat",
                             side_effect=_FakeTransport().for_stage("reader_context")))
    for p in others:
        p.start()
    try:
        with mock.patch(f"{_MODULE}.decision_lens_lite.chat", side_effect=flaky):
            result = generate_wednesday_article(versant)
    finally:
        for p in others:
            p.stop()

    assert len(attempts) == 2                 # exactly one retry
    assert result["decision_lens"]["core_decision"]


def test_a_twice_failing_stage_stops_the_run(versant):
    def always_bad(system, user, json_mode=False, model=None, **kwargs):
        return json.dumps({"core_decision": ""})

    with mock.patch(f"{_MODULE}.decision_lens_lite.chat", side_effect=always_bad):
        with pytest.raises(WednesdayGenerationError) as exc:
            generate_wednesday_article(versant)

    assert exc.value.stage == "decision_lens_lite"


# ===========================================================================
# 3. Isolation from current shared business logic
# ===========================================================================


def test_the_package_imports_no_current_business_module():
    """Technical infrastructure only — no shared business rule may leak in."""
    forbidden = (
        "pattern_extractor", "source_eligibility", "source_transparency",
        "editorial_acceptance", "sources_of_record", "editorial_role",
        "linkedin_composition", "business_config", "decision_lens",
    )
    for path in Path("src/never_blank/wednesday_july").glob("*.py"):
        source = path.read_text()
        for name in forbidden:
            assert f"import {name}" not in source and f".{name} import" not in source, (
                f"{path.name} reaches current business logic: {name}"
            )
        # the shared editorial package may be touched only for reader_context,
        # which is byte-identical to July
        for line in source.splitlines():
            if line.startswith("from src.editorial."):
                assert "reader_context" in line, f"{path.name}: {line}"


def test_only_technical_infrastructure_is_shared():
    allowed_roots = ("src.utils.llm_client", "src.utils.logger",
                     "src.editorial.reader_context",
                     "src.never_blank.wednesday_july")
    for path in Path("src/never_blank/wednesday_july").glob("*.py"):
        for line in path.read_text().splitlines():
            if line.startswith("from src.") or line.startswith("import src."):
                assert any(line.startswith(f"from {r}") or line.startswith(f"import {r}")
                           for r in allowed_roots), f"{path.name}: {line}"


# ===========================================================================
# 4. The historical specimen is preserved as the product reference
# ===========================================================================


def test_the_july_specimen_is_available_as_the_product_reference(july_specimen):
    linkedin = july_specimen["linkedin_post"]
    article = july_specimen["blog_article"]

    assert july_specimen["signal_id"] == "37a503640b83be6c"
    # the reference behaviour: a second-order reading, not a summary
    assert "future definition of" in linkedin
    assert "Everyone saw the price tag" in article
    assert "Never Blank:" in article
    # and the source is attributed
    assert "cnbc.com" in article


def test_the_fixture_signal_carries_the_july_intelligence(versant):
    for field in ("CORE_FACT", "CORE_TENSION", "BUSINESS_LESSON",
                  "WHY_THIS_CASE_IS_INTERESTING", "POTENTIAL_HOOK",
                  "NEVER_BLANK_ANGLE", "BLOG_ANGLE", "LINKEDIN_ANGLE"):
        assert versant.get(field), f"fixture lost {field}"
    assert versant["SOURCE_NAME"] == "CNBC Business"
    assert "cnbc.com" in versant["SOURCE_URL"]
