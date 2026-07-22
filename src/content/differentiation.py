"""
Platform differentiation checker.

Compares all platform outputs using Jaccard word-level similarity.
Flags pairs that are too similar and provides a human-readable report.
No external API calls — pure text comparison.
"""

from src.models import ContentPackage
from src.utils.logger import get_logger

log = get_logger("differentiation")

SIMILARITY_THRESHOLD = 0.45   # word-level Jaccard — above this = too similar
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "be", "been", "have", "has",
    "do", "does", "not", "that", "this", "it", "its", "you", "your", "we",
    "our", "they", "their", "i", "my", "will", "can", "if", "as", "by",
    "from", "when", "what", "which", "who", "how", "all", "so", "more",
    "about", "than", "up", "out", "no", "would", "should", "could",
}


def _word_set(text: str) -> set[str]:
    words = set(text.lower().replace("\n", " ").split())
    return words - STOPWORDS


def jaccard(a: str, b: str) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _platform_texts(pkg: ContentPackage) -> dict[str, str]:
    """Extract comparable text for each platform. Skipped channels (None) are excluded."""
    texts = {
        "blog_intro": " ".join(pkg.blog_body.split()[:80]),   # first ~80 words only
        "linkedin":   pkg.linkedin_text,
        "instagram":  pkg.instagram_caption,
        "facebook":   pkg.facebook_text,
        "threads":    " ".join(pkg.threads_sequence) if pkg.threads_sequence else "",
    }
    if pkg.telegram_text is not None:
        texts["telegram"] = pkg.telegram_text
    return {k: v for k, v in texts.items() if v}


def check_differentiation(pkg: ContentPackage) -> dict:
    """
    Run pairwise Jaccard similarity across all platform outputs.
    Returns a differentiation report dict.
    """
    texts    = _platform_texts(pkg)
    platforms = list(texts.keys())
    pairs    = []
    flags    = []

    for i in range(len(platforms)):
        for j in range(i + 1, len(platforms)):
            p1, p2 = platforms[i], platforms[j]
            sim    = jaccard(texts[p1], texts[p2])
            entry  = {
                "platform_a": p1,
                "platform_b": p2,
                "similarity": round(sim, 3),
                "ok":         sim < SIMILARITY_THRESHOLD,
            }
            pairs.append(entry)
            if sim >= SIMILARITY_THRESHOLD:
                flags.append(entry)
                log.warning(
                    "Differentiation flag: %s ↔ %s similarity=%.3f (threshold=%.2f)",
                    p1, p2, sim, SIMILARITY_THRESHOLD,
                )

    ok          = len(flags) == 0
    unique_count = sum(1 for p in pairs if p["ok"])
    total_pairs  = len(pairs)

    report = {
        "ok":                ok,
        "threshold":         SIMILARITY_THRESHOLD,
        "pairs_checked":     total_pairs,
        "pairs_ok":          unique_count,
        "pairs_flagged":     len(flags),
        "flagged":           flags,
        "all_pairs":         pairs,
        "summary":           _summarize(ok, flags, platforms),
    }

    return report


def _summarize(ok: bool, flags: list[dict], platforms: list[str]) -> str:
    if ok:
        return (
            f"All {len(platforms)} platforms are sufficiently differentiated. "
            f"No similarity above {SIMILARITY_THRESHOLD:.0%} threshold."
        )
    problems = "; ".join(
        f"{f['platform_a']} ↔ {f['platform_b']} ({f['similarity']:.0%})"
        for f in flags
    )
    return f"Similarity flags: {problems}. These platforms may need differentiation review."


def print_differentiation_report(report: dict) -> None:
    """Print a human-readable differentiation report to stdout."""
    status = "✓ PASS" if report["ok"] else "⚠ REVIEW"
    print(f"\n  Differentiation check: {status}")
    print(f"  Threshold: {report['threshold']:.0%} Jaccard similarity")
    print(f"  Pairs checked: {report['pairs_checked']}  |  Flagged: {report['pairs_flagged']}")
    print()
    for p in report["all_pairs"]:
        icon = "✓" if p["ok"] else "⚠"
        print(f"    {icon}  {p['platform_a']:12s} ↔ {p['platform_b']:12s}  {p['similarity']:.0%}")
    if not report["ok"]:
        print()
        print(f"  Summary: {report['summary']}")
