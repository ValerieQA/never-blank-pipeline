"""Stage 11 — publish owner-centred Editorial Engine V2 output.

The research workflow may publish only after the complete cross-platform package passes
hard validation.  A failed generation or validation publishes nothing for that signal.
"""

import dataclasses
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.content.output_guard import (
    validate_platform_output,
    validate_telegram,
)
from src.strategy.validators import validate_article_for_publish
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.editorial.pipeline import ArticleGenerationError, generate_article
from src.lifecycle.signal_lifecycle import ResearchContext
from src.publishing import formatting
from src.publishing.base import DraftPackage
from src.publishing.facebook import FacebookPublisher
from src.publishing.hashtags import generate_hashtags
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.publication_markers import (
    PUBLICATION_UNCONFIRMED,
    PublicationGuard,
    content_digest,
    destination_text,
    proves_publication,
    refused_result,
)
from src.publishing.release_scope import (
    out_of_release_scope,
    restrict_to_release_scope,
)
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import WixPublisher
from src.utils.logger import get_logger

log = get_logger("research.publish_packages")
#: Same root, same rule as the canonical entrypoint (#233 F-02): the
#: production default is unchanged, and ``NB_PACKAGES_DIR`` redirects it so a
#: test never writes package records into the tracked tree.
PACKAGES_DIR = Path(os.environ.get("NB_PACKAGES_DIR", "").strip() or "reports/content_packages")

#: Every publisher this stage knows how to drive. Kept complete on purpose:
#: the classes are real, tested and usable by a manual operator tool, and
#: deleting them would lose working code that Release 2 will want back.
_ALL_PUBLISHERS = [
    ("wix", WixPublisher()),
    ("linkedin", LinkedInPublisher()),
    ("facebook", FacebookPublisher()),
    ("instagram", InstagramPublisher()),
    ("threads", ThreadsPublisher()),
    ("telegram", TelegramPublisher()),
]

#: What this stage may actually publish. #227: this list was the six above,
#: written before Release 1 narrowed its scope and never updated when it did.
#: On 2026-09-06 and 2026-09-07 it published Facebook, Instagram and Telegram
#: while Wix and LinkedIn failed (#159). Authorization now comes from the one
#: shared definition rather than from a literal maintained here.
#:
#: It had looked safe only because an unrelated repeated-sentence check
#: happened to reject these packages first; #222 removed that check, correctly,
#: and the accident it had been covering became visible the next day. An
#: incidental guard is not channel authorization, so this is the authorization.
#:
#: **This stage drives none of them** (#231, owner decision 2026-10-02). It
#: holds no canonical preflight — nothing in it constructs one — and publication
#: authorization is that preflight, not the ability to reach a publisher class.
#: #227 narrowed the stage to Release 1's own two channels, which are exactly
#: the two it cannot drive: it hands the legacy mutable ``DraftPackage`` to
#: publishers that have accepted only the frozen canonical package since
#: #100/#101, and the adapter raised ``AttributeError`` before any provider
#: call. The crash was substantively right and formally wrong — an incidental
#: crash is not a decision — so the refusal is now stated instead of thrown, and
#: Daily Signal Research generates and packages while publishing nothing.
#:
#: Empty rather than deleted: the loop below still handles the results of
#: whatever it is given, which is what a manual or Release 2 caller would use,
#: and a path that offers it nothing cannot publish by accident.
_PUBLISHERS: list[tuple[str, object]] = []

#: The two Release 1 channels this path may not publish to, and why they are a
#: different case from the four below: they are **inside** Release 1 scope, so
#: calling them out-of-scope would be false. What they lack is this stage's
#: canonical preflight. Derived from the one shared definition, never written
#: out here (#227 item 8).
_NO_PREFLIGHT_CHANNELS = tuple(
    name for name, _ in restrict_to_release_scope(_ALL_PUBLISHERS)
)

_WITHHELD_CHANNELS = out_of_release_scope([name for name, _ in _ALL_PUBLISHERS])

