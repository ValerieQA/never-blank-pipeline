"""Issue #221: sentence-level overlap is allowed across ALL Never Blank surfaces.

CONTROLLED_LIVE run 33913287027 produced an article that passed editorial
acceptance and source transparency, then was blocked by:

    LinkedIn opening copies the Wix article opening — not channel-native

The product owner withdrew that requirement, first for Wix↔LinkedIn and then —
authoritatively — for every surface: Blog, LinkedIn, Instagram, Facebook,
Threads, Telegram, and any future channel. A strong hook, a sentence, or the
Never Blank Echo may recur anywhere. **Recurrence alone is not evidence of a
defect and must never block publication.**

The distinction that survives is whole-artifact, not sentence-level: LinkedIn
must not accidentally receive the entire Wix article as its body, because that
is a wiring failure rather than a style judgement. Those guards stay
fail-closed and are pinned here too.

The withdrawn rule must also not return in a weaker disguise — no similarity
percentage, word- or paragraph-overlap threshold, paraphrase requirement, or
LLM uniqueness judgement replaces it.

No paid calls and no network calls.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest

from src.editorial.platform_composer import (
    _FORMAT_CONSTRAINTS,
    _SYSTEM_PROMPT,
    _build_user_prompt,
    LINKEDIN_COMPOSITION_RULES_VERSION,
)

#: The exact sentence that blocked run 33913287027.
LIVE_HOOK = ("Investors cheered not because ChargePoint promised more growth, "
             "but because it finally slowed down.")
ECHO = ("Never Blank: Sometimes, the most compelling growth story is about "
        "knowing when to hit the brakes.")

#: Every surface Never Blank publishes prose to today.
SURFACES = ("blog", "linkedin", "instagram", "facebook", "threads", "telegram")


# ===========================================================================
# The enforcement is gone from the production path
# ===========================================================================


def _production_callers(symbol: str) -> list[str]:
    """Modules that reference `symbol` outside of tests."""
    roots = list(Path("src").rglob("*.py")) + list(Path("scripts").rglob("*.py"))
    return [str(p) for p in roots if symbol in p.read_text()]


def test_no_production_code_policies_repeated_cross_platform_phrases():
    """The rejection primitive has no production caller anywhere."""
    assert _production_callers("repeated_cross_platform_phrases") == []


def test_the_generator_no_longer_validates_across_platforms():
    source = Path("src/content/generator.py").read_text()
    assert "_validate_cross_platform_outputs" not in source
    assert "Cross-platform copy detected" not in source


def test_publishing_no_longer_rejects_a_sentence_shared_by_three_channels():
    source = Path("scripts/research/publish_packages.py").read_text()
    assert "Cross-platform copy detected before publishing" not in source
    assert 'len(d.get("platforms", [])) >= 3' not in source


def test_linkedin_acceptance_no_longer_reaches_a_phrase_check():
    source = Path("src/editorial/linkedin_composition.py").read_text()
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert "repeated_cross_platform_phrases" not in names
    assert "_first_sentence" not in names


def test_the_rule_did_not_return_as_a_threshold():
    """Explicitly out of bounds: no similarity/overlap heuristic replaces it."""
    banned = (
        "similarity_ratio", "SequenceMatcher", "difflib",
        "jaccard", "overlap_ratio", "word_overlap",
        "paraphrase", "uniqueness_score", "cosine_similarity",
    )
    # Scoped to the modules that composed, validated or published prose — a
    # `cosine_similarity` in the embeddings memory is unrelated to this rule.
    guarded = (
        "src/content/generator.py",
        "src/content/output_guard.py",
        "src/editorial/platform_composer.py",
        "src/editorial/linkedin_composition.py",
        "scripts/research/publish_packages.py",
        "scripts/generate_and_publish.py",
    )
    for name in guarded:
        text = Path(name).read_text()
        for token in banned:
            assert token not in text, f"{name}: introduces {token!r}"


# ===========================================================================
# Allowed: the same sentence on any combination of surfaces
# ===========================================================================


def _package(shared: str, surfaces: tuple[str, ...]) -> dict[str, str]:
    """A package where exactly `surfaces` carry `shared`, each still native."""
    bodies = {
        s: f"A body written for {s} and nothing else, in its own shape and length."
        for s in SURFACES
    }
    for surface in surfaces:
        bodies[surface] = f"{shared} {bodies[surface]}"
    return bodies


def _publish_validation(bodies: dict[str, str]) -> None:
    """Run the real pre-publication package validation."""
    from scripts.research.publish_packages import _validate_package

    texts = {k: v for k, v in bodies.items() if k != "threads"}
    _validate_package(texts, [bodies["threads"], "Second post.", "Third post."])


@pytest.mark.parametrize("surfaces", [
    ("blog", "linkedin"),
    ("blog", "instagram"),
    ("linkedin", "telegram"),
    ("blog", "linkedin", "instagram"),
    ("instagram", "facebook", "threads", "telegram"),
    SURFACES,
])
def test_one_sentence_may_be_shared_by_any_set_of_surfaces(surfaces):
    """Item 5: sentence overlap alone never rejects the package."""
    _publish_validation(_package(LIVE_HOOK, surfaces))     # must not raise


def test_the_never_blank_echo_may_close_every_surface():
    bodies = {
        s: f"A body written for {s} and nothing else, in its own shape. {ECHO}"
        for s in SURFACES
    }
    _publish_validation(bodies)


def test_a_shared_hook_and_a_shared_echo_together_are_allowed():
    bodies = {
        s: f"{LIVE_HOOK} A body written for {s} in its own shape here. {ECHO}"
        for s in SURFACES
    }
    _publish_validation(bodies)


@pytest.mark.parametrize("pair", list(itertools.combinations(SURFACES, 2)))
def test_every_surface_pair_may_share_a_sentence(pair):
    """No pair is privileged: the decision is global, not a Wix↔LinkedIn carve-out."""
    _publish_validation(_package(LIVE_HOOK, pair))


# ===========================================================================
# Still refused: whole-artifact and wiring failures
# ===========================================================================


def test_the_whole_body_guard_is_identity_not_similarity():
    """Only an exact whole-body copy — no threshold hides behind the guard.

    The behavioural proof that an identical body is rejected lives in
    ``test_linkedin_composition.py``; what this pins is the *shape* of the
    check, because a similarity threshold reintroduced here would silently
    restore the withdrawn rule under the surviving guard's name.
    """
    tree = ast.parse(Path("src/editorial/linkedin_composition.py").read_text())
    comparisons = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq)
        and isinstance(node.left, ast.Name) and node.left.id == "body"
    ]
    assert comparisons, "the whole-body identity comparison disappeared"


def test_per_surface_output_guards_still_run():
    """Removing the cross-platform check must not disarm per-platform validation."""
    source = Path("scripts/research/publish_packages.py").read_text()
    assert "validate_platform_output(platform, text)" in source
    assert "validate_article_for_publish(text, platform=platform)" in source


def test_a_repeated_echo_within_one_body_is_still_refused():
    """Within one surface, a duplicated Echo is still a generation defect."""
    from src.content.output_guard import validate_no_duplicate_echo

    doubled = f"{ECHO} Something in between the two closings here. {ECHO}"
    with pytest.raises(ValueError):
        validate_no_duplicate_echo(doubled, "linkedin")


# ===========================================================================
# The rule as an ACTIVE MODEL INSTRUCTION
#
# Removing the validators only stops the pipeline from *rejecting* shared
# prose. The composer was still being *told* not to write it, so the withdrawn
# rule went on shaping every body — a product rule enforced by prompt instead
# of by code, which is harder to see and just as binding. These scenarios read
# the prompt actually sent to the model.
# ===========================================================================

ARTICLE = (
    f"{LIVE_HOOK} The company cut its expansion plan by a third and the market "
    "read that as discipline rather than retreat. For an owner, the same "
    "mechanism decides whether slowing down looks like control or collapse. "
    f"{ECHO}"
)

STRUCTURED = {
    "narrative_spine": "Slowing down can be the growth story.",
    "hook": LIVE_HOOK,
    "echo_line": ECHO,
}

#: Phrasings that would forbid a composer from reusing a line another surface
#: already uses. Matched against the rendered prompt, lowercased.
FORBIDDING_PHRASINGS = (
    "never with the blog opening",
    "do not reuse the blog",
    "not reuse the blog or linkedin opening",
    "do not copy sentences from another format",
    "must not copy the blog intro",
    "do not trim or paraphrase another platform's prose",
    "copying its paragraphs or sentences wholesale",
    "do not reproduce a paragraph from another platform",
    "each platform must receive native wording",
)


def _prompt(format_key: str, **kwargs) -> str:
    return _build_user_prompt(STRUCTURED, format_key, "none", **kwargs)


@pytest.mark.parametrize("format_key", sorted(_FORMAT_CONSTRAINTS))
@pytest.mark.parametrize("phrase", FORBIDDING_PHRASINGS)
def test_no_active_format_prompt_forbids_reusing_another_surfaces_line(
    format_key, phrase
):
    rendered = (_prompt(format_key, canonical_body=ARTICLE) + "\n" + _SYSTEM_PROMPT).lower()
    assert phrase not in rendered, f"{format_key} prompt still instructs: {phrase!r}"


def test_the_linkedin_format_rules_no_longer_mention_the_blog_opening():
    rules = _FORMAT_CONSTRAINTS["medium"].lower()
    assert "opening sentence" not in rules
    assert "never with the blog" not in rules
    # ...and the useful half survives.
    assert "native linkedin post, not a shortened blog" in rules


def test_the_facebook_format_rules_no_longer_mention_the_blog_opening():
    rules = _FORMAT_CONSTRAINTS["reading"].lower()
    assert "opening sentence" not in rules
    assert "do not reuse the blog" not in rules


def test_the_short_format_rules_no_longer_forbid_another_platforms_paragraph():
    rules = _FORMAT_CONSTRAINTS["short"].lower()
    assert "another platform" not in rules
    # the format instruction survives: one thought, not a digest
    assert "do not summarize the article" in rules


def test_the_active_prompt_still_forbids_republishing_the_article():
    """Item 4: the distinction we keep — native body vs the whole article."""
    prompt = _prompt("medium", canonical_body=ARTICLE).lower()
    assert "not a shortened blog" in prompt
    assert "reproducing the long-form wholesale" in prompt
    assert "trimmed to length is rejected" in prompt


def test_the_active_prompt_does_not_instruct_copying_the_article():
    """Permitting shared prose is not the same as requesting a copy."""
    prompt = _prompt("medium", canonical_body=ARTICLE).lower()
    for demand in ("copy the article", "reuse the article body",
                   "repeat the article", "use the same body"):
        assert demand not in prompt


def test_the_echo_verbatim_carve_out_survives_the_rewrite():
    prompt = _prompt("medium", canonical_body=ARTICLE)
    assert "governs ORDINARY PROSE ONLY" in prompt
    assert "must still be reproduced exactly as supplied" in prompt


def test_format_instructions_are_preserved():
    """Item 3: length, structure, CTA shape and hashtags are still instructed."""
    prompt = _prompt("medium", canonical_body=ARTICLE)
    assert "TARGET LENGTH:" in prompt
    assert "short paragraphs of one to three sentences" in prompt
    assert "CTA MODE:" in prompt


def test_the_legacy_linkedin_yaml_prompt_no_longer_forbids_the_blog_intro():
    """The legacy `config/prompts/linkedin_post.yaml` carried the rule too.

    Read as text, not via ``load_prompt``: that file does not currently parse
    as YAML (an inline ``#hashtag`` truncates a scalar around line 64), a
    pre-existing defect on the non-R1 ``generate_content_package`` path. The
    withdrawn instruction is still removed, so the rule cannot return with the
    prompt if that path is ever repaired.
    """
    text = Path("config/prompts/linkedin_post.yaml").read_text().lower()
    assert "must not copy the blog intro" not in text
    assert "post, not the article at linkedin length" in text


def test_the_threads_and_brand_voice_instructions_dropped_the_rule_too():
    """Item 3: the sweep covers every surface, not only LinkedIn."""
    threads = Path("config/prompts/threads_post.yaml").read_text().lower()
    assert "use for depth — do not copy" not in threads
    # the thread's own progression rule is a format rule and survives
    assert "do not repeat the same point" in threads

    voice = Path("config/brand_voice.md").read_text().lower()
    assert "not copy-pasted from blog/linkedin" not in voice


def test_the_composition_rules_version_records_the_new_semantics():
    """Item 7: the instruction changed, so records must not claim 1.0."""
    assert LINKEDIN_COMPOSITION_RULES_VERSION == "linkedin-medium-native/1.1"
