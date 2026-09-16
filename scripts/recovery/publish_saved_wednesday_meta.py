#!/usr/bin/env python3
"""Issue #247: publish the saved Meta payloads of Wednesday run 35102307491.

A one-off recovery. The scheduled Wednesday run of 2026-09-16 published Wix and
LinkedIn, and generated Facebook, Instagram, Threads and Telegram payloads that
Release 1 scope skipped. This script publishes three of those saved payloads,
exactly as the run wrote them, and nothing else:

* Facebook  — ``facebook_post``, text only.
* Instagram — ``instagram_caption`` with the run's own Wix 1920×1080 master
  asset (the run produced no Instagram asset; the owner accepted this reuse).
* Threads   — ``threads_sequence``.
* Telegram  — NOT published: the saved ``telegram_text`` is truncated
  mid-sentence. Recorded as skipped, never edited.

What makes it safe to run:

* **Bound to one run.** The evidence files must match the SHA-256 digests below,
  and the run id, signal id and the Wix asset must match too. Anything else
  fails closed before any publisher is constructed.
* **No generation.** Payload text is read from ``generated.json`` and passed
  through untouched. Nothing here imports the model client; ``main`` refuses to
  continue if anything has loaded it.
* **No Wix, no LinkedIn, no consumption.** Only the three publishers above are
  imported. Nothing writes ``published_signal_ids.txt`` or any other repository
  state; the only output is the result record given by ``--result-out``.
* **Single-shot.** A live run requires ``--prior-live-checked``, which the
  workflow passes only after ``check_prior_live_runs.py`` proved from GitHub's
  own run records that no earlier live run ever reached its publish step, and
  only on the first attempt of the run. There are no retries: a lost response
  can hide a created post, so no earlier attempt is ever considered safe.
* **Honest records.** Each channel is written as ATTEMPTING before its publish
  call and replaced atomically after it; an escaped exception is recorded as
  UNKNOWN_OUTCOME.
* **No false success.** ``ThreadsPublisher`` returns PUBLISHED after a failed
  reply; this script counts the posts actually published and reports PARTIAL.
* **Dry run by default.** ``--mode live`` is required to publish.

Remove this script and its workflow after the recovery (separate cleanup PR).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.publishing.base import DraftPackage  # noqa: E402
from src.publishing.facebook import FacebookPublisher  # noqa: E402
from src.publishing.instagram import InstagramPublisher  # noqa: E402
from src.publishing.result import PublishStatus  # noqa: E402
from src.publishing.threads import ThreadsPublisher  # noqa: E402

WORKFLOW_RUN_ID = "35102307491"
RUN_ID = "d2895f1b-9e62-419e-8c26-5c0fd20115aa"
SIGNAL_ID = "f9c2f40f85d82da3"

#: SHA-256 of the evidence files exactly as the run uploaded them.
EXPECTED_DIGESTS = {
    "generated.json": "7bd0abd09e0a548f5a387bb3e989ad9ba426e17cab33c8a0e38e6f8028366468",
    "visual_assets.json": "f9db5630373381eef43376a0d7b972dfccbd93ff1adcd3c8cfdd784b3eaa7328",
}

#: The run's own Wix master asset — the only 1920×1080 image it produced.
EXPECTED_WIX_ASSET = (
    "https://res.cloudinary.com/df0lt7izx/image/upload/v1789565583/"
    "never-blank/posts/research/f9c2f40f85d82da3/blog/1789565583.png"
)

PUBLISHABLE = ("facebook", "instagram", "threads")
PUBLISHERS = {
    "facebook": FacebookPublisher,
    "instagram": InstagramPublisher,
    "threads": ThreadsPublisher,
}
TELEGRAM_SKIP_REASON = (
    "owner decision (#247): the saved telegram_text is truncated mid-sentence "
    "and is not published; it is not edited or regenerated"
)

MODEL_CLIENT_MODULE = "src.utils.llm_client"


class RecoveryIdentityError(RuntimeError):
    """The evidence does not prove it is the exact run this recovery is for."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_verified_evidence(
    run_dir: Path,
    *,
    expected_digests: dict[str, str] = EXPECTED_DIGESTS,
    expected_wix_asset: str = EXPECTED_WIX_ASSET,
) -> tuple[dict, str]:
    """Return ``(generated, wix_asset_url)`` or raise ``RecoveryIdentityError``."""
    for name, expected in expected_digests.items():
        path = run_dir / name
        if not path.is_file():
            raise RecoveryIdentityError(f"missing evidence file: {path}")
        actual = _sha256(path)
        if actual != expected:
            raise RecoveryIdentityError(
                f"{name} digest mismatch: expected {expected}, got {actual}"
            )

    generated = json.loads((run_dir / "generated.json").read_text(encoding="utf-8"))
    visuals = json.loads((run_dir / "visual_assets.json").read_text(encoding="utf-8"))

    for record, label in ((generated, "generated.json"), (visuals, "visual_assets.json")):
        if record.get("run_id") != RUN_ID:
            raise RecoveryIdentityError(f"{label} run_id is {record.get('run_id')!r}")
        if record.get("signal_id") != SIGNAL_ID:
            raise RecoveryIdentityError(f"{label} signal_id is {record.get('signal_id')!r}")

    wix = [d for d in visuals.get("derivatives", []) if d.get("channel") == "wix"]
    if len(wix) != 1:
        raise RecoveryIdentityError(f"expected exactly one wix asset, found {len(wix)}")
    asset = wix[0]
    if (
        asset.get("url") != expected_wix_asset
        or asset.get("width") != 1920
        or asset.get("height") != 1080
        or asset.get("status") != "valid"
    ):
        raise RecoveryIdentityError(f"wix asset is not the expected 1920x1080 master: {asset}")

    for field_name in ("facebook_post", "instagram_caption", "threads_sequence"):
        if not generated.get(field_name):
            raise RecoveryIdentityError(f"generated.json has no {field_name}")

    return generated, asset["url"]


