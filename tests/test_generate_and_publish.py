"""
Focused tests for the canonical Release 1 entry point (Task #26).

Tests A–F per spec. No production credentials, network calls, or real publishing.
"""

from __future__ import annotations

import sys
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_and_publish import (
    _build_legacy_research_context,
    _R1_PUBLISHERS,
    _NON_R1_PUBLISHERS,
    main,
)
from src.intake.content_assignment import ContentAssignment
from src.intake import from_jsonl_signal
from src.run.run_context import ExecutionMode, RunContext
from src.lifecycle.signal_lifecycle import ResearchContext


# ---------------------------------------------------------------------------
# Shared fakes / helpers
# ---------------------------------------------------------------------------

_SIGNAL_ID = "sig-test-001"

_RAW_SIGNAL = {
    "SIGNAL_ID": _SIGNAL_ID,
    "HEADLINE": "AI adoption accelerates in SMBs",
    "CORE_FACT": "According to Gartner, 60 percent of SMBs will adopt AI by 2027.",
    "ARTICLE_READY": "true",
    "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
    "SIGNAL_TYPE": "market_trend",
    "REGION": "global",
    "INDUSTRY": "technology",
    "SOURCE_NAME": "Gartner",
    "SOURCE_URL": "https://gartner.com",
    "SOURCE_DATE": "2026-08-01",
    "DATE_FOUND": "2026-08-11",
    "CONFIDENCE": "high",
    "SOURCE_QUALITY": "high",
    "SOURCE_FOR_CASE": "Gartner",
    "REAL_COMPANY_EXAMPLE": "SMBs",
    "OUTCOME_IF_KNOWN": "adoption",
    "DID_IT_WORK": "yes",
    "EVIDENCE_OF_OUTCOME": "Gartner data",
    "NOTES": "",
    "ARTICLE_READINESS_SCORE": "8",
    "SIGNAL_STRENGTH": "high",
    "CHANNEL_FIT_SCORE": "8",
    "DISCUSSION_POTENTIAL": "high",
    "score_reason": "Strong signal",
    "CORE_TENSION": "AI vs. no AI",
    "BUSINESS_LESSON": "Adopt early",
    "WHY_THIS_CASE_IS_INTERESTING": "Clear data",
    "WHY_IT_MATTERS_TO_BUSINESS": "Competitive",
    "BUSINESS_RESPONSES_OBSERVED": "Adoption",
    "PROBLEM_FACED": "Falling behind",
    "RESPONSE_TAKEN": "AI adoption",
    "COUNTER_EXAMPLE": "None",
    "TIME_HORIZON": "2027",
    "INTERESTING_QUESTION": "Why now?",
    "NEVER_BLANK_ANGLE": "SMB AI",
    "POSSIBLE_SIGNATURE_LINE": "Presence matters",
    "POTENTIAL_HOOK": "60% of SMBs",
    "TARGET_AUDIENCE": "agencies",
    "PRIMARY_CHANNEL": "linkedin",
    "LINKEDIN_ANGLE": "AI angle",
    "BLOG_ANGLE": "Blog angle",
    "THREADS_ANGLE": "Thread angle",
    "STORY_ANGLE": "Story angle",
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
        "long":      {"body": "Blog body text."},
        "medium":    {"body": "LinkedIn post text."},
        "reading":   {"body": "Facebook post text."},
        "instagram": {"body": "Instagram caption text."},
    },
    "structured_article": {
        "hook":                  "60% of SMBs will adopt AI.",
        "surviving_explanation": "The data is clear and compelling.",
        "reframe":               "This is a strategic imperative now.",
        "echo_line":             "Presence matters more than ever.",
        "discovery":             {"aha_setup": "Most SMBs do not realize the gap."},
    },
}


