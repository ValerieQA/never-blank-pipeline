import os
import json
from typing import Any
from openai import OpenAI
from src.utils.logger import get_logger

log = get_logger("llm_client")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("NB_OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("NB_OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=api_key)
    return _client


def _model() -> str:
    return os.environ.get("NB_OPENAI_MODEL", "gpt-4o")


def _embedding_model() -> str:
    return os.environ.get("NB_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def chat(system: str, user: str, json_mode: bool = False) -> str:
    """
    Call OpenAI Chat Completions.
    If json_mode=True, requests JSON output and validates it parses.
    Returns the content string.
    """
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    log.debug("chat() model=%s json_mode=%s", _model(), json_mode)
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""

    if json_mode:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}\nContent: {content[:200]}") from exc

    return content


def chat_json(system: str, user: str) -> dict:
    """Convenience: chat with json_mode=True, returns parsed dict."""
    raw = chat(system, user, json_mode=True)
    return json.loads(raw)


def embed(text: str) -> list[float]:
    """Get embedding vector for a single text."""
    client = _get_client()
    log.debug("embed() model=%s text_len=%d", _embedding_model(), len(text))
    response = client.embeddings.create(
        model=_embedding_model(),
        input=text,
    )
    return response.data[0].embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors for multiple texts in one API call."""
    if not texts:
        return []
    client = _get_client()
    log.debug("embed_batch() model=%s count=%d", _embedding_model(), len(texts))
    response = client.embeddings.create(
        model=_embedding_model(),
        input=texts,
    )
    return [item.embedding for item in response.data]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import numpy as np
    va = np.array(a)
    vb = np.array(b)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
