"""Issue #211 (review round 2): Wednesday's supply is the restored July path.

#212 restored July's research modules and #209/#210 wired July's generation
into the lifecycle — but production still chose Wednesday's *signal* the
current way:

    select_eligible_signal.py → data/research/*.jsonl
      ← written by scripts/research/run_daily_research.py

which is the small-business feed set and the "ALWAYS REJECT … Large company
M&A" selector — the two 2026-07-21 changes that made the Versant specimen
unreachable (#206). Restored discovery plus current supply is still the
regression.

These scenarios drive the **real production entrypoint** and prove the whole
route in one pass:

    historical CNBC RSS fixture
      → production Wednesday dispatch
      → restored July RSS discovery → select → enrich → score → angles
      → the historical 46-field Versant signal
      → generate_for_wednesday(...)
      → downstream publication preparation

Nothing between the fixture and the routing seam is stubbed: the entrypoint's
own branch runs the real ``supply_wednesday_signal``, which runs the real
July research. Only transports are replaced — RSS at ``requests.get``, every
research stage at ``chat``, generation at the routing seam, and the
publishers. **Zero paid calls, zero network calls.**
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.never_blank.wednesday_routing import WEDNESDAY_ROLE_ID
from src.never_blank.wednesday_supply import (
    WednesdaySupplyError,
    published_signal_ids,
    supply_wednesday_signal,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_wednesday_july_research import (
    VERSANT_HEADLINE,
    VERSANT_ID,
    VERSANT_URL,
    _JulyClock,
    _feed_transport,
    _llm_transport,
)
from tests.test_wednesday_wiring import _wednesday_article

FIXTURES = Path("tests/fixtures/wednesday_july")
RESEARCH = "src.never_blank.wednesday_july.research"
MONDAY_ROLE_ID = "never-blank-monday-documented-case"


@pytest.fixture(scope="module")
def cnbc_feed() -> str:
    return (FIXTURES / "cnbc_business_2026-07-06.xml").read_text(encoding="utf-8")


def _run_entrypoint(tmp_path, cnbc_feed, *, role=WEDNESDAY_ROLE_ID, dry_run=True,
                    signal_id=None, overrides=None, store=None,
                    supply_override=None):
    """Drive the REAL entrypoint, with only transports replaced.

    Returns ``(exit_code, patches, http_calls, prompts)``. The Wednesday
    branch is NOT stubbed: `supply_wednesday_signal` and the whole July
    research path execute for real against the committed RSS fixture.
    """
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    # argv is ["prog", "--signal-id", <id>, …]; Wednesday discovers its own,
    # so the id is dropped unless a test is exercising the filter.
    argv = ["prog"] + ([] if signal_id is None else ["--signal-id", signal_id]) + argv[3:]
    if role:
        argv += ["--editorial-role", role]

    # The typed research-context boundary runs for real. The July fields the
    # restored generation consumes have to survive it — `signal_lifecycle`
    # says so in as many words — and a stubbed boundary would hide exactly
    # the kind of field loss this test exists to catch.
    del patches["_build_legacy_research_context"]
    patches["generate_for_wednesday"] = mock.MagicMock(
        return_value=_wednesday_article()
    )
    # The shared engine's stub is attributed too, so a Monday or role-less
    # run in this module fails only for reasons this module is about.
    patches["generate_article"] = mock.MagicMock(
        return_value={**_wednesday_article(), "pattern": {}}
    )
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    # Wednesday's own signal store lives under tmp_path — the real one is
    # never written by a test run.
    patches["WEDNESDAY_SIGNALS_FILE"] = store or (tmp_path / "wednesday.jsonl")
    if overrides:
        patches.update(overrides)

    http_calls: list = []
    prompts: list = []
    transports = [
        mock.patch(f"{RESEARCH}.discover.requests.get",
                   side_effect=_feed_transport(cnbc_feed, http_calls)),
        mock.patch(f"{RESEARCH}.discover.datetime", _JulyClock),
        mock.patch("src.utils.llm_client.chat",
                   side_effect=AssertionError("an unstubbed paid call was made")),
    ] + [
        mock.patch(f"{RESEARCH}.{module}.chat", side_effect=_llm_transport(prompts))
        for module in ("discover", "enrich", "angles", "score")
    ]

    evaluator, _ = _evaluator(_model_output())
    for transport in transports:
        transport.start()
    try:
        supply = supply_override or _store_bound_supply(patches)
        with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
                mock.patch.object(gap, "supply_wednesday_signal",
                                  side_effect=supply):
            code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    finally:
        for transport in transports:
            transport.stop()
    return code, patches, http_calls, prompts


def _store_bound_supply(patches):
    """The REAL supply, with only its output store redirected to tmp_path.

    Not a stub: `run_wednesday_research` and every July stage still execute.
    Redirecting the store is the one concession a test must make so a run
    never appends to the repository's own Wednesday signal file.
    """
    real = supply_wednesday_signal
    store = patches["WEDNESDAY_SIGNALS_FILE"]

    def bound(requested_signal_id="", **kwargs):
        kwargs["store"] = store
        # Pin `seen_ids` rather than inheriting the repository's consumption
        # marker: the day Wednesday actually publishes Versant, its id lands
        # in published_signal_ids.txt and this scenario would quietly stop
        # finding a candidate. The real seen-ids wiring is covered on its own
        # by test_published_signals_are_not_rediscovered.
        kwargs["seen_ids"] = set()
        return real(requested_signal_id, **kwargs)

    return bound


# ===========================================================================
# The production regression — the whole route, in one entrypoint run
# ===========================================================================


def test_versant_travels_from_rss_fixture_to_publication_via_production(
    tmp_path, cnbc_feed
):
    code, patches, http_calls, prompts = _run_entrypoint(
        tmp_path, cnbc_feed, dry_run=False
    )

    assert code == 0, "the production Wednesday run did not complete"

    # ── the restored path produced the signal, and production used it ──────
    assert patches["generate_for_wednesday"].called
    routed = patches["generate_for_wednesday"].call_args.args[0]

    assert routed["SIGNAL_ID"] == VERSANT_ID
    assert routed["HEADLINE"] == VERSANT_HEADLINE
    assert routed["SOURCE_NAME"] == "CNBC Business"
    assert routed["SOURCE_URL"] == VERSANT_URL

    # ── the July enrichment and angle fields survived the whole route ──────
    for field in ("CORE_FACT", "CORE_TENSION", "BUSINESS_LESSON",
                  "WHY_THIS_CASE_IS_INTERESTING", "COUNTER_EXAMPLE"):
        assert routed[field], f"{field} was lost between research and generation"
    for field in ("POTENTIAL_HOOK", "NEVER_BLANK_ANGLE", "LINKEDIN_ANGLE",
                  "BLOG_ANGLE", "THREADS_ANGLE", "STORY_ANGLE",
                  "POSSIBLE_SIGNATURE_LINE"):
        assert routed[field], f"{field} was lost between research and generation"

    # The supplied signal itself — the research output, before the typed
    # editorial boundary — carries the full historical angle set, including
    # INTERESTING_QUESTION. That one field is deliberately not asserted on
    # `routed`: `ResearchContext` carries it, but `to_legacy_dict` does not
    # forward it to generation, and neither July's stages nor today's read
    # it. It is a research-layer planning field, and nothing is losing it
    # that ever used it.
    supplied = json.loads(
        patches["WEDNESDAY_SIGNALS_FILE"].read_text().strip().splitlines()[0]
    )
    assert supplied["SIGNAL_ID"] == VERSANT_ID
    assert supplied["INTERESTING_QUESTION"]
    assert len(supplied) >= 46

    # ── the shared engine was never consulted ──────────────────────────────
    assert not patches["generate_article"].called

    # ── the run reached publication preparation under the historical id ────
    assert list(tmp_path.glob(f"{VERSANT_ID}/runs/*/generated.json"))
    assert patches["WixPublisher"].return_value.publish.called
    assert patches["LinkedInPublisher"].return_value.publish.called


def test_wednesday_never_executes_the_current_discovery_or_selector(
    tmp_path, cnbc_feed
):
    """The negative half: no current research semantics anywhere on the route."""
    code, patches, http_calls, prompts = _run_entrypoint(tmp_path, cnbc_feed)
    assert code == 0

    systems = "\n".join(system for system, _user in prompts)
    for current_rule in (
        "ALWAYS REJECT — no exceptions:",
        "Large company M&A, earnings, product launches with no documented mechanism",
        "It is correct to return an empty list.",
        "Never Blank does NOT publish advice.",
    ):
        assert current_rule not in systems, f"current selector reached production: {current_rule}"

    # July's inclusive instruction is the one that ran
    assert "Be inclusive — prefer false positives over missed signals." in systems

    # only the July feed set was fetched
    fetched = " ".join(http_calls)
    assert "cnbc.com" in fetched
    for current_feed in ("smallbiztrends.com", "score.org", "inc.com",
                         "contentmarketinginstitute.com"):
        assert current_feed not in fetched, f"current feed reached production: {current_feed}"


def test_pattern_extractor_never_runs_on_the_wednesday_route(tmp_path, cnbc_feed):
    with mock.patch(
        "src.editorial.pattern_extractor.extract_pattern",
        side_effect=AssertionError("pattern_extractor ran for Wednesday"),
    ):
        code, _patches, _http, _prompts = _run_entrypoint(tmp_path, cnbc_feed)
    assert code == 0


def test_the_canonical_decision_lens_is_not_consulted(tmp_path, cnbc_feed):
    """Wednesday's authority is its declared policy, persisted as evidence."""
    code, patches, _http, _prompts = _run_entrypoint(tmp_path, cnbc_feed)
    assert code == 0
    assert not patches["production_evaluator"].called
    assert list(tmp_path.glob(f"{VERSANT_ID}/runs/*/decision_policy.json"))
    assert not list(tmp_path.glob(f"{VERSANT_ID}/runs/*/decision.json"))


