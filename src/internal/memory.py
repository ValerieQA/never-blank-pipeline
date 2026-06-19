"""
Memory layer for Never Blank Pipeline.

Manages 6 persistent JSON stores:
  published.json          — every published run with per-channel results
  embeddings.json         — text embeddings for semantic deduplication
  observations.json       — raw observations (deprecated alias → observation_registry.json)
  observation_registry.json — structured observation records with full metadata
  portfolio.json          — running content distribution counters
  theme_registry.json     — semantic theme clusters for diversity tracking
  voice_examples.json     — reference voice samples for QC

Embedding calls use OpenAI when NB_OPENAI_API_KEY is set.
When the key is absent, a deterministic mock embedding is returned so that
dry-runs and tests work without any API access.
"""

import json
import math
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("memory")

MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"

# ── File names ─────────────────────────────────────────────────────────────────

_PUBLISHED           = "published.json"
_EMBEDDINGS          = "embeddings.json"
_OBSERVATIONS        = "observations.json"          # legacy
_OBS_REGISTRY        = "observation_registry.json"
_PORTFOLIO           = "portfolio.json"
_THEME_REGISTRY      = "theme_registry.json"
_VOICE_EXAMPLES      = "voice_examples.json"

# ── Low-level I/O ──────────────────────────────────────────────────────────────

def _load(filename: str, default_factory):
    path = MEMORY_DIR / filename
    if not path.exists():
        return default_factory()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(filename: str, data) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / filename
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ── Mock embedding (deterministic, no API needed) ─────────────────────────────

_MOCK_DIM = 1536  # same dimension as text-embedding-3-small


def _mock_embed(text: str) -> list[float]:
    """
    Deterministic pseudo-embedding for testing without OpenAI.
    Uses character code values spread across _MOCK_DIM dimensions.
    NOT semantically meaningful — only used when NB_OPENAI_API_KEY is absent.
    """
    seed = [ord(c) for c in text]
    vec = []
    for i in range(_MOCK_DIM):
        val = math.sin(sum(seed[j % len(seed)] * (i + j + 1) for j in range(min(len(seed), 8))))
        vec.append(val)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _is_mock_mode() -> bool:
    return not os.environ.get("NB_OPENAI_API_KEY", "").strip()


def get_embedding(text: str) -> list[float]:
    """
    Return embedding for text.
    Uses OpenAI when NB_OPENAI_API_KEY is set; mock otherwise.
    """
    if _is_mock_mode():
        log.debug("mock embedding (NB_OPENAI_API_KEY not set)")
        return _mock_embed(text)
    from src.utils.llm_client import embed
    return embed(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 if either is zero."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Published ──────────────────────────────────────────────────────────────────
#
# Schema per item:
# {
#   "run_id":     "uuid",
#   "slug":       "why-busiest-businesses-look-closed",
#   "title":      "Why the busiest businesses look closed",
#   "published_date": "2026-06-19",
#   "observation_id": "uuid or null",
#   "observation_type": "pattern",
#   "content_goal": "challenge",
#   "source_category": "manual",
#   "tags": ["visibility", "founder"],
#   "voice_score": 0.84,
#   "channels": {
#     "wix":       {"status": "green",  "url": "https://...", "post_id": "..."},
#     "linkedin":  {"status": "green",  "url": "...",         "post_id": "..."},
#     "instagram": {"status": "yellow", "url": null,          "error": "rate_limit"},
#     "facebook":  {"status": "green",  "url": "...",         "post_id": "..."},
#     "threads":   {"status": "green",  "url": "...",         "post_id": "..."},
#     "telegram":  {"status": "green",  "url": "...",         "post_id": "..."}
#   },
#   "overall_status": "partial"
# }

def load_published() -> list[dict]:
    return _load(_PUBLISHED, list)


def save_published(item: dict) -> None:
    """Append a run record to published.json."""
    items = load_published()
    items.append(item)
    _save(_PUBLISHED, items)


def get_published_slugs() -> set[str]:
    return {item.get("slug", "") for item in load_published()}


# ── Embeddings ─────────────────────────────────────────────────────────────────
#
# Schema per item:
# {
#   "id":     "uuid",
#   "slug":   "why-busiest-businesses-look-closed",
#   "text":   "Why the busiest businesses look closed — The visibility gap...",
#   "source": "title+angle",          # what text was embedded
#   "model":  "text-embedding-3-small" or "mock",
#   "date":   "2026-06-19",
#   "vector": [0.012, -0.034, ...]    # 1536 floats
# }

def load_embeddings() -> list[dict]:
    return _load(_EMBEDDINGS, list)


def save_embedding(
    text: str,
    vector: list[float],
    slug: str = "",
    source: str = "title+angle",
) -> None:
    """Persist a pre-computed embedding. Call after get_embedding()."""
    embeddings = load_embeddings()
    model = "mock" if _is_mock_mode() else os.environ.get("NB_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    embeddings.append({
        "id":     str(uuid.uuid4()),
        "slug":   slug,
        "text":   text,
        "source": source,
        "model":  model,
        "date":   date.today().isoformat(),
        "vector": vector,
    })
    _save(_EMBEDDINGS, embeddings)


