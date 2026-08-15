"""Issue #93 / Story #14: LinkedIn composition traceability and acceptance.

Covers the canonical mapping correction (``medium`` IS the LinkedIn artifact),
the deterministic channel acceptance, the strict traceability record, and the
fail-closed entrypoint gate — through the real canonical production path with
injected fakes. No live LLM calls. The live-artifact Story #14 criterion is
deferred live verification (Story #19 / #21), not faked here.
"""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial.linkedin_composition import (
    LINKEDIN_MAX_WORDS,
    LINKEDIN_MIN_WORDS,
    LinkedInCompositionError,
    accept_linkedin_composition,
    article_digest,
    verify_linkedin_composition_record,
)
from src.editorial.platform_composer import (
    LINKEDIN_COMPOSITION_RULES_VERSION,
    _FORMAT_CONSTRAINTS,
    _PLATFORM_NAMES,
    compose_platforms,
)
from src.strategy.execution_context import ConfigurationIdentity
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider


def _identity() -> ConfigurationIdentity:
    return ConfigurationIdentity(
        schema_version="1",
        configuration_id="never-blank-production",
        configuration_version="2.0",
        configuration_hash="sha256:" + "a" * 64,
    )


def _native_linkedin_body() -> str:
    """A channel-native body inside the 120–220-word tolerance band.

    Sentences stay under eight words so the output-guard sentence checks
    treat them as short-form prose, mirroring real LinkedIn cadence.
    """

    sentences = [
        "Your clients notice silence first.", "Not the busy weeks behind it.",
        "Delivery fills every calendar slot.", "Presence quietly loses that fight.",
        "Nobody plans to disappear.", "The system produces the gap.",
        "One owner recognized this pattern.", "Bookings dipped two months later.",
        "The cause sat months earlier.", "Visibility works on a delay.",
        "So the fix is structural.", "Not another burst of posting.",
        "Build presence into operations.", "Make it survive busy seasons.",
        "That is the real question.", "What runs when you cannot?",
        "Start with one weekly slot.", "Protect it like delivery work.",
    ]
    return " ".join(sentences)


ARTICLE_BODY = (
    "The blog article develops a complete owner-centered argument about "
    "structural visibility debt, grounded in the accepted research evidence "
    "and written for careful long-form reading."
)


def _accept_kwargs(**overrides):
    kwargs = dict(
        linkedin_body=_native_linkedin_body(),
        article_body=ARTICLE_BODY,
        run_id="run-a",
        signal_id="sig-test-001",
        configuration_identity=_identity(),
        strategy_id="2026-07-presence-debt-campaign-1",
        strategy_version="1",
    )
    kwargs.update(overrides)
    return kwargs


# ===========================================================================
# 1+3. Canonical mapping correction
# ===========================================================================


def test_medium_is_validated_as_linkedin_and_reading_as_facebook():
    assert _PLATFORM_NAMES["medium"] == "linkedin"
    assert _PLATFORM_NAMES["reading"] == "facebook"


def test_medium_constraint_is_linkedin_native_and_reading_is_facebook():
    assert "LinkedIn" in _FORMAT_CONSTRAINTS["medium"]
    assert "Facebook" not in _FORMAT_CONSTRAINTS["medium"]
    assert "Facebook" in _FORMAT_CONSTRAINTS["reading"]
    assert "native LinkedIn post" not in _FORMAT_CONSTRAINTS["reading"]


# ===========================================================================
# 2+6+7. LinkedIn strategy rules reach the canonical medium composition
# ===========================================================================


def test_linkedin_strategy_rules_reach_the_medium_prompt():
    from src.strategy.business_config import LinkedInChannelRules
    from src.strategy.execution_context import LinkedInStrategyView

    view = LinkedInStrategyView(
        identity=_identity(),
        rules=LinkedInChannelRules(
            opening_rules=("Open with the owner situation, never the company.",),
            length_rules=("Stay within the LinkedIn target length.",),
            formatting_rules=("Use short scannable paragraphs.",),
            link_rules=("Place the source link after the body.",),
            cta_rules=("Close with the configured reflection CTA only.",),
            visual_rules=("Attach the configured visual asset.",),
        ),
    )
    article = {**legacy._FAKE_ARTICLE["structured_article"], "echo_line": None,
               "signature": "", "cta_line": None, "reader_context": None,
               "remaining_uncertainty": None}
    prompts: list[str] = []

    def capture(**kwargs):
        prompts.append(kwargs["user"])
        return json.dumps({"body": "Distinct sentence one here. Another different thought follows."})

    with mock.patch("src.editorial.platform_composer.chat", side_effect=capture):
        compose_platforms(article, cta_mode="diagnostic", linkedin_strategy=view)

    medium_prompt = next(p for p in prompts if "FORMAT: medium" in p)
    assert "CONFIGURED CHANNEL RULES" in medium_prompt
    for rule in ("owner situation", "target length", "scannable paragraphs",
                 "source link", "reflection CTA"):
        assert rule in medium_prompt
    assert "CTA MODE: diagnostic" in medium_prompt
    # rules go to the canonical LinkedIn artifact only, not to reading
    reading_prompt = next(p for p in prompts if "FORMAT: reading" in p)
    assert "CONFIGURED CHANNEL RULES" not in reading_prompt


# ===========================================================================
# 4+5+10. Deterministic channel acceptance
# ===========================================================================