def test_downstream_safety_is_unchanged_on_the_wednesday_route(tmp_path, cnbc_feed):
    code, patches, _http, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, dry_run=False
    )
    assert code == 0
    assert patches["run_editorial_acceptance"].called
    assert patches["accept_linkedin_composition"].called
    assert patches["build_visual_assets_record"].called
    assert patches["evaluate_publication_preflight"].called
    assert patches["build_wix_publication_package"].called
    assert patches["build_linkedin_publication_package"].called
    assert list(tmp_path.glob(f"{VERSANT_ID}/runs/*/accepted_composition.json"))
    assert list(tmp_path.glob(f"{VERSANT_ID}/runs/*/assignment.json"))
    assert list(tmp_path.glob(f"{VERSANT_ID}/runs/*/research.json"))


def test_no_paid_call_and_no_network_call_outside_the_stubs(tmp_path, cnbc_feed):
    """The cost proof, made explicit rather than implied.

    The four July stage modules bind `chat` at import, so the copy on
    `llm_client` is reachable only by some *other* module joining the run —
    and it is armed to fail. HTTP is stubbed at the only module that opens a
    socket, and every URL it requested is recorded.
    """
    code, _patches, http_calls, prompts = _run_entrypoint(tmp_path, cnbc_feed)
    assert code == 0
    # exactly the July research stages spoke to a model: select, enrich,
    # score, enrich_signal, angles
    assert len(prompts) == 5
    assert all("http" in url for url in http_calls)