def is_duplicate(
    text: str,
    threshold: Optional[float] = None,
) -> tuple[bool, float, Optional[str]]:
    """
    Check whether text is semantically too similar to any published item.

    Returns:
        (is_duplicate, highest_similarity, matching_slug_or_None)

    threshold defaults to quality.yaml → deduplication.similarity_threshold (0.85).
    If no embeddings exist yet, returns (False, 0.0, None).
    """
    if threshold is None:
        try:
            from src.utils.config_loader import load_quality
            threshold = load_quality().get("deduplication", {}).get("similarity_threshold", 0.85)
        except Exception:
            threshold = 0.85

    embeddings = load_embeddings()
    if not embeddings:
        return False, 0.0, None

    query_vector = get_embedding(text)

    highest = 0.0
    best_slug = None
    for entry in embeddings:
        stored = entry.get("vector")
        if not stored:
            continue
        sim = cosine_similarity(query_vector, stored)
        if sim > highest:
            highest = sim
            best_slug = entry.get("slug")

    return highest >= threshold, round(highest, 4), best_slug


# ── Observation Registry ───────────────────────────────────────────────────────
#
# Schema per item:
# {
#   "id":                "uuid",
#   "statement":         "Founders treat visibility as a reward, not an input.",
#   "observation_type":  "pattern",
#   "non_obviousness_score": 0.82,
#   "specificity_score":     0.74,
#   "composite_score":       0.78,
#   "source_refs":       ["intelligence/2026-06-19/raw/item_001.json"],
#   "source_category":   "manual",
#   "evergreen":         true,
#   "discovered_date":   "2026-06-19",
#   "use_count":         0,
#   "last_used_date":    null,
#   "used_in":           [],
#   "cooldown_until":    null
# }

def load_observation_registry() -> list[dict]:
    return _load(_OBS_REGISTRY, list)


def save_observation(obs: dict) -> None:
    """
    Persist a new observation. Assigns a uuid if not already set.
    Works for both the legacy observations.json path and the new registry.
    """
    registry = load_observation_registry()
    if not obs.get("id"):
        obs = {**obs, "id": str(uuid.uuid4())}
    if "discovered_date" not in obs:
        obs["discovered_date"] = date.today().isoformat()
    if "use_count" not in obs:
        obs["use_count"] = 0
    registry.append(obs)
    _save(_OBS_REGISTRY, registry)
    # also write to legacy file so existing code reading observations.json still works
    legacy = _load(_OBSERVATIONS, list)
    legacy.append(obs)
    _save(_OBSERVATIONS, legacy)


def mark_observation_used(obs_id: str, used_in_slug: str, used_date: str) -> None:
    """Increment use_count, set last_used_date, record slug, compute cooldown_until."""
    from src.utils.config_loader import load_quality
    cooldown_days = load_quality().get("observations", {}).get("cooldown_days", 60)

    registry = load_observation_registry()
    for obs in registry:
        if obs.get("id") == obs_id:
            obs["use_count"] = obs.get("use_count", 0) + 1
            obs["last_used_date"] = used_date
            obs.setdefault("used_in", []).append(used_in_slug)
            # compute cooldown_until
            try:
                from datetime import datetime, timedelta
                d = datetime.fromisoformat(used_date)
                obs["cooldown_until"] = (d + timedelta(days=cooldown_days)).date().isoformat()
            except Exception:
                pass
    _save(_OBS_REGISTRY, registry)

    # mirror to legacy
    legacy = _load(_OBSERVATIONS, list)
    for obs in legacy:
        if obs.get("id") == obs_id:
            obs["use_count"] = obs.get("use_count", 0) + 1
            obs["last_used_date"] = used_date
            obs.setdefault("used_in", []).append(used_in_slug)
    _save(_OBSERVATIONS, legacy)


