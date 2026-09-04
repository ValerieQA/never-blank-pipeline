"""Issue #213: what the first Wednesday CONTROLLED_LIVE run exposed.

Live run 33281894748 finished green, published nothing, and reported a quiet
news day. It was not a quiet news day. July's feeds returned 74 items, 30
reached the selector, and the selector's request was rejected by the provider
with HTTP 400 `invalid model ID` — because the Wednesday workflow never
passed ``NB_DISCOVERY_MODEL``/``NB_SCORING_MODEL`` (it had no research stage
of its own until #211), so both fell back to ``NB_OPENAI_CHAT_MODEL``.

July's ``discover.py`` then did what it has always done: caught the
exception, logged it, and returned ``[]``. Production read that ``[]`` as
"nothing qualified", stopped cleanly, and exited 0.

Two defects, and only these two:

1. the workflow does not pass the stage models the restored research needs;
2. a provider failure is indistinguishable from an honest empty Wednesday.

The second is fixed **at the seam**. July's modules keep failing soft — they
are a verbatim port and must stay one — but they log every failure on the way
down, and production now reads those reports instead of ignoring them.

No paid calls and no network calls anywhere in this module.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest
import yaml

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.never_blank.wednesday_routing import WEDNESDAY_ROLE_ID
from src.never_blank.wednesday_supply import (
    WednesdayResearchInfrastructureError,
    WednesdaySupplyError,
    supply_wednesday_signal,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_monday_stream import MONDAY_ROLE
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_wednesday_july_research import (
    VERSANT_HEADLINE,
    VERSANT_ID,
    VERSANT_URL,
    _JulyClock,
    _feed_transport,
)
from tests.test_wednesday_wiring import _wednesday_article

FIXTURES = Path("tests/fixtures/wednesday_july")
RESEARCH = "src.never_blank.wednesday_july.research"
WEDNESDAY_WORKFLOW = Path(".github/workflows/wednesday_golden.yml")
DAILY_RESEARCH_WORKFLOW = Path(".github/workflows/daily_signal_research.yml")

#: The provider's actual response in run 33281894748.
INVALID_MODEL = (
    "Error code: 400 - {'error': {'message': 'invalid model ID', "
    "'type': 'invalid_request_error', 'param': None, 'code': None}}"
)


def _generate_step() -> dict:
    workflow = yaml.safe_load(WEDNESDAY_WORKFLOW.read_text())
    steps = workflow["jobs"]["wednesday-golden"]["steps"]
    return next(
        step for step in steps
        if str(step.get("name", "")).startswith("Wednesday Golden — Generate")
    )


# ===========================================================================
# Defect 1 — the stage models the restored research actually needs
# ===========================================================================


def test_wednesday_passes_the_discovery_and_scoring_models():
    """The exact gap that made run 33281894748 fall back and fail."""
    env = _generate_step()["env"]

    assert env["NB_DISCOVERY_MODEL"] == "${{ secrets.NB_DISCOVERY_MODEL }}"
    assert env["NB_SCORING_MODEL"] == "${{ secrets.NB_SCORING_MODEL }}"


def test_the_stage_models_follow_the_existing_daily_research_convention():
    """Same secrets, same spelling — not a new routing scheme."""
    daily = yaml.safe_load(DAILY_RESEARCH_WORKFLOW.read_text())
    daily_env: dict = {}
    for step in daily["jobs"][next(iter(daily["jobs"]))]["steps"]:
        daily_env.update(step.get("env") or {})
    wednesday_env = _generate_step()["env"]

    for name in ("NB_DISCOVERY_MODEL", "NB_SCORING_MODEL", "NB_ENRICH_MODEL",
                 "NB_ARTICLE_MODEL", "NB_SOCIAL_MODEL", "NB_OPENAI_CHAT_MODEL"):
        assert wednesday_env[name] == daily_env[name], name


def test_every_stage_model_the_wednesday_run_can_ask_for_is_supplied():
    """Derived from the code, so a new stage cannot be forgotten again.

    The July research and the shared engine between them call a fixed set of
    ``model_*`` helpers; each maps to one environment variable. Rather than
    listing the ones we happen to remember, read them out of `llm_client` and
    require the workflow to carry all of them.
    """
    import ast

    from src.utils import llm_client

    tree = ast.parse(Path("src/utils/llm_client.py").read_text())
    stage_vars: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("model_"):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    if inner.value.startswith("NB_") and inner.value.endswith("_MODEL"):
                        stage_vars.add(inner.value)

    assert "NB_DISCOVERY_MODEL" in stage_vars    # the helper still exists
    env = _generate_step()["env"]
    # image generation is not a text stage of this run; everything else must
    # be present
    required = {name for name in stage_vars if name != "NB_IMAGE_MODEL"}
    missing = required - set(env)
    assert not missing, f"the Wednesday step cannot route these stages: {missing}"


def test_wednesday_requires_zero_exa_configuration():
    """#211 removed Exa from Wednesday; the secret should have gone with it."""
    # Read as configuration, not as text: the workflow explains in a comment
    # why the variable is absent, and that comment is not a configuration key.
    workflow = yaml.safe_load(WEDNESDAY_WORKFLOW.read_text())
    for step in workflow["jobs"]["wednesday-golden"]["steps"]:
        for name in (step.get("env") or {}):
            assert "EXA" not in name.upper(), f"{step.get('name')}: {name}"

    # and no step body reaches an Exa secret either
    for step in workflow["jobs"]["wednesday-golden"]["steps"]:
        assert "secrets.NB_EXA" not in str(step.get("run", ""))


