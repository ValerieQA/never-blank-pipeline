"""
Stage 3 — Scoring.
Score candidates using explainable rule-based formula from scoring_weights.yaml.
"""

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_scoring
from src.utils.config_loader import load_prompt

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

    prompt = load_prompt("research/score", {
        "criteria_desc": criteria_desc,
        "count":         str(len(candidates)),
        "batch_text":    batch_text,
    })
    system = prompt["system"]
    user   = prompt["user"]

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
        # SCORE_RECOMMENDED_FOR_ARTICLE = numeric threshold only.
        # Factual article readiness is determined later by enrich.py.
        # Semantic field drift: one field must not represent different lifecycle
        # states across pipeline stages.
        score_rec = total >= thresholds.get("select_minimum", 7)
        c.update({
            "SIGNAL_STRENGTH":              entry.get("SIGNAL_STRENGTH", "low"),
            "DISCUSSION_POTENTIAL":         entry.get("DISCUSSION_POTENTIAL", "low"),
            "CHANNEL_FIT_SCORE":            str(entry.get("CHANNEL_FIT_SCORE", 0)),
            "ARTICLE_READINESS_SCORE":      str(total),
            "score_reason":                 entry.get("score_reason", ""),
            "SCORE_RECOMMENDED_FOR_ARTICLE": str(score_rec).lower(),
            # Legacy alias kept for sheet sync and any external consumers;
            # final meaning is set by enrich.py (ARTICLE_READY).
            "RECOMMENDED_FOR_ARTICLE":      str(score_rec).lower(),
        })
        result.append((total, c))

    result.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in result[:top_n]]
