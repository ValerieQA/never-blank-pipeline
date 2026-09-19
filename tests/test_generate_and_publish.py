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

from src.publishing.package import canonical_slug
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
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import ConfigurationIdentity


# ---------------------------------------------------------------------------
# Shared fakes / helpers
# ---------------------------------------------------------------------------

_SIGNAL_ID = "sig-test-001"


def _test_configuration_identity() -> dict:
    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    return ConfigurationIdentity.from_configuration(configuration).model_dump()

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

# Canonical PROCEED-shaped stand-in for the Decision Lens gate (Issue #60).
# require_proceed() inspects the real enum disposition; decision_lens_version
# feeds the entrypoint status line.
from src.editorial.decision_contract import DecisionDisposition as _DecisionDisposition

_FAKE_DECISION = SimpleNamespace(
    disposition=_DecisionDisposition.PROCEED,
    decision_lens_version="never-blank-decision-lens/1.0",
    run_id="",
)

# VALID-shaped stand-in for the visual contract gate (Issue #96): the
# entrypoint reads .status, .linkedin_visual.value, .design_version, and
# .model_dump_json().
def _fake_visual_record(*args, **kwargs):
    return SimpleNamespace(
        status="valid",
        linkedin_visual=SimpleNamespace(value="not_requested"),
        design_version=kwargs.get("design_version", "test-v1"),
        model_dump_json=lambda **_: "{}",
    )


# REUSED-shaped stand-in for the --from-package visual reuse gate (Issue #96):
# the entrypoint reads .status, .origin_run_id, .linkedin_visual.value,
# .wix_url, .linkedin_url, and .model_dump_json().
def _fake_reuse_visual_record(*args, **kwargs):
    return SimpleNamespace(
        status="valid",
        reused=True,
        origin_run_id=kwargs.get("source_run_id", "source-run"),
        linkedin_visual=SimpleNamespace(value="not_requested"),
        wix_url="https://res.cloudinary.com/test/blog.png",
        linkedin_url=None,
        model_dump_json=lambda **_: "{}",
    )


# ACCEPTED-shaped stand-in for the LinkedIn composition gate (Issue #93): the
# entrypoint reads .word_count, .composition_rules_version, .model_dump().
def _fake_linkedin_composition(**kwargs):
    return SimpleNamespace(
        word_count=len(kwargs["linkedin_body"].split()),
        composition_rules_version="linkedin-medium-native/1.1",
        model_dump=lambda **_: {"status": "accepted"},
    )


# Package-shaped stand-ins for the canonical publication packages (Issue
# #100): the entrypoint reads .package_digest(), .title, .slug,
# .body_markdown, .cover_image_url, .target.category_ids/.tag_ids from the
# Wix package and .package_digest(), .linkedin_body, .linkedin_image_url from
# the LinkedIn package. Values are derived from the builder inputs so the
# DraftPackage handed to publishers keeps the exact pre-#100 contents. The
# real builders are covered by tests/test_publication_package.py.
def _fake_wix_package(**kwargs):
    generated = kwargs["generated"]
    visual = kwargs.get("visual_record")
    title = generated.get("headline", "")
    return SimpleNamespace(
        run_id=kwargs["run_id"],
        signal_id=kwargs["signal_id"],
        source_article_digest="sha256:" + "a" * 64,
        title=title,
        slug=canonical_slug(title),
        body_markdown=generated.get("blog_article", ""),
        cover_image_url=getattr(visual, "wix_url", None),
        target=SimpleNamespace(
            category_ids=(), tag_ids=(),
            site_id="stand-in-site", owner_member_id="stand-in-member",
        ),
        package_digest=lambda: "sha256:" + "0" * 64,
    )


def _fake_linkedin_package(**kwargs):
    generated = kwargs["generated"]
    visual = kwargs.get("visual_record")
    return SimpleNamespace(
        run_id=kwargs["run_id"],
        signal_id=kwargs["signal_id"],
        linkedin_body=generated.get("linkedin_post", ""),
        linkedin_image_url=getattr(visual, "linkedin_url", None),
        target=SimpleNamespace(account_id="stand-in-account"),
        package_digest=lambda: "sha256:" + "1" * 64,
    )


