"""
Daily research pipeline orchestrator.
Run: python scripts/research/run_daily_research.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.research.discover import run_discovery
from scripts.research.score import score_candidates, _load_weights
from scripts.research.enrich import enrich_candidates
from scripts.research.angles import add_angles
from scripts.research.prepare_content import prepare_content_packages, format_package_preview
from scripts.research.publish_packages import publish_packages, format_publish_summary
from scripts.research.sync_to_sheets import sync_to_sheets
from scripts.research.archive import run_archive
from src.utils.logger import get_logger

log = get_logger("research.daily")

ACTIVE_FILE   = Path("data/research/signals_active.jsonl")
SELECTED_FILE = Path("data/research/selected_signals.jsonl")
SEEN_FILE     = Path("data/research/seen_index.json")

SCHEMA_DEFAULTS = {
    "CORE_FACT": "", "WHY_IT_MATTERS_TO_BUSINESS": "", "BUSINESS_RESPONSES_OBSERVED": "",
    "REAL_COMPANY_EXAMPLE": None, "PROBLEM_FACED": "", "RESPONSE_TAKEN": "",
    "OUTCOME_IF_KNOWN": "unknown", "SOURCE_FOR_CASE": None, "BUSINESS_LESSON": "",
    "DID_IT_WORK": "unknown", "EVIDENCE_OF_OUTCOME": "", "TIME_HORIZON": "",
    "COUNTER_EXAMPLE": "", "WHY_THIS_CASE_IS_INTERESTING": "",
    "ARTICLE_READINESS_SCORE": "0", "TARGET_AUDIENCE": "", "PRIMARY_CHANNEL": "",
    "CORE_TENSION": "", "LINKEDIN_ANGLE": "", "BLOG_ANGLE": "", "THREADS_ANGLE": "",
    "STORY_ANGLE": "", "DISCUSSION_POTENTIAL": "", "SIGNAL_STRENGTH": "",
    "CHANNEL_FIT_SCORE": "0", "POTENTIAL_HOOK": "", "INTERESTING_QUESTION": "",
    "NEVER_BLANK_ANGLE": "", "POSSIBLE_SIGNATURE_LINE": "", "SOURCE_QUALITY": "",
    "CONFIDENCE": "low", "RECOMMENDED_FOR_ARTICLE": "false",
    "NOTES": "", "APPROVED_OVERRIDE": "", "score_reason": "",
    "raw_summary": "", "discovery_confidence": "",
}


def _load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.load(open(SEEN_FILE))
    return {}


def _save_seen(seen: dict) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def _append_jsonl(path: Path, signals: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for sig in signals:
            line = json.dumps(sig, ensure_ascii=False)
            json.loads(line)
            f.write(line + "\n")


def _within_budget(count: int) -> bool:
    max_cost = float(os.environ.get("NB_RESEARCH_MAX_DAILY_COST_USD", "2.00"))
    est_cost = count * 0.04
    if est_cost > max_cost:
        log.warning("Estimated cost $%.2f exceeds budget $%.2f — capping", est_cost, max_cost)
        return False
    return True


def _publishing_failures(reports: list[dict]) -> list[str]:
    failures = []
    for report in reports:
        for platform, result in report.get("results", {}).items():
            if result.get("status") == "FAILED":
                failures.append(f"{platform}: {result.get('error_message', 'unknown error')}")
    return failures


def run() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = {
        "date": today, "candidates_found": 0, "duplicates_skipped": 0,
        "new_signals_added": 0, "selected_for_content": 0,
        "sheet_sync": "not_run", "archived": 0, "top_signals": [],
        "publish_reports": [],
    }

    cfg = _load_weights()
    thresholds = cfg.get("thresholds", {})
    select_min = thresholds.get("select_minimum", 7)
    top_n_sel = thresholds.get("top_n_to_select", 3)
    seen = _load_seen()
    seen_ids = set(seen.keys())

    log.info("=== Stage 1: Discovery ===")
    candidates = run_discovery(seen_ids)
    summary["candidates_found"] = len(candidates)
    if not candidates:
        log.info("No new candidates — pipeline complete")
        return summary

    new_candidates = [c for c in candidates if c["SIGNAL_ID"] not in seen_ids]
    summary["duplicates_skipped"] = len(candidates) - len(new_candidates)
    if not new_candidates:
        return summary

    log.info("=== Stage 3: Scoring ===")
    scored = score_candidates(new_candidates)
    if not _within_budget(len(scored)):
        scored = scored[:max(3, len(scored) // 2)]

    log.info("=== Stage 4: Enrichment (%d candidates) ===", len(scored))
    enriched = enrich_candidates(scored)
    log.info("=== Stage 5: Angles ===")
    with_angles = add_angles(enriched)

    final_signals = []
    for sig in with_angles:
        full = dict(SCHEMA_DEFAULTS)
        full.update(sig)
        final_signals.append(full)

    log.info("=== Stage 6: Save ===")
    _append_jsonl(ACTIVE_FILE, final_signals)
    summary["new_signals_added"] = len(final_signals)
    now_ts = datetime.now(timezone.utc).isoformat()
    for sig in final_signals:
        seen[sig["SIGNAL_ID"]] = {"date": now_ts, "headline": sig.get("HEADLINE", "")}
    _save_seen(seen)

    selected = [
        s for s in final_signals
        if str(s.get("APPROVED_OVERRIDE", "")).lower() == "true"
        or (
            str(s.get("RECOMMENDED_FOR_ARTICLE", "false")).lower() == "true"
            and int(s.get("ARTICLE_READINESS_SCORE", "0") or "0") >= select_min
        )
    ][:top_n_sel]

    if selected:
        _append_jsonl(SELECTED_FILE, selected)
        summary["selected_for_content"] = len(selected)
        summary["top_signals"] = [s.get("HEADLINE", "")[:80] for s in selected]

    log.info("=== Stage 10: Content Package Preparation ===")
    content_packages = []
    if selected:
        content_packages = prepare_content_packages(selected)
        if not content_packages:
            raise RuntimeError("Selected signals produced no content packages; publishing aborted")
        summary["content_packages"] = len(content_packages)
        summary["images_new"] = sum(p["images"].get("new_images", 0) for p in content_packages)
        summary["images_reused"] = sum(p["images"].get("reused_images", 0) for p in content_packages)

    publish_enabled = os.environ.get("NB_RESEARCH_PUBLISH_ENABLED", "false").lower() == "true"
    log.info("=== Stage 11: Live Publishing (enabled=%s) ===", publish_enabled)
    publish_reports = []
    if selected and content_packages and publish_enabled:
        publish_reports = publish_packages(selected, content_packages)
        summary["publish_reports"] = publish_reports
        failures = _publishing_failures(publish_reports)
        if failures:
            # Fail the Actions run visibly. Editorial generation is completed and saved,
            # but a blocked package must never look like a successful publication.
            raise RuntimeError("Live publishing blocked/failed: " + " | ".join(failures))
        if not publish_reports:
            raise RuntimeError("Publishing was enabled but produced no publish report")

    log.info("=== Stage 7: Sheets Sync ===")
    summary["sheet_sync"] = "success" if sync_to_sheets() else "failed"
    log.info("=== Stage 9: Archive ===")
    summary["archived"] = run_archive()
    summary["_content_packages"] = content_packages
    summary["_publish_reports"] = publish_reports
    return summary


def _print_summary(s: dict) -> None:
    print(f"\nNever Blank Signal Research — {s['date']}")
    print(f"Candidates found:      {s['candidates_found']}")
    print(f"New signals added:     {s['new_signals_added']}")
    print(f"Selected for content:  {s['selected_for_content']}")
    print(f"Duplicates skipped:    {s['duplicates_skipped']}")
    print(f"Sheet sync:            {s['sheet_sync']}")
    print(f"Archive moved:         {s['archived']}")
    for i, headline in enumerate(s.get("top_signals", []), 1):
        print(f"  {i}. {headline}")
    if s.get("_content_packages"):
        print(format_package_preview(s["_content_packages"]))
    if s.get("_publish_reports"):
        print(format_publish_summary(s["_publish_reports"]))


if __name__ == "__main__":
    result = run()
    _print_summary(result)
    Path("reports").mkdir(exist_ok=True)
    report_path = Path(f"reports/research_{result['date']}.json")
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2)
    log.info("Report saved: %s", report_path)