# ===========================================================================
# Monday and role-less runs are untouched
# ===========================================================================


def test_monday_still_loads_its_signal_from_the_shared_store(tmp_path, cnbc_feed):
    code, patches, http_calls, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, role=MONDAY_ROLE_ID, signal_id="sig-test-001"
    )
    assert code == 0
    assert patches["_load_signal"].called          # the shared supply
    assert not patches["generate_for_wednesday"].called
    assert patches["generate_article"].called      # the shared engine
    assert http_calls == []                        # no July RSS fetch


def test_roleless_runs_still_load_their_signal_from_the_shared_store(
    tmp_path, cnbc_feed
):
    code, patches, http_calls, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, role="", signal_id="sig-test-001"
    )
    assert code == 0
    assert patches["_load_signal"].called
    assert not patches["generate_for_wednesday"].called
    assert patches["generate_article"].called
    assert http_calls == []


def test_a_missing_signal_id_is_still_an_error_without_the_wednesday_role(
    tmp_path, cnbc_feed
):
    code, patches, _http, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, role="", signal_id=None
    )
    assert code == 1
    assert not patches["generate_article"].called


# ===========================================================================
# Supply semantics
# ===========================================================================


def test_an_empty_wednesday_stops_cleanly_without_falling_back(tmp_path):
    """July published nothing rather than lowering the bar; so does production."""
    calls = supply_wednesday_signal(
        seen_ids=set(), research=lambda seen_ids: [], store=tmp_path / "s.jsonl"
    )
    assert calls is None