def test_monday_still_receives_its_own_configuration_unchanged():
    monday = yaml.safe_load(Path(".github/workflows/monday_publish.yml").read_text())
    env: dict = {}
    for step in monday["jobs"][next(iter(monday["jobs"]))]["steps"]:
        env.update(step.get("env") or {})

    assert env["NB_EXA_API_KEY"] == "${{ secrets.NB_EXA_API_KEY }}"
    text = Path(".github/workflows/monday_publish.yml").read_text()
    assert "select_eligible_signal.py" in text


# ===========================================================================
# Defect 2 — a failed stage is not a quiet news day
# ===========================================================================


def _failing_research(stage_logger: str, message: str = INVALID_MODEL,
                      signals=None):
    """Reproduce a July stage failing soft: log the error, return a result.

    This is what the real modules do — every one of their `except` blocks
    logs and then returns an empty or partial value — so a test that only
    stubbed the return value would not be testing the masking at all.
    """
    def research(seen_ids):
        logging.getLogger(stage_logger).error(
            "LLM index selection failed: %s", message
        )
        return list(signals or [])
    return research


def _healthy_empty_research(seen_ids):
    """A selector that genuinely ran and chose nothing."""
    logging.getLogger("research.discover").info(
        "LLM selected 0 items from 30 candidates"
    )
    return []


def test_a_genuine_empty_selector_remains_a_healthy_no_publication(tmp_path):
    """The outcome July had on a quiet day, and still has."""
    result = supply_wednesday_signal(
        seen_ids=set(), research=_healthy_empty_research,
        store=tmp_path / "s.jsonl",
    )
    assert result is None                    # publish nothing, cleanly


@pytest.mark.parametrize("stage_logger,stage_name", [
    ("research.discover", "discovery/selection"),
    ("research.score", "scoring"),
    ("research.enrich", "enrichment"),
    ("research.angles", "angles"),
])
def test_a_failed_stage_is_an_infrastructure_error_not_an_empty_wednesday(
    tmp_path, stage_logger, stage_name
):
    with pytest.raises(WednesdayResearchInfrastructureError) as exc:
        supply_wednesday_signal(
            seen_ids=set(),
            research=_failing_research(stage_logger),
            store=tmp_path / "s.jsonl",
        )

    assert stage_name in str(exc.value)          # which stage
    assert "invalid model ID" in str(exc.value)  # normalized provider reason
    # …and it is a WednesdaySupplyError, so the entrypoint's existing handling
    # applies without a second code path
    assert isinstance(exc.value, WednesdaySupplyError)


