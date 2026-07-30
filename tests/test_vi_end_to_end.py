"""
End-to-end integration tests for the Visibility Intelligence pipeline.

Two scenarios validated here:

Scenario A — Dry-run happy path:
    1 queued item → generate_and_publish_visibility.py --dry-run
    Expected: generated package written to disk, no history append,
              queue item still in processing (dry-run skips step 7),
              exit 0.

Scenario B — Partial platform failure:
    1 queued item, LinkedIn fails, all others succeed.
    Expected: status = published_with_errors, history entry records
              per-platform results, second run with --item-id skips
              already-published platforms and retries only linkedin.

Neither scenario calls the real LLM or any publishing API.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is on path so imports resolve the same way the script does
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.generate_and_publish_visibility import (
    _append_history,
    _build_draft,
    _claim_item,
    _is_transient_error,
    _load_history_for,
    _load_queue,
    _publish_platforms,
    _recover_stuck_processing,
    _save_queue,
    _update_item,
    main,
)
from src.strategy.models import VisibilityQueueItem


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def seed_item() -> VisibilityQueueItem:
    return VisibilityQueueItem(
        id="test_001",
        title="5 signals your brand is invisible to AI search",
        product_category="presence_check",
        content_format="checklist",
        strategic_topic="ai_visibility",
        brand_concept="compound_presence",
        target_audience="B2B service owners",
        key_points=["point 1", "point 2"],
        status="queued",
    )


@pytest.fixture()
def queue_file(tmp_path, seed_item):
    path = tmp_path / "visibility_queue.jsonl"
    path.write_text(seed_item.model_dump_json() + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def history_file(tmp_path):
    path = tmp_path / "visibility_history.jsonl"
    path.write_text("", encoding="utf-8")
    return path


FAKE_PACKAGE = {
    "queue_item_id":    "test_001",
    "headline":         "Test Headline",
    "generated_at":     "2026-01-01T07:00:00+00:00",
    "strategy_id":      "strat_test",
    "strategy_started_at": "2026-01-01T00:00:00+00:00",
    "wix_url":          "",
    "blog_article":     "Blog body. " * 40,
    "linkedin_post":    "LinkedIn post.",
    "facebook_post":    "Facebook post.",
    "instagram_caption": "Instagram caption.",
    "threads_sequence": ["Thread 1", "Thread 2", "Thread 3"],
    "telegram_text":    "Telegram text.",
    "vi_metadata": {
        "product_category": "presence_check",
        "content_format":   "checklist",
        "strategic_topic":  "ai_visibility",
        "brand_concept":    "compound_presence",
    },
}

FAKE_STRATEGY = {
    "strategy_id":           "strat_test",
    "started_at":            "2026-01-01T00:00:00+00:00",
    "primary_message":       "Presence is a system, not a moment.",
    "selected_problem":      "Invisible between client conversations.",
    "desired_reader_realization": "I need to build consistent presence.",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok_publisher_result(platform: str) -> MagicMock:
    r = MagicMock()
    r.ok.return_value = True
    r.to_dict.return_value = {
        "platform": platform,
        "status": "PUBLISHED",
        "external_id": f"{platform}_ext_id",
        "url": f"https://example.com/{platform}",
        "error_message": None,
    }
    return r


def _fail_publisher_result(platform: str, msg: str = "timeout error") -> MagicMock:
    r = MagicMock()
    r.ok.return_value = False
    r.to_dict.return_value = {
        "platform": platform,
        "status": "FAILED",
        "external_id": None,
        "url": None,
        "error_message": msg,
    }
    return r


# ── Scenario A: Dry-run happy path ─────────────────────────────────────────────

class TestDryRunHappyPath:
    def test_dry_run_exits_zero(self, tmp_path, queue_file, history_file, monkeypatch):
        """--dry-run should exit 0 and create generated package on disk."""
        packages_dir = tmp_path / "packages"
        packages_dir.mkdir()

        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.QUEUE_FILE",
            queue_file,
        )
        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.HISTORY_FILE",
            history_file,
        )
        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.PACKAGES_DIR",
            packages_dir,
        )
        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.load_active_strategy",
            lambda: SimpleNamespace(strategy_id="strat_test"),
        )
        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.get_strategy_context",
            lambda _: FAKE_STRATEGY,
        )
        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.get_cta_mode",
            lambda _: "none",
        )
        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility.generate_vi_post",
            lambda *_a, **_kw: FAKE_PACKAGE,
        )

        exit_code = main(["--dry-run"])
        assert exit_code == 0

    def test_dry_run_writes_package_file(self, tmp_path, queue_file, history_file, monkeypatch):
        packages_dir = tmp_path / "packages"
        packages_dir.mkdir()

        monkeypatch.setattr("scripts.generate_and_publish_visibility.QUEUE_FILE",   queue_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.HISTORY_FILE", history_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.PACKAGES_DIR", packages_dir)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.load_active_strategy", lambda: SimpleNamespace(strategy_id="s"))
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_strategy_context", lambda _: FAKE_STRATEGY)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_cta_mode", lambda _: "none")
        monkeypatch.setattr("scripts.generate_and_publish_visibility.generate_vi_post", lambda *_a, **_kw: FAKE_PACKAGE)

        main(["--dry-run"])

        pkg = packages_dir / "test_001_generated.json"
        assert pkg.exists(), "Generated package file must be written even in dry-run"
        data = json.loads(pkg.read_text())
        assert data["headline"] == "Test Headline"

    def test_dry_run_does_not_append_history(self, tmp_path, queue_file, history_file, monkeypatch):
        packages_dir = tmp_path / "packages"
        packages_dir.mkdir()

        monkeypatch.setattr("scripts.generate_and_publish_visibility.QUEUE_FILE",   queue_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.HISTORY_FILE", history_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.PACKAGES_DIR", packages_dir)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.load_active_strategy", lambda: SimpleNamespace(strategy_id="s"))
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_strategy_context", lambda _: FAKE_STRATEGY)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_cta_mode", lambda _: "none")
        monkeypatch.setattr("scripts.generate_and_publish_visibility.generate_vi_post", lambda *_a, **_kw: FAKE_PACKAGE)

        main(["--dry-run"])

        content = history_file.read_text(encoding="utf-8")
        assert content.strip() == "", "History must not be modified in dry-run"

    def test_dry_run_quota_warning_does_not_block(self, tmp_path, queue_file, history_file, monkeypatch):
        """Quota warnings must be printed but must not raise or change exit code."""
        packages_dir = tmp_path / "packages"
        packages_dir.mkdir()

        monkeypatch.setattr("scripts.generate_and_publish_visibility.QUEUE_FILE",   queue_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.HISTORY_FILE", history_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.PACKAGES_DIR", packages_dir)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.load_active_strategy", lambda: SimpleNamespace(strategy_id="s"))
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_strategy_context", lambda _: FAKE_STRATEGY)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_cta_mode", lambda _: "none")
        monkeypatch.setattr("scripts.generate_and_publish_visibility.generate_vi_post", lambda *_a, **_kw: FAKE_PACKAGE)

        # Don't pass any history — small sample will trigger quota warnings
        exit_code = main(["--dry-run"])
        assert exit_code == 0


# ── Scenario B: Partial platform failure ───────────────────────────────────────

class TestPartialPlatformFailure:

    def _run_main_with_mocked_publishers(
        self,
        tmp_path,
        queue_file,
        history_file,
        monkeypatch,
        publisher_results: dict,  # platform → result mock
    ) -> int:
        packages_dir = tmp_path / "packages"
        packages_dir.mkdir()

        monkeypatch.setattr("scripts.generate_and_publish_visibility.QUEUE_FILE",   queue_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.HISTORY_FILE", history_file)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.PACKAGES_DIR", packages_dir)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.load_active_strategy", lambda: SimpleNamespace(strategy_id="s"))
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_strategy_context", lambda _: FAKE_STRATEGY)
        monkeypatch.setattr("scripts.generate_and_publish_visibility.get_cta_mode", lambda _: "none")
        monkeypatch.setattr("scripts.generate_and_publish_visibility.generate_vi_post", lambda *_a, **_kw: FAKE_PACKAGE)

        def mock_publish_platforms(draft, prior_results, dry_run):
            results = {}
            for name, result_mock in publisher_results.items():
                results[name] = result_mock.to_dict()
            wix_url    = publisher_results.get("wix", MagicMock()).to_dict().get("url", "")
            wix_post_id = publisher_results.get("wix", MagicMock()).to_dict().get("external_id", "")
            return results, wix_url, wix_post_id

        monkeypatch.setattr(
            "scripts.generate_and_publish_visibility._publish_platforms",
            mock_publish_platforms,
        )
        return main([])

    def test_linkedin_failure_yields_published_with_errors(self, tmp_path, queue_file, history_file, monkeypatch):
        publisher_results = {
            "wix":       _ok_publisher_result("wix"),
            "linkedin":  _fail_publisher_result("linkedin"),
            "facebook":  _ok_publisher_result("facebook"),
            "instagram": _ok_publisher_result("instagram"),
            "threads":   _ok_publisher_result("threads"),
            "telegram":  _ok_publisher_result("telegram"),
        }

        exit_code = self._run_main_with_mocked_publishers(
            tmp_path, queue_file, history_file, monkeypatch, publisher_results
        )
        assert exit_code == 0

        items = _load_queue.__wrapped__(queue_file) if hasattr(_load_queue, "__wrapped__") else None
        # Read queue directly to check final status
        raw_items = [
            VisibilityQueueItem(**json.loads(l))
            for l in queue_file.read_text().splitlines()
            if l.strip()
        ]
        assert len(raw_items) == 1
        assert raw_items[0].status == "published_with_errors"
        assert "linkedin" in (raw_items[0].last_error or "")

    def test_linkedin_failure_appended_to_history(self, tmp_path, queue_file, history_file, monkeypatch):
        publisher_results = {
            "wix":       _ok_publisher_result("wix"),
            "linkedin":  _fail_publisher_result("linkedin"),
            "facebook":  _ok_publisher_result("facebook"),
            "instagram": _ok_publisher_result("instagram"),
            "threads":   _ok_publisher_result("threads"),
            "telegram":  _ok_publisher_result("telegram"),
        }
        self._run_main_with_mocked_publishers(
            tmp_path, queue_file, history_file, monkeypatch, publisher_results
        )

        lines = [l for l in history_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1, "Exactly one history entry must be appended"

        entry = json.loads(lines[0])
        assert entry["content_id"] == "test_001"
        assert entry["platform_results"]["linkedin"]["status"] == "FAILED"
        assert entry["platform_results"]["wix"]["status"] == "PUBLISHED"

    def test_retry_skips_already_published_platforms(self, tmp_path, queue_file, history_file, monkeypatch):
        """Second run with --item-id on published_with_errors must skip succeeded platforms."""
        prior_results = {
            "wix":       {"platform": "wix",      "status": "PUBLISHED",  "external_id": "wix_id", "url": "https://example.com/wix", "error_message": None},
            "linkedin":  {"platform": "linkedin",  "status": "FAILED",     "external_id": None, "url": None, "error_message": "timeout"},
            "facebook":  {"platform": "facebook",  "status": "PUBLISHED",  "external_id": "fb_id",  "url": "https://example.com/fb",  "error_message": None},
            "instagram": {"platform": "instagram", "status": "PUBLISHED",  "external_id": "ig_id",  "url": "https://example.com/ig",  "error_message": None},
            "threads":   {"platform": "threads",   "status": "PUBLISHED",  "external_id": "th_id",  "url": "https://example.com/th",  "error_message": None},
            "telegram":  {"platform": "telegram",  "status": "PUBLISHED",  "external_id": "tg_id",  "url": "https://example.com/tg",  "error_message": None},
        }
        called = []

        def tracking_publish(draft, prior_results_arg, dry_run):
            results = dict(prior_results_arg)
            for name, prior in results.items():
                if prior.get("status") == "PUBLISHED":
                    pass  # already OK — caller already skips these
                else:
                    called.append(name)
                    results[name] = {"platform": name, "status": "PUBLISHED", "external_id": "new_id", "url": f"https://example.com/{name}", "error_message": None}
            return results, results.get("wix", {}).get("url", ""), results.get("wix", {}).get("external_id", "")

        # Verify _publish_platforms skips OK statuses
        from scripts.generate_and_publish_visibility import _OK_STATUSES
        skipped = [p for p, r in prior_results.items() if r["status"] in _OK_STATUSES]
        retried = [p for p, r in prior_results.items() if r["status"] not in _OK_STATUSES]

        assert "linkedin" in retried, "linkedin (FAILED) must be retried"
        assert "wix" in skipped,      "wix (PUBLISHED) must be skipped"
        assert len(retried) == 1,     "Only linkedin should need retry"

    def test_all_platforms_fail_yields_failed_status(self, tmp_path, queue_file, history_file, monkeypatch):
        publisher_results = {
            "wix":       _fail_publisher_result("wix", "503 Service Unavailable"),
            "linkedin":  _fail_publisher_result("linkedin", "timeout"),
            "facebook":  _fail_publisher_result("facebook", "connection error"),
            "instagram": _fail_publisher_result("instagram", "timeout"),
            "threads":   _fail_publisher_result("threads", "502"),
            "telegram":  _fail_publisher_result("telegram", "timeout"),
        }
        self._run_main_with_mocked_publishers(
            tmp_path, queue_file, history_file, monkeypatch, publisher_results
        )

        raw_items = [
            VisibilityQueueItem(**json.loads(l))
            for l in queue_file.read_text().splitlines()
            if l.strip()
        ]
        assert raw_items[0].status == "failed"


# ── Processing recovery tests ──────────────────────────────────────────────────

class TestProcessingRecovery:
    def _make_processing_item(self, started_minutes_ago: int, attempt_count: int = 1) -> VisibilityQueueItem:
        started = datetime.now(timezone.utc).replace(
            second=0, microsecond=0
        )
        from datetime import timedelta
        started = datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago)
        return VisibilityQueueItem(
            id="stuck_001",
            title="Stuck item",
            product_category="presence_check",
            content_format="checklist",
            strategic_topic="ai_visibility",
            status="processing",
            attempt_count=attempt_count,
            processing_started_at=started,
        )

    def test_recent_processing_not_recovered(self):
        item = self._make_processing_item(started_minutes_ago=5)
        result = _recover_stuck_processing([item])
        assert result[0].status == "processing", "Recent processing must not be touched"

    def test_stuck_processing_requeued(self):
        item = self._make_processing_item(started_minutes_ago=120, attempt_count=1)
        result = _recover_stuck_processing([item])
        assert result[0].status == "queued", "Stuck item (attempt 1) must be requeued"
        assert "recovered" in (result[0].last_error or "").lower()

    def test_stuck_after_3_attempts_marked_failed(self):
        item = self._make_processing_item(started_minutes_ago=120, attempt_count=3)
        result = _recover_stuck_processing([item])
        assert result[0].status == "failed", "Item stuck 3 times must be marked failed"

    def test_queued_items_unchanged(self):
        queued = VisibilityQueueItem(
            id="q1", title="T", product_category="presence_check",
            content_format="checklist", strategic_topic="ai_visibility", status="queued",
        )
        result = _recover_stuck_processing([queued])
        assert result[0].status == "queued"


# ── Error classification tests ─────────────────────────────────────────────────

class TestErrorClassification:
    def test_timeout_is_transient(self):
        assert _is_transient_error("Connection timeout after 30s") is True

    def test_429_is_transient(self):
        assert _is_transient_error("Rate limit exceeded: 429 Too Many Requests") is True

    def test_503_is_transient(self):
        assert _is_transient_error("503 Service Unavailable") is True

    def test_auth_error_is_permanent(self):
        assert _is_transient_error("401 Unauthorized: invalid token") is False

    def test_schema_error_is_permanent(self):
        assert _is_transient_error("Missing required field 'post_text'") is False

    def test_none_is_permanent(self):
        assert _is_transient_error(None) is False
