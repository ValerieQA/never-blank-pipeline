"""Issue #211: Wednesday retrieves its own source, without Exa.

Wednesday is the historical control path. Running July discovery, July
enrichment and July generation but *Exa* retrieval made it a hybrid —

    July discovery → July enrichment → Exa retrieval → July generation

— which weakens the comparison against the current Monday system. So for
Wednesday the retrieval stage is replaced by a direct fetch of the exact
SOURCE_URL the July research already selected.

This is fidelity, not distrust of the provider. **Monday keeps Exa,
unchanged**, and verification is re-sourced rather than removed: the fetch
follows redirects and records the final URL, checks the authority, fails
closed when the source cannot be read, and emits `not_assessed` evidence that
the shared assessment stage and the canonical research gate hold to exactly
the same READY standard as Monday's.

The governing scenario drives the real production entrypoint with **no
research provider injected**, so production's own provider selection runs —
which is the only way this can be proven at all. Zero paid calls and zero
network calls: HTTP is stubbed at both the RSS boundary and the direct-fetch
boundary, and the evidence judgment is a local transport.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.never_blank.wednesday_routing import WEDNESDAY_ROLE_ID
from src.research.adapters import direct_url
from src.research.adapters.direct_url import (
    DirectUrlFetchError,
    DirectUrlResearchProvider,
    fetch_source,
)
from src.research.evidence import EvidenceDisposition, EvidenceReadiness
from src.research.provider import (
    ResearchOperationOutcome,
    SourceOrigin,
    RetrievalStatus,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_monday_stream import MONDAY_ROLE, WEDNESDAY_SUPPLY
from tests.test_wednesday_july_research import (
    VERSANT_HEADLINE,
    VERSANT_ID,
    VERSANT_URL,
    _JulyClock,
    _feed_transport,
    _llm_transport,
)
from tests.test_wednesday_supply import _store_bound_supply
from tests.test_wednesday_wiring import _wednesday_article


def _attributed_to_versant() -> dict:
    """A July-shaped article that cites the source THIS run retrieved.

    The run's source-of-record is now the CNBC article the July research
    selected, not the harness fixture's, so the body must attribute that one
    — which is exactly what the transparency gate is for.
    """
    article = _wednesday_article()
    article["platforms"]["long"]["body"] = (
        "Everyone saw the price tag. A media company bought a hardware maker, "
        "and the category line moved before the balance sheet did. "
        f"Source: {VERSANT_HEADLINE} — CNBC ({VERSANT_URL})."
    )
    article["platforms"]["medium"]["body"] = (
        "A different opening for the social surface entirely. The qualifying "
        "question is where the boundary sits, not what the deal cost. "
        "Documented by CNBC."
    )
    return article

FIXTURES = Path("tests/fixtures/wednesday_july")
RESEARCH = "src.never_blank.wednesday_july.research"
DIRECT = "src.research.adapters.direct_url"

#: A minimal CNBC article page — enough for the extractor to find a title, a
#: publisher, a publication time and body text, and nothing more.
VERSANT_PAGE = """<!doctype html>
<html><head>
<title>Versant agrees to buy golf simulator company Full Swing for $530 million</title>
<meta property="og:site_name" content="CNBC">
<meta property="article:published_time" content="2026-07-06T13:05:00Z">
<script>var tracking = {id: "ignore-me"};</script>
</head><body>
<h1>Versant agrees to buy golf simulator company Full Swing for $530 million</h1>
<p>Versant said Monday it agreed to acquire Full Swing, a maker of golf
simulators, for $530 million in cash.</p>
<style>.ad { display: none }</style>
</body></html>"""


@pytest.fixture(scope="module")
def cnbc_feed() -> str:
    return (FIXTURES / "cnbc_business_2026-07-06.xml").read_text(encoding="utf-8")


class AcceptingJudgment:
    """A local evidence assessor: no model, no network, deterministic."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        payload = json.loads(request)
        return json.dumps({"verdicts": [
            {"evidence_id": item["evidence_id"], "disposition": "accepted",
             "rationale": "The retrieved page states the claim in its own text."}
            for item in payload["evidence"]
        ]})


class _Response:
    def __init__(self, body: str, *, status: int = 200, url: str | None = None):
        self.text = body
        self.content = body.encode()
        self.status_code = status
        self.url = url