def test_a_stage_that_failed_still_fails_the_run_when_signals_came_back(tmp_path):
    """A partial result is not a lesser problem — it is a degraded article.

    Angles failing for a signal leaves it without a hook or a Never Blank
    angle, which July's generation consumes. Publishing it would ship
    something the pipeline never actually produced.
    """
    versant = {
        "SIGNAL_ID": VERSANT_ID, "HEADLINE": VERSANT_HEADLINE,
        "CORE_FACT": "Versant agreed to acquire Full Swing for $530 million.",
        "REAL_COMPANY_EXAMPLE": "Versant", "SOURCE_FOR_CASE": VERSANT_URL,
        "CONFIDENCE": "high",
    }
    with pytest.raises(WednesdayResearchInfrastructureError):
        supply_wednesday_signal(
            seen_ids=set(),
            research=_failing_research("research.angles", signals=[versant]),
            store=tmp_path / "s.jsonl",
        )


def test_a_dead_feed_is_not_an_infrastructure_failure(tmp_path):
    """HBR 404s routinely. July published from the other feeds and so do we."""
    def research(seen_ids):
        logging.getLogger("research.discover").warning(
            "RSS fetch failed https://hbr.org/the-latest/rss: 404 Client Error"
        )
        return []

    assert supply_wednesday_signal(
        seen_ids=set(), research=research, store=tmp_path / "s.jsonl"
    ) is None


def test_an_exception_that_escapes_july_is_also_typed(tmp_path):
    def research(seen_ids):
        raise RuntimeError("connection reset by peer")

    with pytest.raises(WednesdayResearchInfrastructureError, match="connection reset"):
        supply_wednesday_signal(
            seen_ids=set(), research=research, store=tmp_path / "s.jsonl"
        )


def test_the_recorder_is_removed_after_the_call(tmp_path):
    """A handler left attached would leak into every later run in-process."""
    before = list(logging.getLogger("research.discover").handlers)
    with pytest.raises(WednesdayResearchInfrastructureError):
        supply_wednesday_signal(
            seen_ids=set(), research=_failing_research("research.discover"),
            store=tmp_path / "s.jsonl",
        )
    assert logging.getLogger("research.discover").handlers == before


def test_a_configured_model_id_never_reaches_the_error_message(
    tmp_path, monkeypatch
):
    """Model ids are secrets in this deployment; the reason is redacted."""
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", "super-secret-model-id")

    with pytest.raises(WednesdayResearchInfrastructureError) as exc:
        supply_wednesday_signal(
            seen_ids=set(),
            research=_failing_research(
                "research.discover",
                message="model 'super-secret-model-id' is invalid",
            ),
            store=tmp_path / "s.jsonl",
        )
    assert "super-secret-model-id" not in str(exc.value)
    assert "<NB_OPENAI_CHAT_MODEL>" in str(exc.value)


# ===========================================================================
# The production path: red, not green
# ===========================================================================


@pytest.fixture(scope="module")
def cnbc_feed() -> str:
    return (FIXTURES / "cnbc_business_2026-07-06.xml").read_text(encoding="utf-8")


def _run_entrypoint(tmp_path, *, research, role=WEDNESDAY_ROLE_ID, signal_id=None):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    argv = ["prog"] + ([] if signal_id is None else ["--signal-id", signal_id]) + argv[3:]
    if role:
        argv += ["--editorial-role", role]
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=_wednesday_article()
    )
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    store = tmp_path / "wednesday.jsonl"

    def supply(requested_signal_id="", **kwargs):
        return supply_wednesday_signal(
            requested_signal_id, seen_ids=set(), research=research, store=store
        )

    evaluator, _ = _evaluator(_model_output())
    # Monday's own path needs a working provider; Wednesday never reaches it.
    patches["ExaResearchAdapter"] = mock.MagicMock(return_value=ReadyProvider())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(gap, "supply_wednesday_signal", side_effect=supply):
        code = main(decision_evaluator=evaluator)
    return code, patches