#: The two stated non-results, one per reason. Every channel gets one: a channel
#: that silently disappears from the report is how #227 stayed hidden for months.
_OUTSIDE_R1_REASON = "outside the Release 1 publishing scope (#227)"
_NO_PREFLIGHT_REASON = (
    "inside the Release 1 publishing scope, but this path holds no canonical "
    "preflight and may not publish without one (#231)"
)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"[\s_]+", "-", slug)[:80]


def ensure_never_blank_signature(text: str, signal: dict) -> str:
    """Backward-compatible tested helper; publishing no longer forces a signature."""
    raw = signal.get("POSSIBLE_SIGNATURE_LINE", "").strip()
    clean = re.sub(r"^Never\s+Blank[:\s]+", "", raw, flags=re.I).strip()
    clean = clean or "The signal is rarely the event itself."
    text = re.sub(r"\n+Never\s+Blank[^\n]*$", "", text.rstrip(), flags=re.I).rstrip()
    return f"{text}\n\nNever Blank: {clean}"


def _clean_line(value: str, max_words: int = 34) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    words = value.split()
    if len(words) <= max_words:
        return value
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _build_telegram(structured: dict, wix_url: str = "") -> str:
    """Build the Telegram channel's own format, never reuse an article body."""
    discovery = structured.get("discovery", {})
    observation = (
        discovery.get("aha_setup")
        or discovery.get("first_wrong_explanation")
        or structured.get("hook")
        or structured.get("narrative_spine")
    )
    implication = structured.get("business_translation") or structured.get("reframe")
    lines = [_clean_line(observation), _clean_line(implication)]
    if wix_url:
        lines.append(wix_url.strip())
    text = "\n".join(line for line in lines if line)
    validate_telegram(text)
    return text


def _build_threads(structured: dict) -> list[str]:
    """Native 3–5 post arc: Hook → Recognition → Mechanism → Reframe → Echo."""
    discovery = structured.get("discovery", {})
    candidates = [
        structured.get("hook", ""),
        discovery.get("aha_setup") or discovery.get("first_wrong_explanation", ""),
        structured.get("surviving_explanation", ""),
        structured.get("reframe", ""),
        structured.get("echo_line", ""),
    ]
    sequence: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        post = _clean_line(value, max_words=55)
        key = post.lower()
        if post and key not in seen:
            validate_platform_output("threads", post)
            sequence.append(post)
            seen.add(key)
    if not 3 <= len(sequence) <= 5:
        raise ValueError(f"Threads requires 3–5 distinct posts; generated {len(sequence)}")
    return sequence


def _validate_package(texts: dict[str, str], threads: list[str]) -> None:
    for platform, text in texts.items():
        # Blog and LinkedIn also get the Compound Presence semantic check.
        if platform in ("blog", "linkedin"):
            validate_article_for_publish(text, platform=platform)
        else:
            validate_platform_output(platform, text)
    for post in threads:
        validate_platform_output("threads", post)

    # #221: sentence-level overlap between surfaces is NOT validated here, by
    # product decision. A hook, a sentence or the Never Blank Echo may recur on
    # any number of channels; recurrence alone is not evidence of a defect and
    # must not block publication. Whole-artifact and wiring failures are caught
    # by the identity, lineage and provenance guards, not by comparing prose.