class _Session:
    """Stands in for requests.Session at the direct-fetch boundary."""

    def __init__(self, pages: dict, log: list):
        self._pages = pages
        self._log = log
        self.max_redirects = None

    def get(self, url, **kwargs):
        self._log.append(url)
        if url not in self._pages:
            raise AssertionError(f"a URL nobody named was fetched: {url}")
        body, status, final = self._pages[url]
        return _Response(body, status=status, url=final or url)


def _direct_transport(pages: dict, log: list):
    return lambda: _Session(pages, log)


def _run_wednesday(tmp_path, cnbc_feed, *, pages=None, dry_run=False,
                   role=WEDNESDAY_ROLE_ID, supply=None, signal_id=None):
    """Drive the entrypoint with production's OWN provider selection.

    Deliberately does not pass ``research_provider``: the whole question is
    which adapter production picks for this role.
    """
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    argv = ["prog"] + ([] if signal_id is None else ["--signal-id", signal_id]) + argv[3:]
    if role:
        argv += ["--editorial-role", role]
    del patches["_build_legacy_research_context"]
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=_attributed_to_versant()
    )
    patches["generate_article"] = mock.MagicMock(
        return_value={**_attributed_to_versant(), "pattern": {}}
    )
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    patches["WEDNESDAY_SIGNALS_FILE"] = tmp_path / "wednesday.jsonl"
    # present so the assertion "was it constructed?" is answerable
    patches["ExaResearchAdapter"] = mock.MagicMock()

    fetched: list = []
    http_calls: list = []
    prompts: list = []
    pages = pages if pages is not None else {VERSANT_URL: (VERSANT_PAGE, 200, None)}
    transports = [
        mock.patch(f"{RESEARCH}.discover.requests.get",
                   side_effect=_feed_transport(cnbc_feed, http_calls)),
        mock.patch(f"{RESEARCH}.discover.datetime", _JulyClock),
        mock.patch(f"{DIRECT}.requests.Session",
                   side_effect=_direct_transport(pages, fetched)),
    ] + [
        mock.patch(f"{RESEARCH}.{module}.chat", side_effect=_llm_transport(prompts))
        for module in ("discover", "enrich", "angles", "score")
    ]

    judgment = AcceptingJudgment()
    evaluator, _ = _evaluator(_model_output())
    for transport in transports:
        transport.start()
    try:
        supplied = supply or _store_bound_supply(patches)
        with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
                mock.patch.object(gap, "supply_wednesday_signal", side_effect=supplied):
            code = main(decision_evaluator=evaluator, evidence_judgment=judgment)
    finally:
        for transport in transports:
            transport.stop()
    return code, patches, fetched, judgment


# ===========================================================================
# The governing regression: the whole Wednesday route, no Exa anywhere
# ===========================================================================


def test_wednesday_reaches_publication_through_direct_retrieval(tmp_path, cnbc_feed):
    code, patches, fetched, judgment = _run_wednesday(tmp_path, cnbc_feed)

    assert code == 0, "the Wednesday control path did not complete"

    # ── Exa is never constructed, so no Exa transport can be called ────────
    assert not patches["ExaResearchAdapter"].called

    # ── only the exact SOURCE_URL July selected was fetched ────────────────
    assert fetched == [VERSANT_URL]

    # ── the historical signal still reaches the restored generation ────────
    routed = patches["generate_for_wednesday"].call_args.args[0]
    assert routed["SIGNAL_ID"] == VERSANT_ID
    assert routed["HEADLINE"] == VERSANT_HEADLINE
    for field in ("CORE_FACT", "CORE_TENSION", "BUSINESS_LESSON",
                  "WHY_THIS_CASE_IS_INTERESTING", "POTENTIAL_HOOK",
                  "NEVER_BLANK_ANGLE"):
        assert routed[field], f"{field} was lost on the control path"

    # ── source transparency received a real, verified source-of-record ─────
    research = json.loads(
        next(tmp_path.glob(f"{VERSANT_ID}/runs/*/research.json")).read_text()
    )
    artifact = research["result"]["artifact"]
    assert artifact["readiness"] == EvidenceReadiness.READY.value
    assert artifact["assessor"]["assessor_id"]
    assert len(artifact["sources"]) == 1
    source = artifact["sources"][0]
    assert source["locator"]["value"] == VERSANT_URL
    assert source["title"] == VERSANT_HEADLINE
    assert source["publisher"] == "CNBC"
    assert source["publication_time"]["status"] == "known"
    assert artifact["evidence"][0]["disposition"] == EvidenceDisposition.ACCEPTED.value
    assert artifact["evidence"][0]["assessment_rationale"]
    assert judgment.calls == 1                     # assessed, not waved through

    # ── the adapter attribution says who retrieved it ──────────────────────
    assert research["result"]["invocation"]["attribution"]["provider_id"] == "direct-url"
    assert all(
        outcome["origin"] == SourceOrigin.CLIENT_SUPPLIED.value
        for outcome in research["result"]["source_outcomes"]
    )

    # ── and the run reached publication preparation ────────────────────────
    assert list(tmp_path.glob(f"{VERSANT_ID}/runs/*/generated.json"))
    assert patches["WixPublisher"].return_value.publish.called
    assert patches["LinkedInPublisher"].return_value.publish.called


