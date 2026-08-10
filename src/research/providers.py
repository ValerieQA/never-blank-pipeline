"""
src/research/providers.py
Abstract provider interfaces for the Research Engine.

These interfaces decouple the research stages from their concrete I/O
implementations (HTTP, LLM API, filesystem cache). The controlled run
injects fake implementations; production uses the real ones.

## Interface hierarchy

  LLMProvider   — language model call (chat completion)
  FeedProvider  — RSS/Atom feed fetch
  CacheAdapter  — key-value cache (read/write/clear)

## Usage

Production (default):
    run_discovery(seen_ids=set())  # uses DefaultLLMProvider + DefaultFeedProvider

Controlled run (injected fakes):
    run_discovery(
        seen_ids=set(),
        llm_provider=FakeLLMProvider(responses=[...]),
        feed_provider=FakeFeedProvider(items=[...]),
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract language model interface used by research stages."""

    @abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        model: str = "",
        **kwargs: Any,
    ) -> str:
        """
        Send a prompt to the language model and return the text response.

        Args:
            system:    System prompt.
            user:      User message.
            json_mode: Request JSON-formatted output.
            model:     Model identifier (empty = provider default).
            **kwargs:  Provider-specific options.

        Returns:
            Raw text response from the model (may be JSON string).
        """


class FeedProvider(ABC):
    """Abstract RSS/Atom feed interface used by run_discovery."""

    @abstractmethod
    def fetch(self, url: str, *, timeout: int = 15) -> bytes:
        """
        Fetch the raw feed content at `url`.

        Returns:
            Raw bytes of the RSS/Atom XML.

        Raises:
            IOError / requests.HTTPError on failure (implementation decides).
        """


class CacheAdapter(ABC):
    """Abstract key-value cache interface. Used to isolate cache reads/writes."""

    @abstractmethod
    def get(self, key: str) -> Any:
        """Return the cached value for `key`, or None if not present."""

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Store `value` under `key`."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all entries from this cache."""


# ---------------------------------------------------------------------------
# Default (production) implementations — thin wrappers around existing code
# ---------------------------------------------------------------------------

class DefaultLLMProvider(LLMProvider):
    """
    Production LLM provider. Delegates to src.utils.llm_client.chat().
    This is the default used by research stages when no provider is injected.
    """

    def chat(self, system: str, user: str, *, json_mode: bool = False,
             model: str = "", **kwargs: Any) -> str:
        from src.utils.llm_client import chat
        return chat(system, user, json_mode=json_mode, model=model or None, **kwargs)


class DefaultFeedProvider(FeedProvider):
    """
    Production feed provider. Uses requests.get() with the standard User-Agent.
    """

    def fetch(self, url: str, *, timeout: int = 15) -> bytes:
        import requests
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "NeverBlank/1.0"})
        resp.raise_for_status()
        return resp.content


class NullCacheAdapter(CacheAdapter):
    """Cache adapter that never stores anything. Used in controlled runs."""

    def get(self, key: str) -> Any:
        return None

    def set(self, key: str, value: Any) -> None:
        pass  # no-op

    def clear(self) -> None:
        pass  # no-op