def _valid_package(*, strategy_version: str = "1", **overrides) -> dict:
    """Return a minimal valid _generated.json package dict."""
    pkg = {
        "signal_id":         _SIGNAL_ID,
        "strategy_id":       "2026-07-presence-debt-campaign-1",
        "strategy_version":  strategy_version,
        "generated_at":      "2026-08-11T10:00:00+00:00",
        "headline":          "AI adoption accelerates in SMBs",
        "blog_article":      "Blog body text sufficient for validation.",
        "linkedin_post":     "LinkedIn post text.",
        "facebook_post":     "Facebook post text.",
        "instagram_caption": "Instagram caption.",
        "threads_sequence":  ["Post 1.", "Post 2.", "Post 3."],
        "telegram_text":     "Telegram text.",
        "echo_line":         "They waited.",
    }
    pkg.update(overrides)
    return pkg


def _write_package(tmp_path: Path, pkg: dict | None = None) -> Path:
    """Write package to tmp_path/<signal_id>_generated.json, return path."""
    f = tmp_path / f"{_SIGNAL_ID}_generated.json"
    f.write_text(json.dumps(_valid_package() if pkg is None else pkg), encoding="utf-8")
    return f


def _make_ok_publish_result(platform: str):
    r = mock.MagicMock()
    r.ok.return_value = True
    r.external_id = f"{platform}-post-id"
    r.url = f"https://example.com/{platform}"
    r.to_dict.return_value = {
        "platform": platform, "status": "PUBLISHED",
        "external_id": f"{platform}-post-id", "url": f"https://example.com/{platform}",
        "error_message": None,
    }
    return r


def _make_formatting_mock():
    m = mock.MagicMock()
    m.source_line.return_value = ""
    m.append_hashtags.side_effect = lambda text, hashtags: text
    m.bold_signature_prefix.side_effect = lambda text, style: text
    return m


def _base_patches(*, dry_run: bool = True, from_package: bool = False) -> tuple[list, dict]:
    """
    Returns (argv, module_patch_kwargs).
    module_patch_kwargs go directly to mock.patch.multiple(gap_module, **kwargs).
    formatting is mocked as a whole object — no dotted sub-attribute keys.
    """
    argv = ["prog", "--signal-id", _SIGNAL_ID]
    if dry_run:
        argv.append("--dry-run")
    if from_package:
        argv.append("--from-package")

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
                to_editorial=mock.MagicMock(
                    return_value=mock.MagicMock(
                        to_legacy_dict=mock.MagicMock(return_value={})
                    )
                )
            )
        ),
    }
    return argv, kwargs


import scripts.generate_and_publish as _gap_module


# ===========================================================================
# A. Fresh-generation dry-run
# ===========================================================================

class TestFreshGenerationDryRun:

    def test_creates_content_assignment(self):
        argv, patches = _base_patches(dry_run=True)
        ca_created = []

        def capturing(signal, **kwargs):
            ca = from_jsonl_signal(signal, **kwargs)
            ca_created.append(ca)
            return ca

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "from_jsonl_signal", side_effect=capturing):
            exit_code = main()

        assert exit_code == 0
        assert len(ca_created) == 1
        assert isinstance(ca_created[0], ContentAssignment)
        assert ca_created[0].assignment_id == _SIGNAL_ID

    def test_creates_exactly_one_run_context(self):
        argv, patches = _base_patches(dry_run=True)
        rc_created = []
        orig = RunContext.from_assignment.__func__

        @classmethod  # type: ignore[misc]
        def capturing(cls, assignment, mode, **kwargs):
            rc = orig(cls, assignment, mode, **kwargs)
            rc_created.append(rc)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            exit_code = main()

        assert exit_code == 0
        assert len(rc_created) == 1

    def test_uses_dry_run_execution_mode(self):
        argv, patches = _base_patches(dry_run=True)
        modes_seen = []
        orig = RunContext.from_assignment.__func__

        @classmethod  # type: ignore[misc]
        def capturing(cls, assignment, mode, **kwargs):
            modes_seen.append(mode)
            return orig(cls, assignment, mode, **kwargs)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            exit_code = main()

        assert exit_code == 0
        assert modes_seen == [ExecutionMode.DRY_RUN]

    def test_invokes_no_publisher_in_dry_run(self):
        argv, patches = _base_patches(dry_run=True)
        wix_mock = mock.MagicMock()
        li_mock = mock.MagicMock()

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix_mock), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li_mock):
            exit_code = main()

        assert exit_code == 0
        wix_mock.publish.assert_not_called()
        li_mock.publish.assert_not_called()

    def test_returns_zero_on_success(self):
        argv, patches = _base_patches(dry_run=True)
        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            assert main() == 0

    def test_same_run_id_at_start_and_completion(self, capsys):
        argv, patches = _base_patches(dry_run=True)
        with mock.patch("sys.argv", argv), mock.patch.multiple(_gap_module, **patches):
            main()

        out = capsys.readouterr().out
        run_ids = []
        for line in out.splitlines():
            if "run_id" in line:
                for token in line.split():
                    token = token.strip().rstrip("]").rstrip(":")
                    if len(token) == 36 and token.count("-") == 4:
                        run_ids.append(token)
        assert len(run_ids) >= 2, f"Expected run_id logged at start and completion; got: {out}"
        assert len(set(run_ids)) == 1, f"run_id changed between start and completion: {run_ids}"