def build_draft(generated: dict, wix_asset_url: str) -> DraftPackage:
    """The saved payloads, untouched. Only Instagram carries an image."""
    return DraftPackage(
        draft_dir=Path("."),
        blog_title="",
        blog_body="",
        blog_meta={},
        linkedin_text="",
        instagram_text=generated["instagram_caption"],
        facebook_text=generated["facebook_post"],
        threads_sequence=list(generated["threads_sequence"]),
        telegram_text="",
        image_url=None,
        platform_image_urls={"instagram": wix_asset_url},
        run_id=RUN_ID,
        metadata={"signal_id": SIGNAL_ID, "recovery_issue": 247},
    )


def _result_record(result) -> dict:
    status = result.status.value if isinstance(result.status, PublishStatus) else str(result.status)
    return {
        "platform": result.platform,
        "status": status,
        "external_id": result.external_id,
        "url": result.url,
        "error_message": result.error_message,
    }


def publish_threads_counted(publisher_cls, draft: DraftPackage, mode: str) -> dict:
    """Publish Threads and report what was really posted.

    ``ThreadsPublisher`` stops at the first failed reply and still returns
    PUBLISHED. The recovery must not call a partial thread complete, so it
    counts the posts the provider actually published — by wrapping the module's
    own publish call for the duration of this one call — and reports PARTIAL
    when fewer than the saved sequence went out. The shared publisher is not
    modified.
    """
    import src.publishing.threads as threads_module

    posted: list[str] = []
    original = threads_module._publish_container

    def counting(token, user_id, container_id):
        media_id, err = original(token, user_id, container_id)
        if not err and media_id:
            posted.append(media_id)
        return media_id, err

    threads_module._publish_container = counting
    try:
        record = _result_record(publisher_cls().publish(draft, mode))
    finally:
        threads_module._publish_container = original

    record["posted_ids"] = list(posted)
    record["expected_posts"] = len(draft.threads_sequence)
    if mode == "live" and record["status"] == "PUBLISHED" and len(posted) != len(draft.threads_sequence):
        record["status"] = "PARTIAL"
        record["error_message"] = (
            f"only {len(posted)} of {len(draft.threads_sequence)} posts were published; "
            "never retried automatically"
        )
    return record