def test_the_live_failure_now_turns_the_run_red(tmp_path, capsys):
    """Run 33281894748, replayed: green before, non-zero now."""
    code, patches = _run_entrypoint(
        tmp_path, research=_failing_research("research.discover")
    )

    assert code == 1                                   # GitHub Actions goes red
    out = capsys.readouterr().out
    assert "invalid model ID" in out
    assert "discovery/selection" in out
    # and nothing downstream ran
    assert not patches["generate_for_wednesday"].called
    assert not patches["generate_article"].called
    assert not patches["WixPublisher"].return_value.publish.called
    assert not patches["LinkedInPublisher"].return_value.publish.called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_genuine_empty_wednesday_still_exits_zero(tmp_path, capsys):
    code, patches = _run_entrypoint(tmp_path, research=_healthy_empty_research)

    assert code == 0                                   # a clean, honest stop
    assert "publishing nothing" in capsys.readouterr().out
    assert not patches["generate_for_wednesday"].called
    assert not patches["WixPublisher"].return_value.publish.called


@pytest.mark.parametrize("stage_logger", [
    "research.score", "research.enrich", "research.angles",
])
def test_a_failure_at_any_later_stage_also_turns_the_run_red(
    tmp_path, stage_logger
):
    code, patches = _run_entrypoint(
        tmp_path, research=_failing_research(stage_logger)
    )
    assert code == 1
    assert not patches["generate_for_wednesday"].called
    assert not patches["WixPublisher"].return_value.publish.called


def test_no_second_candidate_is_attempted_after_a_stage_failure(tmp_path):
    """One research invocation, no retry, no fallback supply."""
    calls: list = []

    def research(seen_ids):
        calls.append(seen_ids)
        logging.getLogger("research.discover").error("LLM index selection failed: x")
        return []

    code, patches = _run_entrypoint(tmp_path, research=research)

    assert code == 1
    assert len(calls) == 1
    assert not patches["_load_signal"].called          # never falls back


def test_monday_is_untouched_by_the_failure_seam(tmp_path):
    """The seam is Wednesday-only; Monday does not reach it at all."""
    called: list = []

    def research(seen_ids):
        called.append(seen_ids)
        return []

    code, patches = _run_entrypoint(
        tmp_path, research=research, role=MONDAY_ROLE, signal_id="sig-test-001"
    )
    assert called == []                                # supply never invoked
    assert patches["_load_signal"].called              # Monday's own path
    assert code in (0, 1)


# ===========================================================================
# The restored July modules are still verbatim
# ===========================================================================


