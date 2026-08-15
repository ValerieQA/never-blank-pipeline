"""
Task #27 — Run identity propagation integration and contract tests.

Structure:
  TestRequireRunId          — _require_run_id() fail-closed guard
  TestAssertRunIdMatch      — _assert_run_id_match() identity assertion
  TestNormalizePublishResult — _normalize_publish_result() adapter
  TestRunContextCreatedOnce — RunContext created exactly once per execution
  TestResearchContextRunId  — compatibility boundary injects run_id
  TestEditorialContextRunId — to_editorial() propagates run_id
  TestVisualArtifactRequest — visual boundary stub carries run_id
  TestValidationResultRunId — ValidationResult typed output carries run_id
  TestGeneratedPackageRunId — generated JSON persists run_id
  TestDraftPackageRunId     — DraftPackage carries run_id
  TestPublishResultRunId    — PublishResult receives run_id via normalizer
  TestFromPackageRunIdentity — --from-package BLOCKER 1 cases
  TestMismatchRejected      — BLOCKER 3 mismatch detection at boundaries
  TestFailClosedBeforeImages — fail-closed before image side effects
  TestFailClosedBeforePublisher — fail-closed before publisher construction
  TestR1RunReportBoundary   — R1RunReport stub contract
  TestCompletePathRunIdentityContract — single canonical-path contract test
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tests.test_generate_and_publish import _test_configuration_identity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_and_publish import (
    _assert_run_id_match,
    _build_legacy_research_context,
    _normalize_publish_result,
    _require_run_id,
    main,
)
from src.intake import from_jsonl_signal
from src.lifecycle.signal_lifecycle import EditorialContext, ResearchContext
from src.publishing.base import DraftPackage
from src.publishing.result import PublishResult, PublishStatus
from src.reporting import R1RunReport
from src.run.run_context import ExecutionMode, RunContext
from src.strategy.validators import ValidationResult
from src.visual import VisualArtifactRequest

import scripts.generate_and_publish as _gap_module


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SIGNAL_ID   = "sig-identity-test-001"
_KNOWN_RUN_ID = "11111111-2222-4333-8444-555555555555"

_RAW_SIGNAL = {
    "SIGNAL_ID":                       _SIGNAL_ID,
    "HEADLINE":                        "Run identity propagation test signal",
    "CORE_FACT":                       "Synthetic fact for identity tracing.",
    "ARTICLE_READY":                   "true",
    "SCORE_RECOMMENDED_FOR_ARTICLE":   "true",
    "SIGNAL_TYPE":                     "market_trend",
    "REGION":                          "global",
    "INDUSTRY":                        "technology",
    "SOURCE_NAME":                     "Test Source",
    "SOURCE_URL":                      "https://example.com",
    "SOURCE_DATE":                     "2026-08-11",
    "DATE_FOUND":                      "2026-08-11",
    "CONFIDENCE":                      "high",
    "SOURCE_QUALITY":                  "high",
    "SOURCE_FOR_CASE":                 "Test Source",
    "REAL_COMPANY_EXAMPLE":            "TestCo",
    "OUTCOME_IF_KNOWN":                "success",
    "DID_IT_WORK":                     "yes",
    "EVIDENCE_OF_OUTCOME":             "data",
    "NOTES":                           "",
    "ARTICLE_READINESS_SCORE":         "9",
    "SIGNAL_STRENGTH":                 "high",
    "CHANNEL_FIT_SCORE":               "9",
    "DISCUSSION_POTENTIAL":            "high",
    "score_reason":                    "high quality signal",
    "CORE_TENSION":                    "tension",
    "BUSINESS_LESSON":                 "lesson",
    "WHY_THIS_CASE_IS_INTERESTING":    "interesting",
    "WHY_IT_MATTERS_TO_BUSINESS":      "matters",
    "BUSINESS_RESPONSES_OBSERVED":     "responses",
    "PROBLEM_FACED":                   "problem",
    "RESPONSE_TAKEN":                  "response",
    "COUNTER_EXAMPLE":                 "none",
    "TIME_HORIZON":                    "2027",
    "INTERESTING_QUESTION":            "Why?",
    "NEVER_BLANK_ANGLE":               "angle",
    "POSSIBLE_SIGNATURE_LINE":         "signature",
    "POTENTIAL_HOOK":                  "hook",
    "TARGET_AUDIENCE":                 "agencies",
    "PRIMARY_CHANNEL":                 "linkedin",
    "LINKEDIN_ANGLE":                  "linkedin angle",
    "BLOG_ANGLE":                      "blog angle",
    "THREADS_ANGLE":                   "threads angle",
    "STORY_ANGLE":                     "story angle",
    "raw_summary":                     "raw",
    "discovery_confidence":            "high",
    "SOURCE_PREMISE_VERIFIED":         "true",
    "FORCE_PUBLISH_OVERRIDE":          "false",
    "FACTUAL_READINESS":               "ready",
    "ADMISSION_STATUS":                "admitted",
}

_STRATEGY_STUB = SimpleNamespace(
    strategy_id="2026-07-presence-debt-campaign-1",
    strategy_version="1",
    started_at=date(2026, 7, 22),
    status=SimpleNamespace(value="active"),
    primary_cta_intent=SimpleNamespace(value="reflection"),
)

_STRATEGY_CONTEXT = {
    "strategy_id":          "2026-07-presence-debt-campaign-1",
    "strategy_name":        "Presence Debt Campaign",
    "primary_message":      "Presence should not depend on your free time",
    "compound_presence_role": "Show systematic presence",
    "target_audience":      "agencies",
}

_FAKE_ARTICLE = {
    "platforms": {
        "long":      {"body": "Blog body text for identity test. presence consistent trust"},
        "medium":    {"body": "LinkedIn post for identity test. presence compound"},
        "reading":   {"body": "Facebook post for identity test."},
        "instagram": {"body": "Instagram caption for identity test."},
    },
    "structured_article": {
        "hook":                  "Identity is propagated.",
        "surviving_explanation": "The run_id flows through every boundary.",
        "reframe":               "This is provenance.",
        "echo_line":             "Trace it.",
        "discovery":             {"aha_setup": "run_id was missing everywhere."},
    },
}


def _make_formatting_mock():
    m = mock.MagicMock()
    m.source_line.return_value = ""
    m.append_hashtags.side_effect = lambda text, hashtags: text
    m.bold_signature_prefix.side_effect = lambda text, style: text
    return m


def _make_assignment(signal=None):
    return from_jsonl_signal(
        signal or _RAW_SIGNAL,
        strategy_ref="2026-07-presence-debt-campaign-1",
        strategy_version="1",
        submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


def _make_run_ctx(assignment=None):
    ca = assignment or _make_assignment()
    return RunContext.from_assignment(ca, ExecutionMode.DRY_RUN)


from tests import test_generate_and_publish as legacy


def _base_patches(*, dry_run: bool = True, from_package: bool = False) -> tuple[list, dict]:
    argv = ["prog", "--signal-id", _SIGNAL_ID]
    if dry_run:
        argv.append("--dry-run")
    if from_package:
        argv.extend(["--from-package", "--source-run-id", _valid_package()["run_id"]])

    def _blrc_real(assignment, raw_signal, run_ctx):
        return _build_legacy_research_context(assignment, raw_signal, run_ctx)

    kwargs = {
        "execute_and_persist_research": mock.MagicMock(
            return_value=mock.MagicMock(signal_id=_SIGNAL_ID)
        ),
        "ExaResearchAdapter": mock.MagicMock(return_value=mock.sentinel.provider),
        "load_research_envelope": mock.MagicMock(return_value=mock.MagicMock()),
        "validate_research_envelope": mock.MagicMock(
            return_value=mock.MagicMock(signal_id=_SIGNAL_ID)
        ),
        # Decision Lens gate (Issue #60): PROCEED-shaped stand-in; the real
        # gate is covered by tests/test_decision_lifecycle.py.
        "production_evaluator": mock.MagicMock(return_value=mock.sentinel.decision_evaluator),
        "evaluate_and_persist_decision": mock.MagicMock(return_value=legacy._FAKE_DECISION),
        "load_decision_artifact": mock.MagicMock(return_value=legacy._FAKE_DECISION),
        "run_editorial_acceptance": mock.MagicMock(side_effect=legacy._fake_acceptance),
        "accept_linkedin_composition": mock.MagicMock(side_effect=legacy._fake_linkedin_composition),
        "write_linkedin_composition_json": mock.MagicMock(),
        "load_active_strategy":      mock.MagicMock(return_value=_STRATEGY_STUB),
        "get_strategy_context":      mock.MagicMock(return_value=_STRATEGY_CONTEXT),
        "get_cta_mode":              mock.MagicMock(return_value="reflection"),
        "_load_signal":              mock.MagicMock(return_value=_RAW_SIGNAL),
        "_load_package_images":      mock.MagicMock(return_value={}),
        "generate_article":          mock.MagicMock(return_value=_FAKE_ARTICLE),
        "validate_article_for_publish": mock.MagicMock(return_value=None),
        "_save_generated":           mock.MagicMock(),
        "generate_hashtags":         mock.MagicMock(return_value=[]),
        "append_published_entry":    mock.MagicMock(),
        "run_analytics_pipeline":    mock.MagicMock(
            return_value=mock.MagicMock(
                format_summary=mock.MagicMock(return_value="")
            )
        ),
        "formatting":                _make_formatting_mock(),
        "CURRENT_DESIGN_VERSION":    "test-v1",
        "_emit_run_report":          mock.MagicMock(),
    }
    return argv, kwargs


def _valid_package(run_id: str = _KNOWN_RUN_ID) -> dict:
    return {
        "run_id":              run_id,
        "signal_id":           _SIGNAL_ID,
        "headline":            "Test headline",
        "generated_at":        "2026-08-01T10:00:00+00:00",
        "strategy_id":         "2026-07-presence-debt-campaign-1",
        "strategy_version":    "1",
        "configuration_identity": _test_configuration_identity(),
        "strategy_started_at": "2026-07-22",
        "wix_url":             "",
        "blog_article":        "Blog body. presence consistent compound trust",
        "linkedin_post":       "LinkedIn post. presence compound",
        "facebook_post":       "Facebook post.",
        "instagram_caption":   "Instagram caption.",
        "threads_sequence":    ["A", "B", "C"],
        "telegram_text":       "Telegram text.",
        "echo_line":           "Echo line.",
    }


# ===========================================================================
# TestRequireRunId
# ===========================================================================

class TestRequireRunId:

    @pytest.mark.story9
    def test_empty_string_raises(self):
        with pytest.raises(RuntimeError, match="run_id is missing or blank"):
            _require_run_id("", "test-stage")

    @pytest.mark.story9
    def test_whitespace_only_raises(self):
        with pytest.raises(RuntimeError, match="run_id is missing or blank"):
            _require_run_id("   ", "test-stage")

    @pytest.mark.story9
    def test_valid_uuid4_passes(self):
        _require_run_id(_KNOWN_RUN_ID, "test-stage")

    def test_stage_name_appears_in_error(self):
        with pytest.raises(RuntimeError, match="my-stage"):
            _require_run_id("", "my-stage")


# ===========================================================================
# TestAssertRunIdMatch
# ===========================================================================

class TestAssertRunIdMatch:

    @pytest.mark.story9
    def test_matching_ids_pass(self):
        _assert_run_id_match(_KNOWN_RUN_ID, _KNOWN_RUN_ID, "boundary")

    @pytest.mark.story9
    def test_mismatched_ids_raise(self):
        with pytest.raises(RuntimeError, match="identity mismatch"):
            _assert_run_id_match(_KNOWN_RUN_ID, "other-id", "research-context")

    def test_boundary_name_in_error(self):
        with pytest.raises(RuntimeError, match="research-context"):
            _assert_run_id_match("A", "B", "research-context")

    def test_both_ids_in_error(self):
        with pytest.raises(RuntimeError, match="expected='A'") as exc_info:
            _assert_run_id_match("A", "B", "boundary")
        assert "actual='B'" in str(exc_info.value)


# ===========================================================================
# TestNormalizePublishResult
# ===========================================================================

class TestNormalizePublishResult:

    def _make_result(self, run_id: str = "") -> PublishResult:
        return PublishResult(platform="wix", status=PublishStatus.PUBLISHED, run_id=run_id)

    def test_injects_run_id_when_empty(self):
        r = self._make_result(run_id="")
        out = _normalize_publish_result(r, _KNOWN_RUN_ID, "wix")
        assert out.run_id == _KNOWN_RUN_ID

    def test_passes_when_run_id_already_matches(self):
        r = self._make_result(run_id=_KNOWN_RUN_ID)
        out = _normalize_publish_result(r, _KNOWN_RUN_ID, "wix")
        assert out.run_id == _KNOWN_RUN_ID

    def test_raises_on_mismatch(self):
        r = self._make_result(run_id="wrong-id")
        with pytest.raises(RuntimeError, match="run_id mismatch"):
            _normalize_publish_result(r, _KNOWN_RUN_ID, "wix")

    def test_platform_name_in_mismatch_error(self):
        r = self._make_result(run_id="wrong-id")
        with pytest.raises(RuntimeError, match="wix"):
            _normalize_publish_result(r, _KNOWN_RUN_ID, "wix")

    def test_returns_same_result_object(self):
        r = self._make_result(run_id="")
        out = _normalize_publish_result(r, _KNOWN_RUN_ID, "wix")
        assert out is r


# ===========================================================================
# TestRunContextCreatedOnce
# ===========================================================================

class TestRunContextCreatedOnce:

    def test_run_context_created_exactly_once(self):
        argv, patches = _base_patches(dry_run=True)
        rc_created = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_created.append(rc)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert len(rc_created) == 1

    def test_run_id_is_uuid4(self):
        argv, patches = _base_patches(dry_run=True)
        ids_seen = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            ids_seen.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert len(ids_seen) == 1
        parsed = uuid.UUID(ids_seen[0], version=4)
        assert str(parsed) == ids_seen[0]


# ===========================================================================
# TestResearchContextRunId
# ===========================================================================

class TestResearchContextRunId:

    def test_boundary_injects_run_id(self):
        ca = _make_assignment()
        run_ctx = _make_run_ctx(ca)
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL, run_ctx)
        assert rc.run_id == run_ctx.run_id

    def test_boundary_run_id_is_uuid4(self):
        ca = _make_assignment()
        run_ctx = _make_run_ctx(ca)
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL, run_ctx)
        parsed = uuid.UUID(rc.run_id, version=4)
        assert str(parsed) == rc.run_id

    def test_from_dict_backward_compat_missing_run_id(self):
        rc = ResearchContext.from_dict({"SIGNAL_ID": "x", "CONFIDENCE": "high",
                                        "SOURCE_PREMISE_VERIFIED": "true"})
        assert rc.run_id == ""

    def test_from_dict_populates_run_id_when_present(self):
        raw = {**_RAW_SIGNAL, "run_id": _KNOWN_RUN_ID}
        rc = ResearchContext.from_dict(raw)
        assert rc.run_id == _KNOWN_RUN_ID


# ===========================================================================
# TestEditorialContextRunId
# ===========================================================================

class TestEditorialContextRunId:

    def _make_rc(self, run_id: str = _KNOWN_RUN_ID) -> ResearchContext:
        rc = ResearchContext.from_dict(_RAW_SIGNAL)
        rc.run_id = run_id
        return rc

    def test_to_editorial_propagates_run_id(self):
        rc = self._make_rc(_KNOWN_RUN_ID)
        ec = rc.to_editorial({})
        assert ec.run_id == _KNOWN_RUN_ID

    def test_editorial_context_default_run_id_is_empty(self):
        ec = EditorialContext(
            signal_id="x", headline="x", factual_readiness="ready",
            admission_status="admitted", force_override=False, article_ready=True,
            source_premise_verified="true", approved_override_raw="",
            core_fact="", core_tension="", business_lesson="",
            real_company_example=None, outcome_if_known="", problem_faced="",
            response_taken="", why_this_case_is_interesting="", counter_example="",
            never_blank_angle="", possible_signature_line="", potential_hook="",
            target_audience="founder", linkedin_angle="", blog_angle="",
            threads_angle="", story_angle="", source_name="", source_url="",
            industry="",
        )
        assert ec.run_id == ""

    def test_to_editorial_empty_run_id_propagates(self):
        rc = self._make_rc("")
        ec = rc.to_editorial({})
        assert ec.run_id == ""


# ===========================================================================
# TestVisualArtifactRequest
# ===========================================================================

class TestVisualArtifactRequest:

    def test_carries_run_id(self):
        req = VisualArtifactRequest(
            run_id=_KNOWN_RUN_ID, signal_id=_SIGNAL_ID, design_version="v1"
        )
        assert req.run_id == _KNOWN_RUN_ID

    def test_blocked_by_default(self):
        req = VisualArtifactRequest(
            run_id=_KNOWN_RUN_ID, signal_id=_SIGNAL_ID, design_version="v1"
        )
        assert req.blocked is True

    def test_assert_identity_passes_on_match(self):
        req = VisualArtifactRequest(
            run_id=_KNOWN_RUN_ID, signal_id=_SIGNAL_ID, design_version="v1"
        )
        req.assert_identity(_KNOWN_RUN_ID)  # must not raise

    def test_assert_identity_raises_on_mismatch(self):
        req = VisualArtifactRequest(
            run_id="wrong-id", signal_id=_SIGNAL_ID, design_version="v1"
        )
        with pytest.raises(RuntimeError, match="VisualArtifactRequest run_id mismatch"):
            req.assert_identity(_KNOWN_RUN_ID)

    def test_canonical_path_constructs_visual_request_with_run_id(self):
        """Canonical path must construct VisualArtifactRequest with run_ctx.run_id."""
        argv, patches = _base_patches(dry_run=True)
        vis_reqs = []
        OrigVAR = VisualArtifactRequest

        class SpyVAR(OrigVAR):
            def __init__(self, **kw):
                super().__init__(**kw)
                vis_reqs.append(self)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "VisualArtifactRequest", SpyVAR):
            main()

        assert len(vis_reqs) >= 1
        rc_ids = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_ids.append(rc.run_id)
            return rc

        vis_reqs.clear()
        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "VisualArtifactRequest", SpyVAR), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert len(vis_reqs) == 1
        assert vis_reqs[0].run_id == rc_ids[0]


# ===========================================================================
# TestValidationResultRunId
# ===========================================================================

class TestValidationResultRunId:

    def test_carries_run_id_on_pass(self):
        vr = ValidationResult(platform="blog", run_id=_KNOWN_RUN_ID, passed=True)
        assert vr.run_id == _KNOWN_RUN_ID
        assert vr.passed is True

    def test_carries_run_id_on_fail(self):
        vr = ValidationResult(
            platform="blog", run_id=_KNOWN_RUN_ID, passed=False,
            error_message="too short",
        )
        assert vr.run_id == _KNOWN_RUN_ID
        assert not vr.passed

    def test_canonical_path_produces_validation_result_with_run_id(self, tmp_path):
        argv, patches = _base_patches(dry_run=True)
        del patches["_save_generated"]
        patches["PACKAGES_DIR"] = tmp_path
        vrs_seen: list[ValidationResult] = []
        OrigVR = ValidationResult

        class SpyVR(OrigVR):
            def __init__(self, **kw):
                super().__init__(**kw)
                vrs_seen.append(self)

        rc_ids = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_ids.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "ValidationResult", SpyVR), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert len(vrs_seen) >= 2
        assert len(rc_ids) == 1
        for vr in vrs_seen:
            assert vr.run_id == rc_ids[0]


# ===========================================================================
# TestGeneratedPackageRunId
# ===========================================================================

class TestGeneratedPackageRunId:

    def test_fresh_gen_package_json_contains_run_id(self, tmp_path):
        argv, patches = _base_patches(dry_run=True)
        del patches["_save_generated"]
        patches["PACKAGES_DIR"] = tmp_path

        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            main()

        pkg = json.loads(next((tmp_path / _SIGNAL_ID / "runs").glob("*/generated.json")).read_text())
        assert "run_id" in pkg
        parsed = uuid.UUID(pkg["run_id"], version=4)
        assert str(parsed) == pkg["run_id"]

    def test_package_run_id_matches_run_context(self, tmp_path):
        argv, patches = _base_patches(dry_run=True)
        del patches["_save_generated"]
        patches["PACKAGES_DIR"] = tmp_path
        ids_captured = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            ids_captured.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        pkg = json.loads(next((tmp_path / _SIGNAL_ID / "runs").glob("*/generated.json")).read_text())
        assert len(ids_captured) == 1
        assert pkg["run_id"] == ids_captured[0]

    def test_fresh_gen_package_has_no_generation_run_id_field(self, tmp_path):
        """Fresh-gen: both runs are the same; no separate generation_run_id needed."""
        argv, patches = _base_patches(dry_run=True)
        del patches["_save_generated"]
        patches["PACKAGES_DIR"] = tmp_path

        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            main()

        pkg = json.loads(next((tmp_path / _SIGNAL_ID / "runs").glob("*/generated.json")).read_text())
        assert "generation_run_id" not in pkg


# ===========================================================================
# TestDraftPackageRunId
# ===========================================================================

class TestDraftPackageRunId:

    def test_default_run_id_is_empty(self):
        draft = DraftPackage(
            draft_dir=Path("."), blog_title="t", blog_body="b",
            blog_meta={}, linkedin_text="li", instagram_text="ig",
            facebook_text="fb", threads_sequence=[], telegram_text="tg",
            image_url=None,
        )
        assert draft.run_id == ""

    def test_accepts_explicit_run_id(self):
        draft = DraftPackage(
            draft_dir=Path("."), blog_title="t", blog_body="b",
            blog_meta={}, linkedin_text="li", instagram_text="ig",
            facebook_text="fb", threads_sequence=[], telegram_text="tg",
            image_url=None, run_id=_KNOWN_RUN_ID,
        )
        assert draft.run_id == _KNOWN_RUN_ID

    def test_canonical_path_passes_run_id_to_draft(self, tmp_path):
        argv, patches = _base_patches(dry_run=False)
        patches["PACKAGES_DIR"] = tmp_path
        drafts_seen: list[DraftPackage] = []

        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED)
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED)
        wix_m = mock.MagicMock()
        li_m  = mock.MagicMock()
        wix_m.publish.return_value = wix_r
        li_m.publish.return_value  = li_r

        rc_ids = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_ids.append(rc.run_id)
            return rc

        OrigDP = DraftPackage

        def spy_dp(**kw):
            dp = OrigDP(**kw)
            drafts_seen.append(dp)
            return dp

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing), \
             mock.patch.object(_gap_module, "DraftPackage", spy_dp), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m):
            main()

        assert len(rc_ids) == 1
        assert len(drafts_seen) == 1
        assert drafts_seen[0].run_id == rc_ids[0]


# ===========================================================================
# TestPublishResultRunId
# ===========================================================================

class TestPublishResultRunId:

    def test_default_run_id_is_empty(self):
        r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED)
        assert r.run_id == ""

    def test_to_dict_includes_run_id(self):
        r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED,
                          run_id=_KNOWN_RUN_ID)
        assert r.to_dict()["run_id"] == _KNOWN_RUN_ID

    def test_canonical_path_normalizes_result_run_id(self, tmp_path):
        argv, patches = _base_patches(dry_run=False)
        patches["PACKAGES_DIR"] = tmp_path

        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED)
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED)
        wix_m = mock.MagicMock()
        li_m  = mock.MagicMock()
        wix_m.publish.return_value = wix_r
        li_m.publish.return_value  = li_r

        rc_ids = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_ids.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m):
            main()

        assert len(rc_ids) == 1
        assert wix_r.run_id == rc_ids[0]
        assert li_r.run_id  == rc_ids[0]


# ===========================================================================
# TestFromPackageRunIdentity  (BLOCKER 1)
# ===========================================================================

_GEN_RUN_ID  = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"  # stable generation identity
_PUB_RUN_ID1 = "11111111-2222-4333-8444-555555555555"  # first publication run
_PUB_RUN_ID2 = "22222222-3333-4444-9555-666666666666"  # second publication run
_PUB_RUN_ID3 = "33333333-4444-4555-a666-777777777777"  # third publication run


@pytest.mark.skip(reason="superseded by immutable source-run contract in Task #28")
class TestFromPackageRunIdentity:
    """
    --from-package lifecycle (Option B):

    - generation_run_id is the identity of the run that generated the content.
    - It is stable: it never changes regardless of how many times --from-package
      is invoked on the same package.
    - Each --from-package execution creates a new publication_run_id.
    - A package with a missing or blank run_id (when generation_run_id is absent)
      predates Task #27 and is rejected before image prep.
    - A package with a present but invalid generation_run_id is corrupt and is
      also rejected before image prep.
    """

    def _run_with_pkg(self, pkg: dict, tmp_path: Path) -> int:
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text(
            json.dumps(pkg), encoding="utf-8"
        )
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        patches["_load_package_images"] = mock.MagicMock(return_value={})
        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            return main()

    def test_missing_run_id_fails_before_image_prep(self, tmp_path):
        pkg = _valid_package()
        del pkg["run_id"]
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_blank_run_id_fails_before_image_prep(self, tmp_path):
        pkg = _valid_package(run_id="")
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_whitespace_run_id_fails_before_image_prep(self, tmp_path):
        pkg = _valid_package(run_id="   ")
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_non_string_run_id_fails_before_image_prep(self, tmp_path):
        pkg = _valid_package()
        pkg["run_id"] = 12345
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_valid_run_id_proceeds(self, tmp_path):
        pkg = _valid_package(run_id=_KNOWN_RUN_ID)
        result = self._run_with_pkg(pkg, tmp_path)
        assert result == 0

    def test_from_package_resave_preserves_generation_run_id(self, tmp_path):
        """Re-save after --from-package publish must write generation_run_id != run_id."""
        pkg = _valid_package(run_id=_KNOWN_RUN_ID)
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text(
            json.dumps(pkg), encoding="utf-8"
        )
        argv, patches = _base_patches(dry_run=False, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path

        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED)
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED)
        wix_m = mock.MagicMock(); wix_m.publish.return_value = wix_r
        li_m  = mock.MagicMock(); li_m.publish.return_value  = li_r

        save_calls: list[dict] = []

        def spy_save(*args, **kw):
            save_calls.append(kw)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "_save_generated", spy_save), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m):
            main()

        assert len(save_calls) == 1
        call = save_calls[0]
        # generation_run_id must preserve the original package run_id
        assert call.get("generation_run_id") == _KNOWN_RUN_ID
        # publication run_id must be a different (new) UUID
        assert call.get("run_id") != _KNOWN_RUN_ID
        assert call.get("run_id", "")  # non-empty

    def test_from_package_publication_run_id_is_uuid4(self, tmp_path):
        pkg = _valid_package(run_id=_KNOWN_RUN_ID)
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text(
            json.dumps(pkg), encoding="utf-8"
        )
        argv, patches = _base_patches(dry_run=False, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path

        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED)
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED)
        wix_m = mock.MagicMock(); wix_m.publish.return_value = wix_r
        li_m  = mock.MagicMock(); li_m.publish.return_value  = li_r

        save_calls: list[dict] = []

        def spy_save(*args, **kw):
            save_calls.append(kw)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "_save_generated", spy_save), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m):
            main()

        assert len(save_calls) == 1
        pub_run_id = save_calls[0].get("run_id", "")
        parsed = uuid.UUID(pub_run_id, version=4)
        assert str(parsed) == pub_run_id

    # ── generation_run_id validation when field is present ──────────────────

    def test_present_blank_generation_run_id_fails_before_image_prep(self, tmp_path):
        """A package with generation_run_id="" is corrupt — fail closed."""
        pkg = _valid_package(run_id=_PUB_RUN_ID1)
        pkg["generation_run_id"] = ""
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_present_whitespace_generation_run_id_fails_before_image_prep(self, tmp_path):
        pkg = _valid_package(run_id=_PUB_RUN_ID1)
        pkg["generation_run_id"] = "   "
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_present_null_generation_run_id_fails_before_image_prep(self, tmp_path):
        """JSON null is a present non-string value and must fail closed."""
        pkg = _valid_package(run_id=_PUB_RUN_ID1)
        pkg["generation_run_id"] = None
        img_spy = mock.MagicMock(return_value={})
        wix_spy = mock.MagicMock()
        li_spy  = mock.MagicMock()
        save_spy = mock.MagicMock()
        with mock.patch.object(_gap_module, "_load_package_images", img_spy), \
             mock.patch.object(_gap_module, "WixPublisher", wix_spy), \
             mock.patch.object(_gap_module, "LinkedInPublisher", li_spy), \
             mock.patch.object(_gap_module, "_save_generated", save_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()
        wix_spy.assert_not_called()
        li_spy.assert_not_called()
        save_spy.assert_not_called()

    def test_present_non_string_generation_run_id_fails_before_image_prep(self, tmp_path):
        pkg = _valid_package(run_id=_PUB_RUN_ID1)
        pkg["generation_run_id"] = 99999
        img_spy = mock.MagicMock(return_value={})
        with mock.patch.object(_gap_module, "_load_package_images", img_spy):
            result = self._run_with_pkg(pkg, tmp_path)
        assert result == 1
        img_spy.assert_not_called()

    def test_valid_generation_run_id_field_proceeds(self, tmp_path):
        """A package that already has generation_run_id set proceeds normally."""
        pkg = _valid_package(run_id=_PUB_RUN_ID1)
        pkg["generation_run_id"] = _GEN_RUN_ID
        result = self._run_with_pkg(pkg, tmp_path)
        assert result == 0

    # ── generation_run_id stability across repeated publications ──────────────
    # These tests exercise serialized package JSON across successive executions.

    def _run_live(self, pkg_path: Path, tmp_path: Path, pub_run_id: str) -> dict:
        """
        Run one controlled-live --from-package execution.
        Patches uuid.uuid4 to return pub_run_id so the publication run_id is
        deterministic.  Lets _save_generated write real JSON to tmp_path.
        Returns the package JSON written by that execution.
        """
        fixed_uuid = uuid.UUID(pub_run_id)
        argv, patches = _base_patches(dry_run=False, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        del patches["_save_generated"]   # use real writer

        wix_r = PublishResult(platform="wix",      status=PublishStatus.PUBLISHED)
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED)
        wix_m = mock.MagicMock(); wix_m.publish.return_value = wix_r
        li_m  = mock.MagicMock(); li_m.publish.return_value  = li_r

        with mock.patch("uuid.uuid4", return_value=fixed_uuid), \
             mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m):
            exit_code = main()

        assert exit_code == 0
        return json.loads(pkg_path.read_text(encoding="utf-8"))

    def test_first_publication_promotes_run_id_to_generation_run_id(self, tmp_path):
        """
        First --from-package publish: generation_run_id absent in fresh package.
        After re-save, generation_run_id == original pkg.run_id (_GEN_RUN_ID).
        """
        pkg_path = tmp_path / f"{_SIGNAL_ID}_generated.json"
        initial_pkg = _valid_package(run_id=_GEN_RUN_ID)  # no generation_run_id
        pkg_path.write_text(json.dumps(initial_pkg), encoding="utf-8")

        saved = self._run_live(pkg_path, tmp_path, _PUB_RUN_ID1)

        assert saved["generation_run_id"] == _GEN_RUN_ID
        assert saved["run_id"] == _PUB_RUN_ID1

    def test_second_publication_preserves_original_generation_run_id(self, tmp_path):
        """
        Second --from-package publish: generation_run_id already set in package.
        After re-save, generation_run_id is unchanged (_GEN_RUN_ID), not promoted.
        """
        pkg_path = tmp_path / f"{_SIGNAL_ID}_generated.json"

        # State after first publication
        pkg_after_pub1 = _valid_package(run_id=_PUB_RUN_ID1)
        pkg_after_pub1["generation_run_id"] = _GEN_RUN_ID
        pkg_path.write_text(json.dumps(pkg_after_pub1), encoding="utf-8")

        saved = self._run_live(pkg_path, tmp_path, _PUB_RUN_ID2)

        assert saved["generation_run_id"] == _GEN_RUN_ID, (
            f"generation_run_id must not change on 2nd publish; "
            f"got {saved['generation_run_id']!r}"
        )
        assert saved["run_id"] == _PUB_RUN_ID2

    def test_third_publication_preserves_original_generation_run_id(self, tmp_path):
        """
        Third --from-package publish: generation_run_id remains unchanged from
        the very first publication.
        """
        pkg_path = tmp_path / f"{_SIGNAL_ID}_generated.json"

        # State after second publication
        pkg_after_pub2 = _valid_package(run_id=_PUB_RUN_ID2)
        pkg_after_pub2["generation_run_id"] = _GEN_RUN_ID
        pkg_path.write_text(json.dumps(pkg_after_pub2), encoding="utf-8")

        saved = self._run_live(pkg_path, tmp_path, _PUB_RUN_ID3)

        assert saved["generation_run_id"] == _GEN_RUN_ID, (
            f"generation_run_id must not change on 3rd publish; "
            f"got {saved['generation_run_id']!r}"
        )
        assert saved["run_id"] == _PUB_RUN_ID3

    def test_three_successive_publications_exercise_serialized_json(self, tmp_path):
        """
        Complete serialized three-round test.
        Runs three successive --from-package executions, each reading the package
        written by the previous one.  Asserts:
        - generation_run_id is identical in all three saved packages (_GEN_RUN_ID);
        - run_id is unique in each saved package (new UUID per publication);
        - no publication run_id is ever promoted to generation_run_id.
        """
        pkg_path = tmp_path / f"{_SIGNAL_ID}_generated.json"

        # Seed: fresh package with only run_id (no generation_run_id)
        pkg_path.write_text(
            json.dumps(_valid_package(run_id=_GEN_RUN_ID)), encoding="utf-8"
        )

        for round_n, pub_id in enumerate(
            [_PUB_RUN_ID1, _PUB_RUN_ID2, _PUB_RUN_ID3], start=1
        ):
            saved = self._run_live(pkg_path, tmp_path, pub_id)

            assert saved["generation_run_id"] == _GEN_RUN_ID, (
                f"Round {round_n}: generation_run_id changed to {saved['generation_run_id']!r}"
            )
            assert saved["run_id"] == pub_id, (
                f"Round {round_n}: publication run_id {saved['run_id']!r} != {pub_id!r}"
            )

        # Confirm: no publication run_id was ever written as generation_run_id
        final = json.loads(pkg_path.read_text(encoding="utf-8"))
        assert final["generation_run_id"] == _GEN_RUN_ID
        assert final["run_id"] == _PUB_RUN_ID3
        assert _PUB_RUN_ID1 not in (final["generation_run_id"],)
        assert _PUB_RUN_ID2 not in (final["generation_run_id"],)

    def test_every_publication_receives_distinct_run_id(self, tmp_path):
        """Each successive publication creates a new unique run_id."""
        pkg_path = tmp_path / f"{_SIGNAL_ID}_generated.json"
        pkg_path.write_text(
            json.dumps(_valid_package(run_id=_GEN_RUN_ID)), encoding="utf-8"
        )

        seen_run_ids = {_GEN_RUN_ID}
        for pub_id in [_PUB_RUN_ID1, _PUB_RUN_ID2, _PUB_RUN_ID3]:
            saved = self._run_live(pkg_path, tmp_path, pub_id)
            assert saved["run_id"] not in seen_run_ids, (
                f"run_id {saved['run_id']!r} was reused across publications"
            )
            seen_run_ids.add(saved["run_id"])


# ===========================================================================
# TestMismatchRejected  (BLOCKER 3)
# ===========================================================================

class TestMismatchRejected:

    @pytest.mark.story9
    def test_research_context_run_id_mismatch_raises(self):
        """If compatibility boundary returns wrong run_id, _assert_run_id_match raises."""
        ca = _make_assignment()
        run_ctx = _make_run_ctx(ca)

        # Force rc.run_id to a different value
        bad_rc = ResearchContext.from_dict(_RAW_SIGNAL)
        bad_rc.run_id = "completely-wrong-id"

        with mock.patch.object(
            _gap_module, "_build_legacy_research_context", return_value=bad_rc
        ):
            argv, patches = _base_patches(dry_run=True)
            with mock.patch("sys.argv", argv), \
                 mock.patch.multiple(_gap_module, **patches):
                with pytest.raises(RuntimeError, match="research-context"):
                    main()

    @pytest.mark.story9
    def test_draft_package_run_id_mismatch_raises(self):
        """If DraftPackage is constructed with wrong run_id, _assert_run_id_match raises."""
        argv, patches = _base_patches(dry_run=False)

        orig_dp_init = DraftPackage.__init__

        def bad_dp_init(self, **kw):
            kw["run_id"] = "wrong-id"
            orig_dp_init(self, **kw)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(DraftPackage, "__init__", bad_dp_init):
            with pytest.raises(RuntimeError, match="draft-package"):
                main()

    @pytest.mark.story9
    def test_publish_result_mismatch_fails_publisher_not_silently_accepted(self, tmp_path):
        """
        _normalize_publish_result raises on mismatch; the publisher loop catches
        it and records FAILED — the run exits with code 1 and the error message
        names the mismatch.  The conflicting run_id is never silently accepted.
        """
        argv, patches = _base_patches(dry_run=False)
        patches["PACKAGES_DIR"] = tmp_path

        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED,
                              run_id="bad-publisher-id")
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED)
        wix_m = mock.MagicMock(); wix_m.publish.return_value = wix_r
        li_m  = mock.MagicMock();  li_m.publish.return_value  = li_r

        results_dict: list[dict] = []
        orig_save = _gap_module._save_generated.__wrapped__ if hasattr(
            _gap_module._save_generated, "__wrapped__"
        ) else None

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m) as _li_p:
            exit_code = main()

        # Mismatch must cause FAILED exit (not silent success)
        assert exit_code == 1


# ===========================================================================
# TestFailClosedBeforeImages
# ===========================================================================

class TestFailClosedBeforeImages:

    @pytest.mark.story9
    def test_require_run_id_evaluated_before_load_package_images(self):
        argv, patches = _base_patches(dry_run=True)
        sentinel_images = mock.MagicMock(return_value={})
        patches["_load_package_images"] = sentinel_images
        patches["_require_run_id"] = mock.MagicMock(
            side_effect=RuntimeError("blank run_id")
        )

        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            with pytest.raises(RuntimeError, match="blank run_id"):
                main()

        sentinel_images.assert_not_called()


# ===========================================================================
# TestFailClosedBeforePublisher
# ===========================================================================

class TestFailClosedBeforePublisher:

    @pytest.mark.story9
    def test_require_run_id_at_publication_blocks_publisher_construction(self):
        argv, patches = _base_patches(dry_run=False)
        wix_cls = mock.MagicMock()
        li_cls  = mock.MagicMock()
        call_count = [0]
        orig_require = _gap_module._require_run_id

        def staged_require(run_id, stage):
            call_count[0] += 1
            if stage == "publication":
                raise RuntimeError("blank run_id at publication")
            orig_require(run_id, stage)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "_require_run_id", side_effect=staged_require), \
             mock.patch.object(_gap_module, "WixPublisher", wix_cls), \
             mock.patch.object(_gap_module, "LinkedInPublisher", li_cls):
            with pytest.raises(RuntimeError, match="publication"):
                main()

        wix_cls.assert_not_called()
        li_cls.assert_not_called()


# ===========================================================================
# TestR1RunReportBoundary
# ===========================================================================

class TestR1RunReportBoundary:

    def test_carries_run_id(self):
        r = R1RunReport(run_id=_KNOWN_RUN_ID, signal_id=_SIGNAL_ID,
                        execution_mode="dry-run")
        assert r.run_id == _KNOWN_RUN_ID

    def test_ok_when_completed_no_errors(self):
        r = R1RunReport(run_id=_KNOWN_RUN_ID, signal_id=_SIGNAL_ID,
                        execution_mode="dry-run", completed=True)
        assert r.ok()

    def test_not_ok_with_errors(self):
        r = R1RunReport(run_id=_KNOWN_RUN_ID, signal_id=_SIGNAL_ID,
                        execution_mode="dry-run", completed=True,
                        errors=["something failed"])
        assert not r.ok()

    def test_canonical_path_emits_run_report_with_correct_run_id(self):
        argv, patches = _base_patches(dry_run=True)
        reports_seen: list[R1RunReport] = []

        def spy_emit(report):
            reports_seen.append(report)

        rc_ids = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_ids.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "_emit_run_report", spy_emit), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert len(reports_seen) == 1
        assert len(rc_ids) == 1
        assert reports_seen[0].run_id == rc_ids[0]
        assert reports_seen[0].signal_id == _SIGNAL_ID

    def test_run_report_completed_on_success(self):
        argv, patches = _base_patches(dry_run=True)
        reports_seen: list[R1RunReport] = []

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "_emit_run_report",
                               side_effect=lambda r: reports_seen.append(r)):
            main()

        assert reports_seen[0].completed is True


# ===========================================================================
# TestCompletePathRunIdentityContract  (BLOCKER 5)
# ===========================================================================

class TestCompletePathRunIdentityContract:
    """
    Single canonical-path contract test.

    Patches uuid.uuid4 to return a fixed UUID so _KNOWN_RUN_ID is used
    everywhere.  Traces that exact value through every named boundary:

      intake → ResearchContext → EditorialContext → generated JSON →
      VisualArtifactRequest → ValidationResult → DraftPackage →
      PublishResult (normalized) → R1RunReport

    Asserts:
    - RunContext created exactly once
    - No stage creates a replacement run_id
    - Every boundary carries _KNOWN_RUN_ID
    """

    @pytest.mark.story9
    def test_known_run_id_at_every_named_boundary(self, tmp_path):
        fixed_uuid = uuid.UUID(_KNOWN_RUN_ID)

        argv, patches = _base_patches(dry_run=False)
        patches["PACKAGES_DIR"] = tmp_path
        # Don't mock _save_generated: let it write to tmp_path so we can read the JSON.
        del patches["_save_generated"]
        # Don't mock _emit_run_report: spy instead.

        # — Capture boundary values —
        rc_ids: list[str]  = []
        ec_ids: list[str]  = []
        vis_ids: list[str] = []
        vr_ids: list[str]  = []
        draft_ids: list[str] = []
        report_ids: list[str] = []

        # Spy: ResearchContext boundary via _build_legacy_research_context
        orig_blrc = _build_legacy_research_context
        def spy_blrc(assignment, raw_signal, run_ctx):
            rc = orig_blrc(assignment, raw_signal, run_ctx)
            rc_ids.append(rc.run_id)
            return rc

        # Spy: EditorialContext boundary via ResearchContext.to_editorial
        orig_to_editorial = ResearchContext.to_editorial
        def spy_to_editorial(self, *args, **kwargs):
            ec = orig_to_editorial(self, *args, **kwargs)
            ec_ids.append(ec.run_id)
            return ec

        # Spy: VisualArtifactRequest constructor
        OrigVAR = VisualArtifactRequest
        class SpyVAR(OrigVAR):
            def __init__(self, **kw):
                super().__init__(**kw)
                vis_ids.append(self.run_id)

        # Spy: ValidationResult constructor
        OrigVR = ValidationResult
        class SpyVR(OrigVR):
            def __init__(self, **kw):
                super().__init__(**kw)
                vr_ids.append(self.run_id)

        # Spy: DraftPackage constructor
        OrigDP = DraftPackage
        def spy_dp(**kw):
            dp = OrigDP(**kw)
            draft_ids.append(dp.run_id)
            return dp

        # Spy: _emit_run_report
        def spy_emit(report):
            report_ids.append(report.run_id)

        # Mock publishers — return empty run_id so normalizer injects it
        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED,
                              external_id="wix-1", url="https://example.com/w")
        li_r  = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED,
                              external_id="li-1",  url="https://linkedin.com/l")
        wix_m = mock.MagicMock(); wix_m.publish.return_value = wix_r
        li_m  = mock.MagicMock(); li_m.publish.return_value  = li_r

        rc_creation_count = [0]
        orig_from_assignment = RunContext.from_assignment.__func__

        @classmethod
        def spy_from_assignment(cls, *args, **kw):
            rc = orig_from_assignment(cls, *args, **kw)
            rc_creation_count[0] += 1
            return rc

        with mock.patch("uuid.uuid4", return_value=fixed_uuid), \
             mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "_build_legacy_research_context", spy_blrc), \
             mock.patch.object(_gap_module, "VisualArtifactRequest", SpyVAR), \
             mock.patch.object(_gap_module, "ValidationResult", SpyVR), \
             mock.patch.object(_gap_module, "DraftPackage", spy_dp), \
             mock.patch.object(_gap_module, "_emit_run_report", spy_emit), \
             mock.patch.object(RunContext, "from_assignment", spy_from_assignment), \
             mock.patch.object(ResearchContext, "to_editorial", spy_to_editorial), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_m), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_m):
            exit_code = main()

        assert exit_code == 0

        # RunContext created exactly once
        assert rc_creation_count[0] == 1

        # Boundary 1: ResearchContext
        assert rc_ids == [_KNOWN_RUN_ID], f"ResearchContext run_ids: {rc_ids}"

        # Boundary 2: EditorialContext
        assert ec_ids == [_KNOWN_RUN_ID], f"EditorialContext run_ids: {ec_ids}"

        # Boundary 3: Generated JSON
        pkg = json.loads((tmp_path / _SIGNAL_ID / "runs" / _KNOWN_RUN_ID / "generated.json").read_text())
        assert pkg["run_id"] == _KNOWN_RUN_ID, f"Generated JSON run_id: {pkg['run_id']}"

        # Boundary 4: VisualArtifactRequest
        assert vis_ids == [_KNOWN_RUN_ID], f"VisualArtifactRequest run_ids: {vis_ids}"

        # Boundary 5: ValidationResult (one per platform validated)
        assert len(vr_ids) >= 2
        assert all(rid == _KNOWN_RUN_ID for rid in vr_ids), f"ValidationResult run_ids: {vr_ids}"

        # Boundary 6: DraftPackage
        assert draft_ids == [_KNOWN_RUN_ID], f"DraftPackage run_ids: {draft_ids}"

        # Boundary 7: PublishResult (normalized — injected from empty by _normalize_publish_result)
        assert wix_r.run_id == _KNOWN_RUN_ID, f"Wix PublishResult run_id: {wix_r.run_id}"
        assert li_r.run_id  == _KNOWN_RUN_ID, f"LinkedIn PublishResult run_id: {li_r.run_id}"

        # Boundary 8: R1RunReport
        assert report_ids == [_KNOWN_RUN_ID], f"R1RunReport run_ids: {report_ids}"

        # No replacement run_id was generated at any boundary
        all_ids = rc_ids + ec_ids + vis_ids + vr_ids + draft_ids + report_ids
        assert all(rid == _KNOWN_RUN_ID for rid in all_ids), (
            f"Some boundary returned wrong run_id: {all_ids}"
        )
