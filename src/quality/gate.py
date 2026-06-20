"""
QC Gate — orchestrates all quality checks and the rewrite loop.

Status system:
  GREEN  = all checks passed
  YELLOW = one or more checks failed, but rewrite succeeded
  ORANGE = item quarantined (duplicate, legal risk, max rewrites exhausted)
  RED    = system-level failure (API errors, unrecoverable state)

Rules:
  - Human Review is optional.
  - Human Dependency is forbidden.
  - YELLOW triggers rewrite_with_feedback (max 2 rewrites from quality.yaml).
  - ORANGE moves item to data/quarantine/ and continues the pipeline.
  - RED stops and logs system failure.
  - QC failure never blocks the pipeline unless RED.
"""

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from src.models import (
    ContentBrief, ContentPackage, QCCheckResult, QCReport,
)
from src.utils.config_loader import load_quality
from src.utils.logger import get_logger
import src.quality.duplication as duplication_check
import src.quality.factuality  as factuality_check
import src.quality.voice       as voice_check
import src.quality.rewrite     as rewrite_mod

log = get_logger("qc.gate")

QUARANTINE_DIR = Path(__file__).parent.parent.parent / "data" / "quarantine"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _aggregate_status(checks: list[QCCheckResult]) -> str:
    """
    Determine overall QC status from individual check results.
    Priority: red > orange > yellow > green.
    """
    statuses = {c.status for c in checks}
    if "red"    in statuses: return "RED"
    if "orange" in statuses: return "ORANGE"
    if "yellow" in statuses: return "YELLOW"
    return "GREEN"


def _failing_checks(checks: list[QCCheckResult]) -> list[QCCheckResult]:
    return [c for c in checks if c.status in ("yellow", "orange", "red")]