def _write(out: Path, record: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out)


def main(argv: list[str] | None = None, *, publishers: dict | None = None,
         forbidden_modules: tuple[str, ...] = (MODEL_CLIENT_MODULE,)) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True,
                        help="Directory the run-evidence artifact was downloaded into")
    parser.add_argument("--mode", choices=("dry_run", "live"), default="dry_run")
    parser.add_argument("--channels", default=",".join(PUBLISHABLE),
                        help="Subset of facebook,instagram,threads")
    parser.add_argument("--prior-live-checked", action="store_true",
                        help="Set by the workflow once no earlier live run reached publication")
    parser.add_argument("--result-out", required=True)
    args = parser.parse_args(argv)

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    unknown = [c for c in channels if c not in PUBLISHABLE]
    if unknown or not channels or len(set(channels)) != len(channels):
        print(f"ERROR: --channels must be a non-empty subset of {PUBLISHABLE}; got {channels}")
        return 2

    run_dir = Path(args.evidence_dir) / RUN_ID
    try:
        generated, wix_asset_url = load_verified_evidence(run_dir)
    except RecoveryIdentityError as exc:
        print(f"ERROR: evidence identity not established — nothing published: {exc}")
        return 3

    loaded = [name for name in forbidden_modules if name in sys.modules]
    if loaded:
        print(f"ERROR: {loaded} loaded; this recovery must make no model calls")
        return 4

    if args.mode == "live" and not args.prior_live_checked:
        print("ERROR: live mode requires --prior-live-checked (single-shot guard)")
        return 5

    draft = build_draft(generated, wix_asset_url)
    registry = publishers or PUBLISHERS
    out = Path(args.result_out)
    record = {
        "recovery_issue": 247,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "run_id": RUN_ID,
        "signal_id": SIGNAL_ID,
        "mode": args.mode,
        "evidence_digests": EXPECTED_DIGESTS,
        "instagram_asset": wix_asset_url,
        "model_calls": 0,
        "signal_consumption_changed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "results": {
            "telegram": {
                "platform": "telegram", "status": "SKIPPED", "external_id": None,
                "url": None, "error_message": TELEGRAM_SKIP_REASON,
            },
            **{
                untouched: {
                    "platform": untouched, "status": "NOT_ATTEMPTED", "external_id": None,
                    "url": None,
                    "error_message": "outside this recovery: already published by the run",
                }
                for untouched in ("wix", "linkedin")
            },
        },
    }

    for channel in channels:
        # Write-ahead: an interrupted call must never read as "not attempted".
        record["results"][channel] = {
            "platform": channel, "status": "ATTEMPTING", "external_id": None,
            "url": None, "error_message": "publish call started; outcome not yet known",
        }
        _write(out, record)
        try:
            if channel == "threads":
                result = publish_threads_counted(registry[channel], draft, args.mode)
            else:
                result = _result_record(registry[channel]().publish(draft, args.mode))
        except Exception as exc:  # noqa: BLE001 - the outcome is unknown, record it
            result = {
                "platform": channel, "status": "UNKNOWN_OUTCOME", "external_id": None,
                "url": None, "error_message": f"{type(exc).__name__}: {exc}"[:500],
            }
        record["results"][channel] = result
        _write(out, record)
        print(f"  {channel:<10} {result['status']}"
              f"  id={result['external_id']}  url={result['url']}"
              + (f"  error={result['error_message']}" if result["error_message"] else ""))

    print(f"  record: {out}")
    success = {"PUBLISHED"} if args.mode == "live" else {"PUBLISHED", "SKIPPED", "DRAFT_CREATED"}
    failed = [c for c in channels if record["results"][c]["status"] not in success]
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