# ===========================================================================
# B. Controlled-live
# ===========================================================================

class TestControlledLive:

    def _run_controlled_live(self):
        argv, patches = _base_patches(dry_run=False)
        modes_seen = []
        orig = RunContext.from_assignment.__func__

        @classmethod  # type: ignore[misc]
        def capturing(cls, a, m, **kw):
            modes_seen.append(m)
            return orig(cls, a, m, **kw)

        wix = mock.MagicMock()
        wix.publish.return_value = _make_ok_publish_result("wix")
        li = mock.MagicMock()
        li.publish.return_value = _make_ok_publish_result("linkedin")

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li):
            exit_code = main()

        return exit_code, modes_seen, wix, li

    def test_uses_controlled_live_mode(self):
        _, modes, _, _ = self._run_controlled_live()
        assert modes == [ExecutionMode.CONTROLLED_LIVE]

    def test_invokes_wix_and_linkedin_once_each(self):
        _, _, wix, li = self._run_controlled_live()
        assert wix.publish.call_count == 1
        assert li.publish.call_count == 1

    def test_never_instantiates_non_r1_publishers(self):
        argv, patches = _base_patches(dry_run=False)
        wix = mock.MagicMock()
        wix.publish.return_value = _make_ok_publish_result("wix")
        li = mock.MagicMock()
        li.publish.return_value = _make_ok_publish_result("linkedin")
        fb_cls = mock.MagicMock()
        ig_cls = mock.MagicMock()
        th_cls = mock.MagicMock()
        tg_cls = mock.MagicMock()

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li), \
             mock.patch.object(_gap_module, "FacebookPublisher", fb_cls), \
             mock.patch.object(_gap_module, "InstagramPublisher", ig_cls), \
             mock.patch.object(_gap_module, "ThreadsPublisher", th_cls), \
             mock.patch.object(_gap_module, "TelegramPublisher", tg_cls):
            exit_code = main()

        assert exit_code == 0
        fb_cls.assert_not_called()
        ig_cls.assert_not_called()
        th_cls.assert_not_called()
        tg_cls.assert_not_called()


# ===========================================================================
# C. Non-R1 publisher isolation
# ===========================================================================

class TestNonR1PublisherIsolation:

    def test_r1_publishers_constant(self):
        assert set(_R1_PUBLISHERS) == {"wix", "linkedin"}

    def test_non_r1_publishers_constant(self):
        assert set(_NON_R1_PUBLISHERS) == {"facebook", "instagram", "threads", "telegram"}

    def test_non_r1_failure_does_not_affect_successful_r1_exit_code(self):
        argv, patches = _base_patches(dry_run=False)
        wix = mock.MagicMock()
        wix.publish.return_value = _make_ok_publish_result("wix")
        li = mock.MagicMock()
        li.publish.return_value = _make_ok_publish_result("linkedin")
        # If non-R1 publisher were ever instantiated it would raise — ensuring exit_code==0 proves it wasn't
        fb_cls = mock.MagicMock(side_effect=RuntimeError("non-R1 should not be called"))

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li), \
             mock.patch.object(_gap_module, "FacebookPublisher", fb_cls):
            exit_code = main()

        assert exit_code == 0
        fb_cls.assert_not_called()