# No-prior-publication stand-in for the Wix idempotency scan (Issue #105): the
# entrypoint reads .match and .evidence_note(). The real scan is covered by
# tests/test_wix_idempotency.py.
def _fake_no_prior_publication(*args, **kwargs):
    return SimpleNamespace(match=None, evidence_note=lambda: None)


# ALLOW-shaped stand-in for the publication preflight gate (Issue #101): the
# entrypoint reads .run_disposition, .channels, .run_blocking_reasons and
# .verdict_for(channel). Digests are taken from the packages actually passed
# in, so the harness still exercises the real digest-binding assertion at the
# publisher boundary. The real gate is covered by
# tests/test_publication_preflight.py.
def _fake_preflight(**kwargs):
    from src.publishing.preflight import PreflightDisposition

    verdicts = {
        outcome.channel: SimpleNamespace(
            channel=outcome.channel,
            disposition=PreflightDisposition.ALLOW,
            blocking_reasons=(),
            package_digest=(
                outcome.package.package_digest() if outcome.package is not None else None
            ),
        )
        for outcome in kwargs["channel_outcomes"]
    }
    return SimpleNamespace(
        run_disposition=PreflightDisposition.ALLOW,
        run_blocking_reasons=(),
        channels=tuple(verdicts.values()),
        verdict_for=verdicts.get,
        model_dump_json=lambda **_: "{}",
    )


# ACCEPT-shaped stand-in for the editorial acceptance gate (Issue #89): the
# entrypoint reads .accepted, .final_article_body, .revised, and .audit.
def _fake_acceptance(**kwargs):
    return SimpleNamespace(
        accepted=True,
        revised=False,
        final_article_body=kwargs["article_body"],
        initial_review=None,
        final_review=None,
        audit={
            "rubric": "never-blank-editorial-acceptance/1.0",
            "accepted": True,
            "revised": False,
            "final_disposition": "accept",
            "initial_review": {"disposition": "accept"},
            "final_review": None,
        },
    )


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
        # run_id is required by Task #27 — packages without it are rejected.
        "run_id":            "00000000-0000-4000-8000-000000000001",
        "signal_id":         _SIGNAL_ID,
        "strategy_id":       "2026-07-presence-debt-campaign-1",
        "strategy_version":  strategy_version,
        "configuration_identity": _test_configuration_identity(),
        "generated_at":      "2026-08-11T10:00:00+00:00",
        "headline":          "AI adoption accelerates in SMBs",
        "blog_article":      "Blog body text sufficient for validation.",
        "linkedin_post":     "LinkedIn post text.",
        "facebook_post":     "Facebook post text.",
        "instagram_caption": "Instagram caption.",
        "threads_sequence":  ["Post 1.", "Post 2.", "Post 3."],
        "telegram_text":     "Telegram text.",
        "echo_line":         "They waited.",
        # #259: packages are reusable only when their social bodies were
        # derived from the final accepted article
        "social_derivation": "final-accepted-article/1",
    }
    pkg.update(overrides)
    return pkg


