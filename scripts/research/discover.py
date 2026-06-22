"""
Stage 1 — Discovery.
Fetch RSS feeds, filter by signal categories, return lightweight candidate list.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat

log = get_logger("research.discover")

SOURCES_CONFIG = Path("config/research_sources.yaml")


def _load_sources() -> dict:
    with open(SOURCES_CONFIG) as f:
        return yaml.safe_load(f)


def _normalize_url(url: str) -> str:
    url = re.sub(r"[?&](utm_[^&]+|source=[^&]+|ref=[^&]+)", "", url)
    url = url.rstrip("&?")
    return url.lower().strip()


def make_signal_id(url: str, headline: str) -> str:
    key = _normalize_url(url) + "|" + headline.lower().strip()
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _fetch_rss(feed_url: str, lookback_hours: int) -> list[dict]:
    try:
        resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "NeverBlank/1.0"})
        resp.raise_for_status()
    except Exception as exc:
        log.warning("RSS fetch failed %s: %s", feed_url, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    items = []

    try:
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
        for item in entries:
            title = (item.findtext("title") or item.findtext("atom:title", namespaces=ns) or "").strip()
            link  = (item.findtext("link") or item.findtext("atom:link", namespaces=ns) or "").strip()
            pub   = (item.findtext("pubDate") or item.findtext("atom:published", namespaces=ns) or "")
            summ  = (item.findtext("description") or item.findtext("atom:summary", namespaces=ns) or "").strip()

            if not title or not link:
                continue

            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
                pub_str = pub_dt.strftime("%Y-%m-%d")
            except Exception:
                pub_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            items.append({
                "title":     title,
                "link":      _normalize_url(link),
                "published": pub_str,
                "summary":   re.sub(r"<[^>]+>", "", summ)[:500],
            })

    except ET.ParseError as exc:
        log.warning("RSS parse error %s: %s", feed_url, exc)

    return items


def _llm_select_indices(items: list[dict], categories: list[str], avoid: list[str]) -> list[int]:
    """Ask LLM to return indices of relevant items. Avoids JSON array parsing issues."""
    batch_text = "\n".join(
        f"[{i}] {it['title']} | {it.get('summary', '')[:150]}"
        for i, it in enumerate(items)
    )
    system = f"""You are a business signal analyst for Never Blank, a content strategy practice for founders.

Select news items that represent genuine business signals:
- Economic, operational, or behavioral shift businesses must respond to
- Relevant to: {', '.join(categories)}
- Avoid: {', '.join(avoid)}

Be inclusive — prefer false positives over missed signals.

Respond with ONLY a JSON object in this exact format:
{{"selected": [0, 3, 7, 12]}}

Where the numbers are indices from the input list. If nothing qualifies, return {{"selected": []}}."""

    user = f"Select relevant items from this list:\n\n{batch_text}"

    try:
        raw = chat(system, user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            indices = parsed.get("selected", [])
            if isinstance(indices, list):
                return [int(i) for i in indices if isinstance(i, (int, float))]
        log.warning("LLM index selection returned unexpected format: %s", str(raw)[:150])
        return []
    except Exception as exc:
        log.error("LLM index selection failed: %s", exc)
        return []


def _llm_enrich_candidates(items: list[dict], categories: list[str]) -> list[dict]:
    """Enrich selected items with signal metadata via LLM."""
    if not items:
        return []

    batch_text = "\n\n".join(
        f"[{i}] HEADLINE: {it['title']}\nDATE: {it['published']}\nURL: {it['link']}\nSUMMARY: {it.get('summary','')[:400]}"
        for i, it in enumerate(items)
    )
    system = f"""You are a business signal analyst. Enrich these news items with signal metadata.

For each item return a JSON object with:
- index: integer (from input)
- REGION: "US" / "Global" / "EU"
- INDUSTRY: main industry
- SIGNAL_TYPE: one of [{', '.join(categories)}]
- raw_summary: 2-3 sentence factual business summary
- discovery_confidence: "high" / "medium" / "low"

Respond with: {{"signals": [{{...}}, {{...}}]}}"""

    user = f"Enrich these {len(items)} items:\n\n{batch_text}"

    try:
        raw = chat(system, user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception as exc:
        log.error("LLM enrichment failed: %s", exc)
        return []


def _llm_filter_candidates(items: list[dict], categories: list[str], avoid: list[str]) -> list[dict]:
    if not items:
        return []

    # Step 1: get indices of relevant items (simple, reliable)
    indices = _llm_select_indices(items, categories, avoid)
    if not indices:
        log.info("LLM selected 0 items from %d candidates", len(items))
        return []

    selected_items = [items[i] for i in indices if i < len(items)]
    log.info("LLM selected %d items by index: %s", len(selected_items), indices)

    # Step 2: enrich selected items with signal metadata
    enriched = _llm_enrich_candidates(selected_items, categories)

    # Map enriched metadata back onto selected items
    meta_by_idx = {e.get("index", i): e for i, e in enumerate(enriched)}
    result = []
    for local_idx, item in enumerate(selected_items):
        meta = meta_by_idx.get(local_idx, {})
        result.append({
            "index":               indices[local_idx] if local_idx < len(indices) else local_idx,
            "HEADLINE":            item["title"],
            "SOURCE_URL":          item["link"],
            "SOURCE_DATE":         item["published"],
            "REGION":              meta.get("REGION", "US"),
            "INDUSTRY":            meta.get("INDUSTRY", ""),
            "SIGNAL_TYPE":         meta.get("SIGNAL_TYPE", ""),
            "raw_summary":         meta.get("raw_summary", item.get("summary", "")[:300]),
            "discovery_confidence": meta.get("discovery_confidence", "medium"),
            "SOURCE_NAME":         item.get("SOURCE_NAME", ""),
        })
    return result


def run_discovery(seen_ids: set) -> list[dict]:
    cfg      = _load_sources()
    lookback = cfg.get("lookback_hours", 72)
    cats     = cfg.get("signal_categories", [])
    avoid    = cfg.get("avoid_categories", [])
    max_cand = cfg.get("max_candidates", 30)

    all_items: list[dict] = []
    for source in cfg.get("rss_feeds", []):
        items = _fetch_rss(source["url"], lookback)
        for it in items:
            it["SOURCE_NAME"] = source["name"]
        all_items.extend(items)
        log.info("Fetched %d items from %s", len(items), source["name"])

    log.info("Total RSS items: %d", len(all_items))

    new_items = []
    for it in all_items:
        sid = make_signal_id(it["link"], it["title"])
        if sid not in seen_ids:
            it["_candidate_id"] = sid
            new_items.append(it)

    log.info("Unseen items: %d", len(new_items))
    if not new_items:
        return []

    filtered = _llm_filter_candidates(new_items[:max_cand], cats, avoid)
    log.info("LLM selected %d candidates", len(filtered))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidates = []
    for entry in filtered:
        source_url = entry.get("SOURCE_URL", "")
        headline   = entry.get("HEADLINE", "")
        if not source_url or not headline:
            continue
        entry["SIGNAL_ID"]  = make_signal_id(source_url, headline)
        entry["DATE_FOUND"] = today
        entry.pop("index", None)
        entry.pop("_candidate_id", None)
        candidates.append(entry)

    return candidates


if __name__ == "__main__":
    seen_path = Path("data/research/seen_index.json")
    seen = set(json.load(open(seen_path)).keys()) if seen_path.exists() else set()
    results = run_discovery(seen)
    print(json.dumps(results, indent=2))
