"""
Never Blank Pipeline — Content Generator (Phase 3 + Content Matrix + QC).

Generates a full content package for one topic:
  Topic → Content Matrix → Blog / LinkedIn / Instagram / Stories / Facebook / Threads / Telegram

With --qc: runs the full QC gate (voice + factuality + duplication),
rewrites on YELLOW, quarantines on ORANGE.

Does NOT publish anything. No publisher APIs are called.

Usage:
    python scripts/generate.py              # generate only
    python scripts/generate.py --qc         # generate + QC gate
    python scripts/generate.py --dry        # validate setup, no OpenAI calls
    python scripts/generate.py --topic-id 1 # force a specific manual topic
"""

import sys
import os
import json
import argparse
import dataclasses
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.utils.logger import get_logger
from src.utils.env_validator import validate
from src.internal.topic_prioritizer import get_next_topic
from src.internal.strategy import build_content_brief
from src.internal.memory import is_duplicate, get_embedding, save_embedding
from src.content.matrix import generate_content_matrix, matrix_to_dict
from src.content.generator import generate_content_package
from src.content.differentiation import check_differentiation, print_differentiation_report
from src.models import ContentBrief, ContentMatrix, ContentPackage, QCReport, QCCheckResult

log = get_logger("generate")

DRAFTS_DIR   = Path(__file__).parent.parent / "data" / "drafts"
LATEST_DIR   = DRAFTS_DIR / "latest"
ARCHIVE_ROOT = DRAFTS_DIR / date.today().isoformat()

SEP = "─" * 60


# ── Output helpers ─────────────────────────────────────────────────────────────