def test_native_composition_is_accepted_with_full_lineage():
    record = accept_linkedin_composition(**_accept_kwargs())
    assert record.status.value == "accepted"
    assert record.run_id == "run-a"
    assert record.signal_id == "sig-test-001"
    assert record.configuration_identity == _identity()
    assert record.strategy_id == "2026-07-presence-debt-campaign-1"
    assert record.strategy_version == "1"
    assert record.composition_rules_version == LINKEDIN_COMPOSITION_RULES_VERSION
    assert record.source_article_digest == article_digest(ARTICLE_BODY)
    assert record.linkedin_body == _native_linkedin_body()
    assert LINKEDIN_MIN_WORDS <= record.word_count <= LINKEDIN_MAX_WORDS


def test_identical_copy_of_the_article_is_rejected():
    with pytest.raises(LinkedInCompositionError, match="identical"):
        accept_linkedin_composition(**_accept_kwargs(linkedin_body=ARTICLE_BODY))


def test_copied_opening_is_rejected():
    body = ("The blog article develops a complete owner-centered argument about "
            "structural visibility debt. " + _native_linkedin_body())
    with pytest.raises(LinkedInCompositionError, match="opening"):
        accept_linkedin_composition(**_accept_kwargs(
            linkedin_body=body,
            article_body="The blog article develops a complete owner-centered "
                         "argument about structural visibility debt. And then "
                         "continues into the long-form reasoning at length.",
        ))


def test_sentence_length_copying_is_rejected():
    stolen = ("A business whose presence depends entirely on the owner will be "
              "least visible when it most needs attention.")
    article = ARTICLE_BODY + " " + stolen
    body = _native_linkedin_body() + " " + stolen
    with pytest.raises(LinkedInCompositionError, match="copies sentence-length"):
        accept_linkedin_composition(**_accept_kwargs(
            linkedin_body=body, article_body=article))


@pytest.mark.parametrize("words,expect", [(20, "outside"), (400, "outside")])
def test_length_outside_release1_tolerance_is_rejected(words, expect):
    body = " ".join(f"word{i}" for i in range(words))
    with pytest.raises(LinkedInCompositionError, match=expect):
        accept_linkedin_composition(**_accept_kwargs(linkedin_body=body))


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_malformed_or_empty_composition_fails_closed(bad):
    with pytest.raises(LinkedInCompositionError, match="empty or malformed"):
        accept_linkedin_composition(**_accept_kwargs(linkedin_body=bad))


# ===========================================================================
# 9. Cross-run / configuration / source drift fails closed
# ===========================================================================


def test_record_verification_fails_closed_on_drift():
    record = accept_linkedin_composition(**_accept_kwargs())
    verify_linkedin_composition_record(
        record, run_id="run-a", configuration_identity=_identity(),
        article_body=ARTICLE_BODY,
    )
    with pytest.raises(LinkedInCompositionError, match="different run"):
        verify_linkedin_composition_record(
            record, run_id="run-b", configuration_identity=_identity(),
            article_body=ARTICLE_BODY,
        )
    with pytest.raises(LinkedInCompositionError, match="configuration identity"):
        verify_linkedin_composition_record(
            record, run_id="run-a",
            configuration_identity=_identity().model_copy(
                update={"configuration_hash": "sha256:" + "b" * 64}),
            article_body=ARTICLE_BODY,
        )
    with pytest.raises(LinkedInCompositionError, match="source article"):
        verify_linkedin_composition_record(
            record, run_id="run-a", configuration_identity=_identity(),
            article_body=ARTICLE_BODY + " tampered",
        )


# ===========================================================================
# 8+11+12+13. Real canonical entrypoint
# ===========================================================================


def _entry(tmp_path, *, medium_body, long_body=None, dry_run=True):
    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    del patches["accept_linkedin_composition"]      # exercise the real gate
    del patches["write_linkedin_composition_json"]
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = long_body or ARTICLE_BODY
    article["platforms"]["medium"]["body"] = medium_body
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


def test_entrypoint_persists_traceable_record_for_accepted_composition(tmp_path):
    code, patches = _entry(tmp_path, medium_body=_native_linkedin_body())
    assert code == 0
    records = list(tmp_path.glob("*/runs/*/linkedin_composition.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    run_id = records[0].parent.name
    # exact run/source/strategy/rule-version lineage (criterion 8)
    assert record["run_id"] == run_id
    assert record["signal_id"] == legacy._SIGNAL_ID
    assert record["strategy_id"] == legacy._STRATEGY_STUB.strategy_id
    assert record["strategy_version"] == legacy._STRATEGY_STUB.strategy_version
    assert record["composition_rules_version"] == LINKEDIN_COMPOSITION_RULES_VERSION
    assert record["status"] == "accepted"
    generated = json.loads(next(tmp_path.glob("*/runs/*/generated.json")).read_text())
    assert record["source_article_digest"] == article_digest(generated["blog_article"])
    # the canonical LinkedIn body is the medium composition, never reading (12)
    assert record["linkedin_body"] == generated["linkedin_post"]
    assert record["linkedin_body"] == _native_linkedin_body()
    assert record["linkedin_body"] != legacy._FAKE_ARTICLE["platforms"]["reading"]["body"]
    # article generation ran exactly once — no channel regeneration (13)
    assert patches["generate_article"].call_count == 1


def test_failed_linkedin_acceptance_produces_zero_publisher_effects(tmp_path):
    # medium identical to the article: not channel-native → fail closed (11)
    code, patches = _entry(
        tmp_path, medium_body=ARTICLE_BODY, dry_run=False
    )
    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    assert not list(tmp_path.glob("*/runs/*/publication_results.json"))
    # no record for a failed composition, and no fallback to reading (12)
    assert not list(tmp_path.glob("*/runs/*/linkedin_composition.json"))
