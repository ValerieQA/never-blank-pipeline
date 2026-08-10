"""
Telegram publisher — sends a message to the configured channel.

Appends Wix post URL as a link at the end if available.
If no Wix URL exists and mode is not 'live', SKIPS rather than posting linkless.

dry_run    — validate env + payload, no API call
draft_only — SKIPPED
live       — POST sendMessage → PUBLISHED

Requires: NB_TELEGRAM_BOT_TOKEN, NB_TELEGRAM_CHANNEL_ID
"""
import json
import os

from src.publishing.base import BasePublisher, DraftPackage, _fetch
from src.publishing.result import PublishResult, PublishStatus


class TelegramPublisher(BasePublisher):
    name = "telegram"

    def publish(  # type: ignore[override]  # wix_url extends base signature
        self,
        draft: DraftPackage,
        mode: str,
        wix_url: str = None,
        *,
        policy=None,
    ) -> PublishResult:
        """Override: accepts wix_url kwarg. Calls _check_policy before any I/O."""
        self._check_policy(policy, operation="publication")
        return self._publish_with_wix_url(draft, mode, wix_url=wix_url)

    def _publish_impl(self, draft: DraftPackage, mode: str) -> PublishResult:  # type: ignore[override]
        return self._publish_with_wix_url(draft, mode, wix_url=None)

    def _publish_with_wix_url(self, draft: DraftPackage, mode: str, wix_url: str = None) -> PublishResult:
        token      = os.getenv("NB_TELEGRAM_BOT_TOKEN", "")
        channel_id = os.getenv("NB_TELEGRAM_CHANNEL_ID", "")

        missing = [k for k, v in {
            "NB_TELEGRAM_BOT_TOKEN":  token,
            "NB_TELEGRAM_CHANNEL_ID": channel_id,
        }.items() if not v]
        if missing:
            return self._fail(f"Missing env vars: {missing}")

        if mode == "draft_only":
            return self._skip("Telegram publishes immediately — skipped in draft_only mode")

        base_text = draft.telegram_text
        if not base_text:
            return self._fail("telegram.txt is empty")

        # Attach Wix URL if known (passed from orchestrator or from draft metadata)
        url = wix_url or draft.metadata.get("wix_url", "")
        text = base_text
        if url:
            text = f"{base_text}\n\n[Read more →]({url})"

        if mode == "dry_run":
            return PublishResult(
                platform=self.name,
                status=PublishStatus.SKIPPED,
                error_message=(
                    f"dry_run: payload valid — {len(text)} chars, "
                    f"channel={channel_id!r}, wix_url={url!r}"
                ),
            )

        payload = json.dumps({
            "chat_id":    channel_id,
            "text":       text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }).encode()

        code, resp, _ = _fetch(
            f"https://api.telegram.org/bot{token}/sendMessage",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=payload,
        )

        if code == 200 and resp.get("ok"):
            msg    = resp.get("result", {})
            msg_id = str(msg.get("message_id", ""))
            chat   = msg.get("chat", {})
            username = chat.get("username", "")
            tg_url = f"https://t.me/{username}/{msg_id}" if username and msg_id else None
            return self._published(external_id=msg_id, url=tg_url)

        err = resp.get("description", resp.get("_raw", ""))[:200]
        return self._fail(f"HTTP {code}: {err}")
