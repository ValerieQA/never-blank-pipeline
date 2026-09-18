"""Issue #219: Wednesday cites the source it actually retrieved.

Live run 33884765429 reached further than any Wednesday run before it. July's
selector chose 16 of 30 candidates, ChargePoint won, direct retrieval returned
200, the evidence gate returned READY, the restored July pipeline produced a
complete article across five surfaces, and **editorial acceptance returned
ACCEPT**. Then source transparency stopped it:

    the article body carries no attribution to any of this run's sources

Correctly. The body contained no URL, no "CNBC", and no source headline.

The cause is structural rather than editorial. July had no transparency gate,
so its composer never wrote attribution; and Wednesday's role rules are
deliberately inert during generation (#209/#210), so the sources-of-record
block that tells Monday's model to cite never reaches it.

The footer itself is not new — the formatting stage already appends exactly
this line for every stream. It just appended it *after* the gate, so the body
being validated was never the body being published. Applying it before the
gate for Wednesday closes both: real attribution, and validated body ==
published body.

**The validator is not touched.** These scenarios pin that: a body without
attribution still fails, and a URL the run never retrieved is never cited.

No paid calls and no network calls.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import _source_of_record_attribution, main
from src.editorial.source_transparency import (
    SourceTransparencyError,
    validate_source_transparency,
)
from src.never_blank.wednesday_routing import WEDNESDAY_ROLE_ID
from src.publishing import formatting
from src.research.evidence import (
    EvidenceAssessorIdentity,
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_monday_stream import MONDAY_ROLE, WEDNESDAY_SUPPLY
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_wednesday_wiring import _wednesday_article

#: Two real publishers, so nothing can pass by hard-coding one of them.
CNBC = {
    "publisher": "CNBC",
    "signal_name": "CNBC Business",
    "title": "ChargePoint CEO says 70% stock surge 'is the beginning of the momentum'",
    "url": "https://www.cnbc.com/2026/09/03/chargepoint-ceo-momentum.html",
}
BLOOMBERG = {
    "publisher": "Bloomberg",
    "signal_name": "Bloomberg Technology",
    "title": "Chipmaker rewrites its supply contracts after a single customer defection",
    "url": "https://www.bloomberg.com/news/articles/2026-09-02/supply-contracts.html",
}

#: The body live run 33884765429 actually produced — no attribution anywhere.
UNATTRIBUTED_BODY = (
    "ChargePoint's record stock surge wasn't driven by a bold new vision—just "
    "by showing investors a stopwatch. At first glance, one might assume the "
    "stock surged because of a groundbreaking new product. But there was no "
    "major product announcement on the day the stock jumped. The catalyst was "
    "more subtle: the company released an update showing it was on track, "
    "almost down to the quarter, to hit its promised profitability targets.\n\n"
    "Never Blank: In markets where hope wears thin, precision and proof can "
    "move the needle faster than hype."
)


def _artifact(source: dict) -> NormalizedResearchArtifact:
    """A research artifact shaped exactly as the direct-URL adapter records one."""
    now = datetime.now(timezone.utc)
    return NormalizedResearchArtifact(
        artifact_id="research-1",
        run_id="11111111-1111-4111-8111-111111111111",
        assignment_id="sig-1",
        signal_id="sig-1",
        configuration_identity=_identity(),
        created_at=now,
        sources=(NormalizedSource(
            source_id="source-1",
            locator=SourceLocator(kind=SourceLocatorKind.URL, value=source["url"]),
            title=source["title"],
            publisher=source["publisher"],
            publication_time=PublicationTime(
                status=PublicationTimeStatus.KNOWN, value=now - timedelta(days=1)
            ),
            retrieved_at=now,
        ),),
        evidence=(ExtractedEvidence(
            evidence_id="evidence-1",
            claim="The company reported progress against its stated milestones.",
            source_ids=("source-1",),
            support=(SupportReference(
                source_id="source-1",
                excerpt="The company reported progress against its stated milestones.",
            ),),
            disposition=EvidenceDisposition.ACCEPTED,
            assessment_rationale="The cited excerpt states the claim.",
        ),),
        readiness=EvidenceReadiness.READY,
        assessor=EvidenceAssessorIdentity(
            assessor_id="never-blank-evidence-assessor", version="1.0"
        ),
    )


def _identity():
    from src.strategy.business_config import load_business_strategy_configuration
    from src.strategy.execution_context import StrategyExecutionContext

    return StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    ).identity


def _signal(source: dict) -> dict:
    return {**WEDNESDAY_SUPPLY,
            "SOURCE_NAME": source["signal_name"], "SOURCE_URL": source["url"]}


# ===========================================================================
# The rendered attribution, and what it must satisfy
# ===========================================================================


@pytest.mark.parametrize("source", [CNBC, BLOOMBERG], ids=["cnbc", "bloomberg"])
def test_the_attributed_body_satisfies_the_untouched_validator(source):
    """The governing property, for two different publishers."""
    research = _artifact(source)

    # the body as generation produces it — blocked, exactly as live
    with pytest.raises(SourceTransparencyError, match="carries no attribution"):
        validate_source_transparency(
            article_body=UNATTRIBUTED_BODY, research=research
        )

    name, url = _source_of_record_attribution(_signal(source), research)
    attributed = formatting.ensure_source_line(
        UNATTRIBUTED_BODY, name, url, "blog_markdown"
    )

    # …and passes once the deterministic footer is applied
    validate_source_transparency(article_body=attributed, research=research)

    assert source["url"] in attributed
    assert attributed.endswith(f"[{source['signal_name']}]({source['url']})")


def test_the_attribution_is_the_selected_source_not_a_hard_coded_one():
    cnbc_name, cnbc_url = _source_of_record_attribution(_signal(CNBC), _artifact(CNBC))
    bb_name, bb_url = _source_of_record_attribution(
        _signal(BLOOMBERG), _artifact(BLOOMBERG)
    )

    assert (cnbc_name, cnbc_url) == (CNBC["signal_name"], CNBC["url"])
    assert (bb_name, bb_url) == (BLOOMBERG["signal_name"], BLOOMBERG["url"])
    assert "cnbc" not in bb_url.lower() and "CNBC" not in bb_name


def test_no_source_url_on_the_signal_cites_nothing():
    assert _source_of_record_attribution(
        {**_signal(CNBC), "SOURCE_URL": ""}, _artifact(CNBC)
    ) is None


def test_a_url_the_run_never_retrieved_is_never_cited():
    """Fail closed: the footer may only carry a source-of-record URL.

    Citing a URL the research artifact does not hold would either fail the
    gate anyway or — worse — publish a link no stage ever fetched.
    """
    mismatched = {**_signal(CNBC), "SOURCE_URL": "https://example.com/invented.html"}
    assert _source_of_record_attribution(mismatched, _artifact(CNBC)) is None


def test_a_malformed_artifact_cites_nothing():
    assert _source_of_record_attribution(_signal(CNBC), object()) is None


def test_the_footer_is_applied_at_most_once():
    body = formatting.ensure_source_line(
        UNATTRIBUTED_BODY, CNBC["signal_name"], CNBC["url"], "blog_markdown"
    )
    twice = formatting.ensure_source_line(
        body, CNBC["signal_name"], CNBC["url"], "blog_markdown"
    )
    assert twice == body
    assert body.count("## Source") == 1


def test_a_body_that_merely_mentions_the_url_still_gets_the_footer():
    """Idempotence is exact-suffix, so no stream loses attribution it has."""
    prose = f"As {CNBC['publisher']} reported at {CNBC['url']}, the plan held."
    out = formatting.ensure_source_line(
        prose, CNBC["signal_name"], CNBC["url"], "blog_markdown"
    )
    assert out.endswith(f"[{CNBC['signal_name']}]({CNBC['url']})")


def test_the_validator_itself_was_not_weakened():
    """Same refusals as before — no Wednesday exception anywhere in it."""
    source = Path("src/editorial/source_transparency.py").read_text()
    for forbidden in ("wednesday", "WEDNESDAY", "role_id", "never-blank-wednesday"):
        assert forbidden not in source

    research = _artifact(CNBC)
    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(article_body=UNATTRIBUTED_BODY, research=research)
    # a body that DOES cite the run's source but also links elsewhere is
    # still refused — the second check is intact too
    cited = formatting.ensure_source_line(
        UNATTRIBUTED_BODY, CNBC["signal_name"], CNBC["url"], "blog_markdown"
    )
    with pytest.raises(SourceTransparencyError, match="not one of this run's sources"):
        validate_source_transparency(
            article_body=cited + "\n\nhttps://example.com/elsewhere",
            research=research,
        )


# ===========================================================================
# The production seam
# ===========================================================================


def _run(tmp_path, *, role=WEDNESDAY_ROLE_ID, source=CNBC, article_body=None,
         signal_overrides=None):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    if role:
        argv = argv + ["--editorial-role", role]
    supplied = {**_signal(source), **(signal_overrides or {})}
    argv = [supplied["SIGNAL_ID"] if i == 2 else part for i, part in enumerate(argv)]
    patches["supply_wednesday_signal"] = mock.MagicMock(return_value=supplied)
    patches["_load_signal"] = mock.MagicMock(return_value=supplied)

    article = _wednesday_article()
    article["platforms"]["long"]["body"] = (
        UNATTRIBUTED_BODY if article_body is None else article_body
    )
    patches["generate_for_wednesday"] = mock.MagicMock(return_value=article)
    patches["generate_article"] = mock.MagicMock(
        return_value={**article, "pattern": {}}
    )
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)

    # The REAL formatting module renders the footer: the shared harness mocks
    # `formatting` wholesale, which would make the attribution under test a
    # MagicMock rather than text.
    patches.pop("formatting", None)

    # The REAL acceptance stage runs: `blog_body` must be the actual accepted
    # article, not a stand-in, or the seam under test has nothing to append to.
    del patches["run_editorial_acceptance"]

    class _AcceptingReviewer:
        def complete(self, *, instructions, request):
            return json.dumps({
                "disposition": "accept", "failed_criterion_ids": [],
                "rationale": "Every criterion passes on the accepted evidence.",
                "revision_guidance": "",
            })

    provider = _ProviderFor(source)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=provider, decision_evaluator=evaluator,
                    editorial_reviewer=_AcceptingReviewer())
    return code, patches


class _ProviderFor(ReadyProvider):
    """ReadyProvider, but its single source is the one under test.

    The envelope contract requires the artifact's sources and the successful
    retrieval outcomes to match exactly, so both are rebuilt — not just the
    artifact.
    """

    def __init__(self, source: dict) -> None:
        super().__init__()
        self._source = source

    def research(self, request):
        result = super().research(request)
        artifact = _artifact(self._source).model_copy(update={
            "run_id": request.run_id,
            "assignment_id": request.assignment_id,
            "signal_id": request.signal_id,
            "configuration_identity": request.strategy.identity,
        })
        outcome = result.source_outcomes[0].model_copy(update={
            "source_id": "source-1", "locator": self._source["url"],
        })
        # the envelope compares {source_id: retrieved_at} on both sides
        source = artifact.sources[0].model_copy(
            update={"retrieved_at": outcome.retrieved_at}
        )
        artifact = artifact.model_copy(update={"sources": (source,)})
        return result.model_copy(update={
            "artifact": artifact, "source_outcomes": (outcome,),
        })


def _run_dir(tmp_path):
    dirs = list(tmp_path.glob("*/runs/*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _wix_blog_body(patches) -> str:
    """The article body actually handed to the Wix package builder."""
    call = patches["build_wix_publication_package"].call_args
    assert call is not None, "the Wix package was never built"
    return call.kwargs["generated"]["blog_article"]


def _linkedin_body(patches) -> str:
    call = patches["build_linkedin_publication_package"].call_args
    assert call is not None, "the LinkedIn package was never built"
    return call.kwargs["generated"]["linkedin_post"]


@pytest.mark.parametrize("source", [CNBC, BLOOMBERG], ids=["cnbc", "bloomberg"])
def test_wednesday_reaches_publication_with_deterministic_attribution(
    tmp_path, source
):
    """Live run 33884765429, replayed: blocked before, published now."""
    code, patches = _run(tmp_path, source=source)

    assert code == 0
    assert patches["WixPublisher"].return_value.publish.called

    # the body handed to the Wix package builder actually carries it
    published = _wix_blog_body(patches)
    assert source["url"] in published
    assert published.count("## Source") == 1
    assert published.endswith(f"[{source['signal_name']}]({source['url']})")


def test_a_wednesday_article_with_no_citable_source_still_fails_closed(tmp_path):
    """No source-of-record URL → nothing is cited → the gate stops the run."""
    code, patches = _run(
        tmp_path, signal_overrides={"SOURCE_URL": "https://example.com/never-fetched"}
    )

    assert code == 1
    assert not patches["WixPublisher"].return_value.publish.called
    assert not patches["LinkedInPublisher"].return_value.publish.called


def test_the_validated_body_is_the_published_body(tmp_path):
    """No validate-A-publish-B gap: the footer exists at both points."""
    seen: list = []
    real = gap.validate_source_transparency

    def capture(*, article_body, research, allowed_destinations=()):
        seen.append(article_body)
        return real(article_body=article_body, research=research,
                    allowed_destinations=allowed_destinations)

    with mock.patch.object(gap, "validate_source_transparency", side_effect=capture):
        code, _patches = _run(tmp_path)  # noqa: F841 — patches read below

    assert code == 0
    assert len(seen) == 1
    validated = seen[0]
    published = _wix_blog_body(_patches)

    assert CNBC["url"] in validated                    # validated body cites it
    assert validated.count("## Source") == 1
    assert published == validated                      # byte-identical, no gap
    assert published.count("## Source") == 1           # exactly once, not twice


def test_linkedin_still_derives_from_the_canonical_lifecycle(tmp_path):
    """The post carries the canonical article link, never the source URL."""
    code, patches = _run(tmp_path)

    assert code == 0
    assert patches["LinkedInPublisher"].return_value.publish.called
    # #196: the original source URL belongs to the article, not to the post
    assert CNBC["url"] not in _linkedin_body(patches)


# ===========================================================================
# Everything else is unchanged
# ===========================================================================


def test_monday_keeps_its_one_canonical_sources_section(tmp_path):
    """Monday's model writes its own citation; the seam never runs for it —
    and, since the Monday preview-readiness repair, neither does the
    signal-derived footer: a branded-echo-then-sources body already ends in
    its one canonical Sources section (controlled live run 35383199073
    carried both)."""
    attributed = (
        UNATTRIBUTED_BODY
        + f"\n\nSources: {CNBC['publisher']} · {CNBC['title']} · {CNBC['url']}"
    )
    code, patches = _run(tmp_path, role=MONDAY_ROLE, article_body=attributed)

    assert code == 0
    assert patches["generate_article"].called
    assert not patches["generate_for_wednesday"].called
    published = _wix_blog_body(patches)
    assert "## Source" not in published
    # the signal's SOURCE_NAME is not a source-record field and never appears
    assert CNBC["signal_name"] not in published
    assert published.rstrip().endswith(
        f"Sources: {CNBC['publisher']} · {CNBC['title']} · {CNBC['url']}"
    )


def test_a_roleless_run_is_unchanged(tmp_path):
    attributed = UNATTRIBUTED_BODY + f"\n\nSource: {CNBC['url']}"
    code, patches = _run(tmp_path, role="", article_body=attributed)

    assert code == 0
    assert _wix_blog_body(patches).count("## Source") == 1


def test_the_seam_is_gated_on_the_wednesday_routing_predicate():
    """One predicate for routing and for attribution, so they cannot drift."""
    import ast

    tree = ast.parse(Path("scripts/generate_and_publish.py").read_text())
    guards = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and getattr(node.test.func, "id", "") == "is_wednesday_role"
    ]
    bodies = [ast.dump(node) for node in guards]
    assert any("generate_for_wednesday" in body for body in bodies)
    assert any("_source_of_record_attribution" in body for body in bodies)


def test_no_text_model_call_was_introduced():
    """The footer is rendered, never generated."""
    import ast

    src = Path("src/publishing/formatting.py").read_text()
    for forbidden in ("chat(", "llm_client", "model_article", "model_social"):
        assert forbidden not in src

    tree = ast.parse(Path("scripts/generate_and_publish.py").read_text())
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_source_of_record_attribution"
    )
    called = {
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for n in ast.walk(fn) if isinstance(n, ast.Call)
    }
    assert not called & {"chat", "complete", "recompose_platform", "generate_article"}


#: Every restored July file paired with its pinned copy of the c7d3a23
#: original. Checked against the in-repo fixtures rather than by shelling out
#: to git: CI's shallow checkout has no `origin/main` to resolve — the same
#: trap that broke the first #208 head and again in #213.
_RESTORED_JULY = [
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

FIXTURES = Path("tests/fixtures/wednesday_july")


@pytest.mark.parametrize("path,original", _RESTORED_JULY)
def test_the_restored_july_package_is_untouched(path, original):
    """This fix lives entirely outside the restored package.

    Line containment rather than byte equality, because the ported files carry
    an isolation banner and the two mechanical deviations #211 recorded — the
    same contract the #211 fidelity tests enforce, restated here so a change
    made by *this* PR fails this PR's own suite.
    """
    ported = Path(path).read_text()
    for line in (FIXTURES / original).read_text().splitlines():
        if 'SOURCES_CONFIG = Path("config/research_sources.yaml")' in line:
            continue
        if "parents[2]" in line:
            continue
        if line.strip().startswith("from src.editorial."):
            continue
        assert line in ported, f"{path}: lost July line {line!r}"


def test_the_july_feed_configuration_is_untouched():
    assert Path(
        "src/never_blank/wednesday_july/research/research_sources_july.yaml"
    ).read_text() == (
        FIXTURES / "july_research_originals" / "research_sources.yaml.txt"
    ).read_text()


def test_no_july_file_mentions_the_attribution_seam():
    """The seam is outside the package, and stays outside it."""
    for path in Path("src/never_blank/wednesday_july").rglob("*.py"):
        source = path.read_text()
        for name in ("ensure_source_line", "_source_of_record_attribution",
                     "source_line", "validate_source_transparency"):
            assert name not in source, f"{path}: {name}"
