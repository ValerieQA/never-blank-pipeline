"""ENGINE: is a social derivative faithful to the final accepted content? (#260)

A social surface is an adaptation of the FINAL ACCEPTED article: it may
shorten, reorder, restructure and apply platform mechanics, but it may not
state a claim, condition, conclusion, generalization or implication the
accepted article does not — and it may never restore what Editorial
Acceptance/Revision removed. Controlled live run 35417616416 broke exactly
that: Instagram attempts added "without changing the ad or budget" and a
renewed small-business generalization, neither of which the accepted
article stated.

Two enforced, fail-closed checks run on every derivation (the composer
applies them inside its retry-once contract), and one piece of evidence
feeds the second:

1. figures — deterministic, in ``platform_composer`` (#262): no number the
   accepted content does not contain. Numbers compare mechanically;
2. support — an injected fidelity judge lists anything in the derivative the
   accepted content does not state or directly support; any listed item, or
   an unreadable answer, rejects the derivative;
3. removed-by-review evidence — deterministic, here: the phrases the
   reviewed draft had, the final accepted article no longer has, and the
   derivative reuses. Wording is not meaning — revision may reword a claim
   it kept ("rose by twenty eight percent" → "increased 28%"), so reused
   draft wording never rejects on its own (#262 review). It is handed to the
   judge, which is told to treat each such phrase as unsupported unless the
   final content supports the same claim in other words. A genuinely
   removed claim ("without changing the ad or budget") is still rejected,
   by the judge's confirmation.

Generic Engine behaviour: nothing here knows a client, a brand, an audience
or an argument. The judge is given only the two texts and the platform name.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

#: Length of the phrases compared for resurrection. Five words is long enough
#: that an ordinary phrase shared by any two texts ("the number of people who")
#: rarely matches by accident, and short enough to catch a removed clause
#: ("without changing the ad or budget") however it is re-punctuated.
RESURRECTION_NGRAM = 5

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)

#: Words that carry no claim on their own. A removed phrase counts only when it
#: holds at least two words outside this set, so a run of connective words the
#: draft happened to use cannot reject a faithful derivative.
_FUNCTION_WORDS = frozenset("""
a an the and or but nor so yet for of to in on at by with without from into onto
over under about as than then that this these those it its is are was were be
been being has have had do does did not no can could will would should may might
must shall you your we our they their he she his her i me my us them who whom
which what when where why how if because while there here all any each some more
most other such only own same too very just also
""".split())


def _words(text: str) -> list[str]:
    return [word.casefold().replace("’", "'") for word in _WORD.findall(text or "")]


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def removed_phrases(draft: str, final: str, n: int = RESURRECTION_NGRAM) -> frozenset[tuple[str, ...]]:
    """Phrases the reviewed draft contained and the final accepted article does not.

    Only phrases carrying at least two content words count — the removed
    wording, not the connective tissue both versions share.
    """
    final_grams = _ngrams(_words(final), n)
    return frozenset(
        gram for gram in _ngrams(_words(draft), n) - final_grams
        if sum(1 for word in gram if word not in _FUNCTION_WORDS) >= 2
    )


def resurrected_phrases(derivative: str, removed: frozenset[tuple[str, ...]]) -> list[str]:
    """The removed phrases a derivative carries, as readable text, in order."""
    if not removed:
        return []
    words = _words(derivative)
    n = len(next(iter(removed)))
    seen: list[str] = []
    for i in range(len(words) - n + 1):
        gram = tuple(words[i:i + n])
        if gram in removed:
            text = " ".join(gram)
            if text not in seen:
                seen.append(text)
    return seen


class FidelityJudge(Protocol):
    """Lists what a derivative states that its source content does not support.

    ``removed_by_review``: draft phrases the final content no longer carries
    and the derivative reuses — evidence to weigh, not a verdict.
    """

    def unsupported(self, *, final_content: str, derivative: str, surface: str,
                    removed_by_review: tuple[str, ...] = ()) -> list[str]: ...


class FidelityJudgeError(RuntimeError):
    """The judge could not give a usable answer — the derivative is not proven faithful."""


FIDELITY_INSTRUCTIONS = """You check whether a platform adaptation is faithful to the final content it was
adapted from. The adaptation may shorten, compress, omit, reorder and restructure the content,
address the reader directly, and follow platform formatting. It may not say anything the
content does not.

List every factual claim, figure, condition, conclusion, generalization or implication in
ADAPTATION that FINAL CONTENT does not state or directly support. A generalization to a wider
group, a condition ("without...", "only if...", "regardless of..."), a cause, or a consequence
counts as unsupported unless FINAL CONTENT itself says it. Quote each item as it appears in
ADAPTATION. Rephrasings of what FINAL CONTENT says, and lines copied from it, are supported.

REMOVED BY REVIEW, when present, lists wording that an earlier draft had, that FINAL CONTENT no
longer has, and that ADAPTATION reuses. The reviewer may have removed the claim, or only
reworded it. Treat each as unsupported unless FINAL CONTENT states or directly supports the same
claim in other words.

Return ONLY valid JSON: {"unsupported": ["quoted phrase from ADAPTATION", ...]}
Use an empty list when everything in ADAPTATION is supported."""


class ModelFidelityJudge:
    """The production judge: one budget-charged model call per derivative."""

    def unsupported(self, *, final_content: str, derivative: str, surface: str,
                    removed_by_review: tuple[str, ...] = ()) -> list[str]:
        from src.utils.llm_client import chat, model_enrich

        request = {"platform": surface, "FINAL CONTENT": final_content,
                   "ADAPTATION": derivative}
        if removed_by_review:
            request["REMOVED BY REVIEW"] = list(removed_by_review)
        raw = chat(
            system=FIDELITY_INSTRUCTIONS,
            user=json.dumps(request, ensure_ascii=False),
            json_mode=True,
            model=model_enrich(),
        )
        return parse_judgment(raw)


def parse_judgment(raw: str) -> list[str]:
    """The judge's answer, strictly: a list of quoted strings, or an error."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise FidelityJudgeError(f"fidelity judge returned invalid JSON: {exc}") from exc
    items = data.get("unsupported") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise FidelityJudgeError(
            "fidelity judge answer must be {\"unsupported\": [strings]}")
    return [item.strip() for item in items if item.strip()]
