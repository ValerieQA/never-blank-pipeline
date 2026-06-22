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


def _llm_filter_candidates(items: list[dict], categories: list[str], avoid: list[str]) -> list[dict]:
    if not items:
        return []

    batch_text = "\n\n".join(
        f"[{i}] HEADLINE: {it['title']}\nDATE: {it['published']}\nURL: {it['link']}\nSUMMARY: {it['summary'][:300]}"
        for i, it in enumerate(items)
    )

    system = f"""You are a business signal analyst for Never Blank, a content strategy practice for founders.

Evaluate each news item. Select only genuine BUSINESS SIGNALS:
- Real economic, operational, or behavioral shift businesses must respond to
- Contains or implies measurable data, observable trend, or identifiable business behavior
- Relevant to: {', '.join(categories)}
- AVOID: {', '.join(avoid)}

For each selected item return a JSON object with:
- index: integer (from the input)
- HEADLINE: string
- SOURCE_URL: string (from URL field)
- SOURCE_DATE: string (YYYY-MM-DD)
- REGION: "US" / "Global" / "EU" / infer from context
- INDUSTRY: main industry
- SIGNAL_TYPE: one of the signal categories
- raw_summary: 2-3 sentence factual summary
- discovery_confidence: "high" / "medium" / "low"

Return JSON array. Skip opinion, general AI news without specifics, and motivational content."""

    user = f"Evaluate these {len(items)} news items:\n\n{batch_text}"

    try:
        raw = chat(system, user, json_mode=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            parsed = parsed.get("signals", parsed.get("items", list(parsed.values())[0] if parsed else []))
        return parsed if isinstance(parsed, list) else []
    except Exception as exc:
        log.error("LLM filter failed: %s", exc)
        return []


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
        idx = entry.get("index", -1)
        src = new_items[idx] if isinstance(idx, int) and 0 <= idx < len(new_items) else {}
        source_url = entry.get("SOURCE_URL") or src.get("link", "")
        headline   = entry.get("HEADLINE") or src.get("title", "")
        candidates.append({
            "SIGNAL_ID":            make_signal_id(source_url, headline),
            "DATE_FOUND":           today,
            "SOURCE_DATE":          entry.get("SOURCE_DATE") or src.get("published", today),
            "SOURCE_NAME":          src.get("SOURCE_NAME", ""),
            "SOURCE_URL":           source_url,
            "HEADLINE":             headline,
            "REGION":               entry.get("REGION", "US"),
            "INDUSTRY":             entry.get("INDUSTRY", ""),
            "SIGNAL_TYPE":          entry.get("SIGNAL_TYPE", ""),
            "raw_summary":          entry.get("raw_summary", ""),
            "discovery_confidence": entry.get("discovery_confidence", "medium"),
        })

    return candidates


if __name__ == "__main__":
    seen_path = Path("data/research/seen_index.json")
    seen = set(json.load(open(seen_path)).keys()) if seen_path.exists() else set()
    results = run_discovery(seen)
    print(json.dumps(results, indent=2))