def test_retrieval_failure_stops_the_run_fail_closed(tmp_path, cnbc_feed):
    """A source nobody could read is not evidence, and never becomes a post."""
    code, patches, fetched, _judgment = _run_wednesday(
        tmp_path, cnbc_feed, pages={VERSANT_URL: ("", 404, None)}
    )

    assert code == 1
    assert fetched == [VERSANT_URL]
    assert not patches["generate_for_wednesday"].called
    assert not patches["WixPublisher"].return_value.publish.called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_redirect_is_followed_and_the_final_url_recorded(tmp_path, cnbc_feed):
    redirected = "https://www.cnbc.com/2026/07/06/versant-full-swing-final.html"
    code, _patches, fetched, _judgment = _run_wednesday(
        tmp_path, cnbc_feed,
        pages={VERSANT_URL: (VERSANT_PAGE, 200, redirected)},
    )

    assert code == 0
    assert fetched == [VERSANT_URL]                # requested the named URL…
    research = json.loads(
        next(tmp_path.glob(f"{VERSANT_ID}/runs/*/research.json")).read_text()
    )
    # …recorded where it actually landed, as retrieval diagnostics…
    assert research["result"]["source_outcomes"][0]["locator"] == redirected
    # …and kept the source-of-record as the URL the signal cites, which is
    # what the article attributes. A publication moving its own article to a
    # new path has not become a different source, and treating it as one
    # would make transparency reject an article for citing its own research.
    assert research["result"]["artifact"]["sources"][0]["locator"]["value"] == VERSANT_URL


# ===========================================================================
# Monday keeps Exa, unchanged
# ===========================================================================


def test_monday_still_uses_the_exa_provider_path(tmp_path, cnbc_feed):
    """The control path change must not touch the system under test."""
    code, patches, fetched, _judgment = _run_wednesday(
        tmp_path, cnbc_feed, role=MONDAY_ROLE, signal_id="sig-test-001",
        dry_run=True,
    )

    # Monday still asks production for its provider, and production still
    # answers with Exa — the adapter is constructed on Monday's path.
    assert patches["ExaResearchAdapter"].called
    # …and no direct fetch happened for Monday
    assert fetched == []
    assert not patches["generate_for_wednesday"].called
    # (the harness Exa mock returns a MagicMock provider, so the run itself
    # stops at the research gate; the assertion under test is which adapter
    # production selected, which is already answered above)
    assert code in (0, 1)


def test_roleless_runs_still_use_the_exa_provider_path(tmp_path, cnbc_feed):
    _code, patches, fetched, _judgment = _run_wednesday(
        tmp_path, cnbc_feed, role="", signal_id="sig-test-001", dry_run=True,
    )
    assert patches["ExaResearchAdapter"].called
    assert fetched == []


# ===========================================================================
# The adapter's own contract: it cannot discover
# ===========================================================================


