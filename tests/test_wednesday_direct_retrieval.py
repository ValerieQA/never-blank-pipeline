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


class _Hop:
    """One recorded HTTP attempt: what was requested, and to which address."""

    __slots__ = ("url", "pinned_ip")

    def __init__(self, url, pinned_ip):
        self.url = url
        self.pinned_ip = pinned_ip

    def __repr__(self):
        return f"<{self.url} via {self.pinned_ip}>"


def _transport(pages: dict, attempted: list):
    """A recording stand-in for the pinned transport.

    ``pages`` maps URL → (status, headers, body). Every attempt is appended
    to ``attempted`` BEFORE the response is produced, so a test can prove a
    request was never made — the whole point of the redirect regressions.
    """
    def send(url, *, pinned_ip, headers, timeout):
        attempted.append(_Hop(url, pinned_ip))
        if url not in pages:
            raise AssertionError(f"a URL nobody named was requested: {url}")
        status, response_headers, body = pages[url]
        return direct_url._RawResponse(
            status=status, headers=response_headers, text=body
        )
    return send


def _resolver(mapping: dict | None = None):
    """A stand-in for getaddrinfo. Unknown hosts resolve to a public address."""
    mapping = mapping or {}

    def resolve(host, port, *args, **kwargs):
        addresses = mapping.get(host, ["93.184.216.34"])
        return [(2, 1, 6, "", (address, port)) for address in addresses]

    return resolve


def _ok(body: str = None):
    return (200, {}, body if body is not None else VERSANT_PAGE)


def _redirect(to: str, status: int = 301):
    return (status, {"location": to}, "")


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
    pages = pages if pages is not None else {VERSANT_URL: _ok()}
    transports = [
        mock.patch(f"{RESEARCH}.discover.requests.get",
                   side_effect=_feed_transport(cnbc_feed, http_calls)),
        mock.patch(f"{RESEARCH}.discover.datetime", _JulyClock),
        mock.patch(f"{DIRECT}._pinned_transport",
                   side_effect=_transport(pages, fetched)),
        mock.patch(f"{DIRECT}.socket.getaddrinfo", side_effect=_resolver()),
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

    # ── only the exact SOURCE_URL July selected was requested ──────────────
    assert [hop.url for hop in fetched] == [VERSANT_URL]

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
        tmp_path, cnbc_feed, pages={VERSANT_URL: (404, {}, "")}
    )

    assert code == 1
    assert [hop.url for hop in fetched] == [VERSANT_URL]
    assert not patches["generate_for_wednesday"].called
    assert not patches["WixPublisher"].return_value.publish.called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_redirect_is_followed_and_the_final_url_recorded(tmp_path, cnbc_feed):
    redirected = "https://www.cnbc.com/2026/07/06/versant-full-swing-final.html"
    code, _patches, fetched, _judgment = _run_wednesday(
        tmp_path, cnbc_feed,
        pages={VERSANT_URL: _redirect(redirected), redirected: _ok()},
    )

    assert code == 0
    # both hops were requested, in order, and both were on cnbc.com
    assert [hop.url for hop in fetched] == [VERSANT_URL, redirected]
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


def test_an_unsafe_redirect_stops_the_production_run_without_requesting_it(
    tmp_path, cnbc_feed
):
    """The blocker, at the production entrypoint rather than the unit."""
    code, patches, attempted, _judgment = _run_wednesday(
        tmp_path, cnbc_feed,
        pages={VERSANT_URL: _redirect("http://127.0.0.1/internal")},
    )

    assert code == 1
    # the redirect target was never requested by the runner
    assert [hop.url for hop in attempted] == [VERSANT_URL]
    assert not patches["generate_for_wednesday"].called
    assert not patches["WixPublisher"].return_value.publish.called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_cross_site_redirect_stops_the_production_run(tmp_path, cnbc_feed):
    elsewhere = "https://www.example.com/republished.html"
    code, patches, attempted, _judgment = _run_wednesday(
        tmp_path, cnbc_feed,
        pages={VERSANT_URL: _redirect(elsewhere), elsewhere: _ok()},
    )

    assert code == 1
    assert [hop.url for hop in attempted] == [VERSANT_URL]
    assert not patches["generate_for_wednesday"].called


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
# The fetch: every hop validated BEFORE it is requested
# ===========================================================================

LOCAL_TARGET = "http://127.0.0.1/internal"
PRIVATE_NAME = "https://intranet.cnbc.com/secrets"


