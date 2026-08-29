"""Issue #211: Wednesday's research half, restored from July.

#207/#208 restored July's generation core and #209/#210 wired it to the
publication lifecycle — but both began from a signal the *current* shared
research path produced. That path is what made the Versant specimen
unreachable (#206): its feed set no longer carries CNBC Business, and its
selector rejects "Large company M&A" by name where July's said *"Be
inclusive — prefer false positives over missed signals."*

These scenarios drive the restored research path end to end over a
historical RSS fixture and prove the Versant item survives every stage,
arriving at the generation seam as the historical 46-field signal — with the
exact historical SIGNAL_ID, which the recovered July algorithm reproduces
deterministically.

**Zero paid calls and zero network calls.** RSS is served from a committed
fixture through the module's own `requests` boundary; every LLM stage is
stubbed at its transport.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from src.never_blank.wednesday_july.research import (
    DELIBERATELY_UNUSED_CURRENT_RESEARCH,
    JULY_RESEARCH_STAGE_ORDER,
    SCHEMA_DEFAULTS,
    make_signal_id,
    run_wednesday_research,
)

FIXTURES = Path("tests/fixtures/wednesday_july")
RESEARCH = "src.never_blank.wednesday_july.research"

VERSANT_ID = "37a503640b83be6c"
VERSANT_URL = (
    "https://www.cnbc.com/2026/07/06/"
    "versant-to-buy-golf-simulator-company-full-swing.html"
)
VERSANT_HEADLINE = (
    "Versant agrees to buy golf simulator company Full Swing for $530 million"
)

#: The specimen's own publication day. July's discovery only accepts items
#: inside a 72-hour lookback, so a historical fixture is only reachable from
#: a historical clock — the alternative would be re-dating the evidence.
JULY_6 = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


class _JulyClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return JULY_6 if tz else JULY_6.replace(tzinfo=None)


@pytest.fixture(scope="module")
def historical_signal() -> dict:
    return json.loads(
        (FIXTURES / "versant_full_swing_signal.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def cnbc_feed() -> str:
    return (FIXTURES / "cnbc_business_2026-07-06.xml").read_text(encoding="utf-8")


# ===========================================================================
# Signal identity — the recovered July algorithm, reproduced exactly
# ===========================================================================


def test_the_july_id_algorithm_reproduces_the_historical_signal_id():
    """The governing determinism check: same URL + headline → same ID."""
    assert make_signal_id(VERSANT_URL, VERSANT_HEADLINE) == VERSANT_ID


def test_the_id_is_stable_under_the_july_url_normalisation():
    """July stripped tracking parameters before hashing."""
    assert make_signal_id(
        VERSANT_URL + "?utm_source=newsletter", VERSANT_HEADLINE
    ) == VERSANT_ID
    # …and headline case is normalised
    assert make_signal_id(VERSANT_URL, VERSANT_HEADLINE.upper()) == VERSANT_ID


# ===========================================================================
# Offline transports — no network, no spend
# ===========================================================================


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200
        self.content = text.encode()

    def raise_for_status(self) -> None:
        return None


def _feed_transport(feed_body: str, calls: list):
    def fake_get(url, *args, **kwargs):
        calls.append(url)
        # only the CNBC feed has content; the rest answer empty, as July's
        # own runs routinely did
        if "cnbc.com" in url:
            return _FakeResponse(feed_body)
        return _FakeResponse(
            '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        )
    return fake_get


def _llm_transport(prompts: list):
    """Answers each July research stage in its own schema."""

    def fake_chat(system, user, json_mode=False, model=None, **kwargs):
        prompts.append((system, user))
        blob = f"{system}\n{user}"
        if "Respond with ONLY a JSON object in this exact format" in system or (
            '"selected"' in system
        ):
            return json.dumps({"selected": [0]})          # keep the Versant item
        if "Enrich these news items with signal metadata" in system:
            return json.dumps({"signals": [{
                "index": 0, "REGION": "US", "INDUSTRY": "Media & Entertainment",
                "SIGNAL_TYPE": "operational change",
                "raw_summary": "Versant agreed to acquire Full Swing for $530 million.",
                "discovery_confidence": "high",
            }]})
        if "Score business signals for Never Blank" in system:
            return json.dumps({"scores": [{
                "index": 0, "total_score": 10, "CHANNEL_FIT_SCORE": 9,
                "DISCUSSION_POTENTIAL": "high", "SIGNAL_STRENGTH": "high",
                "score_reason": "documented case with a real company and a source",
            }]})
        if "business research analyst" in system:              # enrich_signal
            return json.dumps({
                "CORE_FACT": "Versant agreed to acquire Full Swing for $530 million.",
                "WHY_IT_MATTERS_TO_BUSINESS": "Cable revenue is declining.",
                "BUSINESS_RESPONSES_OBSERVED": "Media groups buy experiential assets.",
                "REAL_COMPANY_EXAMPLE": "Comcast's Sky acquisition.",
                "PROBLEM_FACED": "Declining cable television revenues.",
                "RESPONSE_TAKEN": "Acquisition of an experiential technology company.",
                "OUTCOME_IF_KNOWN": "unknown", "SOURCE_FOR_CASE": VERSANT_URL,
                "BUSINESS_LESSON": "Diversifying into technology-enabled assets "
                                   "mitigates legacy decline.",
                "DID_IT_WORK": "unknown", "EVIDENCE_OF_OUTCOME": "unknown",
                "TIME_HORIZON": "Short-term announcement; long-term unknown.",
                "COUNTER_EXAMPLE": "Quibi failed to gain traction.",
                "WHY_THIS_CASE_IS_INTERESTING": "It shows media conglomerates "
                                                "redrawing their own category.",
                "CORE_TENSION": "Investing in unproven formats while legacy "
                                "revenue declines.",
                "CONFIDENCE": "high", "NOTES": "",
            })
        if "editorial angles" in system:                       # generate_angles
            return json.dumps({
                "LINKEDIN_ANGLE": "When legacy media bets $530M on a simulator…",
                "BLOG_ANGLE": "Signal, case study, outcome, lesson.",
                "THREADS_ANGLE": "Media giants are buying exits.",
                "STORY_ANGLE": "What happens when growth is a golf simulator?",
                "POTENTIAL_HOOK": "A $530M golf simulator deal says more about "
                                  "cable TV's future than any ratings chart.",
                "INTERESTING_QUESTION": "How do you know when your core business "
                                        "is the risk?",
                "NEVER_BLANK_ANGLE": "The smartest operators are quietly building "
                                     "lifeboats while the ship looks seaworthy.",
                "POSSIBLE_SIGNATURE_LINE": "Never Blank: the real pivot is away "
                                           "from old certainty.",
                "TARGET_AUDIENCE": "founder", "PRIMARY_CHANNEL": "linkedin",
            })
        raise AssertionError(f"unexpected research stage prompt: {system[:120]}")

    return fake_chat


def _run_research(feed_body: str):
    """Drive the REAL research orchestration over offline transports."""
    http_calls: list = []
    prompts: list = []
    stages = ("discover", "enrich", "angles", "score")
    patches = [
        mock.patch(f"{RESEARCH}.discover.requests.get",
                   side_effect=_feed_transport(feed_body, http_calls)),
        mock.patch(f"{RESEARCH}.discover.datetime", _JulyClock),
        # Belt and braces on the no-spend guarantee: the four stage modules
        # bound `chat` at import, so this copy is reachable only by some
        # *other* module joining the run. Nothing may.
        mock.patch("src.utils.llm_client.chat",
                   side_effect=AssertionError("an unstubbed paid call was made")),
    ]
    # Network: `discover` is the only module that opens a socket, and its
    # `requests.get` is stubbed above. `http_calls` records every URL it was
    # asked for, and the feed-set test asserts what those may be.
    patches += [mock.patch(f"{RESEARCH}.{m}.chat", side_effect=_llm_transport(prompts))
                for m in stages]
    for p in patches:
        p.start()
    try:
        signals = run_wednesday_research(seen_ids=set())
    finally:
        for p in patches:
            p.stop()
    return signals, http_calls, prompts


# ===========================================================================
# The golden regression — Versant survives the whole research path
# ===========================================================================


def test_versant_traverses_the_restored_research_path(cnbc_feed, historical_signal):
    signals, http_calls, prompts = _run_research(cnbc_feed)

    assert signals, "the Versant item did not survive discovery"
    versant = next(s for s in signals if s["SIGNAL_ID"] == VERSANT_ID)

    # identity, straight from the July algorithm
    assert versant["SIGNAL_ID"] == VERSANT_ID
    assert versant["SOURCE_NAME"] == "CNBC Business"
    assert versant["SOURCE_URL"] == VERSANT_URL
    assert versant["HEADLINE"] == VERSANT_HEADLINE

    # the enrichment fields the July generation stages consume
    for field in ("CORE_FACT", "CORE_TENSION", "BUSINESS_LESSON",
                  "WHY_THIS_CASE_IS_INTERESTING", "COUNTER_EXAMPLE"):
        assert versant[field], f"{field} missing from the restored signal"

    # the angle fields — July's framing intelligence
    for field in ("POTENTIAL_HOOK", "NEVER_BLANK_ANGLE", "BLOG_ANGLE",
                  "LINKEDIN_ANGLE", "INTERESTING_QUESTION",
                  "POSSIBLE_SIGNATURE_LINE", "THREADS_ANGLE", "STORY_ANGLE"):
        assert versant[field], f"{field} missing from the restored signal"

    # the historical 46-field contract, field for field
    assert set(versant) == set(historical_signal), (
        f"schema drift: "
        f"missing={sorted(set(historical_signal) - set(versant))} "
        f"extra={sorted(set(versant) - set(historical_signal))}"
    )


def test_the_restored_signal_reaches_the_generation_seam(cnbc_feed):
    """Research output is exactly what the restored generator consumes."""
    signals, _http, _prompts = _run_research(cnbc_feed)
    versant = next(s for s in signals if s["SIGNAL_ID"] == VERSANT_ID)

    with mock.patch(
        "src.never_blank.wednesday_july.pipeline.generate_decision_lens",
        side_effect=AssertionError("generation stage ran — should be stubbed"),
    ):
        with mock.patch(
            "src.never_blank.wednesday_routing.generate_wednesday_article"
        ) as generation:
            from src.never_blank.wednesday_routing import generate_for_wednesday

            generation.return_value = {
                "decision_lens": {}, "narrative_spine": {},
                "structured_article": {"signature": "Never Blank: x."},
                "platforms": {"long": {"body": "b"}, "medium": {"body": "m"}},
            }
            generate_for_wednesday(versant)

    routed = generation.call_args.args[0]
    assert routed["SIGNAL_ID"] == VERSANT_ID
    assert routed["CORE_TENSION"]
    assert routed["POTENTIAL_HOOK"]


# ===========================================================================
# July selection semantics — inclusive, and never the current filters
# ===========================================================================


def test_the_selector_prompt_is_the_inclusive_july_one(cnbc_feed):
    _signals, _http, prompts = _run_research(cnbc_feed)
    systems = "\n".join(system for system, _user in prompts)

    assert "Be inclusive — prefer false positives over missed signals." in systems

    # …and not one line of the current selector reaches this path. These are
    # verbatim from config/prompts/research/signal_selector.yaml — the second
    # of the two 2026-07-21 changes that made the specimen unreachable.
    for current_rule in (
        "ALWAYS REJECT — no exceptions:",
        "Large company M&A, earnings, product launches with no documented mechanism",
        "It is correct to return an empty list.",
        "corporate case study, no owner mechanism",
        "Never Blank does NOT publish advice.",
    ):
        assert current_rule not in systems, f"current selector rule leaked: {current_rule}"


def test_the_july_feed_set_is_used_not_the_current_one(cnbc_feed):
    _signals, http_calls, _prompts = _run_research(cnbc_feed)

    fetched = " ".join(http_calls)
    # July's sources
    for july_feed in ("cnbc.com", "bloomberg.com", "techcrunch.com",
                      "arstechnica.com", "axios.com", "hbr.org"):
        assert july_feed in fetched, f"July feed missing: {july_feed}"
    # the current small-business set must not be consulted
    for current_feed in ("smallbiztrends.com", "score.org", "inc.com",
                         "hubspot.com", "contentmarketinginstitute.com",
                         "searchenginejournal.com"):
        assert current_feed not in fetched, f"current feed leaked: {current_feed}"


def test_the_shared_scoring_weights_have_not_drifted_from_july():
    """The one config this path still shares — pinned, not assumed.

    ``score.py`` reads ``config/scoring_weights.yaml``, which is byte-identical
    to its July state, so sharing it changes nothing today. But its criteria
    are editorial judgment, not infrastructure: if Monday work ever retunes
    them, Wednesday would inherit the change silently. This fails first.
    """
    july = (FIXTURES / "july_research_originals" /
            "scoring_weights.yaml.txt").read_text()
    assert Path("config/scoring_weights.yaml").read_text() == july, (
        "config/scoring_weights.yaml drifted from July. Wednesday reads it. "
        "Either pin a July copy inside wednesday_july/research/ or make the "
        "change deliberately for both products."
    )


def test_the_isolated_feed_configuration_travels_with_the_package():
    from src.never_blank.wednesday_july.research import discover

    assert discover.SOURCES_CONFIG.name == "research_sources_july.yaml"
    assert discover.SOURCES_CONFIG.parent.name == "research"
    assert discover.SOURCES_CONFIG.exists()

    import yaml

    config = yaml.safe_load(discover.SOURCES_CONFIG.read_text())
    names = {feed["name"] for feed in config["rss_feeds"]}
    assert "CNBC Business" in names
    assert "Small Business Trends" not in names


# ===========================================================================
# Isolation and anti-regression
# ===========================================================================


def test_the_research_package_calls_no_current_business_logic():
    """No current business rule is *executed* here — prose about them is fine."""
    import ast

    forbidden = {
        "ExaResearchAdapter", "extract_pattern", "select_eligible_signal",
        "resolve_editorial_role", "generate_decision_lens",
        "evaluate_editorial_acceptance", "validate_source_transparency",
        "load_prompt",           # the current prompt registry (signal_selector)
    }
    for path in Path("src/never_blank/wednesday_july/research").glob("*.py"):
        tree = ast.parse(path.read_text())
        used = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute))
        }
        leaked = used & forbidden
        assert not leaked, f"{path.name} calls current business logic: {leaked}"


def test_only_technical_infrastructure_is_shared():
    allowed = ("src.utils.llm_client", "src.utils.logger",
               "src.never_blank.wednesday_july")
    for path in Path("src/never_blank/wednesday_july/research").glob("*.py"):
        for line in path.read_text().splitlines():
            if line.startswith("from src.") or line.startswith("import src."):
                assert any(line.startswith(f"from {root}") or
                           line.startswith(f"import {root}") for root in allowed), (
                    f"{path.name}: {line}"
                )


def test_wednesday_research_can_never_be_routed_through_current_discovery():
    """The anti-regression: silently reverting must fail a test, not a run.

    Read as an import graph rather than as text — the modules *name* the
    current path in prose in order to explain why they avoid it, and prose
    must not be mistaken for a dependency.
    """
    import ast

    imported: set[str] = set()
    for path in Path("src/never_blank/wednesday_july/research").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)

    # the orchestration calls the RESTORED stages
    assert "src.never_blank.wednesday_july.research.discover" in imported

    # …and reaches nothing from the current research path
    for module in imported:
        assert not module.startswith("scripts.research"), module
        assert not module.startswith("src.research"), module
        assert "exa" not in module.lower(), module

    for banned in DELIBERATELY_UNUSED_CURRENT_RESEARCH:
        if banned.endswith(".yaml"):
            continue                      # a path, checked by the feed-set test
        assert banned not in imported, f"current research module re-entered: {banned}"


def test_the_ported_research_modules_are_verbatim_july():
    originals = FIXTURES / "july_research_originals"
    for original in sorted(originals.glob("*.py.txt")):
        module = original.name.replace(".py.txt", "")
        ported = Path(
            f"src/never_blank/wednesday_july/research/{module}.py"
        ).read_text()
        for line in original.read_text().splitlines():
            # the two recorded mechanical adaptations
            if 'SOURCES_CONFIG = Path("config/research_sources.yaml")' in line:
                continue
            if "parents[2]" in line:
                continue
            assert line in ported, f"{module}: lost July line {line!r}"


def test_the_july_feed_file_is_verbatim():
    original = (FIXTURES / "july_research_originals" /
                "research_sources.yaml.txt").read_text()
    ported = Path(
        "src/never_blank/wednesday_july/research/research_sources_july.yaml"
    ).read_text()
    assert ported == original


def test_the_generation_modules_are_untouched_by_this_change():
    originals = FIXTURES / "july_originals"
    for original in sorted(originals.glob("*.py.txt")):
        module = original.name.replace(".py.txt", "")
        ported = Path(f"src/never_blank/wednesday_july/{module}.py").read_text()
        for line in original.read_text().splitlines():
            if line.strip().startswith("from src.editorial."):
                continue
            assert line in ported, f"{module}: research work altered generation"


def test_the_stage_order_is_the_july_order():
    assert JULY_RESEARCH_STAGE_ORDER == (
        "discovery", "scoring", "enrichment", "angles"
    )


def test_no_eligible_candidate_is_an_acceptable_outcome():
    """July published nothing rather than lowering the bar; so does this."""
    signals = run_wednesday_research(seen_ids=set(), discovery=lambda seen: [])
    assert signals == []


def test_already_seen_candidates_are_not_reprocessed():
    seen = {VERSANT_ID}
    signals = run_wednesday_research(
        seen_ids=seen,
        discovery=lambda _seen: [{"SIGNAL_ID": VERSANT_ID, "HEADLINE": "x"}],
        scorer=lambda items: (_ for _ in ()).throw(
            AssertionError("scoring ran for a seen candidate")
        ),
    )
    assert signals == []


def test_the_schema_defaults_carry_every_historical_field(historical_signal):
    """No historical field may be silently dropped because nothing reads it."""
    supplied_by_discovery = {
        "SIGNAL_ID", "HEADLINE", "SOURCE_URL", "SOURCE_DATE", "SOURCE_NAME",
        "REGION", "INDUSTRY", "SIGNAL_TYPE", "DATE_FOUND",
    }
    for field in historical_signal:
        assert field in SCHEMA_DEFAULTS or field in supplied_by_discovery, (
            f"historical field {field} would be lost"
        )
