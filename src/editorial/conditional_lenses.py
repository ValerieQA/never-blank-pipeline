"""ENGINE: resolve a client's conditional lenses from a run's research evidence (#263).

A client may write a lens that applies only when a condition holds — its own
``## Activation`` text (see ``src/strategy/client_contracts.py``). This module is
the Engine side: for each conditional lens it asks a judge whether the client's
condition is met by this run's RESEARCH EVIDENCE, and returns which lenses are
active. It knows nothing about any client's condition, behaviour or tone; it
passes the client's criteria through verbatim.

Resolved before the canonical article is composed — after research, before
generation — so an active lens shapes the article from the start rather than
being applied cosmetically afterwards.

The judge sees the research evidence and the signal's own source claims, and
never any text the pipeline generated: a mismatch introduced by our own
writing is a generation error for editorial acceptance to reject, never a
condition a lens can be activated by.

A judge that cannot answer is an error, never an inactive default: a lens the
client asked for must not silently vanish from a run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from src.research.evidence import NormalizedResearchArtifact


@dataclass(frozen=True, slots=True)
class ActivationDecision:
    lens_id: str
    lens_version: str
    active: bool
    #: What in the evidence meets (or fails) the condition — handed to the
    #: writers when active, so they write from the same finding.
    finding: str
    reason: str


class LensActivationJudge(Protocol):
    def decide(self, *, criteria: str, evidence: dict) -> tuple[bool, str, str]:
        """(active, finding, reason) for the client's criteria on this evidence."""


class LensActivationError(RuntimeError):
    """The activation judge could not give a usable answer."""


ACTIVATION_INSTRUCTIONS = """A client supplied a condition under which one of its editorial lenses applies.
Decide whether the condition is met by the RESEARCH EVIDENCE supplied — the sources, the
evidence records extracted from them, any recorded contradictions, and the source signal's own
claims. You are given no article text and must not assume one.

Apply the client's condition as written. Do not infer that it is met merely because the topic
would make an interesting story; decide only from what the evidence shows.

Return ONLY valid JSON:
{"active": true|false,
 "finding": "when active: what in the evidence meets the condition, stated precisely; otherwise an empty string",
 "reason": "one sentence explaining the decision"}"""


def evidence_for_activation(research: NormalizedResearchArtifact, signal: dict) -> dict:
    """The run's research evidence, and the source signal's own claims — nothing generated."""
    return {
        "source_claims": {key: signal.get(key) for key in (
            "HEADLINE", "CORE_FACT", "CORE_TENSION", "BUSINESS_LESSON") if signal.get(key)},
        "sources": [
            {"title": source.title, "publisher": source.publisher,
             "url": getattr(source.locator, "value", None)}
            for source in research.sources
        ],
        "evidence": [
            {"claim": item.claim, "disposition": getattr(item.disposition, "value", str(item.disposition)),
             "support": [ref.excerpt for ref in item.support]}
            for item in research.evidence
        ],
        "contradictions": [
            item.model_dump(mode="json") for item in research.contradictions
        ],
    }


class ModelLensActivationJudge:
    """The production judge: one budget-charged model call per conditional lens."""

    #: The setting that names the model — recorded instead of the model value,
    #: which deployments keep as a secret.
    model_setting = "NB_ENRICH_MODEL"

    def decide(self, *, criteria: str, evidence: dict) -> tuple[bool, str, str]:
        from src.utils.llm_client import chat, model_enrich

        raw = chat(
            system=ACTIVATION_INSTRUCTIONS,
            user=json.dumps({"CLIENT CONDITION": criteria, "RESEARCH EVIDENCE": evidence},
                            ensure_ascii=False),
            json_mode=True,
            model=model_enrich(),
        )
        return parse_activation(raw)


def parse_activation(raw: str) -> tuple[bool, str, str]:
    """The judge's answer, strictly — or an error, never a default."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise LensActivationError(f"activation judge returned invalid JSON: {exc}") from exc
    if (not isinstance(data, dict) or not isinstance(data.get("active"), bool)
            or not isinstance(data.get("finding", ""), str)
            or not isinstance(data.get("reason", ""), str)):
        raise LensActivationError(
            'activation judge answer must be {"active": bool, "finding": str, "reason": str}')
    finding = data.get("finding", "").strip()
    if data["active"] and not finding:
        raise LensActivationError("an active decision must state its finding")
    return data["active"], finding, data.get("reason", "").strip()


def resolve_conditional_lenses(
    lenses, research: NormalizedResearchArtifact, signal: dict, judge: LensActivationJudge,
) -> tuple[ActivationDecision, ...]:
    """One decision per conditional lens, in the client's order."""
    decisions = []
    evidence = evidence_for_activation(research, signal) if lenses else {}
    for lens in lenses:
        active, finding, reason = judge.decide(
            criteria=lens.activation_criteria, evidence=evidence)
        decisions.append(ActivationDecision(
            lens_id=lens.lens_id, lens_version=lens.version,
            active=active, finding=finding, reason=reason))
    return tuple(decisions)


def active_guidance(lenses, decisions) -> str:
    """The active lenses' own behaviour, each with the finding that activated it.

    Handed to the generation stages that shape the argument — the narrative
    spine, the hook, the voice/closing stage — through the signal they all
    read. Empty when nothing is active, so an inactive lens changes nothing.
    """
    by_id = {lens.lens_id: lens for lens in lenses}
    blocks = []
    for decision in decisions:
        if not decision.active:
            continue
        lens = by_id[decision.lens_id]
        blocks.append(f"{lens.text}\n\nFinding for this run (from the research evidence): "
                      f"{decision.finding}")
    return "\n\n".join(blocks)


#: The key in the signal the generation stages read the active guidance from.
ACTIVE_GUIDANCE_KEY = "ACTIVE_CLIENT_GUIDANCE"


def guidance_block(signal: dict) -> str:
    """The prompt block a generation stage appends, or '' when nothing is active."""
    guidance = (signal.get(ACTIVE_GUIDANCE_KEY) or "").strip()
    if not guidance:
        return ""
    return ("\n\nACTIVE CLIENT LENS — the client's own rules, active for this article "
            "because the research evidence met their condition. Follow them; they take "
            "precedence over any default framing above:\n" + guidance + "\n")
