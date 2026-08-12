"""
Task #27 — Run identity propagation integration tests.

These tests inject one known synthetic run_id and trace that exact value
through the complete non-live canonical path, asserting it at every named
Release 1 boundary:

  1. RunContext (created once, intake boundary)
  2. ResearchContext (compatibility boundary)
  3. EditorialContext (editorial boundary)
  4. Generated-package JSON (persistence boundary)
  5. DraftPackage (publication package boundary)
  6. PublishResult (publisher result boundary)

Fail-closed tests prove that _require_run_id raises before image preparation
and publisher construction when run_id is blank.

Visual artifact metadata (boundary 5 in the audit) is owned by the Visual
System story and is not tested here.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_and_publish import (
    _build_legacy_research_context,
    _require_run_id,
    main,
)
from src.intake import from_jsonl_signal
from src.lifecycle.signal_lifecycle import EditorialContext, ResearchContext
from src.publishing.base import DraftPackage
from src.publishing.result import PublishResult, PublishStatus
from src.run.run_context import ExecutionMode, RunContext
from src.reporting import R1RunReport

import scripts.generate_and_publish as _gap_module


# ---------------------------------------------------------------------------
# Shared fakes — same signal / strategy as test_generate_and_publish.py
# ---------------------------------------------------------------------------

_SIGNAL_ID = "sig-identity-test-001"
_KNOWN_RUN_ID = "11111111-2222-4333-8444-555555555555"

_RAW_SIGNAL = {
    "SIGNAL_ID": _SIGNAL_ID,
    "HEADLINE": "Run identity propagation test signal",
    "CORE_FACT": "Synthetic fact for identity tracing.",
    "ARTICLE_READY": "true",
    "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
    "SIGNAL_TYPE": "market_trend",
    "REGION": "global",
    "INDUSTRY": "technology",
    "SOURCE_NAME": "Test Source",
    "SOURCE_URL": "https://example.com",
    "SOURCE_DATE": "2026-08-11",
    "DATE_FOUND": "2026-08-11",
    "CONFIDENCE": "high",
    "SOURCE_QUALITY": "high",
    "SOURCE_FOR_CASE": "Test Source",
    "REAL_COMPANY_EXAMPLE": "TestCo",
    "OUTCOME_IF_KNOWN": "success",
    "DID_IT_WORK": "yes",
    "EVIDENCE_OF_OUTCOME": "data",
    "NOTES": "",
    "ARTICLE_READINESS_SCORE": "9",
    "SIGNAL_STRENGTH": "high",
    "CHANNEL_FIT_SCORE": "9",
    "DISCUSSION_POTENTIAL": "high",
    "score_reason": "high quality signal",
    "CORE_TENSION": "tension",
    "BUSINESS_LESSON": "lesson",
    "WHY_THIS_CASE_IS_INTERESTING": "interesting",
    "WHY_IT_MATTERS_TO_BUSINESS": "matters",
    "BUSINESS_RESPONSES_OBSERVED": "responses",
    "PROBLEM_FACED": "problem",
    "RESPONSE_TAKEN": "response",
    "COUNTER_EXAMPLE": "none",
    "TIME_HORIZON": "2027",
    "INTERESTING_QUESTION": "Why?",
    "NEVER_BLANK_ANGLE": "angle",
    "POSSIBLE_SIGNATURE_LINE": "signature",
    "POTENTIAL_HOOK": "hook",
    "TARGET_AUDIENCE": "agencies",
    "PRIMARY_CHANNEL": "linkedin",
    "LINKEDIN_ANGLE": "linkedin angle",
    "BLOG_ANGLE": "blog angle",
    "THREADS_ANGLE": "threads angle",
    "STORY_ANGLE": "story angle",
    "raw_summary": "raw",
    "discovery_confidence": "high",
    "SOURCE_PREMISE_VERIFIED": "true",
    "FORCE_PUBLISH_OVERRIDE": "false",
    "FACTUAL_READINESS": "ready",
    "ADMISSION_STATUS": "admitted",
}

_STRATEGY_STUB = SimpleNamespace(
    strategy_id="2026-07-presence-debt-campaign-1",
    strategy_version="1",
    started_at=date(2026, 7, 22),
    status=SimpleNamespace(value="active"),
    primary_cta_intent=SimpleNamespace(value="reflection"),
)

_STRATEGY_CONTEXT = {
    "strategy_id": "2026-07-presence-debt-campaign-1",
    "strategy_name": "Presence Debt Campaign",
    "primary_message": "Presence should not depend on your free time",
    "compound_presence_role": "Show systematic presence",
    "target_audience": "agencies",
}

_FAKE_ARTICLE = {
    "platforms": {
        "long":      {"body": "Blog body text for identity test."},
        "medium":    {"body": "LinkedIn post for identity test."},
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


def _make_ok_publish_result(platform: str):
    r = mock.MagicMock(spec=PublishResult)
    r.ok.return_value = True
    r.external_id = f"{platform}-ext-id"
    r.url = f"https://example.com/{platform}"
    r.run_id = ""  # will be injected by main()
    r.to_dict.return_value = {
        "platform": platform, "status": "PUBLISHED",
        "external_id": f"{platform}-ext-id", "url": f"https://example.com/{platform}",
        "error_message": None, "run_id": "",
    }
    return r


def _base_patches(*, dry_run: bool = True) -> tuple[list, dict]:
    argv = ["prog", "--signal-id", _SIGNAL_ID]
    if dry_run:
        argv.append("--dry-run")
    kwargs = {
        "load_active_strategy": mock.MagicMock(return_value=_STRATEGY_STUB),
        "get_strategy_context": mock.MagicMock(return_value=_STRATEGY_CONTEXT),
        "get_cta_mode": mock.MagicMock(return_value="reflection"),
        "_load_signal": mock.MagicMock(return_value=_RAW_SIGNAL),
        "_load_package_images": mock.MagicMock(return_value={}),
        "generate_article": mock.MagicMock(return_value=_FAKE_ARTICLE),
        "validate_article_for_publish": mock.MagicMock(return_value=None),
        "_save_generated": mock.MagicMock(),
        "generate_hashtags": mock.MagicMock(return_value=[]),
        "append_published_entry": mock.MagicMock(),
        "run_analytics_pipeline": mock.MagicMock(
            return_value=mock.MagicMock(format_summary=mock.MagicMock(return_value=""))
        ),
        "formatting": _make_formatting_mock(),
        "CURRENT_DESIGN_VERSION": "test-v1",
        "_build_legacy_research_context": mock.MagicMock(
            return_value=mock.MagicMock(
                run_id=_KNOWN_RUN_ID,
                to_editorial=mock.MagicMock(
                    return_value=mock.MagicMock(
                        run_id=_KNOWN_RUN_ID,
                        to_legacy_dict=mock.MagicMock(return_value={}),
                    )
                ),
            )
        ),
    }
    return argv, kwargs


# ===========================================================================
# 1. RunContext created exactly once
# ===========================================================================

class TestRunContextCreatedOnce:

    def test_run_context_created_exactly_once_dry_run(self):
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

    def test_run_context_id_is_uuid4(self):
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
# 2. ResearchContext receives run_id via compatibility boundary
# ===========================================================================

class TestResearchContextRunId:

    def test_boundary_injects_run_id_from_run_ctx(self):
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="2026-07-presence-debt-campaign-1",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        run_ctx = RunContext.from_assignment(ca, ExecutionMode.DRY_RUN)
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL, run_ctx)
        assert rc.run_id == run_ctx.run_id

    def test_boundary_run_id_is_uuid4_string(self):
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="2026-07-presence-debt-campaign-1",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        run_ctx = RunContext.from_assignment(ca, ExecutionMode.DRY_RUN)
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL, run_ctx)
        parsed = uuid.UUID(rc.run_id, version=4)
        assert str(parsed) == rc.run_id

    def test_from_dict_backward_compat_missing_run_id_defaults_to_empty(self):
        """Old JSONL records without run_id must deserialize without error."""
        rc = ResearchContext.from_dict({"SIGNAL_ID": "x", "CONFIDENCE": "high",
                                        "SOURCE_PREMISE_VERIFIED": "true"})
        assert rc.run_id == ""

    def test_from_dict_populates_run_id_when_present(self):
        """If a future JSONL record includes run_id it must be preserved."""
        raw = {**_RAW_SIGNAL, "run_id": _KNOWN_RUN_ID}
        rc = ResearchContext.from_dict(raw)
        assert rc.run_id == _KNOWN_RUN_ID


# ===========================================================================
# 3. EditorialContext receives run_id via to_editorial()
# ===========================================================================

class TestEditorialContextRunId:

    def _make_rc(self, run_id: str = _KNOWN_RUN_ID) -> ResearchContext:
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="2026-07-presence-debt-campaign-1",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        rc = ResearchContext.from_dict(_RAW_SIGNAL)
        rc.run_id = run_id
        return rc

    def test_to_editorial_propagates_run_id(self):
        rc = self._make_rc(run_id=_KNOWN_RUN_ID)
        ec = rc.to_editorial({})
        assert ec.run_id == _KNOWN_RUN_ID

    def test_editorial_context_default_run_id_is_empty(self):
        """EditorialContext constructed without run_id gets default ""."""
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

    def test_to_editorial_from_rc_without_run_id_propagates_empty(self):
        """A ResearchContext without run_id (old path) passes empty string through."""
        rc = ResearchContext.from_dict(_RAW_SIGNAL)
        assert rc.run_id == ""
        ec = rc.to_editorial({})
        assert ec.run_id == ""


# ===========================================================================
# 4. Generated-package JSON persists run_id
# ===========================================================================

class TestGeneratedPackageRunId:

    def test_fresh_gen_package_json_contains_run_id(self, tmp_path):
        argv, patches = _base_patches(dry_run=True)
        del patches["_save_generated"]
        patches["PACKAGES_DIR"] = tmp_path

        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            main()

        pkg = json.loads((tmp_path / f"{_SIGNAL_ID}_generated.json").read_text())
        assert "run_id" in pkg
        parsed = uuid.UUID(pkg["run_id"], version=4)
        assert str(parsed) == pkg["run_id"]

    def test_package_run_id_matches_run_context_run_id(self, tmp_path):
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

        pkg = json.loads((tmp_path / f"{_SIGNAL_ID}_generated.json").read_text())
        assert len(ids_captured) == 1
        assert pkg["run_id"] == ids_captured[0]


# ===========================================================================
# 5. DraftPackage carries run_id
# ===========================================================================

class TestDraftPackageRunId:

    def test_draft_package_default_run_id_is_empty(self):
        from src.publishing.base import DraftPackage
        draft = DraftPackage(
            draft_dir=Path("."), blog_title="t", blog_body="b",
            blog_meta={}, linkedin_text="li", instagram_text="ig",
            facebook_text="fb", threads_sequence=[], telegram_text="tg",
            image_url=None,
        )
        assert draft.run_id == ""

    def test_draft_package_accepts_explicit_run_id(self):
        from src.publishing.base import DraftPackage
        draft = DraftPackage(
            draft_dir=Path("."), blog_title="t", blog_body="b",
            blog_meta={}, linkedin_text="li", instagram_text="ig",
            facebook_text="fb", threads_sequence=[], telegram_text="tg",
            image_url=None, run_id=_KNOWN_RUN_ID,
        )
        assert draft.run_id == _KNOWN_RUN_ID

    def test_canonical_path_passes_run_id_to_draft_package(self, tmp_path):
        argv, patches = _base_patches(dry_run=False)
        patches["PACKAGES_DIR"] = tmp_path
        drafts_seen = []

        wix = mock.MagicMock()
        wix.publish.side_effect = lambda draft, mode: (
            drafts_seen.append(draft) or _make_ok_publish_result("wix")
        )
        li = mock.MagicMock()
        li.publish.side_effect = lambda draft, mode: (
            drafts_seen.append(draft) or _make_ok_publish_result("linkedin")
        )

        ids_captured = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            ids_captured.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li):
            main()

        assert len(ids_captured) == 1
        run_id = ids_captured[0]
        wix_draft = drafts_seen[0]
        assert wix_draft.run_id == run_id


# ===========================================================================
# 6. PublishResult carries run_id (injected post-publish)
# ===========================================================================

class TestPublishResultRunId:

    def test_publish_result_default_run_id_is_empty(self):
        result = PublishResult(platform="wix", status=PublishStatus.PUBLISHED)
        assert result.run_id == ""

    def test_publish_result_to_dict_includes_run_id(self):
        result = PublishResult(
            platform="wix", status=PublishStatus.PUBLISHED,
            run_id=_KNOWN_RUN_ID,
        )
        d = result.to_dict()
        assert d["run_id"] == _KNOWN_RUN_ID

    def test_canonical_path_injects_run_id_into_publish_result(self, tmp_path):
        argv, patches = _base_patches(dry_run=False)
        patches["PACKAGES_DIR"] = tmp_path
        wix_results = []
        li_results = []

        wix_mock = mock.MagicMock()
        wix_r = PublishResult(platform="wix", status=PublishStatus.PUBLISHED,
                              external_id="wix-id", url="https://example.com/wix")
        wix_mock.publish.return_value = wix_r

        li_mock = mock.MagicMock()
        li_r = PublishResult(platform="linkedin", status=PublishStatus.PUBLISHED,
                             external_id="li-id", url="https://linkedin.com/post/1")
        li_mock.publish.return_value = li_r

        ids_captured = []
        orig = RunContext.from_assignment.__func__

        @classmethod
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            ids_captured.append(rc.run_id)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_mock), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_mock):
            exit_code = main()

        assert exit_code == 0
        assert len(ids_captured) == 1
        run_id = ids_captured[0]
        # PublishResult instances were mutated in-place by main()
        assert wix_r.run_id == run_id
        assert li_r.run_id == run_id


# ===========================================================================
# Fail-closed: _require_run_id raises on blank/missing
# ===========================================================================

class TestRequireRunId:

    def test_empty_string_raises(self):
        with pytest.raises(RuntimeError, match="run_id is missing or blank"):
            _require_run_id("", "test-stage")

    def test_whitespace_only_raises(self):
        with pytest.raises(RuntimeError, match="run_id is missing or blank"):
            _require_run_id("   ", "test-stage")

    def test_valid_uuid4_passes(self):
        _require_run_id(_KNOWN_RUN_ID, "test-stage")  # must not raise

    def test_stage_name_appears_in_error_message(self):
        with pytest.raises(RuntimeError, match="my-stage"):
            _require_run_id("", "my-stage")


# ===========================================================================
# Fail-closed before image preparation
# ===========================================================================

class TestFailClosedBeforeImagePrep:

    def test_require_run_id_called_before_load_package_images(self, tmp_path):
        """
        Prove that _require_run_id is evaluated before _load_package_images by
        making _require_run_id raise and asserting _load_package_images is not called.
        """
        argv, patches = _base_patches(dry_run=True)
        patches["PACKAGES_DIR"] = tmp_path
        sentinel_images = mock.MagicMock(return_value={})
        patches["_load_package_images"] = sentinel_images

        require_raise = mock.MagicMock(side_effect=RuntimeError("blank run_id"))
        patches["_require_run_id"] = require_raise

        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            with pytest.raises(RuntimeError, match="blank run_id"):
                main()

        sentinel_images.assert_not_called()


# ===========================================================================
# Fail-closed before publisher construction
# ===========================================================================

class TestFailClosedBeforePublisher:

    def test_require_run_id_called_before_publisher_construction(self):
        """
        Patch _require_run_id to raise at 'publication' stage; assert neither
        WixPublisher nor LinkedInPublisher are instantiated.
        """
        argv, patches = _base_patches(dry_run=False)
        wix_cls = mock.MagicMock()
        li_cls = mock.MagicMock()

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
# R1RunReport stub
# ===========================================================================

class TestR1RunReportStub:

    def test_r1_run_report_carries_run_id(self):
        report = R1RunReport(
            run_id=_KNOWN_RUN_ID,
            signal_id=_SIGNAL_ID,
            execution_mode="dry-run",
        )
        assert report.run_id == _KNOWN_RUN_ID

    def test_r1_run_report_ok_when_completed_no_errors(self):
        report = R1RunReport(
            run_id=_KNOWN_RUN_ID,
            signal_id=_SIGNAL_ID,
            execution_mode="dry-run",
            completed=True,
        )
        assert report.ok()

    def test_r1_run_report_not_ok_with_errors(self):
        report = R1RunReport(
            run_id=_KNOWN_RUN_ID,
            signal_id=_SIGNAL_ID,
            execution_mode="dry-run",
            completed=True,
            errors=["something failed"],
        )
        assert not report.ok()