def get_available_observations(today: Optional[str] = None) -> list[dict]:
    """
    Return observations that are not on cooldown and below max_uses.
    """
    from src.utils.config_loader import load_quality
    q = load_quality().get("observations", {})
    max_uses = q.get("max_uses", 3)
    today_str = today or date.today().isoformat()

    return [
        obs for obs in load_observation_registry()
        if obs.get("use_count", 0) < max_uses
        and (obs.get("cooldown_until") is None or obs["cooldown_until"] <= today_str)
    ]


# ── Voice Examples ─────────────────────────────────────────────────────────────
#
# Schema per item:
# {
#   "id":       "uuid",
#   "platform": "linkedin",
#   "text":     "Most founders don't have a visibility problem...",
#   "score":    0.91,
#   "added_date": "2026-06-19"
# }

def load_voice_examples() -> list[dict]:
    return _load(_VOICE_EXAMPLES, list)


# ── Portfolio ──────────────────────────────────────────────────────────────────
#
# Schema:
# {
#   "total_published": 0,
#   "observation_type_counts": {"pattern": 3, "paradox": 1, ...},
#   "content_goal_counts":     {"challenge": 2, "educate": 1, ...},
#   "source_category_counts":  {"manual": 5, "intelligence": 0},
#   "tag_counts":              {"visibility": 4, "founder": 2, ...},
#   "voice_scores_rolling":    [0.84, 0.79, 0.88],   # last 10
#   "last_used_observation_types": ["pattern", "gap"],  # rolling 20
#   "last_used_content_goals":     ["challenge", "educate"],
#   "last_published_date":     "2026-06-19"
# }

_PORTFOLIO_DEFAULTS = {
    "total_published": 0,
    "observation_type_counts": {},
    "content_goal_counts": {},
    "source_category_counts": {},
    "tag_counts": {},
    "voice_scores_rolling": [],
    "last_used_observation_types": [],
    "last_used_content_goals": [],
    "last_published_date": None,
}


def load_portfolio() -> dict:
    stored = _load(_PORTFOLIO, dict)
    return {**_PORTFOLIO_DEFAULTS, **stored}


def update_portfolio(
    observation_type: str,
    content_goal: str,
    tags: list[str],
    source_category: str,
    voice_score: Optional[float] = None,
    published_date: Optional[str] = None,
) -> None:
    """
    Record one published piece in the portfolio.
    Called after a successful run.
    """
    p = load_portfolio()

    p["total_published"] = p.get("total_published", 0) + 1

    p["observation_type_counts"][observation_type] = (
        p["observation_type_counts"].get(observation_type, 0) + 1
    )
    p["content_goal_counts"][content_goal] = (
        p["content_goal_counts"].get(content_goal, 0) + 1
    )
    p["source_category_counts"][source_category] = (
        p["source_category_counts"].get(source_category, 0) + 1
    )
    for tag in tags:
        p["tag_counts"][tag] = p["tag_counts"].get(tag, 0) + 1

    last_types = p["last_used_observation_types"]
    last_types.append(observation_type)
    p["last_used_observation_types"] = last_types[-20:]

    last_goals = p["last_used_content_goals"]
    last_goals.append(content_goal)
    p["last_used_content_goals"] = last_goals[-20:]

    if voice_score is not None:
        scores = p["voice_scores_rolling"]
        scores.append(round(voice_score, 4))
        p["voice_scores_rolling"] = scores[-10:]

    p["last_published_date"] = published_date or date.today().isoformat()

    _save(_PORTFOLIO, p)


def rolling_voice_score() -> Optional[float]:
    """Average of last ≤10 voice scores. None if no data yet."""
    scores = load_portfolio().get("voice_scores_rolling", [])
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


# ── Theme Registry ─────────────────────────────────────────────────────────────
#
# Tracks semantic theme clusters to enforce diversity across runs.
# Each entry is a theme cluster, with a centroid embedding and members.
#
# Schema per item:
# {
#   "theme_id":   "uuid",
#   "label":      "visibility gap for founders",    # auto-generated summary
#   "centroid":   [0.01, -0.03, ...],              # average of member vectors
#   "members": [
#     {"slug": "why-busiest-businesses-look-closed", "date": "2026-06-19"}
#   ],
#   "last_used_date": "2026-06-19",
#   "use_count": 1
# }