def _build_draft(signal: dict, package: dict, blog_body: str, linkedin_text: str,
                 facebook_text: str, instagram_text: str, threads_seq: list[str],
                 telegram_text: str, image_url_blog: Optional[str] = None) -> DraftPackage:
    preview = package.get("content", {})
    blog_title = preview.get("blog", {}).get("headline") or signal.get("HEADLINE", "")
    wix_category_id = os.getenv("NB_WIX_BLOG_CATEGORY_ID", "")
    wix_tags_raw = os.getenv("NB_WIX_BLOG_TAG_IDS", "")
    wix_tags = [x.strip() for x in wix_tags_raw.split(",") if x.strip()]
    wix_slug = _slugify(blog_title)
    return DraftPackage(
        draft_dir=PACKAGES_DIR,
        blog_title=blog_title,
        blog_body=blog_body,
        blog_meta={
            "title": blog_title,
            "wix_slug": wix_slug,
            "wix_category_id": wix_category_id,
            "wix_tags": wix_tags,
            "meta_description": preview.get("blog", {}).get("angle", "")[:500],
        },
        linkedin_text=linkedin_text,
        instagram_text=instagram_text,
        facebook_text=facebook_text,
        threads_sequence=threads_seq,
        telegram_text=telegram_text,
        image_url=image_url_blog,
        wix_slug=wix_slug,
        wix_category_id=wix_category_id,
        wix_tags=wix_tags,
        # #393: the target identity, which July's publishers read from the
        # environment themselves. #100 moved that read into the package —
        # "the package target is the external target" — and this caller was
        # never adapted, so the adapters now fail closed with "Missing package
        # target identity". Read here instead: the same three variables, the
        # same values, one layer up. Still exactly one read per run.
        wix_site_id=os.getenv("NB_WIX_SITE_ID", ""),
        wix_owner_member_id=os.getenv("NB_WIX_POST_OWNER_ID", ""),
        linkedin_account_id=os.getenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", ""),
        metadata={"signal_id": signal.get("SIGNAL_ID"), "published_at": datetime.now(timezone.utc).isoformat()},
    )


class UnknownDestination(ValueError):
    """A destination this stage cannot drive was requested."""


def _publishers_for(channels: Optional[Sequence[str]]) -> list[tuple[str, object]]:
    """Which publishers this call drives, and the two reporting sets beside it.

    ``channels=None`` is every existing caller, and it is **unchanged**: the
    stage drives nothing, Release 1's two channels are reported as having no
    canonical preflight (#231) and the other four as outside Release 1 scope
    (#227). Daily Signal Research still generates and packages and publishes
    nothing.

    A caller that names channels is an explicit non-Release-1 operator — MVP 1
    (#393) — and drives exactly what it named. It does not widen Release 1:
    `release_scope.py` is untouched and still answers what an automatic R1 run
    may do. An unknown name is refused rather than silently skipped, because a
    destination that disappears from a report is how #227 stayed hidden for
    months.
    """

    if channels is None:
        return list(_PUBLISHERS)
    requested = [name.strip().lower() for name in channels if str(name).strip()]
    known = {name for name, _ in _ALL_PUBLISHERS}
    unknown = [name for name in requested if name not in known]
    if unknown:
        raise UnknownDestination(
            f"unknown destination(s): {', '.join(unknown)}; "
            f"this stage drives {', '.join(sorted(known))}"
        )
    if not requested:
        raise UnknownDestination("no destination requested")
    return [(name, pub) for name, pub in _ALL_PUBLISHERS if name in requested]


