"""Regression tests for publish_packages() — filesystem isolation and all-failure contracts."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.research.publish_packages as pp
import src.strategy.history as h
from src.publishing.release_scope import NON_R1_PUBLISH_CHANNELS
from src.publishing.result import PublishResult, PublishStatus


_SIGNAL = {
    "SIGNAL_ID": "reg-test-0001",
    "HEADLINE": "Regression Test Headline",
    "SOURCE_NAME": "TestSource",
    "SOURCE_URL": "https://example.com/test",
    "SOURCE_DATE": "2026-08-01",
    "FORCE_PUBLISH_OVERRIDE": "true",
    "APPROVED_OVERRIDE": "test-approved",
}

_PACKAGE = {"SIGNAL_ID": "reg-test-0001", "images": {"platform_images": {}}, "content": {}}

# structured_article fields are consumed directly by _build_threads() and _build_telegram().
# _build_threads() reads: hook, discovery.aha_setup, surviving_explanation, reframe, echo_line.
# It requires 3–5 distinct non-empty posts after _clean_line(); all five are supplied here.
# _build_telegram() reads: discovery.aha_setup (observation) and reframe (implication).
_FAKE_ARTICLE = {
    "platforms": {
        "long":      {"body": "Blog body text for regression test."},
        "medium":    {"body": "LinkedIn body text."},
        "reading":   {"body": "Facebook body text."},
        "instagram": {"body": "Instagram body text."},
        "short":     {"body": "Short body text."},
    },
    "structured_article": {
        "hook":                  "Most businesses assume visibility compounds automatically.",
        "discovery": {
            "aha_setup":             "The assumption breaks the moment a buyer cannot find them.",
        },
        "surviving_explanation": "Presence debt accumulates silently while revenue feels stable.",
        "reframe":               "Consistency of signal matters more than volume of content.",
        "echo_line":             "The specialty a buyer cannot see is still private capacity.",
        "cta_line":              "",
        "body_paragraphs":       [],
        "signature":             "",
    },
}

_FAKE_STRATEGY_CONTEXT = {
    "strategy_id":                "reg-test-strategy",
    "primary_message":            "",
    "compound_presence_role":     "",
    "desired_reader_realization": "",
    "selected_problem":           "",
    "presence_debt_focus":        False,
}


def _fake_strategy():
    s = MagicMock()
    s.strategy_id = "reg-test-strategy"
    s.started_at = None
    return s


def _setup_common(monkeypatch, tmp_path):
    monkeypatch.setenv("NB_RESEARCH_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN", "1")
    monkeypatch.setattr(pp, "generate_article", lambda *a, **kw: _FAKE_ARTICLE)
    monkeypatch.setattr(pp, "_validate_package", lambda *a, **kw: None)
    monkeypatch.setattr(pp, "load_active_strategy", _fake_strategy)
    monkeypatch.setattr(pp, "get_cta_mode", lambda *a: "reflection")
    monkeypatch.setattr(pp, "get_strategy_context", lambda *a: _FAKE_STRATEGY_CONTEXT)
    monkeypatch.setattr(pp, "generate_hashtags", lambda *a, **kw: [])
    # Redirect PACKAGES_DIR to tmp_path so _save_generated never touches the repo
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    monkeypatch.setattr(pp, "PACKAGES_DIR", packages_dir)
    # Redirect PUBLISHED_INDEX to tmp_path so append_published_entry never touches the repo
    index_path = tmp_path / "index.jsonl"
    monkeypatch.setattr(h, "PUBLISHED_INDEX", index_path)
    return index_path


def test_publish_packages_wires_typed_editorial_context(monkeypatch, tmp_path):
    """The live research publisher must not drop the selected editorial angle."""
    _setup_common(monkeypatch, tmp_path)
    captured = {}

    signal = {
        **_SIGNAL,
        "ARTICLE_READY": "true",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "false",
        "NEVER_BLANK_ANGLE": "Memory, not volume, is the missing system.",
        "POTENTIAL_HOOK": "Every new post acts like nothing came before it.",
    }
    package = {
        **_PACKAGE,
        "content": {"blog": {"angle": "Regularity without memory becomes noise."}},
    }

    def capture_generate(payload, **kwargs):
        captured["payload"] = payload
        return _FAKE_ARTICLE

    class FailedPublisher:
        def publish(self, draft, mode, **kw):
            return PublishResult(platform="wix", status=PublishStatus.FAILED)

    monkeypatch.setattr(pp, "generate_article", capture_generate)
    monkeypatch.setattr(pp, "_PUBLISHERS", [("wix", FailedPublisher())])

    pp.publish_packages([signal], [package])

    assert captured["payload"]["NEVER_BLANK_ANGLE"] == signal["NEVER_BLANK_ANGLE"]
    assert captured["payload"]["POTENTIAL_HOOK"] == signal["POTENTIAL_HOOK"]
    assert captured["payload"]["CONTENT_PACKAGE"] == package


class TestPublishPackagesFilesystemIsolation:
    """Test A: when publishers succeed, history is written only to the monkeypatched index."""

    def test_successful_publish_writes_to_redirected_index_not_production(
        self, monkeypatch, tmp_path
    ):
        index_path = _setup_common(monkeypatch, tmp_path)

        class FakeWix:
            name = "wix"
            def publish(self, draft, mode, **kw):
                return PublishResult(
                    platform="wix",
                    status=PublishStatus.PUBLISHED,
                    external_id="post-reg-001",
                    url="https://example.com/blog/reg-test",
                )

        monkeypatch.setattr(pp, "_PUBLISHERS", [("wix", FakeWix())])

        production_index = Path("strategy/published_content_index.jsonl")
        before = production_index.read_text() if production_index.exists() else None

        reports = pp.publish_packages([_SIGNAL], [_PACKAGE])

        # Redirected index received the entry
        assert index_path.exists(), "Redirected index must be created when publish succeeds"
        lines = [l for l in index_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["content_id"] == "reg-test-0001"
        assert record["strategy_id"] == "reg-test-strategy"
        assert "wix" in record["publications"]

        # Production index is unchanged
        after = production_index.read_text() if production_index.exists() else None
        assert before == after, "Production published_content_index.jsonl must not be modified"

        # Report carries the publish result
        assert len(reports) == 1
        assert reports[0]["results"]["wix"]["status"] == "PUBLISHED"


class TestPublishPackagesAllPlatformFailure:
    """Test B: when all publishers return FAILED, no history entry must be written."""

    def test_all_publishers_failed_does_not_write_history_entry(
        self, monkeypatch, tmp_path
    ):
        index_path = _setup_common(monkeypatch, tmp_path)

        class FailingPublisher:
            def __init__(self, name):
                self.name = name
            def publish(self, draft, mode, **kw):
                return PublishResult(platform=self.name, status=PublishStatus.FAILED,
                                     error_message="simulated failure")

        monkeypatch.setattr(pp, "_PUBLISHERS", [
            ("wix",       FailingPublisher("wix")),
            ("linkedin",  FailingPublisher("linkedin")),
        ])

        production_index = Path("strategy/published_content_index.jsonl")
        before = production_index.read_text() if production_index.exists() else None

        reports = pp.publish_packages([_SIGNAL], [_PACKAGE])

        # Redirected index must NOT be created (or must be empty)
        if index_path.exists():
            lines = [l for l in index_path.read_text().splitlines() if l.strip()]
            assert lines == [], (
                "No history entry must be written when all publishers returned FAILED"
            )

        # Production index is unchanged
        after = production_index.read_text() if production_index.exists() else None
        assert before == after, "Production published_content_index.jsonl must not be modified"

        # Reports retain FAILED results
        assert len(reports) == 1
        result_statuses = {k: v["status"] for k, v in reports[0]["results"].items()}
        # #227: the channels outside Release 1's publishing scope are recorded
        # as SKIPPED rather than omitted, so the report says why they are absent
        # instead of leaving a silent gap. Every channel that was *attempted*
        # still has to have failed for this scenario to mean anything.
        attempted = {k: v for k, v in result_statuses.items() if v != "SKIPPED"}
        assert attempted, "no publisher was attempted; the scenario proves nothing"
        assert all(s == "FAILED" for s in attempted.values()), (
            f"Every attempted publisher must be FAILED, got: {result_statuses}"
        )
        assert set(result_statuses) - set(attempted) <= set(NON_R1_PUBLISH_CHANNELS)


class TestStage11PublishesNothing:
    """#231, option A: Stage 11 generates and packages, and publishes nothing.

    Behavioural, not textual. The status of every channel in the returned report
    is what a restored publisher invocation would change, however it was
    restored: deriving ``_PUBLISHERS`` from the inventory again, or adding a
    direct call. A fake publisher that merely accepts the legacy draft cannot
    satisfy these assertions either — a fake returning ``PUBLISHED`` flips the
    status just as a real one would.
    """

    def _run(self, monkeypatch, tmp_path):
        index_path = _setup_common(monkeypatch, tmp_path)
        exploded: list[str] = []

        class _Explodes:
            """A publisher that must never be reached from this path."""

            def __init__(self, name: str) -> None:
                self.name = name

            def publish(self, draft, mode, **kw):
                exploded.append(self.name)
                raise AssertionError(
                    f"{self.name} was published to; Stage 11 holds no canonical "
                    "preflight and must invoke no publisher (#231)"
                )

        # The inventory, exploding. A loop that iterates it at run time — rather
        # than the empty list the stage is given — lands here.
        monkeypatch.setattr(
            pp,
            "_ALL_PUBLISHERS",
            [(name, _Explodes(name)) for name, _ in pp._ALL_PUBLISHERS],
        )

        signal = {**_SIGNAL, "ARTICLE_READY": "true",
                  "SCORE_RECOMMENDED_FOR_ARTICLE": "false"}
        reports = pp.publish_packages([signal], [_PACKAGE])
        assert len(reports) == 1
        return reports[0]["results"], exploded, index_path

    def test_every_channel_is_recorded_and_none_is_published(
        self, monkeypatch, tmp_path
    ):
        results, exploded, _ = self._run(monkeypatch, tmp_path)

        assert exploded == [], "no publisher may be reached from this path"
        assert set(results) == {
            "wix", "linkedin", "facebook", "instagram", "threads", "telegram",
        }, "a channel missing from the report is how #227 stayed hidden"
        for name, result in results.items():
            assert result["status"] == pp.PublishStatus.SKIPPED.value, (
                f"{name} reports {result['status']}; a publisher was invoked"
            )

    def test_the_two_reasons_say_two_different_true_things(
        self, monkeypatch, tmp_path
    ):
        results, _, _ = self._run(monkeypatch, tmp_path)

        for name in ("wix", "linkedin"):
            reason = results[name]["error_message"]
            assert "canonical preflight" in reason, name
            assert "outside" not in reason, (
                f"{name} is inside Release 1 scope; saying otherwise is false"
            )
        for name in ("facebook", "instagram", "threads", "telegram"):
            reason = results[name]["error_message"]
            assert "outside the Release 1 publishing scope" in reason, name
            assert "preflight" not in reason, name

    def test_nothing_reaches_the_published_index(self, monkeypatch, tmp_path):
        """The strongest behavioural signal: no entry was treated as published.

        ``append_published_entry`` is reached only for a channel whose status is
        among the publication-ok set, so an index that was never created is a run
        in which nothing was published — and it is written to the redirected path,
        so a regression here cannot touch the repository either.
        """

        _, _, index_path = self._run(monkeypatch, tmp_path)

        assert not index_path.exists(), "a publication was recorded (#231)"
