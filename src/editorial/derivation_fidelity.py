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
   an unreadable answer, rejects the derivative. It judges what each sentence
   of the derivative CLAIMS, never how similar its tokens are to the source
   (#269): a faithful rephrase, a question, an imperative, an evaluation,
   reader-facing stakes and platform-native framing all pass, while a claim
   that is merely stated more strongly fails even though every word of it
   came from the article;
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

import hashlib
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


#: What makes a derivative item unsupported — materially NEW meaning (#263),
#: extended by #269 with the ways a claim is not new but *stronger*. Anything
#: else — paraphrase, compression, restructuring, a question, an imperative,
#: an evaluation, reader-facing stakes, a restatement of what the article says
#: or reasonably entails — is faithful.
#:
#: Whether a derivative may carry an author-experience fact the article does
#: not state is an open Product Owner decision (#266). Until it is made such a
#: sentence is ``new_fact``, which fails closed; if it is permitted it needs
#: its own provenance channel rather than a hole in this list.
UNSUPPORTED_KINDS = frozenset({
    "new_fact", "new_number", "new_entity", "new_timeframe", "new_cause",
    "new_condition", "broader_generalization", "new_conclusion",
    "strengthened_claim", "invented_attribution",
})

FIDELITY_INSTRUCTIONS = """You check a platform adaptation against the FINAL CONTENT it was adapted from.

The adaptation may freely paraphrase, compress, reorder, restructure, change emphasis, ask a
question, address the reader directly, give an instruction, offer an evaluation, name what is at
stake for the reader and follow platform formatting. Different wording is NOT a problem: you are
not checking wording, and you are not comparing texts token by token — you are judging what each
sentence of ADAPTATION claims. A sentence that says in other words what FINAL CONTENT says, or
what FINAL CONTENT reasonably entails, is faithful — including restatements of its mechanism, its
conclusions and its advice.

Report an item ONLY when it adds materially new meaning, or states an existing claim more
strongly, than FINAL CONTENT states or reasonably entails — and only of one of these kinds:
- new_fact: a fact FINAL CONTENT does not establish;
- new_number: a figure, quantity, share or rate FINAL CONTENT does not contain;
- new_entity: a company, product, person, institution, place or law FINAL CONTENT does not name;
- new_timeframe: a date, period, deadline or duration FINAL CONTENT does not state;
- new_cause: a causal relationship FINAL CONTENT does not claim;
- new_condition: a condition, scope limit or qualifier FINAL CONTENT does not state
  ("without...", "only if...", "regardless of...");
- broader_generalization: a claim extended to a wider group, market or situation than FINAL
  CONTENT covers;
- new_conclusion: a conclusion, business implication or recommendation FINAL CONTENT does not
  draw or reasonably entail;
- strengthened_claim: the same claim stated more strongly than FINAL CONTENT states it — in
  modality (may becomes does, often becomes always), scope, direction, or causality (a link
  FINAL CONTENT reports as association presented as cause);
- invented_attribution: words, a finding or a position attributed to a source, a company or a
  study that FINAL CONTENT does not attribute to it.

REMOVED BY REVIEW, when present, lists wording an earlier draft had that FINAL CONTENT no longer
has and that ADAPTATION reuses. The reviewer may have removed the claim or only reworded it:
report it only if its meaning is not stated or reasonably entailed by FINAL CONTENT.

Quote each item exactly as it appears in ADAPTATION. Return ONLY valid JSON:
{"unsupported": [{"quote": "...", "kind": "<one of the kinds above>", "reason": "one sentence"}]}
Use an empty list when the adaptation adds no materially new meaning."""


class ModelFidelityJudge:
    """The production judge: one budget-charged model call per derivative."""

    #: The setting that names the model — recorded instead of the model value,
    #: which deployments keep as a secret.
    model_setting = "NB_ENRICH_MODEL"

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


def parse_judgment(raw: str) -> list[dict]:
    """The judge's answer, strictly: materially-new items of known kinds, or an error."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise FidelityJudgeError(f"fidelity judge returned invalid JSON: {exc}") from exc
    items = data.get("unsupported") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise FidelityJudgeError('fidelity judge answer must be {"unsupported": [items]}')
    parsed: list[dict] = []
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get("quote"), str)
                or not item["quote"].strip() or item.get("kind") not in UNSUPPORTED_KINDS
                or not isinstance(item.get("reason", ""), str)):
            raise FidelityJudgeError(
                "every unsupported item must be {quote, kind, reason} with kind one of "
                + ", ".join(sorted(UNSUPPORTED_KINDS)))
        parsed.append({"quote": item["quote"].strip(), "kind": item["kind"],
                       "reason": item.get("reason", "").strip()})
    return parsed


def item_text(item) -> str:
    """An unsupported item as text, whichever judge produced it."""
    return item.get("quote", "") if isinstance(item, dict) else str(item)


class RecordedFidelityJudge:
    """Wraps a judge and records every check it makes (#263 diagnostics).

    One record per check — surface, the final accepted content's identity,
    the derivative, the removed-by-review evidence supplied, the items the
    judge returned, PASS/FAIL (or ERROR when the judge could not answer),
    and which judge ran. Diagnostic evidence only: the record never feeds
    back into a verdict or a publication.
    """

    def __init__(self, inner: FidelityJudge, *, sink, identity: dict) -> None:
        self.inner, self.sink, self.identity = inner, sink, dict(identity)

    def unsupported(self, *, final_content: str, derivative: str, surface: str,
                    removed_by_review: tuple[str, ...] = ()) -> list:
        record = {
            **self.identity,
            "surface": surface,
            "final_content_digest": "sha256:" + hashlib.sha256(
                final_content.encode("utf-8")).hexdigest(),
            "derivative": derivative,
            "removed_by_review": list(removed_by_review),
            "judge": type(self.inner).__name__,
            "model_setting": getattr(self.inner, "model_setting", None),
        }
        try:
            found = self.inner.unsupported(
                final_content=final_content, derivative=derivative, surface=surface,
                removed_by_review=removed_by_review)
        except Exception as exc:
            self.sink({**record, "unsupported": [], "verdict": "ERROR",
                       "error": f"{type(exc).__name__}: {exc}"})
            raise
        self.sink({**record, "unsupported": list(found),
                   "verdict": "FAIL" if found else "PASS"})
        return found