def test_a_requested_id_filters_but_never_bypasses(tmp_path):
    versant = {"SIGNAL_ID": VERSANT_ID, "HEADLINE": VERSANT_HEADLINE}
    store = tmp_path / "s.jsonl"

    chosen = supply_wednesday_signal(
        VERSANT_ID, seen_ids=set(), research=lambda seen_ids: [versant], store=store
    )
    assert chosen["SIGNAL_ID"] == VERSANT_ID
    assert chosen["HEADLINE"] == VERSANT_HEADLINE

    # a signal the Wednesday research did not produce is refused outright,
    # rather than fetched from the shared store
    with pytest.raises(WednesdaySupplyError, match="does not read the shared"):
        supply_wednesday_signal(
            "sig-from-monday", seen_ids=set(),
            research=lambda seen_ids: [versant], store=store,
        )


def test_published_signals_are_not_rediscovered(tmp_path):
    seen_seen: list = []

    def research(seen_ids):
        seen_seen.append(set(seen_ids))
        return []

    marker = tmp_path / "published.txt"
    marker.write_text(f"{VERSANT_ID}\nother-signal\n", encoding="utf-8")
    supply_wednesday_signal(
        seen_ids=published_signal_ids(marker), research=research,
        store=tmp_path / "s.jsonl",
    )
    assert seen_seen == [{VERSANT_ID, "other-signal"}]


def test_the_store_is_append_only_and_deduplicated(tmp_path):
    store = tmp_path / "s.jsonl"
    versant = {"SIGNAL_ID": VERSANT_ID, "HEADLINE": VERSANT_HEADLINE}

    for _ in range(3):
        supply_wednesday_signal(
            seen_ids=set(), research=lambda seen_ids: [versant], store=store
        )
    assert len(store.read_text().strip().splitlines()) == 1

    supply_wednesday_signal(
        seen_ids=set(),
        research=lambda seen_ids: [versant, {"SIGNAL_ID": "second", "HEADLINE": "x"}],
        store=store,
    )
    lines = [json.loads(line) for line in store.read_text().strip().splitlines()]
    assert [item["SIGNAL_ID"] for item in lines] == [VERSANT_ID, "second"]


def test_a_research_failure_is_a_stop_not_a_fallback(tmp_path):
    def broken(seen_ids):
        raise RuntimeError("feed unreachable")

    with pytest.raises(WednesdaySupplyError, match="feed unreachable"):
        supply_wednesday_signal(
            seen_ids=set(), research=broken, store=tmp_path / "s.jsonl"
        )


