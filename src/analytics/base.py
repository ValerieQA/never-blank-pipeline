"""
Never Blank Analytics — BaseCollector (Phase 4D.1).

Shared infrastructure for all platform collectors:
  - retry with exponential backoff
  - rate limit handling (HTTP 429)
  - uniform exception wrapping
  - staleness guard: skip update if existing data is newer than incoming

Collectors inherit from BaseCollector and call _fetch_with_retry() for HTTP.
They implement collect() and filter to their platform.

Staleness guard is enforced in _is_stale(): if PublishedEntry.analytics_fetched_at
is more recent than the data timestamp a collector would write, the orchestrator
should skip that entry. BaseCollector does not call update_entry() itself —
it signals staleness via the AnalyticsRecord.collected_at field and the
orchestrator (or scorer) enforces the rule.

Staleness enforcement is in the orchestrator: if record.collected_at <
entry.analytics_fetched_at, the patch is not written. This keeps collectors
stateless and the guard consistent across all platforms.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("analytics.base")

# Retry configuration
_MAX_RETRIES   = 3
_BACKOFF_BASE  = 2.0   # seconds; actual delay = _BACKOFF_BASE ** attempt
_RATE_LIMIT_WAIT = 60  # seconds to wait on HTTP 429 before retrying


class CollectorError(Exception):
    """Base class for all collector failures."""


class AuthorizationCollectorError(CollectorError):
    """
    Raised on HTTP 401 or 403. Signals that credentials are invalid or expired.
    The orchestrator treats this as a whole-collector failure — it is not safe
    to continue collecting other entries with the same broken credentials.
    """


class EntryCollectorError(CollectorError):
    """
    Raised when a single entry cannot be fetched (network timeout, 404, etc.).
    The collector may skip this entry and continue with the rest.
    """


class BaseCollector:
    """
    Base class for all platform analytics collectors.

    Provides:
      - _fetch_with_retry(url, headers) → dict   HTTP GET with retry + 429 handling
      - _now() → datetime                         UTC timestamp helper

    Subclasses must define:
      platform: str
      collect(entries: list[PublishedEntry]) -> list[AnalyticsRecord]
    """

    platform: str = ""

    def _fetch_with_retry(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 15,
    ) -> dict:
        """
        HTTP GET with retry and rate-limit handling.

        Retries up to _MAX_RETRIES times with exponential backoff.
        On HTTP 429, waits _RATE_LIMIT_WAIT seconds before retrying.
        Raises CollectorError if all retries are exhausted.

        Returns parsed JSON response as dict.
        """
        headers = headers or {}
        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body)

            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    log.warning(
                        "%s: rate limited (HTTP 429) — waiting %ds before retry %d/%d",
                        self.platform, _RATE_LIMIT_WAIT, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(_RATE_LIMIT_WAIT)
                    last_exc = exc
                    continue
                elif exc.code in (401, 403):
                    raise AuthorizationCollectorError(
                        f"{self.platform}: authorization failed (HTTP {exc.code}) — check API credentials"
                    ) from exc
                elif exc.code >= 500:
                    log.warning(
                        "%s: server error HTTP %d (attempt %d/%d)",
                        self.platform, exc.code, attempt + 1, _MAX_RETRIES,
                    )
                    last_exc = exc
                else:
                    raise CollectorError(
                        f"{self.platform}: HTTP {exc.code} — {exc.reason}"
                    ) from exc

            except urllib.error.URLError as exc:
                log.warning(
                    "%s: network error (attempt %d/%d): %s",
                    self.platform, attempt + 1, _MAX_RETRIES, exc.reason,
                )
                last_exc = exc

            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise CollectorError(
                    f"{self.platform}: invalid JSON response from API"
                ) from exc

            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_BASE ** attempt
                log.info("%s: retrying in %.1fs...", self.platform, wait)
                time.sleep(wait)

        raise CollectorError(
            f"{self.platform}: all {_MAX_RETRIES} retries exhausted"
        ) from last_exc

    def _fetch_with_status(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 15,
    ) -> tuple[int, dict]:
        """
        HTTP GET with retry; returns (http_status_code, parsed_response_dict).

        Unlike _fetch_with_retry, exposes the HTTP status code of 2xx responses
        so callers can distinguish e.g. 200 (ready) from 202 (pending).

        Error handling is identical to _fetch_with_retry:
          401/403 → AuthorizationCollectorError (propagates immediately)
          429     → wait _RATE_LIMIT_WAIT seconds, retry
          5xx     → exponential backoff, retry
          other 4xx → CollectorError with "HTTP {code}" in message
          network/JSON → CollectorError
        """
        headers = headers or {}
        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                    code = resp.status
                    try:
                        data = json.loads(body) if body.strip() else {}
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise CollectorError(
                            f"{self.platform}: invalid JSON response from API"
                        ) from exc
                    return code, data

            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    log.warning(
                        "%s: rate limited (HTTP 429) — waiting %ds before retry %d/%d",
                        self.platform, _RATE_LIMIT_WAIT, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(_RATE_LIMIT_WAIT)
                    last_exc = exc
                    continue
                elif exc.code in (401, 403):
                    raise AuthorizationCollectorError(
                        f"{self.platform}: authorization failed (HTTP {exc.code}) — check API credentials"
                    ) from exc
                elif exc.code >= 500:
                    log.warning(
                        "%s: server error HTTP %d (attempt %d/%d)",
                        self.platform, exc.code, attempt + 1, _MAX_RETRIES,
                    )
                    last_exc = exc
                else:
                    raise CollectorError(
                        f"{self.platform}: HTTP {exc.code} — {exc.reason}"
                    ) from exc

            except urllib.error.URLError as exc:
                log.warning(
                    "%s: network error (attempt %d/%d): %s",
                    self.platform, attempt + 1, _MAX_RETRIES, exc.reason,
                )
                last_exc = exc

            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_BASE ** attempt
                log.info("%s: retrying in %.1fs...", self.platform, wait)
                time.sleep(wait)

        raise CollectorError(
            f"{self.platform}: all {_MAX_RETRIES} retries exhausted"
        ) from last_exc

    def _now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    def _is_stale(
        self,
        data_timestamp: Optional[datetime],
        existing_fetched_at: Optional[datetime],
    ) -> bool:
        """
        Return True if data_timestamp is older than existing_fetched_at.

        Collectors call this to decide whether to include an entry.
        If True, the caller should skip the entry — existing data is fresher.

        Both datetimes must be timezone-aware for correct comparison.
        If either is None, staleness cannot be determined → returns False (not stale).
        """
        if data_timestamp is None or existing_fetched_at is None:
            return False
        # Ensure both are timezone-aware before comparing
        if data_timestamp.tzinfo is None:
            data_timestamp = data_timestamp.replace(tzinfo=timezone.utc)
        if existing_fetched_at.tzinfo is None:
            existing_fetched_at = existing_fetched_at.replace(tzinfo=timezone.utc)
        return data_timestamp < existing_fetched_at