def publish_packages(
    signals: list[dict],
    packages: list[dict],
    mode: Optional[str] = None,
    channels: Optional[Sequence[str]] = None,
) -> list[dict]:
    if not signals:
        return []
    publishers = _publishers_for(channels)
    driving = [name for name, _ in publishers]
    withheld = tuple(name for name in _WITHHELD_CHANNELS if name not in driving)
    no_preflight = tuple(name for name in _NO_PREFLIGHT_CHANNELS if name not in driving)
    if os.getenv("NB_RESEARCH_PUBLISH_ENABLED", "false").lower() != "true":
        log.info("Publishing disabled — skipping Stage 11")
        return []

    max_signals = int(os.getenv("NB_RESEARCH_MAX_PUBLISH_SIGNALS_PER_RUN", "1"))
    signals = signals[:max_signals]
    mode = mode or os.getenv("NB_PUBLISH_MODE", "live")
    pkg_map = {p.get("SIGNAL_ID"): p for p in packages}
    reports = []

    # Load active strategy once — used for cta_mode and strategy context injection
    active_strategy  = load_active_strategy()
    strategy_cta     = get_cta_mode(active_strategy)
    strategy_context    = get_strategy_context(active_strategy)
    _strategy_id        = strategy_context.get("strategy_id", "")
    _strategy_started_at = str(active_strategy.started_at) if active_strategy and active_strategy.started_at else ""
    log.info("Strategy context: id=%s cta_mode=%s", _strategy_id, strategy_cta)
    # #227: say out loud what this stage will not publish. The previous
    # behaviour was not a decision anyone had made — it was a list nobody had
    # revisited — and it stayed invisible because nothing ever named it.
    if withheld:
        log.info(
            "Release 1 scope: publishing %s; withholding %s (generated and "
            "packaged, not published)",
            ", ".join(driving) or "nothing",
            ", ".join(withheld),
        )

    for signal in signals:
        rc = ResearchContext.from_dict(signal)
        sig_id = rc.signal_id or "unknown"
        headline = rc.headline
        package = pkg_map.get(sig_id, {})
        pimgs = package.get("images", {}).get("platform_images", {})
        # Signal-level CTA_MODE overrides strategy (allows per-article override via content plan)
        cta_mode = str(signal.get("CTA_MODE") or strategy_cta or "none")

        # Generate and validate the entire package before the first publisher API call.
        try:
            editorial = rc.to_editorial(package)
            article = generate_article(
                editorial.to_legacy_dict(),
                cta_mode=cta_mode,
                strategy_context=strategy_context,
            )
            platforms = article["platforms"]
            structured = article["structured_article"]

            blog_body = platforms["long"]["body"]
            linkedin_text = platforms["medium"]["body"]
            # Facebook gets the conversational reading adaptation, not LinkedIn's medium body.
            facebook_text = platforms["reading"]["body"]
            instagram_text = platforms["instagram"]["body"]
            threads_seq = _build_threads(structured)
            telegram_text = _build_telegram(structured)

            _validate_package({
                "blog": blog_body,
                "linkedin": linkedin_text,
                "facebook": facebook_text,
                "instagram": instagram_text,
                "telegram": telegram_text,
            }, threads_seq)
        except (ArticleGenerationError, ValueError, KeyError) as exc:
            log.error("Signal %s blocked before publishing: %s", sig_id, exc)
            reports.append({
                "signal_id": sig_id,
                "headline": headline,
                "mode": mode,
                "results": {"editorial_gate": PublishResult(
                    platform="editorial_gate", status=PublishStatus.FAILED,
                    error_message=str(exc),
                ).to_dict()},
                "generated_file": "",
            })
            continue

        source_name = signal.get("SOURCE_NAME", "")
        source_url = signal.get("SOURCE_URL", "")
        blog_body += formatting.source_line(source_name, source_url, "blog_markdown")
        linkedin_text = formatting.append_hashtags(
            formatting.bold_signature_prefix(linkedin_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url"),
            generate_hashtags(signal, "linkedin"),
        )
        facebook_text = (
            formatting.bold_signature_prefix(facebook_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url")
        )
        instagram_text = formatting.append_hashtags(
            formatting.bold_signature_prefix(instagram_text, "unicode"),
            generate_hashtags(signal, "instagram"),
        )
        # Threads has no hashtags under the platform strategy.

        draft = _build_draft(
            signal, package, blog_body, linkedin_text, facebook_text,
            instagram_text, threads_seq, telegram_text,
            pimgs.get("blog", {}).get("url") or None,
        )
        generated_path = PACKAGES_DIR / f"{sig_id}_generated.json"
        _save_generated(generated_path, sig_id, headline, blog_body, linkedin_text,
                        facebook_text, instagram_text, threads_seq, telegram_text, "",
                        strategy_id=_strategy_id, strategy_started_at=_strategy_started_at)

        results: dict = {
            name: PublishResult(
                platform=name,
                status=PublishStatus.SKIPPED,
                error_message=reason,
            ).to_dict()
            for names, reason in (
                (withheld, _OUTSIDE_R1_REASON),
                (no_preflight, _NO_PREFLIGHT_REASON),
            )
            for name in names
        }
        wix_url = ""
        wix_post_id: Optional[str] = None
        # ── Publication marker authority (NB-00a, invariant S3-I1) ──────────
        # Consulted before every irreversible call and written immediately
        # after each destination succeeds, independently of the index and
        # history writes further down: evidence that depended on those could
        # be lost exactly when a partial failure made it matter most.
        #
        # Only ``live`` reaches it. A dry run makes no external call, so an
        # intent written by one would suppress the real publication that
        # follows — the authority must record what happened, never a rehearsal.
        guard = (
            PublicationGuard(source_signal_ids=[sig_id], run_id=draft.run_id)
            if mode == "live"
            else None
        )
        unconfirmed: list[str] = []
        for name, publisher in publishers:
            platform_img = pimgs.get(name, {}).get("url") or draft.image_url
            use_draft = _swap_image(draft, platform_img) if name in ("linkedin", "facebook", "instagram") else draft
            digest = content_digest(destination_text(use_draft, name))
            if guard is not None:
                decision = guard.check(name)
                if decision.proceed:
                    decision = guard.record_intent(name, content_digest=digest)
                if not decision.proceed:
                    refused = refused_result(decision, run_id=draft.run_id)
                    log.info(
                        "%s not published: %s", name,
                        refused.error_message or f"reusing {refused.external_id}",
                    )
                    results[name] = refused.to_dict()
                    if name == "wix" and refused.url:
                        wix_url = refused.url
                        wix_post_id = refused.external_id
                    continue
            try:
                if name == "telegram":
                    final_telegram = _build_telegram(structured, wix_url=wix_url)
                    use_draft.telegram_text = final_telegram
                    result = publisher.publish(use_draft, mode, wix_url=wix_url)
                    telegram_text = final_telegram
                else:
                    result = publisher.publish(use_draft, mode)
                if guard is not None and proves_publication(result) and (
                    guard.record_marker(name, result, content_digest=digest) is None
                ):
                    # The post exists and its marker does not. The intent
                    # stays, so the next run treats the key as possibly
                    # published and skips it (at most once).
                    unconfirmed.append(guard.key(name))
                    log.error("%s: %s", PUBLICATION_UNCONFIRMED, name)
                if name == "wix" and result.ok():
                    if result.url:
                        wix_url = result.url
                    if result.external_id:
                        wix_post_id = result.external_id
                result_dict = result.to_dict()
                if result.ok() and not result.url:
                    result_dict["status"] = "published_url_unavailable"
                results[name] = result_dict
            except Exception as exc:
                log.error("%s publish error: %s", name, exc)
                results[name] = PublishResult(
                    platform=name, status=PublishStatus.FAILED, error_message=str(exc)
                ).to_dict()

        _save_generated(generated_path, sig_id, headline, blog_body, linkedin_text,
                        facebook_text, instagram_text, threads_seq, telegram_text, wix_url,
                        strategy_id=_strategy_id, strategy_started_at=_strategy_started_at)
        # Append to published content index (History Engine 4B.3).
        # Non-fatal: index failure must never block a completed publish.
        _pub_strategy_id = strategy_context.get("strategy_id", "")
        if not _pub_strategy_id or _pub_strategy_id == "none":
            log.warning("Published index: skipping entry for %s — no active strategy", sig_id)
        else:
            try:
                from src.strategy.history import append_published_entry
                from src.strategy.models import PlatformPublication, PublishedEntry
                # pattern_id: check all known field names used across the pipeline
                _pattern_id = (
                    signal.get("source_pattern_id")
                    or signal.get("PATTERN_ID")
                    or pkg_map.get(sig_id, {}).get("source_pattern_id")
                    or None
                )
                # Compute strategy_week from publication date and strategy start
                _strategy_week: Optional[int] = None
                if active_strategy and active_strategy.started_at:
                    _days = (datetime.now(timezone.utc).date() - active_strategy.started_at).days
                    _strategy_week = max(1, (_days // 7) + 1)
                # Build per-platform publication map from publisher results
                _published_at = datetime.now(timezone.utc)
                _publications: dict[str, PlatformPublication] = {}
                _ok_statuses = {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable"}
                for _pub_name, _pub_dict in results.items():
                    if _pub_dict.get("status") in _ok_statuses:
                        _publications[_pub_name] = PlatformPublication(
                            platform=_pub_name,
                            external_id=_pub_dict.get("external_id") or None,
                            url=_pub_dict.get("url") or "",
                            published_at=_published_at,
                            status=_pub_dict.get("status", "published").lower(),
                        )
                if _publications:
                    append_published_entry(PublishedEntry(
                        content_id=sig_id,
                        strategy_id=_pub_strategy_id,
                        pattern_id=_pattern_id,
                        published_at=_published_at,
                        platform="blog",
                        url=wix_url,
                        platform_content_id=wix_post_id,
                        publications=_publications,
                        echo=structured.get("echo_line") or None,
                        hook=structured.get("hook", ""),
                        topic=headline,
                        cta_mode=cta_mode,
                        strategy_week=_strategy_week,
                    ))
            except Exception as _index_exc:
                log.warning("Published index append failed (non-fatal): %s", _index_exc)

        reports.append({
            "signal_id": sig_id,
            "headline": headline,
            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "mode": mode,
            "results": results,
            "wix_url": wix_url,
            # NB-00a §3.6 p5: keys whose post exists but whose marker could not
            # be made durable. Named here so a person can see which ones the
            # next run will skip, instead of discovering it as a silent skip.
            PUBLICATION_UNCONFIRMED: unconfirmed,
            "generated_file": str(generated_path),
            "platform_images": {p: {
                "url": pimgs.get(p, {}).get("url", ""),
                "size": pimgs.get(p, {}).get("size", ""),
            } for p in ("blog", "linkedin", "facebook", "instagram", "threads", "stories")},
            "instagram_signature": not bool(structured.get("echo_line")) or bool(structured.get("echo_line") in instagram_text),
            # Telegram intentionally uses signal + implication + optional link, not Echo/signature.
            "telegram_signature": True,
            "wix_cover_image_attached": bool(draft.image_url),
            "image_design_version": package.get("images", {}).get("design_version", ""),
            "image_hook_text": package.get("images", {}).get("hook_text", ""),
            "image_visual_family": package.get("images", {}).get("visual_family", ""),
            "image_method": package.get("images", {}).get("image_method", ""),
        })

    return reports


def _swap_image(draft: DraftPackage, image_url: str) -> DraftPackage:
    """The same draft, aimed at one platform's image. Everything else is the draft.

    This enumerated its fields until run 37715852447, and so silently dropped
    the five it did not name — ``platform_image_urls``, ``run_id`` and the three
    target-identity fields added for this lane in #393. All five default to
    empty, so nothing failed at construction: LinkedIn, the only destination
    that is both image-swapped and identity-requiring, failed at its publisher
    with ``Missing package target identity`` after four surfaces had already
    published.

    ``replace`` is not a tidier spelling of that list — it is the reason the
    defect cannot recur. A copy that names fields can omit a future one; a copy
    that replaces one cannot.
    """

    return dataclasses.replace(draft, image_url=image_url)


def _save_generated(path: Path, sig_id, headline, blog_body, linkedin, facebook,
                    instagram, threads, telegram, wix_url,
                    strategy_id: str = "", strategy_started_at: str = ""):
    path.write_text(json.dumps({
        "signal_id":           sig_id,
        "headline":            headline,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "strategy_id":         strategy_id,
        "strategy_started_at": strategy_started_at,
        "wix_url":             wix_url,
        "blog_article":        blog_body,
        "linkedin_post":       linkedin,
        "facebook_post":       facebook,
        "instagram_caption":   instagram,
        "threads_sequence":    threads,
        "telegram_text":       telegram,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def format_publish_summary(reports: list[dict]) -> str:
    if not reports:
        return "No signals published."
    lines = ["\n## Publishing Summary\n"]
    for report in reports:
        lines.append(f"### {report.get('headline', '')[:70]}")
        for platform, result in report.get("results", {}).items():
            status = result.get("status", "")
            error = result.get("error_message", "")
            icon = "✅" if status in ("PUBLISHED", "DRAFT_CREATED", "published_url_unavailable") else "❌"
            lines.append(f"- {icon} **{platform.title()}** {status}{' — ' + error if error else ''}")
        lines.append("")
    return "\n".join(lines)