def _fetch(url=VERSANT_URL, *, pages=None, resolves=None, attempted=None):
    attempted = attempted if attempted is not None else []
    return fetch_source(
        url,
        transport=_transport(pages if pages is not None else {url: _ok()}, attempted),
        resolver=_resolver(resolves),
        sleep=lambda _s: None,
    ), attempted


def test_the_fetch_extracts_title_publisher_and_publication_time():
    page, attempted = _fetch()

    assert [hop.url for hop in attempted] == [VERSANT_URL]
    assert page.title == VERSANT_HEADLINE
    assert page.publisher == "CNBC"
    assert page.published_at == datetime(2026, 7, 6, 13, 5, tzinfo=timezone.utc)
    assert "acquire Full Swing" in page.text
    # script and style contents are never mistaken for article text
    assert "tracking" not in page.text
    assert "display: none" not in page.text
    assert page.redirected is False


def test_the_connection_is_made_to_a_validated_address_not_a_hostname():
    """The pinning that closes the rebinding window, asserted directly."""
    _page, attempted = _fetch(resolves={"www.cnbc.com": ["93.184.216.34"]})
    assert attempted[0].pinned_ip == "93.184.216.34"


# ── the blocker: an unsafe redirect destination is never requested ─────────


def test_a_redirect_to_loopback_is_never_requested():
    attempted: list = []
    pages = {VERSANT_URL: _redirect(LOCAL_TARGET)}

    with pytest.raises(DirectUrlFetchError) as exc:
        _fetch(pages=pages, attempted=attempted)

    # the FIRST request happened; the second one never did
    assert [hop.url for hop in attempted] == [VERSANT_URL]
    assert LOCAL_TARGET not in [hop.url for hop in attempted]
    assert "non-public address" in str(exc.value) or "unsafe" in str(exc.value)


@pytest.mark.parametrize("target", [
    "http://127.0.0.1/internal",
    "http://169.254.169.254/latest/meta-data/",     # cloud metadata
    "http://10.0.0.5/admin",
    "http://192.168.1.1/",
    "http://[::1]/internal",
    "http://localhost/internal",
])
def test_no_redirect_into_non_public_space_is_ever_requested(target):
    attempted: list = []
    with pytest.raises(DirectUrlFetchError):
        _fetch(pages={VERSANT_URL: _redirect(target)}, attempted=attempted)
    assert [hop.url for hop in attempted] == [VERSANT_URL]


def test_a_hostname_resolving_into_private_space_is_never_requested():
    """The name looks public; its answer does not. Refused before connecting."""
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="non-public address"):
        _fetch(
            PRIVATE_NAME,
            pages={PRIVATE_NAME: _ok()},
            resolves={"intranet.cnbc.com": ["10.1.2.3"]},
            attempted=attempted,
        )
    assert attempted == []                          # nothing was requested


def test_a_redirect_to_a_name_resolving_into_private_space_is_never_requested():
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="non-public address"):
        _fetch(
            pages={VERSANT_URL: _redirect(PRIVATE_NAME), PRIVATE_NAME: _ok()},
            resolves={"intranet.cnbc.com": ["169.254.169.254"]},
            attempted=attempted,
        )
    assert [hop.url for hop in attempted] == [VERSANT_URL]


def test_a_name_with_one_private_answer_among_public_ones_is_refused():
    """Picking the public answer would only mean trying again."""
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="non-public address"):
        _fetch(
            resolves={"www.cnbc.com": ["93.184.216.34", "127.0.0.1"]},
            attempted=attempted,
        )
    assert attempted == []


# ── same-site redirects only ──────────────────────────────────────────────


def test_a_same_site_redirect_is_followed():
    final = "https://www.cnbc.com/2026/07/06/versant-full-swing-final.html"
    page, attempted = _fetch(
        pages={VERSANT_URL: _redirect(final), final: _ok()}
    )
    assert [hop.url for hop in attempted] == [VERSANT_URL, final]
    assert page.final_url == final
    assert page.requested_url == VERSANT_URL       # the cited URL is preserved
    assert page.redirected is True


def test_a_subdomain_redirect_is_followed():
    final = "https://amp.cnbc.com/2026/07/06/versant-full-swing.html"
    page, attempted = _fetch(pages={VERSANT_URL: _redirect(final), final: _ok()})
    assert [hop.url for hop in attempted] == [VERSANT_URL, final]
    assert page.final_url == final