def _save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if dataclasses.is_dataclass(data):
        data = _brief_to_dict(data) if isinstance(data, ContentBrief) else dataclasses.asdict(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _brief_to_dict(brief: ContentBrief) -> dict:
    return {
        "title":                brief.title,
        "angle":                brief.angle,
        "hook":                 brief.hook,
        "content_goal":         brief.content_goal.value,
        "observation_statement": brief.observation_statement,
        "observation_type":     brief.observation_type.value,
        "platforms":            brief.platforms,
        "tone_notes":           brief.tone_notes,
        "source_signals":       brief.source_signals,
        "wix_slug":             brief.wix_slug,
        "wix_category_id":      brief.wix_category_id,
        "wix_tags":             brief.wix_tags,
        "observation_id":       brief.observation_id,
        "manual_topic_id":      brief.manual_topic_id,
    }


def save_package(pkg: ContentPackage, output_dir: Path) -> dict[str, Path]:
    """Save all content package outputs. Returns {label: path} map."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}

    # Content Matrix — saved first, it's the source of all platform content
    p = output_dir / "content_matrix.json"
    _save_json(p, matrix_to_dict(pkg.matrix))
    files["content_matrix"] = p

    # ContentBrief
    p = output_dir / "content_brief.json"
    _save_json(p, pkg.brief)
    files["content_brief"] = p

    # Blog post (Markdown)
    p = output_dir / "blog_post.md"
    _save_text(p, pkg.blog_body)
    files["blog_post"] = p

    # Blog meta
    p = output_dir / "blog_meta.json"
    _save_json(p, {
        "title":            pkg.blog_title,
        "meta_description": pkg.blog_meta_description,
        "hook_sentence":    pkg.blog_hook_sentence,
        "wix_slug":         pkg.brief.wix_slug,
        "wix_category_id":  pkg.brief.wix_category_id,
        "wix_tags":         pkg.brief.wix_tags,
    })
    files["blog_meta"] = p

    # LinkedIn
    p = output_dir / "linkedin.txt"
    _save_text(p, pkg.linkedin_text)
    files["linkedin"] = p

    # Instagram caption
    p = output_dir / "instagram.txt"
    hashtag_line = " ".join(f"#{h}" for h in pkg.instagram_hashtags)
    _save_text(p, pkg.instagram_caption + "\n\n" + hashtag_line)
    files["instagram"] = p

    # Instagram / Facebook Stories
    p = output_dir / "stories.json"
    _save_json(p, {"stories": pkg.stories_sequence})
    files["stories"] = p

    if pkg.stories_sequence is not None:
        p = output_dir / "stories_readable.txt"
        readable = "\n\n---\n\n".join(
            f"[Story {s.get('story_number', i+1)} — {s.get('type','').upper()}]\n"
            f"{s.get('text','')}\n"
            f"Sticker: {s.get('sticker_suggestion','none')}\n"
            f"Visual: {s.get('visual_note','')}"
            for i, s in enumerate(pkg.stories_sequence)
        )
        _save_text(p, readable)
        files["stories_readable"] = p

    # Facebook
    p = output_dir / "facebook.txt"
    _save_text(p, pkg.facebook_text)
    files["facebook"] = p

    # Threads
    p = output_dir / "threads.json"
    _save_json(p, {"sequence": pkg.threads_sequence})
    files["threads"] = p

    p = output_dir / "threads_readable.txt"
    _save_text(p, "\n\n---\n\n".join(
        f"[{i+1}/{len(pkg.threads_sequence)}]\n{post}"
        for i, post in enumerate(pkg.threads_sequence)
    ))
    files["threads_readable"] = p

    # Telegram
    if pkg.telegram_text is not None:
        p = output_dir / "telegram.txt"
        _save_text(p, pkg.telegram_text)
        files["telegram"] = p

    # Image prompt
    p = output_dir / "image_prompt.txt"
    _save_text(p, pkg.image_prompt)
    files["image_prompt"] = p

    # Metadata
    p = output_dir / "metadata.json"
    _save_json(p, {
        "generated_at":     pkg.generated_at,
        "title":            pkg.blog_title,
        "wix_slug":         pkg.brief.wix_slug,
        "observation_type": pkg.brief.observation_type.value,
        "content_goal":     pkg.brief.content_goal.value,
        "platforms":        pkg.brief.platforms,
        "manual_topic_id":  pkg.brief.manual_topic_id,
    })
    files["metadata"] = p

    return files


# ── QC helpers ─────────────────────────────────────────────────────────────────

def _qc_report_to_dict(report: QCReport) -> dict:
    return {
        "overall_status":    report.overall_status,
        "final_status":      report.final_status,
        "rewrite_count":     report.rewrite_count,
        "quarantined":       report.quarantined,
        "quarantine_reason": report.quarantine_reason,
        "quarantine_path":   report.quarantine_path,
        "generated_at":      report.generated_at,
        "checks": [
            {"check_name": c.check_name, "status": c.status, "score": c.score,
             "issues": c.issues, "guidance": c.guidance, "risk_level": c.risk_level,
             "legal_risk": c.legal_risk, "checked_at": c.checked_at}
            for c in report.checks
        ],
    }


def _print_qc_summary(report: QCReport) -> None:
    icons = {"GREEN": "✓", "YELLOW": "⚠", "ORANGE": "○", "RED": "✗"}
    icon  = icons.get(report.final_status, "?")
    print(f"\n  {icon}  QC final status: {report.final_status}")
    print(f"     Rewrites applied: {report.rewrite_count}")
    if report.quarantined:
        print(f"     Quarantined: {report.quarantine_path}")
    for c in report.checks:
        ci = "✓" if c.status == "green" else ("⚠" if c.status == "yellow" else "○")
        print(f"     {ci}  {c.check_name}: {c.status} (score={c.score:.2f})")
        for issue in c.issues[:2]:
            print(f"        → {issue[:80]}")


# ── Matrix report ──────────────────────────────────────────────────────────────

def _print_matrix_report(matrix: ContentMatrix) -> None:
    print(f"\n{SEP}")
    print("  Content Matrix")
    print(SEP)
    print(f"  hook_type:        {matrix.hook_type}")
    print(f"  primary_hook:     {matrix.primary_hook[:100]}")
    print(f"  mechanism:        {matrix.mechanism[:100]}")
    print(f"  cost_of_ignoring: {matrix.cost_of_ignoring[:100]}")
    print(f"  visual_anchor:    {matrix.visual_anchor}")
    print(f"  sales_angle:      {matrix.sales_angle[:100]}")
    print(f"  soft_cta:         {matrix.soft_cta[:100]}")
    print(f"  supporting_points: {len(matrix.supporting_points)} points")
    for i, p in enumerate(matrix.supporting_points, 1):
        print(f"    {i}. {p[:80]}")


# ── Sample outputs ─────────────────────────────────────────────────────────────

def _print_sample_outputs(pkg: ContentPackage) -> None:
    print(f"\n{SEP}")
    print("  Sample Platform Outputs")
    print(SEP)

    def _preview(label: str, text: str, chars: int = 160) -> None:
        t = (text or "").replace("\n", " ").strip()
        print(f"  [{label}]")
        print(f"  {t[:chars]}{'…' if len(t) > chars else ''}")
        print()

    _preview("Blog intro",   pkg.blog_body[:200] if pkg.blog_body else "")
    _preview("LinkedIn",     pkg.linkedin_text)
    _preview("Instagram",    pkg.instagram_caption)
    _preview("Facebook",     pkg.facebook_text)
    _preview("Threads [1]",  pkg.threads_sequence[0] if pkg.threads_sequence else "")
    _preview("Telegram",     pkg.telegram_text)
    if pkg.stories_sequence:
        s1 = pkg.stories_sequence[0]
        print(f"  [Stories — Story 1 ({s1.get('type','')})]\n  {s1.get('text','')[:160]}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def run(topic_id: str | None = None, dry: bool = False, with_qc: bool = False) -> None:
    print("\n╔══════════════════════════════════════════════════╗")
    print("║       Never Blank Pipeline — Content Generator   ║")
    mode_label = "Phase 3 + Matrix + QC" if with_qc else "Phase 3 + Matrix"
    print(f"║       {mode_label:<42}║")
    print("╚══════════════════════════════════════════════════╝\n")

    api_key_set = bool(os.environ.get("NB_OPENAI_API_KEY", "").strip())
    print(f"  {'✓' if api_key_set else '✗'}  NB_OPENAI_API_KEY {'set' if api_key_set else 'NOT SET'}")
    print(f"  ✓  Model: {os.environ.get('NB_OPENAI_CHAT_MODEL', '(not set — default gpt-4o)')}")

    if dry:
        topic = get_next_topic()
        if topic:
            brief = build_content_brief(topic)
            print(f"\n  [dry] Topic: {topic.title!r}")
            print(f"  [dry] Slug:  {brief.wix_slug}")
        else:
            print("\n  [dry] No pending topic in manual queue")
        print("\n  [dry] Matrix + platform generation requires OpenAI — not called in dry mode.")
        print(f"  [dry] Ready: {'YES' if api_key_set else 'NO (API key missing)'}")
        return

    if not api_key_set:
        print("\n  ✗  NB_OPENAI_API_KEY is not set.")
        sys.exit(1)

    # ── 1. Topic ───────────────────────────────────────────────────────────────
    print("\n  Loading topic...")
    topic = get_next_topic()
    if topic is None:
        print("  ✗  No topic available. Add rows to topics_manual.csv with status=pending.")
        sys.exit(1)
    print(f"  ✓  Topic: {topic.title!r}")
    print(f"     Source: {topic.source} | Goal: {topic.content_goal.value}")

    # ── 2. ContentBrief ────────────────────────────────────────────────────────
    brief = build_content_brief(topic)
    print(f"  ✓  Slug: {brief.wix_slug}")

    # ── 3. Deduplication ───────────────────────────────────────────────────────
    print("\n  Checking for semantic duplicates...")
    dedup_text = f"{brief.title} — {brief.angle}"
    is_dup, sim_score, matched_slug = is_duplicate(dedup_text)
    if is_dup:
        print(f"  ✗  Duplicate detected (similarity={sim_score:.4f}, matched={matched_slug!r})")
        sys.exit(1)
    print(f"  ✓  Not a duplicate (highest similarity: {sim_score:.4f})")

    # ── 4. Content Matrix ──────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Generating Content Matrix (1 OpenAI call)...")
    print(SEP)
    matrix = generate_content_matrix(brief)
    _print_matrix_report(matrix)

    # ── 5. Generate content ────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Generating platform content (7 OpenAI calls)...")
    print("  This may take 30–60 seconds...")
    print(SEP)

    pkg = generate_content_package(brief, matrix)

    print(f"  ✓  Blog post:      {len(pkg.blog_body)} chars")
    print(f"  ✓  LinkedIn:       {len(pkg.linkedin_text)} chars")
    print(f"  ✓  Instagram:      {len(pkg.instagram_caption)} chars + {len(pkg.instagram_hashtags)} hashtags")
    print(f"  ✓  Facebook:       {len(pkg.facebook_text)} chars")
    print(f"  ✓  Threads:        {len(pkg.threads_sequence)} posts")
    print(f"  {'✓' if pkg.telegram_text is not None else '—'}  Telegram:       {len(pkg.telegram_text) if pkg.telegram_text is not None else 'SKIPPED'}")
    print(f"  {'✓' if pkg.stories_sequence is not None else '—'}  Stories:        {len(pkg.stories_sequence) if pkg.stories_sequence is not None else 'SKIPPED'}")
    print(f"  ✓  Image prompt:   {len(pkg.image_prompt)} chars")

    # ── 6. Differentiation check ───────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Platform differentiation check...")
    print(SEP)
    diff_report = check_differentiation(pkg)
    print_differentiation_report(diff_report)

    # ── 7. QC gate (optional) ──────────────────────────────────────────────────
    qc_report: QCReport | None = None
    final_pkg = pkg

    if with_qc:
        print(f"\n{SEP}")
        print("  Running QC gate (voice + factuality + duplication)...")
        print(SEP)
        from src.quality.gate import run_qc
        final_pkg, qc_report = run_qc(pkg, brief)
        _print_qc_summary(qc_report)

        if qc_report.final_status == "RED":
            print("\n  ✗  QC RED — system failure. Check logs.")
            sys.exit(2)

        if qc_report.quarantined:
            print(f"\n  ○  Content quarantined — not saving to final/")
            save_package(final_pkg, LATEST_DIR)
            _save_json(LATEST_DIR / "qc_report.json", _qc_report_to_dict(qc_report))
            _save_json(LATEST_DIR / "differentiation_report.json", diff_report)
            return

    # ── 8. Save outputs ────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Saving outputs...")
    print(SEP)

    files = save_package(final_pkg, LATEST_DIR)

    if with_qc and qc_report and not qc_report.quarantined:
        save_package(final_pkg, LATEST_DIR / "final")
        _save_json(LATEST_DIR / "qc_report.json", _qc_report_to_dict(qc_report))
        print(f"  ✓  Approved content: data/drafts/latest/final/")

    archive_dir = ARCHIVE_ROOT / brief.wix_slug
    save_package(final_pkg, archive_dir)
    if qc_report:
        _save_json(archive_dir / "qc_report.json", _qc_report_to_dict(qc_report))

    # Save differentiation report
    _save_json(LATEST_DIR / "differentiation_report.json", diff_report)

    # Save embedding
    vec = get_embedding(dedup_text)
    save_embedding(dedup_text, vec, slug=brief.wix_slug, source="title+angle")

    # ── 9. Google Sheets export ────────────────────────────────────────────────
    if os.environ.get("NB_GOOGLE_SHEETS_CREDENTIALS_JSON") and os.environ.get("NB_GOOGLE_SHEET_ID"):
        print(f"\n{SEP}")
        print("  Exporting to Google Sheets (Content Matrix tab)...")
        print(SEP)
        try:
            from src.utils.google_sheets import write_content_matrix_row
            ok = write_content_matrix_row(
                matrix_to_dict(final_pkg.matrix),
                status="draft" if not with_qc else (qc_report.final_status if qc_report else "draft"),
            )
            if ok:
                print("  ✓  Content Matrix row written to Google Sheet")
            else:
                print("  ○  Google Sheets write failed — check logs")
        except Exception as exc:
            print(f"  ○  Google Sheets export skipped: {exc.__class__.__name__}: {str(exc)[:60]}")
    else:
        print("  ○  Google Sheets credentials not set — skipping export")

    # ── 10. Sample outputs ─────────────────────────────────────────────────────
    _print_sample_outputs(final_pkg)

    # ── 11. Summary ────────────────────────────────────────────────────────────
    print(f"{SEP}")
    print(f"  Topic:             {final_pkg.blog_title!r}")
    print(f"  Slug:              {brief.wix_slug}")
    print(f"  Generated at:      {final_pkg.generated_at}")
    print(f"  Hook type:         {matrix.hook_type}")
    print(f"  Primary hook:      {matrix.primary_hook[:80]}")
    print(f"  Cost of ignoring:  {matrix.cost_of_ignoring[:80]}")
    print(f"  Sales angle:       {matrix.sales_angle[:80]}")
    print(f"  Visual anchor:     {matrix.visual_anchor}")
    print(f"  Differentiation:   {'✓ PASS' if diff_report['ok'] else '⚠ ' + str(diff_report['pairs_flagged']) + ' pairs flagged'}")
    if qc_report:
        print(f"  QC status:         {qc_report.final_status} (rewrites: {qc_report.rewrite_count})")
    print(f"  Output:            data/drafts/latest/")
    if with_qc and qc_report and not qc_report.quarantined:
        print(f"  Approved:          data/drafts/latest/final/")
    print()
    print("  Next step: review drafts → python scripts/generate_image.py --upload → python scripts/publish.py --live")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", help="Force a specific manual topic ID")
    parser.add_argument("--dry",      action="store_true", help="Validate setup, no OpenAI calls")
    parser.add_argument("--qc",       action="store_true", help="Run QC gate after generation")
    args = parser.parse_args()
    run(topic_id=args.topic_id, dry=args.dry, with_qc=args.qc)
