import json
import uuid
from pathlib import Path
from src.utils.logger import get_logger
from src.utils.llm_client import embed, cosine_similarity

log = get_logger("memory")

MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"


def _load(filename: str) -> list | dict:
    path = MEMORY_DIR / filename
    if not path.exists():
        return [] if filename != "portfolio.json" else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(filename: str, data: list | dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / filename
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ── Published ─────────────────────────────────────────────────────────────────

def load_published() -> list[dict]:
    return _load("published.json")


def save_published(item: dict) -> None:
    items = load_published()
    items.append(item)
    _save("published.json", items)


# ── Observations ──────────────────────────────────────────────────────────────

def load_observations() -> list[dict]:
    return _load("observations.json")


def save_observation(obs: dict) -> None:
    observations = load_observations()
    if not obs.get("id"):
        obs["id"] = str(uuid.uuid4())
    observations.append(obs)
    _save("observations.json", observations)


def mark_observation_used(obs_id: str, used_in_slug: str, date: str) -> None:
    observations = load_observations()
    for obs in observations:
        if obs.get("id") == obs_id:
            obs["use_count"] = obs.get("use_count", 0) + 1
            obs["last_used_date"] = date
            obs.setdefault("used_in", []).append(used_in_slug)
    _save("observations.json", observations)


# ── Voice Examples ────────────────────────────────────────────────────────────

def load_voice_examples() -> list[dict]:
    return _load("voice_examples.json")


# ── Portfolio ─────────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    default = {
        "observation_type_counts": {},
        "content_goal_counts": {},
        "source_category_counts": {},
        "tag_counts": {},
        "voice_scores_rolling": [],
        "last_used_observation_types": [],
        "last_used_content_goals": [],
    }
    stored = _load("portfolio.json")
    return {**default, **stored}


def update_portfolio(observation_type: str, content_goal: str, tags: list[str],
                     source_category: str, voice_score: float | None = None) -> None:
    p = load_portfolio()

    p["observation_type_counts"][observation_type] = \
        p["observation_type_counts"].get(observation_type, 0) + 1
    p["content_goal_counts"][content_goal] = \
        p["content_goal_counts"].get(content_goal, 0) + 1
    p["source_category_counts"][source_category] = \
        p["source_category_counts"].get(source_category, 0) + 1

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

    _save("portfolio.json", p)


def rolling_voice_score() -> float | None:
    scores = load_portfolio().get("voice_scores_rolling", [])
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


# ── Embeddings / Deduplication ────────────────────────────────────────────────

def load_embeddings() -> list[dict]:
    return _load("embeddings.json")


def save_embedding(text: str, vector: list[float], slug: str = "") -> None:
    embeddings = load_embeddings()
    embeddings.append({"text": text, "slug": slug, "vector": vector})
    _save("embeddings.json", embeddings)


def is_duplicate(text: str, threshold: float = 0.85) -> tuple[bool, float]:
    """
    Check if text is semantically similar to any previously published item.
    Returns (is_duplicate, highest_similarity_score).
    Calls OpenAI Embeddings API — requires NB_OPENAI_API_KEY.
    """
    embeddings = load_embeddings()
    if not embeddings:
        return False, 0.0

    try:
        query_vector = embed(text)
    except Exception as exc:
        log.error("embed() failed during dedup check: %s", exc)
        return False, 0.0

    highest = 0.0
    for entry in embeddings:
        stored_vector = entry.get("vector")
        if not stored_vector:
            continue
        sim = cosine_similarity(query_vector, stored_vector)
        if sim > highest:
            highest = sim

    return highest >= threshold, round(highest, 4)
