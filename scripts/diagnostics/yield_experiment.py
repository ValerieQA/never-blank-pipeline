"""Read-only diagnostic: does the source change or the selector change explain
the post-2026-07-21 yield collapse? (Story #21)

Two changes shipped the same day, so correlation cannot separate them. This
runs the two cells that can:

    V2 = new sources + old selector
    V3 = old sources + new selector

against one fixed corpus fetched once. V4 (both new) is production and already
measured; V1 (both old) is not needed to separate the hypotheses.

Nothing here writes canonical state. It does not touch signals_active.jsonl,
selected_signals.jsonl, seen_index.json or published_signal_ids.txt, does not
publish, does not commit, and does not modify the active configuration — the
historical variant is read out of git history into memory. Output goes to a
diagnostics directory that is uploaded as an artifact and never committed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

from scripts.research.discover import (
    _fetch_rss,
    _llm_filter_candidates,
    make_signal_id,
)

OUT = Path("diagnostics")
ACTIVE_CONFIG = Path("config/research_sources.yaml")

#: The two commits that changed each dimension on 2026-07-21. Their parents
#: carry the pre-change state, which is where the historical variant is read
#: from — git history, never a hand-written copy.
SOURCES_CHANGE = "218719a"
SELECTOR_CHANGE = "a557855"


def _config_at(ref: str) -> dict:
    """Read a configuration revision out of git history, into memory only."""

    blob = subprocess.run(
        ["git", "show", f"{ref}:{ACTIVE_CONFIG}"],
        capture_output=True, text=True, check=True,
    ).stdout
    return yaml.safe_load(blob)


def _fetch(feeds: list[dict], lookback: int) -> list[dict]:
    items = []
    for source in feeds:
        fetched = _fetch_rss(source["url"], lookback)
        for it in fetched:
            it["SOURCE_NAME"] = source["name"]
            it["_feed"] = source["name"]
        print(f"    {source['name']:32} {len(fetched):>3} items")
        items.extend(fetched)
    return items


def _identity(item: dict) -> str:
    return make_signal_id(item.get("link", ""), item.get("title", ""))


def _classify(selected: list[dict]) -> dict:
    """Run the corrected classifier over what each variant selected."""

    from scripts.research.angles import generate_angles

    counts: dict[str, int] = {}
    for entry in selected:
        try:
            audience = generate_angles(entry).get("TARGET_AUDIENCE", "unclassified")
        except Exception:                      # a classifier failure is not a label
            audience = "unclassified"
        counts[audience] = counts.get(audience, 0) + 1
    return counts


def _run_variant(name: str, corpus: list[dict], feeds: list[dict],
                 categories: list[str], avoid: list[str], cap: int) -> dict:
    """One cell of the experiment, over the shared corpus."""

    eligible_feeds = {f["name"] for f in feeds}
    eligible = [i for i in corpus if i["_feed"] in eligible_feeds]
    evaluated = eligible[:cap]

    print(f"\n  {name}: eligible={len(eligible)} evaluated={len(evaluated)} "
          f"truncated={len(eligible) - len(evaluated)}")

    selected = _llm_filter_candidates(evaluated, categories, avoid)
    selected_ids = {
        make_signal_id(e.get("SOURCE_URL", ""), e.get("HEADLINE", "")) for e in selected
    }

    # Where did the selections sit in the evaluation order? Only meaningful
    # within the evaluated window; anything past the cap was never offered.
    positions = [
        idx for idx, item in enumerate(eligible)
        if _identity(item) in {_identity(i) for i in evaluated}
        and any(e.get("HEADLINE", "") == item.get("title", "") for e in selected)
    ]

    # The same selector, run over what the cap excluded — observation only,
    # to see whether selectable material exists beyond position 30.
    beyond = eligible[cap:]
    beyond_selected = _llm_filter_candidates(beyond, categories, avoid) if beyond else []

    result = {
        "variant": name,
        "source_eligible": len(eligible),
        "evaluated": len(evaluated),
        "truncated": len(eligible) - len(evaluated),
        "selected": len(selected),
        "selection_rate": round(len(selected) / len(evaluated), 4) if evaluated else None,
        "selected_within_first_cap": len(selected),
        "selected_beyond_cap": len(beyond_selected),
        "selected_positions": positions,
        "audience_counts": _classify(selected),
        "audience_counts_beyond_cap": _classify(beyond_selected),
        "selector_exposes_reasons": False,
    }
    print(f"    selected={result['selected']} "
          f"beyond_cap_selected={result['selected_beyond_cap']} "
          f"audiences={result['audience_counts']}")
    return result


def main() -> int:
    OUT.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    current = yaml.safe_load(ACTIVE_CONFIG.read_text())
    old_sources_cfg = _config_at(f"{SOURCES_CHANGE}^")
    old_selector_cfg = _config_at(f"{SELECTOR_CHANGE}^")

    cap = current.get("max_candidates", 30)
    lookback = current.get("lookback_hours", 72)

    new_feeds = current["rss_feeds"]
    old_feeds = old_sources_cfg["rss_feeds"]

    print("Fetching NEW portfolio:")
    corpus = _fetch(new_feeds, lookback)
    print("Fetching OLD portfolio:")
    corpus += _fetch(old_feeds, lookback)

    # One fixed corpus, deduplicated by canonical identity. Both variants draw
    # their eligible subsets from exactly this set.
    seen: set[str] = set()
    fixed: list[dict] = []
    for item in corpus:
        ident = _identity(item)
        if ident in seen:
            continue
        seen.add(ident)
        item["_identity"] = ident
        fixed.append(item)

    print(f"\nFixed corpus: {len(fixed)} unique items "
          f"(cap={cap}, so {max(0, len(fixed) - cap)} would be truncated)")

    (OUT / "corpus.json").write_text(json.dumps({
        "captured_at": now,
        "size": len(fixed),
        "max_candidates": cap,
        "items": [
            {
                "identity": i["_identity"],
                "feed": i["_feed"],
                "title": i.get("title", ""),
                "url": i.get("link", ""),
                "published": str(i.get("published", "")),
            }
            for i in fixed
        ],
    }, indent=2))

    v2 = _run_variant(
        "V2 new sources + OLD selector", fixed, new_feeds,
        old_selector_cfg["signal_categories"], old_selector_cfg["avoid_categories"], cap,
    )
    v3 = _run_variant(
        "V3 OLD sources + new selector", fixed, old_feeds,
        current["signal_categories"], current["avoid_categories"], cap,
    )

    summary = {
        "captured_at": now,
        "corpus_size": len(fixed),
        "max_candidates": cap,
        "variants": [v2, v3],
        "note": (
            "The selector returns a selection, not a rationale, so no "
            "per-item rejection reason is available and none is invented."
        ),
    }
    (OUT / "v2.json").write_text(json.dumps(v2, indent=2))
    (OUT / "v3.json").write_text(json.dumps(v3, indent=2))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary["variants"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