def _request(**overrides):
    """A real ResearchProviderRequest built the way production builds one."""
    from datetime import timedelta

    from src.intake import from_jsonl_signal
    from src.research.lifecycle import build_research_request
    from src.run import ExecutionMode, RunContext
    from src.strategy.business_config import load_business_strategy_configuration
    from src.strategy.execution_context import StrategyExecutionContext

    strategy = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    signal = {**WEDNESDAY_SUPPLY, **overrides}
    assignment = from_jsonl_signal(
        signal, strategy_ref="2026-07-presence-debt-campaign-1",
        strategy_version="1", submitted_at=datetime.now(timezone.utc),
    )
    run = RunContext.from_assignment(
        assignment, ExecutionMode.DRY_RUN, configuration_identity=strategy.identity
    )
    return build_research_request(
        run, assignment, signal, strategy.research, now=datetime.now(timezone.utc)
    )


def _page(url=VERSANT_URL):
    return direct_url._FetchedPage(
        requested_url=url, final_url=url, status=200, title="A verified report",
        publisher="cnbc.com", published_at=None, text="A verified claim.",
        redirected=False,
    )


def test_the_adapter_fetches_only_the_exact_required_url():
    fetched: list = []

    def fetch(url):
        fetched.append(url)
        return _page(url)

    provider = DirectUrlResearchProvider(fetch=fetch)
    result = provider.research(_request())

    assert fetched == [VERSANT_URL]
    assert result.outcome is ResearchOperationOutcome.COMPLETE
    assert result.artifact.sources[0].locator.value == VERSANT_URL
    assert result.source_outcomes[0].origin is SourceOrigin.CLIENT_SUPPLIED
    assert result.source_outcomes[0].status is RetrievalStatus.RETRIEVED


def test_the_adapter_refuses_a_discovery_directive():
    provider = DirectUrlResearchProvider(
        fetch=lambda url: (_ for _ in ()).throw(
            AssertionError("a discovery request reached the network")
        )
    )
    result = provider.research(_request(ALLOW_OPEN_DISCOVERY="true"))

    assert result.outcome is ResearchOperationOutcome.FAILED
    assert "cannot discover" in result.operation_failure.message
    assert getattr(result, "artifact", None) is None


def test_the_adapter_refuses_a_bare_domain_directive():
    provider = DirectUrlResearchProvider(
        fetch=lambda url: (_ for _ in ()).throw(
            AssertionError("a domain search reached the network")
        )
    )
    result = provider.research(_request(PREFERRED_SOURCES="reuters.com"))

    assert result.outcome is ResearchOperationOutcome.FAILED
    assert "cannot discover" in result.operation_failure.message


def test_the_adapter_has_no_search_capability_at_all():
    """Structural, not behavioural: there is nothing here that could search.

    Read as code rather than as text — the module explains in prose why it
    is not Exa, and prose must not be mistaken for a capability.
    """
    import ast

    provider = DirectUrlResearchProvider()
    assert not hasattr(provider, "search")

    tree = ast.parse(Path("src/research/adapters/direct_url.py").read_text())
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    for forbidden in ("search", "ExaResearchAdapter", "ExaTransport",
                      "include_domains", "exclude_domains", "numResults"):
        assert forbidden not in names, f"direct-url adapter can reach {forbidden}"

    # nothing is imported from the Exa adapter either
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "exa" not in (node.module or "").lower()
        elif isinstance(node, ast.Import):
            assert all("exa" not in alias.name.lower() for alias in node.names)

    # and no endpoint path literal exists anywhere in it
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in ("/search", "/contents")


def test_a_failed_fetch_produces_a_typed_failure_and_no_artifact():
    def fetch(url):
        raise DirectUrlFetchError("source returned HTTP 500")

    result = DirectUrlResearchProvider(fetch=fetch).research(_request())

    assert result.outcome is ResearchOperationOutcome.FAILED
    assert getattr(result, "artifact", None) is None
    assert result.source_outcomes[0].status is RetrievalStatus.FAILED
    assert "500" in result.operation_failure.message


def test_the_invocation_id_is_deterministic():
    """A create-once envelope is compared byte-for-byte on reload."""
    first = DirectUrlResearchProvider(fetch=lambda url: _page()).research(_request())
    request = _request()
    second = DirectUrlResearchProvider(fetch=lambda url: _page()).research(request)
    third = DirectUrlResearchProvider(fetch=lambda url: _page()).research(request)

    assert second.invocation.attribution.invocation_id == (
        third.invocation.attribution.invocation_id
    )
    # …and distinct runs are distinct
    assert first.invocation.attribution.invocation_id != (
        second.invocation.attribution.invocation_id
    )