def _write_package(tmp_path: Path, pkg: dict | None = None) -> Path:
    """Write a run-scoped generated.json and return its exact path."""
    data = _valid_package() if pkg is None else pkg
    run_id = data.get("run_id", "invalid-source-run")
    f = tmp_path / _SIGNAL_ID / "runs" / str(run_id) / "generated.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data), encoding="utf-8")
    snapshot = f.with_name("business_strategy.json")
    snapshot.write_text(
        Path("strategy/current/business_strategy.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return f


def _make_ok_publish_result(platform: str):
    r = mock.MagicMock()
    r.ok.return_value = True
    r.run_id = ""   # empty so _normalize_publish_result injects the canonical run_id
    r.external_id = f"{platform}-post-id"
    r.url = f"https://example.com/{platform}"
    r.to_dict.return_value = {
        "platform": platform, "status": "PUBLISHED",
        "external_id": f"{platform}-post-id", "url": f"https://example.com/{platform}",
        "error_message": None, "run_id": "",
    }
    return r


def _fake_canonical_verdict(**kwargs):
    """VERIFIED-shaped stand-in for the Issue #200 canonical URL gate."""
    from src.publishing.canonical_url import CanonicalUrlVerdict
    from src.publishing.result import UrlProvenance

    return CanonicalUrlVerdict(
        url=kwargs.get("url") or "",
        provenance=UrlProvenance.PROVIDER_LOOKUP,
        verified=bool(kwargs.get("url")),
        http_status=200,
        attempts=1,
    )


def _fake_wednesday_article() -> dict:
    """A July-shaped generation result for the restored Wednesday path."""
    import copy

    article = copy.deepcopy(_FAKE_ARTICLE)
    article.pop("pattern", None)                  # July had no Pattern Extractor
    structured = article.setdefault("structured_article", {})
    structured.setdefault("signature", structured.get("echo_line", ""))
    for platform in article.get("platforms", {}).values():
        platform.pop("title", None)               # July composed no title
    return article


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
        argv.extend(["--from-package", "--source-run-id", _valid_package()["run_id"]])

    # #174: reuse binds the dispatched role to the source assignment.json —
    # the immutable provenance anchor. The legacy synthetic packages never
    # wrote one, so the harness supplies a valid roleless anchor matching
    # the synthetic run identity. Role-binding behaviour itself is covered
    # by tests/test_from_package_retry.py against REAL source runs.
    _source_assignment_record = {
        "schema_version": "1.2",
        "run_id": _valid_package()["run_id"],
        "execution_mode": "dry-run",
        "configuration_identity": _test_configuration_identity(),
        "assignment": {
            "assignment_id": _SIGNAL_ID,
            "origin": "jsonl",
            "topic": "AI adoption accelerates in SMBs",
            "submitted_at": "2026-08-01T00:00:00+00:00",
            "strategy_ref": "2026-07-presence-debt-campaign-1",
            "strategy_version": "1",
        },
        "editorial_role": None,
    }

    kwargs_ref: dict = {}
    kwargs = {
        # echo the requested identity: the harness anchor binds to whatever
        # (signal, run) the test addresses, exactly as a real anchor would
        "load_assignment_json": mock.MagicMock(
            side_effect=lambda packages_dir, signal_id, source_run_id: {
                **_source_assignment_record,
                "run_id": source_run_id,
                "assignment": {
                    **_source_assignment_record["assignment"],
                    "assignment_id": signal_id,
                },
            }
        ),
        # The stand-in research artifact carries the execution signal identity
        # the decision gate reads (research_artifact.signal_id).
        "execute_and_persist_research": mock.MagicMock(
            return_value=mock.MagicMock(signal_id=_SIGNAL_ID)
        ),
        "ExaResearchAdapter": mock.MagicMock(return_value=mock.sentinel.provider),
        "load_research_envelope": mock.MagicMock(return_value=mock.MagicMock()),
        "validate_research_envelope": mock.MagicMock(
            return_value=mock.MagicMock(signal_id=_SIGNAL_ID)
        ),
        # Decision Lens gate (Issue #60): legacy suites patch the lifecycle
        # boundary with a canonical PROCEED-shaped stand-in; require_proceed
        # stays real and passes because disposition is the true enum value.
        # The real gate behavior is covered by tests/test_decision_lifecycle.py.
        "production_evaluator": mock.MagicMock(return_value=mock.sentinel.decision_evaluator),
        "evaluate_and_persist_decision": mock.MagicMock(return_value=_FAKE_DECISION),
        "load_decision_artifact": mock.MagicMock(return_value=_FAKE_DECISION),
        # Editorial acceptance gate (Issue #89): ACCEPT-shaped stand-in that
        # returns the original article; the real gate is covered by
        # tests/test_editorial_acceptance.py.
        "run_editorial_acceptance": mock.MagicMock(side_effect=_fake_acceptance),
        # LinkedIn composition gate (Issue #93): ACCEPTED-shaped stand-in; the
        # real gate is covered by tests/test_linkedin_composition.py.
        "accept_linkedin_composition": mock.MagicMock(side_effect=_fake_linkedin_composition),
        "write_linkedin_composition_json": mock.MagicMock(),
        # Visual contract gate (Issue #96): VALID-shaped stand-in; the real
        # gate is covered by tests/test_visual_contract.py.
        "build_visual_assets_record": mock.MagicMock(side_effect=_fake_visual_record),
        # Canonical publication packages (Issue #100): package-shaped
        # stand-ins; the real builders are covered by
        # tests/test_publication_package.py. Target models are stubbed so the
        # harness needs no NB_* target environment.
        # Publication preflight gate (Issue #101): ALLOW-shaped stand-in; the
        # real gate is covered by tests/test_publication_preflight.py.
        "find_prior_wix_publication": mock.MagicMock(
            side_effect=_fake_no_prior_publication
        ),
        "find_prior_linkedin_publication": mock.MagicMock(
            side_effect=_fake_no_prior_publication
        ),
        "evaluate_publication_preflight": mock.MagicMock(side_effect=_fake_preflight),
        "write_preflight_result_json": mock.MagicMock(),
        "build_wix_publication_package": mock.MagicMock(side_effect=_fake_wix_package),
        "build_linkedin_publication_package": mock.MagicMock(side_effect=_fake_linkedin_package),
        # Canonical-link enrichment + social lineage gate (Issue #196):
        # identity-shaped stand-ins — the legacy packages are SimpleNamespace
        # stand-ins the real binder would refuse. The real enrichment and
        # gate are covered by tests/test_canonical_social_lineage.py.
        # Canonical URL verification (Issue #200): verified-shaped stand-in —
        # the harness has no network and its publish stubs carry synthetic
        # URLs. The real resolution/verification contract is covered by
        # tests/test_canonical_url.py.
        "verify_canonical_url": mock.MagicMock(
            side_effect=lambda **kw: _fake_canonical_verdict(**kw)
        ),
        "bind_canonical_article_url": mock.MagicMock(
            side_effect=lambda package, url: package
        ),
        "validate_social_lineage": mock.MagicMock(return_value=None),
        # Social derivation from the final accepted article (Issue #197;
        # Monday preview readiness: every canonical run derives its social
        # bodies after acceptance). Stand-in that mirrors a faithful
        # derivation: the body the test's own generator composed for that
        # format — so suites that exercise the real LinkedIn gate keep the
        # body they chose. The real seam is covered by
        # tests/test_social_recomposition.py.
        "recompose_platform": mock.MagicMock(side_effect=_fake_derivation(kwargs_ref)),
        "WixPublicationTarget": mock.MagicMock(return_value=mock.sentinel.wix_target),
        "LinkedInPublicationTarget": mock.MagicMock(return_value=mock.sentinel.linkedin_target),
        "load_linkedin_composition_json": mock.MagicMock(return_value={"stand-in": True}),
        "load_visual_assets_json": mock.MagicMock(return_value={"stand-in": True}),
        "reuse_visual_assets_record": mock.MagicMock(side_effect=_fake_reuse_visual_record),
        "write_visual_assets_json": mock.MagicMock(),
        "load_active_strategy": mock.MagicMock(return_value=_STRATEGY_STUB),
        "get_strategy_context": mock.MagicMock(return_value=_STRATEGY_CONTEXT),
        "get_cta_mode": mock.MagicMock(return_value="reflection"),
        "_load_signal": mock.MagicMock(return_value=_RAW_SIGNAL),
        "_load_package_images": mock.MagicMock(return_value={}),
        "generate_article": mock.MagicMock(return_value=_FAKE_ARTICLE),
        # #209: Wednesday generates through the restored July package. The
        # harness stands in for the routing seam so any role-driven test
        # reaches the same post-generation lifecycle. July's result carries
        # no ``pattern`` and no composed ``title``; the routing adapter
        # supplies ``echo_line`` from July's ``signature``.
        "generate_for_wednesday": mock.MagicMock(
            side_effect=lambda signal, **kwargs: _fake_wednesday_article()
        ),
        "validate_article_for_publish": mock.MagicMock(return_value=None),
        "_save_generated": mock.MagicMock(),
        "generate_hashtags": mock.MagicMock(return_value=[]),
        "append_published_entry": mock.MagicMock(),
        "run_analytics_pipeline": mock.MagicMock(
            return_value=mock.MagicMock(format_summary=mock.MagicMock(return_value=""))
        ),
        "formatting": _make_formatting_mock(),
        "CURRENT_DESIGN_VERSION": "test-v1",
        # Propagates run_ctx.run_id into rc and ec mocks so that
        # _assert_run_id_match passes at both the research-context and
        # editorial-context boundaries.
        "_build_legacy_research_context": mock.MagicMock(
            side_effect=lambda assignment, raw_signal, run_ctx: _make_rc_mock(run_ctx.run_id)
        ),
        "_emit_run_report": mock.MagicMock(),
    }
    kwargs_ref["patches"] = kwargs
    return argv, kwargs


def _fake_derivation(ref: dict):
    """A derivation stand-in faithful to "derive from the final article".

    When the final accepted article is the draft the test composed (no
    revision), the test's own body for that format IS a faithful derivation
    of it and is returned — so suites exercising the real LinkedIn gate keep
    the body they chose. When acceptance revised the article, the draft
    body no longer derives from it and is never returned: a fixed body
    stands in for the derivation of the final content (#197 semantics).
    Reads the generator stub through ``ref`` at call time, so a test that
    replaces ``patches["generate_article"]`` after building the harness is
    still honoured.
    """
    def derive(structured, format_key, *, canonical_body="", **kwargs):
        generator = ref.get("patches", {}).get("generate_article")
        article = getattr(generator, "return_value", None)
        if not isinstance(article, dict):
            article = _FAKE_ARTICLE
        platforms = article.get("platforms", {})
        draft_long = platforms.get("long", {}).get("body", "")
        body = platforms.get(format_key, {}).get("body") if (
            draft_long and canonical_body.strip() == draft_long.strip()
        ) else None
        body = body or "Re-composed social body derived from the final accepted article."
        if format_key == "threads":
            # the Threads adapter contract is a 3–6 post sequence (#259)
            body = "\n---\n".join([body, "Second post.", "Third post."])
        return {"body": body, "word_count": len(body.split()),
                "echo_included": True, "title": None}
    return derive


def _make_rc_mock(run_id: str):
    """Return a ResearchContext-like mock with run_id and article_ready set."""
    ec_mock = mock.MagicMock()
    ec_mock.run_id = run_id
    ec_mock.to_legacy_dict.return_value = {}

    rc_mock = mock.MagicMock()
    rc_mock.run_id = run_id
    rc_mock.article_ready = True
    rc_mock.force_override = False
    rc_mock.factual_readiness = "ready"
    rc_mock.source_premise_verified = "true"
    rc_mock.to_editorial.return_value = ec_mock
    return rc_mock


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

        adapter = mock.MagicMock()
        adapter.adapt.side_effect = capturing

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "DEFAULT_INTAKE_ADAPTER", adapter):
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

    @pytest.mark.story9
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

        adapter = mock.MagicMock()
        adapter.adapt.side_effect = capturing

        with mock.patch("sys.argv", argv), \
             mock.patch.multiple(_gap_module, **patches), \
             mock.patch.object(_gap_module, "DEFAULT_INTAKE_ADAPTER", adapter):
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

    def _make_run_ctx(self, ca=None) -> RunContext:
        if ca is None:
            ca = from_jsonl_signal(
                _RAW_SIGNAL,
                strategy_ref="2026-07-presence-debt-campaign-1",
                strategy_version="1",
                submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            )
        return RunContext.from_assignment(ca, ExecutionMode.DRY_RUN)

    def test_matching_ids_succeed(self):
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="2026-07-presence-debt-campaign-1",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        run_ctx = self._make_run_ctx(ca)
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL, run_ctx)
        assert isinstance(rc, ResearchContext)
        assert rc.signal_id == _SIGNAL_ID

    def test_matching_ids_propagate_run_id(self):
        """Compatibility boundary must inject run_id onto the returned ResearchContext."""
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="2026-07-presence-debt-campaign-1",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        run_ctx = self._make_run_ctx(ca)
        rc = _build_legacy_research_context(ca, _RAW_SIGNAL, run_ctx)
        assert rc.run_id == run_ctx.run_id

    def test_mismatched_ids_fail_closed(self):
        ca = from_jsonl_signal(
            _RAW_SIGNAL,
            strategy_ref="r",
            strategy_version="1",
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        run_ctx = self._make_run_ctx(ca)
        different_signal = {**_RAW_SIGNAL, "SIGNAL_ID": "sig-different-999"}
        with pytest.raises(ValueError, match="does not match"):
            _build_legacy_research_context(ca, different_signal, run_ctx)

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

        written = list((tmp_path / _SIGNAL_ID / "runs").glob("*/generated.json"))
        assert len(written) == 1
        return written[0]

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

    def test_publish_does_not_modify_generated_strategy_provenance(self, tmp_path):
        """Publication writes separately and leaves generated.json unchanged."""
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

        written = next((tmp_path / _SIGNAL_ID / "runs").glob("*/generated.json"))
        assert written.exists()
        pkg = json.loads(written.read_text())
        assert pkg["strategy_version"] == "1"
        assert pkg["strategy_id"] == "2026-07-presence-debt-campaign-1"

    def test_fresh_gen_generated_at_is_immutable_after_publish(self, tmp_path):
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
            exit_code = main()

        assert exit_code == 0
        generated = next((tmp_path / _SIGNAL_ID / "runs").glob("*/generated.json"))
        pkg = json.loads(generated.read_text())
        # Must be a valid ISO 8601 timestamp
        dt = datetime.fromisoformat(pkg["generated_at"])
        assert dt.tzinfo is not None
        # generated_at must be a fixed string, not "now" re-evaluated at re-save time.
        # The field value is the one captured before the first save; re-save must echo it.
        assert pkg["generated_at"] == pkg["generated_at"].strip()

    def test_from_package_publish_preserves_source_bytes_and_generated_at(self, tmp_path):
        original_ts = "2026-08-10T08:30:00+00:00"
        source = _write_package(
            tmp_path,
            _valid_package(
                generated_at=original_ts,
                strategy_started_at="2026-07-22",
            ),
        )
        original_bytes = source.read_bytes()

        argv, patches = _base_patches(dry_run=False, from_package=True)
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
            exit_code = main()

        assert exit_code == 0
        assert source.read_bytes() == original_bytes
        pkg = json.loads(source.read_text())
        assert pkg["generated_at"] == original_ts, (
            f"generated_at was overwritten: expected {original_ts!r}, got {pkg['generated_at']!r}"
        )

    def test_from_package_source_preserves_all_provenance_fields(self, tmp_path):
        original_ts = "2026-08-10T08:30:00+00:00"
        source = _write_package(
            tmp_path,
            _valid_package(
                generated_at=original_ts,
                strategy_started_at="2026-07-22",
            ),
        )
        original_bytes = source.read_bytes()

        argv, patches = _base_patches(dry_run=False, from_package=True)
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
            exit_code = main()

        assert exit_code == 0
        assert source.read_bytes() == original_bytes
        pkg = json.loads(source.read_text())
        assert pkg["generated_at"] == original_ts
        assert pkg["strategy_id"] == "2026-07-presence-debt-campaign-1"
        assert pkg["strategy_version"] == "1"
        assert pkg["signal_id"] == _SIGNAL_ID
        assert pkg["strategy_started_at"] == "2026-07-22"


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