def test_a_wednesday_signal_asking_for_open_discovery_is_refused(
    tmp_path, cnbc_feed
):
    """The one way current sources could still reach Wednesday, closed.

    Wednesday's evidence must be the source its own July research cited. A
    signal that opts into provider-side open discovery would let today's
    retrieval surface sources July never had — current discovery semantics
    arriving through the evidence stage instead of the supply stage. July's
    46-field contract has no such field, so this cannot happen by accident;
    the guard exists so it cannot happen on purpose either.
    """
    from tests.test_monday_stream import WEDNESDAY_SUPPLY

    opted_in = {**WEDNESDAY_SUPPLY, "ALLOW_OPEN_DISCOVERY": "true"}
    code, patches, _http, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, supply_override=lambda *a, **k: dict(opted_in)
    )

    assert code == 1
    # refused before any editorial work, not after
    assert not patches["generate_for_wednesday"].called
    assert not patches["generate_article"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_preferred_domain_is_refused_for_the_same_reason(tmp_path, cnbc_feed):
    """A domain directive reaches the provider's search endpoint too."""
    from tests.test_monday_stream import WEDNESDAY_SUPPLY

    with_domain = {**WEDNESDAY_SUPPLY, "PREFERRED_SOURCES": "reuters.com"}
    code, patches, _http, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, supply_override=lambda *a, **k: dict(with_domain)
    )

    assert code == 1
    assert not patches["generate_for_wednesday"].called


def test_an_exact_preferred_url_is_still_allowed(tmp_path, cnbc_feed):
    """Retrieval of a named URL is contents-fetching, not discovery."""
    from tests.test_monday_stream import WEDNESDAY_SUPPLY

    with_url = {**WEDNESDAY_SUPPLY, "PREFERRED_SOURCES": "https://www.cnbc.com/x.html"}
    code, patches, _http, _prompts = _run_entrypoint(
        tmp_path, cnbc_feed, supply_override=lambda *a, **k: dict(with_url)
    )

    assert code == 0
    assert patches["generate_for_wednesday"].called


def test_the_best_article_ready_candidate_is_chosen(tmp_path):
    """Scoring order is July's; readiness is today's gate. Both apply."""
    store = tmp_path / "s.jsonl"
    # highest-scored first, as July's scoring stage returns them — but the
    # leader cites no source, so today's gate would refuse it
    unsourced = {
        "SIGNAL_ID": "top-but-unsourced", "HEADLINE": "No source for this one",
        "CORE_FACT": "Something happened.", "CONFIDENCE": "high",
    }
    sourced = {
        "SIGNAL_ID": VERSANT_ID, "HEADLINE": VERSANT_HEADLINE,
        "CORE_FACT": "Versant agreed to acquire Full Swing for $530 million.",
        "REAL_COMPANY_EXAMPLE": "Versant", "SOURCE_FOR_CASE": VERSANT_URL,
        "CONFIDENCE": "high",
    }

    chosen = supply_wednesday_signal(
        seen_ids=set(), research=lambda seen_ids: [unsourced, sourced], store=store
    )
    assert chosen["SIGNAL_ID"] == VERSANT_ID
    assert chosen["ARTICLE_READY"] == "true"
    assert chosen["SOURCE_PREMISE_VERIFIED"] == "true"


def test_candidates_none_of_which_are_article_ready_publish_nothing(tmp_path):
    """The gate is applied, not softened, when nothing qualifies."""
    unsourced = {
        "SIGNAL_ID": "unsourced", "HEADLINE": "No source",
        "CORE_FACT": "Something happened.", "CONFIDENCE": "high",
    }
    chosen = supply_wednesday_signal(
        seen_ids=set(), research=lambda seen_ids: [unsourced],
        store=tmp_path / "s.jsonl",
    )
    assert chosen is None


def test_every_discovered_candidate_is_still_persisted(tmp_path):
    """Even the ones not chosen — the discovery record is the evidence."""
    store = tmp_path / "s.jsonl"
    unsourced = {
        "SIGNAL_ID": "unsourced", "HEADLINE": "No source",
        "CORE_FACT": "Something happened.", "CONFIDENCE": "high",
    }
    supply_wednesday_signal(
        seen_ids=set(), research=lambda seen_ids: [unsourced], store=store
    )
    persisted = [json.loads(line) for line in store.read_text().strip().splitlines()]
    assert [item["SIGNAL_ID"] for item in persisted] == ["unsourced"]
    assert persisted[0]["ARTICLE_READY"] == "false"