# ===========================================================================
# The fetch itself
# ===========================================================================


def test_the_fetch_extracts_title_publisher_and_publication_time():
    calls: list = []
    page = fetch_source(
        VERSANT_URL,
        session_factory=_direct_transport({VERSANT_URL: (VERSANT_PAGE, 200, None)},
                                          calls),
    )

    assert page.title == VERSANT_HEADLINE
    assert page.publisher == "CNBC"
    assert page.published_at == datetime(2026, 7, 6, 13, 5, tzinfo=timezone.utc)
    assert "acquire Full Swing" in page.text
    # script and style contents are never mistaken for article text
    assert "tracking" not in page.text
    assert "display: none" not in page.text
    assert page.redirected is False


def test_the_fetch_refuses_an_unsafe_authority():
    with pytest.raises(DirectUrlFetchError, match="unsafe source authority"):
        fetch_source(
            "http://127.0.0.1:8080/internal",
            session_factory=_direct_transport({}, []),
        )


def test_the_fetch_refuses_a_redirect_to_an_unsafe_authority():
    pages = {VERSANT_URL: (VERSANT_PAGE, 200, "http://localhost/admin")}
    with pytest.raises(DirectUrlFetchError, match="unsafe authority"):
        fetch_source(VERSANT_URL, session_factory=_direct_transport(pages, []))


def test_a_non_success_status_is_a_failure_not_an_empty_page():
    pages = {VERSANT_URL: ("<html></html>", 503, None)}
    with pytest.raises(DirectUrlFetchError, match="HTTP 503"):
        fetch_source(VERSANT_URL, session_factory=_direct_transport(pages, []))


def test_a_transport_error_is_retried_then_fails_closed():
    attempts: list = []

    def flaky():
        attempts.append(1)
        raise OSError("connection reset")

    with pytest.raises(DirectUrlFetchError, match="could not be retrieved"):
        fetch_source(VERSANT_URL, session_factory=flaky, sleep=lambda _s: None)
    assert len(attempts) == direct_url.MAX_ATTEMPTS


def test_a_transport_error_that_clears_is_not_a_failure():
    attempts: list = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("connection reset")
        return _Session({VERSANT_URL: (VERSANT_PAGE, 200, None)}, [])

    page = fetch_source(VERSANT_URL, session_factory=flaky, sleep=lambda _s: None)
    assert page.title == VERSANT_HEADLINE
    assert len(attempts) == 2


def test_the_entrypoint_guard_and_the_adapter_refuse_the_same_things():
    """The rule is stated twice on purpose; the two must not drift apart.

    The entrypoint stops the run before a provider exists, in terms of
    Wednesday's supply. The adapter refuses as a provider contract. A
    directive the entrypoint waved through and the adapter then rejected
    would still be fail-closed, but the run would fail for a confusing
    reason — so both are exercised against the same inputs.
    """
    from src.research.provider import SourceDirectiveKind, SourcePriority

    def entrypoint_refuses(request) -> bool:
        # the exact expression the entrypoint evaluates
        searchable = tuple(
            directive.directive_id
            for directive in request.source_directives
            if directive.priority is not SourcePriority.EXCLUDED
            and (
                directive.priority is SourcePriority.DISCOVERY
                or directive.kind is not SourceDirectiveKind.URL
            )
        )
        return bool(searchable) or request.freshness.allow_open_discovery

    def adapter_refuses(request) -> bool:
        result = DirectUrlResearchProvider(
            fetch=lambda url: _page(url)
        ).research(request)
        return result.outcome is ResearchOperationOutcome.FAILED

    cases = [
        {},                                              # the plain July shape
        {"ALLOW_OPEN_DISCOVERY": "true"},                # open discovery
        {"PREFERRED_SOURCES": "reuters.com"},            # a bare domain
        {"PREFERRED_SOURCES": "https://www.reuters.com/x.html"},   # an exact URL
        {"EXCLUDED_SOURCES": "example.com"},             # an exclusion only
    ]
    for overrides in cases:
        request = _request(**overrides)
        assert entrypoint_refuses(request) == adapter_refuses(request), overrides