_THEME_CLUSTER_THRESHOLD = 0.78  # similarity to merge into existing cluster


def load_theme_registry() -> list[dict]:
    return _load(_THEME_REGISTRY, list)


def _average_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    centroid = [0.0] * dim
    for vec in vectors:
        for i, v in enumerate(vec):
            centroid[i] += v
    n = len(vectors)
    raw = [c / n for c in centroid]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def register_theme(text: str, slug: str, published_date: Optional[str] = None) -> str:
    """
    Embed text, find matching cluster or create new one.
    Returns theme_id.
    """
    vector = get_embedding(text)
    registry = load_theme_registry()
    today = published_date or date.today().isoformat()

    best_sim = 0.0
    best_idx = -1
    for i, cluster in enumerate(registry):
        centroid = cluster.get("centroid", [])
        if not centroid:
            continue
        sim = cosine_similarity(vector, centroid)
        if sim > best_sim:
            best_sim = sim
            best_idx = i

    if best_sim >= _THEME_CLUSTER_THRESHOLD and best_idx >= 0:
        # merge into existing cluster
        cluster = registry[best_idx]
        cluster["members"].append({"slug": slug, "date": today})
        cluster["use_count"] = cluster.get("use_count", 0) + 1
        cluster["last_used_date"] = today
        # update centroid
        all_vectors = [
            emb["vector"] for emb in load_embeddings()
            if emb.get("slug") in {m["slug"] for m in cluster["members"]}
            and emb.get("vector")
        ]
        if all_vectors:
            cluster["centroid"] = _average_vector(all_vectors)
        theme_id = cluster["theme_id"]
    else:
        # new cluster
        theme_id = str(uuid.uuid4())
        registry.append({
            "theme_id": theme_id,
            "label": text[:80],
            "centroid": vector,
            "members": [{"slug": slug, "date": today}],
            "last_used_date": today,
            "use_count": 1,
        })

    _save(_THEME_REGISTRY, registry)
    return theme_id


def get_theme_saturation(text: str) -> float:
    """
    Return highest cosine similarity between text and any existing theme centroid.
    0.0 = completely new territory. 1.0 = already heavily covered.
    """
    vector = get_embedding(text)
    registry = load_theme_registry()
    if not registry:
        return 0.0
    return max(
        cosine_similarity(vector, c.get("centroid", []))
        for c in registry
        if c.get("centroid")
    )


# ── Diversity Scoring ──────────────────────────────────────────────────────────

def get_diversity_adjustment(
    observation_type: str,
    content_goal: str,
) -> float:
    """
    Return a score adjustment in [-0.2, +0.2] based on how over/under-represented
    this observation_type and content_goal are in the current portfolio.

    Positive = boost (underrepresented → encourage).
    Negative = penalty (overrepresented → discourage).
    """
    p = load_portfolio()
    total = p.get("total_published", 0)
    if total == 0:
        return 0.0

    type_counts = p.get("observation_type_counts", {})
    goal_counts = p.get("content_goal_counts", {})

    n_types = len(ObservationTypeValues)
    n_goals = len(ContentGoalValues)

    type_share = type_counts.get(observation_type, 0) / total
    goal_share = goal_counts.get(content_goal, 0) / total

    type_ideal = 1.0 / n_types   # equal distribution
    goal_ideal = 1.0 / n_goals

    # positive delta → overrepresented → negative adjustment
    type_delta = type_ideal - type_share
    goal_delta = goal_ideal - goal_share

    raw = (type_delta + goal_delta) / 2
    # clamp to [-0.2, +0.2]
    return round(max(-0.2, min(0.2, raw)), 4)


def is_voice_drifting() -> tuple[bool, Optional[float]]:
    """
    Return (is_drifting, current_rolling_average).
    Drifting = rolling average below alert_threshold from quality.yaml.
    """
    try:
        from src.utils.config_loader import load_quality
        threshold = load_quality().get("voice_drift", {}).get("alert_threshold", 0.72)
    except Exception:
        threshold = 0.72

    avg = rolling_voice_score()
    if avg is None:
        return False, None
    return avg < threshold, avg


# Enum value lists used in diversity calculation
ObservationTypeValues = ["pattern", "paradox", "reversal", "gap", "behavior_delta", "signal_cluster", "implication"]
ContentGoalValues     = ["educate", "challenge", "demonstrate", "invite"]
