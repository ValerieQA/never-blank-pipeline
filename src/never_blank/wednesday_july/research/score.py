"""
Stage 3 — Scoring.
Score candidates using explainable rule-based formula from scoring_weights.yaml.
"""
# ─────────────────────────────────────────────────────────────────────────────
# ISOLATED WEDNESDAY RESEARCH MODULE — restored verbatim from c7d3a23 (#211).
#
# A literal port of the July 6 2026 research stage that produced the Versant /
# Full Swing signal. It is deliberately NOT the shared scripts/research module
# of the same name: those have since been retargeted at small-business feeds
# and given a selector that rejects large-company M&A by name — the two
# changes (218719a, a557855, both 2026-07-21) that made the specimen
# unreachable. Bypassing them is the point.
#
# Do not "reconcile" this file with scripts/research/. Do not refactor it into
# the shared pipeline. If the shared module changes, this file must NOT follow.
#
# Only current TECHNICAL infrastructure is used — llm_client (provider,
# per-stage model routing, call budget, retry ceilings), requests and logging.
# No current business rule reaches this module.
# ─────────────────────────────────────────────────────────────────────────────

import json
import sys
from pathlib import Path

import yaml

# #211 forced deviation: this file moved deeper, so the repo root is
# four parents up rather than two. Same target, adjusted depth.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_scoring

log = get_logger("research.score")

WEIGHTS_CONFIG = Path("config/scoring_weights.yaml")


def _load_weights() -> dict:
    with open(WEIGHTS_CONFIG) as f:
        return yaml.safe_load(f)


def _llm_score_batch(candidates: list[dict], criteria: dict) -> list[dict]:
    if not candidates:
        return []

    criteria_desc = "\n".join(
        f"- {k} ({v['weight']} pts): {v['description']}"
        for k, v in criteria.items()
    )
    batch_text = "\n\n".join(
        f"[{i}] SIGNAL_ID: {c['SIGNAL_ID']}\nHEADLINE: {c['HEADLINE']}\nTYPE: {c.get('SIGNAL_TYPE','')}\nSUMMARY: {c.get('raw_summary','')}"
        for i, c in enumerate(candidates)
    )

    system = f"""Score business signals for Never Blank, a content practice for founders.

Scoring criteria (binary — earned or not):
{criteria_desc}

Respond with this exact JSON structure:
{{"scores": [
  {{"index": 0, "total_score": 8, "score_reason": "...", "SIGNAL_STRENGTH": "high", "DISCUSSION_POTENTIAL": "high", "CHANNEL_FIT_SCORE": 9}},
  ...
]}}

One object per input signal, in order."""

    user = f"Score these {len(candidates)} signals:\n\n{batch_text}"

    try:
        raw = chat(system, user, json_mode=True, model=model_scoring())
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
            log.warning("score LLM returned dict with no list: %s", list(parsed.keys()))
            return []
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception as exc:
        log.error("LLM scoring failed: %s", exc)
        return []


def score_candidates(candidates: list[dict]) -> list[dict]:
    cfg        = _load_weights()
    criteria   = cfg.get("criteria", {})
    thresholds = cfg.get("thresholds", {})
    top_n      = thresholds.get("top_n_to_enrich", 10)

    scored_meta = _llm_score_batch(candidates, criteria)

    result = []
    for entry in scored_meta:
        idx = entry.get("index", -1)
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
            continue
        c = dict(candidates[idx])
        total = int(entry.get("total_score", 0))
        c.update({
            "SIGNAL_STRENGTH":       entry.get("SIGNAL_STRENGTH", "low"),
            "DISCUSSION_POTENTIAL":  entry.get("DISCUSSION_POTENTIAL", "low"),
            "CHANNEL_FIT_SCORE":     str(entry.get("CHANNEL_FIT_SCORE", 0)),
            "ARTICLE_READINESS_SCORE": str(total),
            "score_reason":          entry.get("score_reason", ""),
            "RECOMMENDED_FOR_ARTICLE": str(total >= thresholds.get("select_minimum", 7)).lower(),
        })
        result.append((total, c))

    result.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in result[:top_n]]