# ===========================================================================
# D. --from-package
# ===========================================================================

class TestFromPackage:

    def test_from_package_creates_content_assignment(self, tmp_path):
        _write_package(tmp_path)

        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        ca_created = []

        def capturing(signal, **kwargs):
            ca = from_jsonl_signal(signal, **kwargs)
            ca_created.append(ca)
            return ca

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "from_jsonl_signal", side_effect=capturing):
            exit_code = main()

        assert exit_code == 0
        assert len(ca_created) == 1
        assert isinstance(ca_created[0], ContentAssignment)

    def test_from_package_creates_exactly_one_run_context(self):
        argv, patches = _base_patches(dry_run=True, from_package=True)
        rc_created = []
        orig = RunContext.from_assignment.__func__

        @classmethod  # type: ignore[misc]
        def capturing(cls, a, m, **kw):
            rc = orig(cls, a, m, **kw)
            rc_created.append(rc)
            return rc

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert len(rc_created) == 1

    def test_from_package_with_dry_run_uses_dry_run_mode(self):
        argv, patches = _base_patches(dry_run=True, from_package=True)
        modes = []
        orig = RunContext.from_assignment.__func__

        @classmethod  # type: ignore[misc]
        def capturing(cls, a, m, **kw):
            modes.append(m)
            return orig(cls, a, m, **kw)

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing):
            main()

        assert modes == [ExecutionMode.DRY_RUN]

    def test_from_package_without_dry_run_uses_controlled_live_mode(self):
        argv, patches = _base_patches(dry_run=False, from_package=True)
        modes = []
        orig = RunContext.from_assignment.__func__

        @classmethod  # type: ignore[misc]
        def capturing(cls, a, m, **kw):
            modes.append(m)
            return orig(cls, a, m, **kw)

        wix = mock.MagicMock()
        wix.publish.return_value = _make_ok_publish_result("wix")
        li = mock.MagicMock()
        li.publish.return_value = _make_ok_publish_result("linkedin")

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(RunContext, "from_assignment", capturing), \
             mock.patch.object(_gap_module, "WixPublisher", return_value=wix), \
             mock.patch.object(_gap_module, "LinkedInPublisher", return_value=li):
            main()

        assert modes == [ExecutionMode.CONTROLLED_LIVE]


# ===========================================================================
# E. Compatibility boundary
# ===========================================================================

class TestCompatibilityBoundary:

    def test_matching_ids_succeed(self):
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="2026-07-presence-debt-campaign-1",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL)
        assert isinstance(rc, ResearchContext)
        assert rc.signal_id == _SIGNAL_ID

    def test_mismatched_ids_fail_closed(self):
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="r",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        different_signal = {**_RAW_SIGNAL, "SIGNAL_ID": "sig-different-999"}
        with pytest.raises(ValueError, match="does not match"):
            _build_legacy_research_context(ca, different_signal)

    def test_main_does_not_bypass_compatibility_boundary(self):
        """
        main() must not call ResearchContext.from_dict directly.
        The only route is through _build_legacy_research_context.
        """
        import inspect
        src = inspect.getsource(_gap_module.main)
        assert "ResearchContext.from_dict" not in src


# ===========================================================================
# F. Discovery-only path classification
# ===========================================================================

