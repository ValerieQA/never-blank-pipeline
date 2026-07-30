import os
import json
from typing import Any, TypeVar
from pydantic import BaseModel as PydanticBaseModel
from openai import OpenAI, BadRequestError
from src.utils.logger import get_logger

_T = TypeVar("_T", bound=PydanticBaseModel)

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


def _temperature() -> float:
    return float(os.environ.get("NB_OPENAI_TEMPERATURE", "0.7"))


def _qc_temperature() -> float:
    return float(os.environ.get("NB_OPENAI_QC_TEMPERATURE", "0.2"))


def _model(stage_var: str | None = None) -> str:
    """
    Return the model for a given pipeline stage.
    Stage-specific var takes precedence; falls back to NB_OPENAI_CHAT_MODEL, then gpt-4o.
    """
    fallback = os.environ.get("NB_OPENAI_CHAT_MODEL", "gpt-4o")
    if stage_var:
        return os.environ.get(stage_var, fallback)
    return fallback


def model_discovery() -> str:
    return _model("NB_DISCOVERY_MODEL")


def model_scoring() -> str:
    return _model("NB_SCORING_MODEL")


def model_enrich() -> str:
    return _model("NB_ENRICH_MODEL")


def model_article() -> str:
    return _model("NB_ARTICLE_MODEL")


def model_social() -> str:
    return _model("NB_SOCIAL_MODEL")


def model_image() -> str:
    return os.environ.get("NB_IMAGE_MODEL", "gpt-image-1")


def _embedding_model() -> str:
    return os.environ.get("NB_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def chat(system: str, user: str, json_mode: bool = False, model: str | None = None) -> str:
    """
    Call OpenAI Chat Completions.
    If json_mode=True, requests JSON output and validates it parses.
    model: explicit model override; if None, falls back to NB_OPENAI_CHAT_MODEL / gpt-4o.
    Returns the content string.
    """
    client = _get_client()
    model = model or _model()
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": _temperature(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    log.debug("chat() model=%s temp=%s json_mode=%s", model, _temperature(), json_mode)
    try:
        response = client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        if "temperature" in str(exc):
            log.warning("Model %s rejected temperature — retrying without it", model)
            kwargs.pop("temperature", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise
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


def chat_qc(system: str, user: str, json_mode: bool = False, model: str | None = None) -> str:
    """
    Same as chat() but uses NB_OPENAI_QC_TEMPERATURE (default 0.2).
    Use for factuality checks and voice scoring — low temp for consistency.
    """
    client = _get_client()
    model = model or _model()
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": _qc_temperature(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    log.debug("chat_qc() model=%s temp=%s", model, _qc_temperature())
    try:
        response = client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        if "temperature" in str(exc):
            log.warning("Model %s rejected temperature — retrying without it", model)
            kwargs.pop("temperature", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise
    content = response.choices[0].message.content or ""

    if json_mode:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"QC LLM returned invalid JSON: {exc}") from exc

    return content


def chat_qc_json(system: str, user: str) -> dict:
    """QC variant: low temperature + json_mode, returns parsed dict."""
    raw = chat_qc(system, user, json_mode=True)
    return json.loads(raw)


def chat_parsed(
    system: str,
    user: str,
    response_model: type[_T],
    model: str | None = None,
) -> _T:
    """Call OpenAI with structured output (strict schema).

    Uses client.beta.chat.completions.parse() which enforces the Pydantic
    model schema server-side. Returns a validated instance of response_model.

    Raises pydantic.ValidationError if the model returns content that fails
    schema validation (should not happen with strict mode, but is possible
    with older model versions that don't support strict structured output).

    Use this instead of chat_json() when the output schema is critical and
    partial regeneration logic depends on a typed object.
    """
    client = _get_client()
    model = model or _model()
    log.debug("chat_parsed() model=%s response_model=%s", model, response_model.__name__)
    try:
        response = client.beta.chat.completions.parse(
            model=model,
            temperature=_temperature(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_model,
        )
    except BadRequestError as exc:
        if "temperature" in str(exc):
            log.warning("Model %s rejected temperature — retrying without it", model)
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=response_model,
            )
        else:
            raise
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError(
            f"chat_parsed() returned None — model may have refused or content_filter triggered. "
            f"Model: {model}"
        )
    return parsed


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
