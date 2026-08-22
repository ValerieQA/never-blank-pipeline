"""Issue #176: hashtags are a deterministic formatting rule, not a model call.

The last model-backed hashtag call reachable on the canonical path (LinkedIn)
is replaced by a deterministic implementation of the documented product rule:
three branded tags first, then bounded article-specific tags, prohibitions
enforced. These scenarios prove determinism, structural zero-transport,
sanitization, bounds, assembly position, and that every cost-safety contract
from #170–#175 composes unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import src.publishing.hashtags as hashtags
from src.publishing.formatting import append_hashtags
from src.publishing.hashtags import (
    BRANDED_HASHTAGS,
    PROHIBITED_HASHTAGS,
    generate_hashtags,
)
from src.utils import llm_client


SIGNAL = {
    "SIGNAL_ID": "sig-hash",
    "HEADLINE": "Neighborhood bakery doubled repeat orders with a posted schedule",
    "INDUSTRY": "food service",
    "SIGNAL_TYPE": "market_trend",
    "REAL_COMPANY_EXAMPLE": "Corner Bakery",
    "BUSINESS_LESSON": "Schedules build repeat demand.",
}


# ===========================================================================
# 1–2. Deterministic, and no transport can exist
# ===========================================================================


def test_identical_input_always_produces_identical_output():
    runs = [generate_hashtags(dict(SIGNAL), "linkedin") for _ in range(5)]
    assert all(r == runs[0] for r in runs)
    assert runs[0][:3] == list(BRANDED_HASHTAGS)


def test_no_model_transport_is_structurally_possible(monkeypatch):
    class ExplodingClient:
        def __getattr__(self, name):
            raise AssertionError("hashtags reached a model transport")

    monkeypatch.setattr(llm_client, "_client", ExplodingClient())
    tags = generate_hashtags(SIGNAL, "linkedin")
    assert len(tags) >= 3
    monkeypatch.setattr(llm_client, "_client", None)
    # and the module no longer even imports the chat client
    source = Path("src/publishing/hashtags.py").read_text()
    assert "chat" not in source.replace("hashtags", "")
    assert "llm_client" not in source
    assert not hasattr(hashtags, "chat")


# ===========================================================================
# 3–5. Sanitization, dedupe, bounds
# ===========================================================================


def test_duplicates_are_eliminated_case_insensitively():
    signal = {**SIGNAL, "INDUSTRY": "never blank", "SIGNAL_TYPE": "NEVER BLANK"}
    tags = generate_hashtags(signal, "linkedin")
    lowered = [t.casefold() for t in tags]
    assert len(lowered) == len(set(lowered))
    assert lowered.count("#neverblank") == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("INDUSTRY", ""), ("INDUSTRY", "   "), ("INDUSTRY", "###"),
        ("INDUSTRY", "a"), ("INDUSTRY", 42), ("INDUSTRY", None),
        ("HEADLINE", "https://gartner.com/report?id=secret-token-123"),
        ("SIGNAL_TYPE", "x" * 100),
    ],
    ids=["empty", "whitespace", "punctuation", "too-short", "non-string",
         "none", "url-shaped-headline", "overlong"],
)
def test_malformed_candidates_are_refused_deterministically(field, value):
    signal = {**SIGNAL, field: value}
    tags = generate_hashtags(signal, "linkedin")
    for tag in tags:
        assert tag.startswith("#")
        assert " " not in tag and "\n" not in tag
        assert 2 <= len(tag) <= 41
        assert "http" not in tag.casefold()
        assert "secret" not in tag.casefold()
    # branded contract survives any field damage
    assert tags[:3] == list(BRANDED_HASHTAGS)


def test_unicode_input_is_normalized_safely():
    signal = {**SIGNAL, "INDUSTRY": "cafés & pâtisserie",
              "HEADLINE": "Рестораны получили новую лицензию быстро"}
    tags = generate_hashtags(signal, "linkedin")
    for tag in tags:
        assert tag.startswith("#") and " " not in tag


@pytest.mark.parametrize("platform,hi", [("linkedin", 6), ("facebook", 6),
                                         ("instagram", 6), ("threads", 2)])
def test_count_is_bounded_per_platform(platform, hi):
    tags = generate_hashtags(SIGNAL, platform)
    assert len(tags) <= hi


def test_prohibited_tags_never_appear():
    signal = {**SIGNAL, "INDUSTRY": "presence system",
              "SIGNAL_TYPE": "content marketing"}
    tags = generate_hashtags(signal, "linkedin")
    assert all(t.casefold() not in PROHIBITED_HASHTAGS for t in tags)


def test_company_names_never_become_hashtags():
    tags = generate_hashtags(SIGNAL, "linkedin")
    assert "#CornerBakery" not in tags
    # nor via the headline keyword path
    signal = {**SIGNAL, "HEADLINE": "Corner Bakery doubled repeat orders"}
    tags = generate_hashtags(signal, "linkedin")
    assert all("corner" not in t.casefold() and "bakery" not in t.casefold()
               for t in tags)


# ===========================================================================
# 6. Assembly: the hashtag line still lands last on LinkedIn
# ===========================================================================


def test_linkedin_assembly_places_hashtags_at_the_end():
    body = "LinkedIn body text.\n\nSource: example"
    tags = generate_hashtags(SIGNAL, "linkedin")
    assembled = append_hashtags(body, tags)
    assert assembled.endswith(" ".join(tags))
    assert assembled.startswith(body)
    assert f"\n\n{tags[0]}" in assembled


# ===========================================================================
# 7–8. The canonical entrypoint contract, both streams
# ===========================================================================


def test_the_canonical_run_still_calls_hashtags_for_linkedin_only(tmp_path):
    import scripts.generate_and_publish as gap
    from scripts.generate_and_publish import main
    from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
    from tests.test_research_artifact_lifecycle import ReadyProvider

    from tests import test_generate_and_publish as legacy

    argv, patches = _entry_patches(tmp_path)
    del patches["formatting"]           # real deterministic assembly
    evaluator, _ = _evaluator(_model_output())
    # the real R1 shape (#175): inactive surfaces are never composed, so
    # their gate never fires — the legacy all-platform fake would
    # legitimately trigger the (gated) instagram call
    patches["generate_article"] = mock.MagicMock(return_value={
        "platforms": {
            "long": {"body": "Blog body text.", "title": "T"},
            "medium": {"body": "LinkedIn post text."},
        },
        "structured_article": legacy._FAKE_ARTICLE["structured_article"],
    })
    calls: list = []
    real = generate_hashtags

    def recording(signal, platform):
        calls.append(platform)
        return real(signal, platform)

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(gap, "generate_hashtags", side_effect=recording):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert calls == ["linkedin"]        # #175 gate + the deterministic call
    pkg = json.loads(next(tmp_path.glob("*/runs/*/generated.json")).read_text())
    # the branded trio leads the hashtag line inside the published artifact
    linkedin = pkg["linkedin_post"]
    assert "#NeverBlank #CompoundPresence #CustomerTrust" in linkedin
    # and the hashtag line is the final line of the post
    assert linkedin.rstrip().splitlines()[-1].startswith("#NeverBlank")


def test_both_streams_share_the_same_hashtag_call_site():
    source = Path("scripts/generate_and_publish.py").read_text()
    assert source.count('generate_hashtags(signal, "linkedin")') == 1
    assert source.count('generate_hashtags(signal, "instagram")') == 1  # gated by #175


# ===========================================================================
# 9–14. Cost-safety contracts compose unchanged (full suites in the battery)
# ===========================================================================


def test_cost_safety_contracts_survive(monkeypatch):
    import os
    from src.editorial.source_eligibility import SourceEligibilityError
    from src.run.call_budget import (
        RunCallBudget, RunCallBudgetExceededError, activate_call_budget,
    )

    # #170 scope classification intact
    assert SourceEligibilityError("x").scope == "candidate"
    # #171: hashtags no longer charge the budget at all — an exhausted
    # budget cannot be tripped by hashtag generation
    exhausted = RunCallBudget(limit=1)
    exhausted.spend()
    with activate_call_budget(exhausted):
        tags = generate_hashtags(SIGNAL, "linkedin")   # no charge, no raise
    assert tags[:3] == list(BRANDED_HASHTAGS)
    # #172: credentials stripped here
    assert os.environ.get("NB_OPENAI_API_KEY") is None
    # #173: social-model routing no longer has a hashtag consumer; the
    # resolver itself is untouched
    monkeypatch.setenv("NB_SOCIAL_MODEL", "test-social-model")
    assert llm_client.model_social() == "test-social-model"