class TestDiscoveryOnlyPath:

    def _research_module_source(self) -> str:
        import inspect
        import scripts.research.run_daily_research as rdm
        return inspect.getsource(rdm)

    def test_has_classification_marker(self):
        src = self._research_module_source()
        assert "_classification" in src

    def test_summary_includes_classification_value(self):
        src = self._research_module_source()
        assert "discovery-preparation-only" in src

    def test_does_not_instantiate_run_context(self):
        """RunContext may appear in comments; it must not be instantiated."""
        src = self._research_module_source()
        assert "RunContext(" not in src
        assert "RunContext.from_assignment" not in src

    def test_print_summary_labels_as_not_release_1(self, capsys):
        from scripts.research.run_daily_research import _print_summary
        _print_summary({
            "date": "2026-08-11",
            "_classification": "discovery-preparation-only",
            "candidates_found": 0,
            "new_signals_added": 0,
            "selected_for_content": 0,
            "duplicates_skipped": 0,
            "sheet_sync": "not_run",
            "archived": 0,
            "top_signals": [],
        })
        out = capsys.readouterr().out
        assert "not a Release 1 canonical run" in out or "discovery" in out.lower()


# ===========================================================================
# BLOCKER 1 — strategy_version provenance in generated packages
# ===========================================================================