#: Every restored July file, paired with the pinned copy of what it was at
#: ``c7d3a23``. Checked against the in-repo originals rather than by shelling
#: out to git: a shallow CI checkout has no `origin/main` to resolve, which
#: is the same trap that broke the first #208 CI head.
_RESTORED_JULY_FILES = [
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


@pytest.mark.parametrize("path,original", _RESTORED_JULY_FILES)
def test_the_restored_july_files_still_carry_every_july_line(path, original):
    """This fix is at the seam; not one July line may have moved.

    Line-containment rather than byte-equality, because the ported files
    carry an isolation banner and the two mechanical deviations #211
    recorded — the same contract the #211 fidelity tests enforce, restated
    here so a change made *by this PR* would fail this PR's own suite.
    """
    ported = Path(path).read_text()
    for line in (FIXTURES / original).read_text().splitlines():
        if 'SOURCES_CONFIG = Path("config/research_sources.yaml")' in line:
            continue                       # #211 deviation 1: packaged feeds
        if "parents[2]" in line:
            continue                       # #211 deviation 2: moved deeper
        if line.strip().startswith("from src.editorial."):
            continue                       # shared byte-identical module
        assert line in ported, f"{path}: lost July line {line!r}"


def test_the_july_feed_configuration_is_still_verbatim():
    assert Path(
        "src/never_blank/wednesday_july/research/research_sources_july.yaml"
    ).read_text() == (
        FIXTURES / "july_research_originals" / "research_sources.yaml.txt"
    ).read_text()


def test_the_july_selector_instruction_is_still_inclusive():
    source = Path(
        "src/never_blank/wednesday_july/research/discover.py"
    ).read_text()
    assert "Be inclusive — prefer false positives over missed signals." in source
    assert "ALWAYS REJECT" not in source


def test_the_july_fail_soft_behaviour_itself_is_preserved():
    """The seam observes July's modules; it does not change how they behave."""
    for module in ("discover", "enrich", "score", "angles"):
        source = Path(
            f"src/never_blank/wednesday_july/research/{module}.py"
        ).read_text()
        assert "except Exception" in source, module
        # no re-raise was bolted on
        assert "raise WednesdaySupplyError" not in source
        assert "WednesdayResearchInfrastructureError" not in source


# ===========================================================================
# The watch cannot be switched off by unrelated logging configuration
# ===========================================================================


def test_the_watch_survives_logging_disable(tmp_path):
    """A safety check an unrelated logging tweak can silence is not one.

    Found while verifying this fix: with ``logging.disable(CRITICAL)`` in
    effect the records never reach the recorder, and the masking returns
    exactly as it was.
    """
    logging.disable(logging.CRITICAL)
    try:
        with pytest.raises(WednesdayResearchInfrastructureError):
            supply_wednesday_signal(
                seen_ids=set(),
                research=_failing_research("research.discover"),
                store=tmp_path / "s.jsonl",
            )
    finally:
        logging.disable(logging.NOTSET)


def test_the_watch_survives_a_raised_logger_level(tmp_path):
    logger = logging.getLogger("research.discover")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        with pytest.raises(WednesdayResearchInfrastructureError):
            supply_wednesday_signal(
                seen_ids=set(),
                research=_failing_research("research.discover"),
                store=tmp_path / "s.jsonl",
            )
    finally:
        logger.setLevel(previous)


def test_logging_configuration_is_restored_afterwards(tmp_path):
    """Forcing the level is scoped to the call, including on the failure path."""
    logger = logging.getLogger("research.discover")
    logger.setLevel(logging.CRITICAL)
    logging.disable(logging.CRITICAL)
    try:
        with pytest.raises(WednesdayResearchInfrastructureError):
            supply_wednesday_signal(
                seen_ids=set(),
                research=_failing_research("research.discover"),
                store=tmp_path / "s.jsonl",
            )
        assert logger.level == logging.CRITICAL
        assert logging.root.manager.disable == logging.CRITICAL
    finally:
        logger.setLevel(logging.NOTSET)
        logging.disable(logging.NOTSET)


# ===========================================================================
# The real July module, not a stub: run 33281894748 replayed
# ===========================================================================


_LIVE_FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>A documented business decision</title>
<link>https://www.cnbc.com/2026/08/29/a-real-story.html</link>
<pubDate>Fri, 29 Aug 2026 12:00:00 GMT</pubDate>
<description>Something happened.</description></item>
</channel></rss>"""


class _LiveRunClock(datetime):
    """Keep the 2026-08-29 replay inside July discovery's 72-hour window."""

    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        return value if tz else value.replace(tzinfo=None)


def test_the_live_invalid_model_failure_is_caught_through_the_real_modules(
    tmp_path,
):
    """End to end through July's own code, with its own fail-soft intact.

    The stubs above model the masking; this proves the real modules mask it
    the same way and that the seam sees through them. The provider raises the
    exact error run 33281894748 received.
    """
    class _Feed:
        def __init__(self, text):
            self.text, self.content, self.status_code = text, text.encode(), 200

        def raise_for_status(self):
            return None

    def fetch(url, *args, **kwargs):
        return _Feed(_LIVE_FEED if "cnbc" in url else
                     '<?xml version="1.0"?><rss><channel></channel></rss>')

    def provider_rejects(*args, **kwargs):
        raise RuntimeError(INVALID_MODEL)

    patches = [
        mock.patch(f"{RESEARCH}.discover.requests.get", side_effect=fetch),
        mock.patch(f"{RESEARCH}.discover.datetime", _LiveRunClock),
    ]
    patches += [
        mock.patch(f"{RESEARCH}.{module}.chat", side_effect=provider_rejects)
        for module in ("discover", "enrich", "angles", "score")
    ]
    for patch in patches:
        patch.start()
    try:
        with pytest.raises(WednesdayResearchInfrastructureError) as exc:
            supply_wednesday_signal(seen_ids=set(), store=tmp_path / "s.jsonl")
    finally:
        for patch in patches:
            patch.stop()

    assert "discovery/selection" in str(exc.value)
    assert "invalid model ID" in str(exc.value)
    # July's own behaviour is untouched: it still returned [] and logged
    assert not (tmp_path / "s.jsonl").exists()
