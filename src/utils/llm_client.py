import os
import json
from typing import Any, TypeVar
from pydantic import BaseModel as PydanticBaseModel
from openai import OpenAI, BadRequestError
from src.run.call_budget import charge_active_call_budget
from src.run.stage_routing import observe_request
from src.utils.logger import get_logger

_T = TypeVar("_T", bound=PydanticBaseModel)

log = get_logger("llm_client")

_client: OpenAI | None = None


#: The complete set of retry policies Release 1 permits. This is a strict
#: string-to-value table, not a numeric parse: only the exact canonical
#: representations are configuration.
_ALLOWED_MAX_RETRIES = {"0": 0, "1": 1}


def max_retries() -> int:
    """Explicit SDK retry policy (#170).

    The SDK default of 2 silently turns one logical request into up to three
    HTTP attempts — and it retries 429s, so a rate-limit event is amplified
    exactly when the provider is asking for less traffic. One retry is the
    smallest policy that still absorbs a single transient network blip; the
    SDK backs off and honours Retry-After on the one retry it gets.

    Release 1 accepts exactly ``NB_OPENAI_MAX_RETRIES=0`` or ``=1`` (unset
    means 1). Everything else — negatives, 2 or more, floats, empty or
    malformed strings, whitespace variants — is refused before any OpenAI
    client is constructed. A bad value is a configuration error to surface,
    never a policy to silently adjust: clamping ``999999`` to 1 would hide
    the mistake, and honouring it would permit a million HTTP attempts for
    one logical request.
    """
    raw = os.environ.get("NB_OPENAI_MAX_RETRIES")
    if raw is None:
        return 1
    if raw in _ALLOWED_MAX_RETRIES:
        return _ALLOWED_MAX_RETRIES[raw]
    raise EnvironmentError(
        "NB_OPENAI_MAX_RETRIES must be exactly '0' or '1' for Release 1; "
        f"got {raw!r}. Refusing to construct an OpenAI client from an "
        "invalid retry configuration."
    )


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("NB_OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("NB_OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=api_key, max_retries=max_retries())
    return _client


def _temperature() -> float:
    return float(os.environ.get("NB_OPENAI_TEMPERATURE", "0.7"))


def _qc_temperature() -> float:
    return float(os.environ.get("NB_OPENAI_QC_TEMPERATURE", "0.2"))


def _model(stage_var: str | None = None) -> str:
    """
    Return the model for a given pipeline stage.
    Stage-specific var takes precedence; falls back to NB_OPENAI_CHAT_MODEL, then gpt-4o.

    Empty and whitespace-only values are treated as absent (#173): GitHub
    Actions renders an unset secret as an empty string in ``env:``, and an
    empty string must mean "not configured" — never a literal model id sent
    to the API.
    """
    if stage_var:
        value = os.environ.get(stage_var, "").strip()
        if value:
            return value
    return os.environ.get("NB_OPENAI_CHAT_MODEL", "").strip() or "gpt-4o"


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
    charge_active_call_budget()  # #171: one logical call, refused before any paid transport
    # #279: measure what actually goes out, against what this stage was routed.
    # After the budget gate on purpose: a call the budget refuses never
    # reaches a provider, so it must not appear as one that did. A no-op
    # outside a recorded run; stores a digest, never the prompt.
    observe_request(system, user)
    try:
        response = client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        if "temperature" in str(exc):
            log.warning("Model %s rejected temperature — retrying without it", model)
            kwargs.pop("temperature", None)
            # #171: the fallback is a second application-level transport —
            # charged like any other, and refused when the budget is spent
            charge_active_call_budget()
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
    charge_active_call_budget()  # #171: one logical call, refused before any paid transport
    observe_request(system, user)                                            # #279
    try:
        response = client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        if "temperature" in str(exc):
            log.warning("Model %s rejected temperature — retrying without it", model)
            kwargs.pop("temperature", None)
            # #171: the fallback is a second application-level transport —
            # charged like any other, and refused when the budget is spent
            charge_active_call_budget()
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
    charge_active_call_budget()  # #171: one logical call, refused before any paid transport
    observe_request(system, user)                                            # #279
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
            # #171: the fallback is a second application-level transport —
            # charged like any other, and refused when the budget is spent
            charge_active_call_budget()
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