class TestStrategyVersionProvenance:

    def _run_fresh_gen_with_real_save(self, tmp_path: Path) -> Path:
        """Run fresh-gen dry-run letting _save_generated write to tmp_path. Return written path."""
        import scripts.generate_and_publish as gap_module
        from scripts.generate_and_publish import _save_generated as real_save

        argv, patches = _base_patches(dry_run=True)
        del patches["_save_generated"]  # let the real one run
        patches["PACKAGES_DIR"] = tmp_path

        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            main()

        return tmp_path / f"{_SIGNAL_ID}_generated.json"

    def test_fresh_gen_persists_exact_strategy_version(self, tmp_path):
        written = self._run_fresh_gen_with_real_save(tmp_path)
        assert written.exists(), "Generated JSON was not written"
        pkg = json.loads(written.read_text())
        assert pkg["strategy_version"] == "1"

    def test_fresh_gen_strategy_version_matches_active_strategy(self, tmp_path):
        written = self._run_fresh_gen_with_real_save(tmp_path)
        pkg = json.loads(written.read_text())
        assert pkg["strategy_version"] == _STRATEGY_STUB.strategy_version

    def test_from_package_matching_version_accepted(self, tmp_path):
        _write_package(tmp_path, _valid_package(strategy_version="1"))
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()

        assert exit_code == 0

    def test_from_package_mismatched_version_fails_before_publisher(self, tmp_path, capsys):
        _write_package(tmp_path, _valid_package(strategy_version="2"))  # active is "1"
        argv, patches = _base_patches(dry_run=False, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        wix_cls = mock.MagicMock()
        li_cls = mock.MagicMock()

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(gap_module, **patches), \
             mock.patch.object(gap_module, "WixPublisher", wix_cls), \
             mock.patch.object(gap_module, "LinkedInPublisher", li_cls):
            exit_code = main()

        assert exit_code == 1
        out = capsys.readouterr().out
        assert "strategy_version" in out and "mismatch" in out
        wix_cls.assert_not_called()
        li_cls.assert_not_called()

    def test_from_package_missing_version_fails_closed(self, tmp_path, capsys):
        pkg = _valid_package()
        del pkg["strategy_version"]
        _write_package(tmp_path, pkg)
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()

        assert exit_code == 1
        out = capsys.readouterr().out
        assert "strategy_version" in out

    def test_from_package_blank_version_fails_closed(self, tmp_path, capsys):
        _write_package(tmp_path, _valid_package(strategy_version=""))
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()

        assert exit_code == 1
        out = capsys.readouterr().out
        assert "strategy_version" in out

    def test_resave_after_publish_preserves_strategy_version(self, tmp_path):
        """After controlled-live publish, re-save must keep strategy_version == "1"."""
        from scripts.generate_and_publish import _save_generated as real_save

        argv, patches = _base_patches(dry_run=False)
        del patches["_save_generated"]
        patches["PACKAGES_DIR"] = tmp_path
        wix = mock.MagicMock()
        wix.publish.return_value = _make_ok_publish_result("wix")
        li = mock.MagicMock()
        li.publish.return_value = _make_ok_publish_result("linkedin")

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(gap_module, **patches), \
             mock.patch.object(gap_module, "WixPublisher", return_value=wix), \
             mock.patch.object(gap_module, "LinkedInPublisher", return_value=li):
            main()

        written = tmp_path / f"{_SIGNAL_ID}_generated.json"
        assert written.exists(), "Re-saved JSON not found"
        pkg = json.loads(written.read_text())
        assert pkg["strategy_version"] == "1"
        assert pkg["strategy_id"] == "2026-07-presence-debt-campaign-1"


# ===========================================================================
# BLOCKER 2 — validation in --from-package path
# ===========================================================================

class TestFromPackageValidation:

    def test_validation_runs_for_blog_content(self, tmp_path):
        _write_package(tmp_path)
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        validate_mock = mock.MagicMock(return_value=None)
        patches["validate_article_for_publish"] = validate_mock

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()

        assert exit_code == 0
        blog_calls = [c for c in validate_mock.call_args_list if c.kwargs.get("platform") == "blog"]
        assert len(blog_calls) == 1

    def test_validation_runs_for_linkedin_content(self, tmp_path):
        _write_package(tmp_path)
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        validate_mock = mock.MagicMock(return_value=None)
        patches["validate_article_for_publish"] = validate_mock

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()

        assert exit_code == 0
        li_calls = [c for c in validate_mock.call_args_list if c.kwargs.get("platform") == "linkedin"]
        assert len(li_calls) == 1

    def test_failing_validation_prevents_publisher_instantiation(self, tmp_path):
        _write_package(tmp_path)
        argv, patches = _base_patches(dry_run=False, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path
        patches["validate_article_for_publish"] = mock.MagicMock(
            side_effect=ValueError("content too short")
        )
        wix_cls = mock.MagicMock()
        li_cls = mock.MagicMock()

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(gap_module, **patches), \
             mock.patch.object(gap_module, "WixPublisher", wix_cls), \
             mock.patch.object(gap_module, "LinkedInPublisher", li_cls):
            exit_code = main()

        assert exit_code == 1
        wix_cls.assert_not_called()
        li_cls.assert_not_called()

    def test_dry_run_from_package_message_is_truthful(self, tmp_path, capsys):
        _write_package(tmp_path)
        argv, patches = _base_patches(dry_run=True, from_package=True)
        patches["PACKAGES_DIR"] = tmp_path

        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "existing package loaded and validated" in out
        assert "generation" not in out.lower() or "not published" in out


# ===========================================================================
# Sequencing — --from-package failures happen before image side effects
# ===========================================================================

class TestFromPackageSequencing:
    """
    Package existence, JSON parsing, provenance/staleness, and content validation
    must all fail BEFORE _load_package_images() or prepare_content_packages() run.
    No source-text assertions — behaviour is verified by mock call counts.
    """

    def _patches_with_image_sentinels(self, *, dry_run: bool = True, from_package: bool = True):
        """Base patches with _load_package_images as a sentinel mock."""
        argv, patches = _base_patches(dry_run=dry_run, from_package=from_package)
        load_images_sentinel = mock.MagicMock(return_value={})
        patches["_load_package_images"] = load_images_sentinel
        return argv, patches, load_images_sentinel

    def _run(self, argv, patches, tmp_path, extra_ctx=()):
        import scripts.generate_and_publish as gap_module
        patches["PACKAGES_DIR"] = tmp_path
        ctx_managers = [
            mock.patch("sys.argv", argv),
            mock.patch.multiple(gap_module, **patches),
        ] + list(extra_ctx)
        with ctx_managers[0]:
            with ctx_managers[1]:
                for cm in ctx_managers[2:]:
                    cm.__enter__()
                exit_code = main()
                for cm in reversed(ctx_managers[2:]):
                    cm.__exit__(None, None, None)
        return exit_code

    def _run_simple(self, argv, patches, tmp_path):
        import scripts.generate_and_publish as gap_module
        patches["PACKAGES_DIR"] = tmp_path
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            return main()

    def test_missing_package_does_not_call_load_package_images(self, tmp_path):
        argv, patches, sentinel = self._patches_with_image_sentinels()
        # tmp_path is empty — no generated file
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_malformed_json_does_not_call_load_package_images(self, tmp_path):
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text("{not valid json", encoding="utf-8")
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_malformed_json_returns_1_not_traceback(self, tmp_path):
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text("[}", encoding="utf-8")
        argv, patches, sentinel = self._patches_with_image_sentinels()
        # Should not raise — controlled failure only
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1

    def test_missing_strategy_version_does_not_call_load_package_images(self, tmp_path):
        pkg = _valid_package()
        del pkg["strategy_version"]
        _write_package(tmp_path, pkg)
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_mismatched_strategy_version_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(strategy_version="99"))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_stale_generated_at_does_not_call_load_package_images(self, tmp_path):
        # strategy started 2026-07-22; a package from 2026-07-01 is stale
        _write_package(tmp_path, _valid_package(generated_at="2026-07-01T00:00:00+00:00"))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_failed_validation_does_not_instantiate_publishers(self, tmp_path):
        _write_package(tmp_path)
        argv, patches, sentinel = self._patches_with_image_sentinels(dry_run=False)
        patches["validate_article_for_publish"] = mock.MagicMock(
            side_effect=ValueError("too short")
        )
        wix_cls = mock.MagicMock()
        li_cls = mock.MagicMock()

        import scripts.generate_and_publish as gap_module
        patches["PACKAGES_DIR"] = tmp_path
        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(gap_module, **patches), \
             mock.patch.object(gap_module, "WixPublisher", wix_cls), \
             mock.patch.object(gap_module, "LinkedInPublisher", li_cls):
            exit_code = main()

        assert exit_code == 1
        wix_cls.assert_not_called()
        li_cls.assert_not_called()

    def test_json_array_does_not_call_load_package_images(self, tmp_path):
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text("[]", encoding="utf-8")
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_json_null_does_not_call_load_package_images(self, tmp_path):
        (tmp_path / f"{_SIGNAL_ID}_generated.json").write_text("null", encoding="utf-8")
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_strategy_id_does_not_call_load_package_images(self, tmp_path):
        pkg = _valid_package()
        pkg["strategy_id"] = 123
        _write_package(tmp_path, pkg)
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_strategy_version_does_not_call_load_package_images(self, tmp_path):
        pkg = _valid_package()
        pkg["strategy_version"] = 1
        _write_package(tmp_path, pkg)
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_generated_at_does_not_call_load_package_images(self, tmp_path):
        pkg = _valid_package()
        pkg["generated_at"] = 20260811
        _write_package(tmp_path, pkg)
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_fresh_gen_path_still_calls_load_package_images(self, tmp_path):
        """Regression guard: fresh-gen path must still call _load_package_images."""
        argv, patches, sentinel = self._patches_with_image_sentinels(dry_run=True, from_package=False)
        patches["PACKAGES_DIR"] = tmp_path
        import scripts.generate_and_publish as gap_module
        with mock.patch("sys.argv", argv), mock.patch.multiple(gap_module, **patches):
            exit_code = main()
        assert exit_code == 0
        sentinel.assert_called_once()

    # --- BLOCKER 1: signal_id identity ---

    def test_missing_signal_id_does_not_call_load_package_images(self, tmp_path):
        pkg = _valid_package()
        del pkg["signal_id"]
        _write_package(tmp_path, pkg)
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_blank_signal_id_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(signal_id=""))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_signal_id_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(signal_id=999))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_mismatched_signal_id_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(signal_id="wrong-signal-id"))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    # --- BLOCKER 2: R1 content field types ---

    def test_non_string_headline_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(headline=123))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_blog_article_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(blog_article=123))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_linkedin_post_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(linkedin_post=123))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_string_facebook_post_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(facebook_post=False))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()

    def test_non_list_threads_sequence_does_not_call_load_package_images(self, tmp_path):
        _write_package(tmp_path, _valid_package(threads_sequence="not a list"))
        argv, patches, sentinel = self._patches_with_image_sentinels()
        exit_code = self._run_simple(argv, patches, tmp_path)
        assert exit_code == 1
        sentinel.assert_not_called()