def test_a_relative_redirect_is_resolved_against_the_current_url():
    final = "https://www.cnbc.com/2026/07/06/moved.html"
    page, attempted = _fetch(
        pages={VERSANT_URL: _redirect("/2026/07/06/moved.html"), final: _ok()}
    )
    assert [hop.url for hop in attempted] == [VERSANT_URL, final]


def test_a_cross_site_redirect_fails_closed_and_is_never_requested():
    """Attesting the cited URL with another site's content is the defect."""
    elsewhere = "https://www.example.com/republished.html"
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="off-site"):
        _fetch(
            pages={VERSANT_URL: _redirect(elsewhere), elsewhere: _ok()},
            attempted=attempted,
        )
    assert [hop.url for hop in attempted] == [VERSANT_URL]


def test_a_redirect_chain_cannot_walk_off_site_one_hop_at_a_time():
    """Each hop is compared to the ORIGIN, not merely to the previous hop."""
    hop1 = "https://amp.cnbc.com/a.html"
    hop2 = "https://amp.cnbc.example.net/a.html"
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="off-site"):
        _fetch(
            pages={VERSANT_URL: _redirect(hop1), hop1: _redirect(hop2),
                   hop2: _ok()},
            attempted=attempted,
        )
    assert [hop.url for hop in attempted] == [VERSANT_URL, hop1]


def test_a_redirect_loop_is_bounded():
    pages = {VERSANT_URL: _redirect(VERSANT_URL)}
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="exceeded"):
        _fetch(pages=pages, attempted=attempted)
    assert len(attempted) == direct_url.MAX_REDIRECTS + 1


def test_automatic_redirect_following_is_never_used():
    """Structural: the client must not be allowed to follow a redirect."""
    source = Path("src/research/adapters/direct_url.py").read_text()
    assert "allow_redirects=True" not in source
    assert "redirect=False" in source          # urllib3's equivalent, explicit


def test_a_redirect_without_a_location_is_a_failure():
    with pytest.raises(DirectUrlFetchError, match="no Location"):
        _fetch(pages={VERSANT_URL: (301, {}, "")})


# ── the rest of the fetch contract ────────────────────────────────────────


def test_the_fetch_refuses_an_unsafe_authority_before_requesting():
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="unsafe source authority"):
        _fetch("http://127.0.0.1:8080/internal", pages={}, attempted=attempted)
    assert attempted == []


def test_a_non_http_scheme_is_refused_before_requesting():
    attempted: list = []
    with pytest.raises(DirectUrlFetchError, match="scheme"):
        _fetch("file:///etc/passwd", pages={}, attempted=attempted)
    assert attempted == []


def test_a_non_success_status_is_a_failure_not_an_empty_page():
    with pytest.raises(DirectUrlFetchError, match="HTTP 503"):
        _fetch(pages={VERSANT_URL: (503, {}, "<html></html>")})


def test_a_transport_error_is_retried_then_fails_closed():
    attempts: list = []

    def flaky(url, *, pinned_ip, headers, timeout):
        attempts.append(url)
        raise OSError("connection reset")

    with pytest.raises(DirectUrlFetchError, match="could not be retrieved"):
        fetch_source(VERSANT_URL, transport=flaky, resolver=_resolver(),
                     sleep=lambda _s: None)
    assert len(attempts) == direct_url.MAX_ATTEMPTS


def test_a_transport_error_that_clears_is_not_a_failure():
    attempts: list = []

    def flaky(url, *, pinned_ip, headers, timeout):
        attempts.append(url)
        if len(attempts) == 1:
            raise OSError("connection reset")
        return direct_url._RawResponse(status=200, headers={}, text=VERSANT_PAGE)

    page = fetch_source(VERSANT_URL, transport=flaky, resolver=_resolver(),
                        sleep=lambda _s: None)
    assert page.title == VERSANT_HEADLINE
    assert len(attempts) == 2


def test_an_unresolvable_host_fails_closed_without_requesting():
    import socket as _socket

    attempted: list = []

    def failing_resolver(*args, **kwargs):
        raise _socket.gaierror("Name or service not known")

    with pytest.raises(DirectUrlFetchError, match="could not be resolved"):
        fetch_source(VERSANT_URL, transport=_transport({}, attempted),
                     resolver=failing_resolver, sleep=lambda _s: None)
    assert attempted == []


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