def _quarantine(
    pkg: ContentPackage,
    brief: ContentBrief,
    reason: str,
) -> str:
    """
    Save content package to data/quarantine/YYYY-MM-DD/slug/.
    Returns the quarantine directory path as a string.
    """
    q_dir = QUARANTINE_DIR / date.today().isoformat() / brief.wix_slug
    q_dir.mkdir(parents=True, exist_ok=True)

    (q_dir / "reason.txt").write_text(reason, encoding="utf-8")
    (q_dir / "blog_post.md").write_text(
        f"# {pkg.blog_title}\n\n{pkg.blog_body}", encoding="utf-8"
    )
    (q_dir / "linkedin.txt").write_text(pkg.linkedin_text, encoding="utf-8")
    (q_dir / "metadata.json").write_text(
        json.dumps({
            "quarantine_reason": reason,
            "quarantined_at":    datetime.now(timezone.utc).isoformat(),
            "title":             pkg.blog_title,
            "slug":              brief.wix_slug,
            "observation_type":  brief.observation_type.value,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.warning("Content quarantined: %s — reason: %s", q_dir, reason)
    return str(q_dir)


# ── Main gate ─────────────────────────────────────────────────────────────────

def run_checks(pkg: ContentPackage, brief: ContentBrief) -> list[QCCheckResult]:
    """Run all QC checks on a content package. Returns list of check results."""
    quality = load_quality()
    enabled = quality.get("qc_checks", {})

    checks: list[QCCheckResult] = []

    # 1. Duplication (on blog body — heavier check than the pre-generation title check)
    if enabled.get("duplication", True):
        dup_text = f"{brief.title} — {brief.angle} — {pkg.blog_body[:400]}"
        checks.append(duplication_check.check(dup_text, brief.wix_slug))

    # 2. Factual risk assessment (blog body only — source of truth for all platforms)
    if enabled.get("factuality", True):
        checks.append(factuality_check.check(pkg.blog_body, brief))

    # 3–8. Voice check — all platforms
    if enabled.get("voice", True):
        voice_targets = [
            (pkg.blog_body,                       "blog",      "voice_blog"),
            (pkg.linkedin_text,                    "linkedin",  "voice_linkedin"),
            (pkg.instagram_caption,                "instagram", "voice_instagram"),
            (pkg.facebook_text,                    "facebook",  "voice_facebook"),
            (" ".join(pkg.threads_sequence or []), "threads",   "voice_threads"),
            (pkg.telegram_text,                    "telegram",  "voice_telegram"),
        ]
        for content, platform, check_name in voice_targets:
            if content and content.strip():
                checks.append(voice_check.check(
                    content=content,
                    platform=platform,
                    observation_statement=brief.observation_statement,
                    check_name=check_name,
                ))

    return checks


def run_qc(
    pkg: ContentPackage,
    brief: ContentBrief,
) -> tuple[ContentPackage, QCReport]:
    """
    Run the full QC gate including rewrite loop.

    Returns (final_package, qc_report).
    The final_package may differ from the input if rewrites were applied.
    The pipeline should use the returned package, not the input.
    """
    quality     = load_quality()
    max_rewrites = quality.get("rewrites", {}).get("max_rewrites", 2)
    now         = datetime.now(timezone.utc).isoformat()

    log.info("QC gate starting for: %r", brief.title)

    rewrite_count   = 0
    quarantined     = False
    quarantine_path: Optional[str] = None
    quarantine_reason = ""
    all_check_rounds: list[QCCheckResult] = []

    current_pkg = pkg

    for attempt in range(max_rewrites + 1):
        checks = run_checks(current_pkg, brief)
        all_check_rounds = checks   # keep the latest round
        overall = _aggregate_status(checks)

        log.info("QC attempt %d/%d: %s", attempt + 1, max_rewrites + 1, overall)
        for c in checks:
            log.debug("  %s: %s (score=%.4f)", c.check_name, c.status, c.score)

        if overall == "RED":
            # System failure — stop immediately
            log.error("QC RED: system failure on attempt %d", attempt + 1)
            return current_pkg, QCReport(
                overall_status="RED",
                checks=all_check_rounds,
                rewrite_count=rewrite_count,
                final_status="RED",
                quarantined=False,
                quarantine_reason="System failure during QC",
                quarantine_path=None,
                generated_at=now,
            )

        if overall == "ORANGE":
            # Quarantine and stop — do not rewrite orange items
            failing = _failing_checks(checks)
            quarantine_reason = "; ".join(
                f"{c.check_name}: {'; '.join(c.issues[:2])}"
                for c in failing if c.status == "orange"
            )
            quarantine_path = _quarantine(current_pkg, brief, quarantine_reason)
            quarantined = True
            break

        if overall == "GREEN":
            break

        # overall == "YELLOW" — attempt a rewrite if budget allows
        if attempt < max_rewrites:
            failing_yellow = [c for c in checks if c.status == "yellow"]
            log.info(
                "QC YELLOW — rewriting attempt %d/%d, failing: %s",
                attempt + 1, max_rewrites,
                [c.check_name for c in failing_yellow],
            )
            rewrite_count += 1
            current_pkg = rewrite_mod.apply_feedback(
                pkg=current_pkg,
                brief=brief,
                failing_checks=failing_yellow,
                attempt=attempt + 1,
            )
        else:
            # Exhausted rewrites — quarantine
            quarantine_reason = (
                f"Max rewrites ({max_rewrites}) exhausted. "
                + "; ".join(
                    f"{c.check_name}: {'; '.join(c.issues[:1])}"
                    for c in _failing_checks(checks)
                )
            )
            quarantine_path = _quarantine(current_pkg, brief, quarantine_reason)
            quarantined = True
            overall = "ORANGE"
            break

    final_status = "ORANGE" if quarantined else overall

    report = QCReport(
        overall_status=_aggregate_status(all_check_rounds) if not quarantined else "ORANGE",
        checks=all_check_rounds,
        rewrite_count=rewrite_count,
        final_status=final_status,
        quarantined=quarantined,
        quarantine_reason=quarantine_reason,
        quarantine_path=quarantine_path,
        generated_at=now,
    )

    log.info(
        "QC complete: final=%s rewrites=%d quarantined=%s",
        final_status, rewrite_count, quarantined,
    )
    return current_pkg, report
