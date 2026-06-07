#!/usr/bin/env python3
"""
Fetch publication data from Google Scholar and update publications.json.
Runs in GitHub Actions daily. Preserves badge metadata from existing data.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

SCHOLAR_ID = os.environ.get("SCHOLAR_ID", "J5UZz7sAAAAJ")

# Badges assigned by hand — keyed by partial lowercase title match
BADGE_MAP = {
    "surface potential tuned":                ["Hot Article"],
    "deep learning enabled perceptive":       ["Hot Article"],
    "deep learning enabled early predicting": ["Hot Article"],
    "programmable polymeric-interface":       ["Journal Cover"],
    "ai-enabled wearable sensor for real":    ["Invited"],
    "machine learning-aided all-organic":     [],
}

def assign_badges(title: str) -> list:
    t = title.lower()
    for key, badges in BADGE_MAP.items():
        if key in t:
            return badges
    return []

def load_existing() -> dict | None:
    try:
        with open("publications.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def existing_badge_map(existing: dict) -> dict:
    """Build title → badges map from existing data so we don't lose manual badges."""
    if not existing:
        return {}
    return {p["title"].lower(): p.get("badges", []) for p in existing.get("publications", [])}

def fetch_with_scholarly() -> dict:
    from scholarly import scholarly

    print("Connecting to Google Scholar (no proxy — GitHub Actions IP)...", file=sys.stderr)
    author = scholarly.search_author_id(SCHOLAR_ID)
    author = scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])
    print(f"Author: {author.get('name')} | Citations: {author.get('citedby')} | h-index: {author.get('hindex')}", file=sys.stderr)

    existing = load_existing()
    badge_lookup = existing_badge_map(existing)

    publications = []
    pubs = author.get("publications", [])
    print(f"Filling {len(pubs)} publications...", file=sys.stderr)

    for i, pub in enumerate(pubs):
        try:
            filled = scholarly.fill(pub)
            bib = filled.get("bib", {})
            title = bib.get("title", "")
            citations = filled.get("num_citations", 0)
            url = filled.get("pub_url") or filled.get("eprint_url") or ""

            # Restore badges: prefer existing data, fall back to keyword map
            badges = badge_lookup.get(title.lower()) or assign_badges(title)

            publications.append({
                "rank": i + 1,
                "title": title,
                "authors": bib.get("author", ""),
                "journal": (bib.get("journal") or bib.get("booktitle") or bib.get("publisher") or "").strip(),
                "year": str(bib.get("pub_year", "")),
                "citations": citations,
                "url": url,
                "badges": badges,
            })
            print(f"  [{i+1}/{len(pubs)}] {title[:60]}... ({citations} cites)", file=sys.stderr)

            # Be polite — avoid triggering Scholar rate-limit
            if i > 0 and i % 5 == 0:
                time.sleep(1)

        except Exception as e:
            print(f"  Warning: could not fill pub {i}: {e}", file=sys.stderr)

    publications.sort(key=lambda x: x["citations"], reverse=True)
    for i, p in enumerate(publications):
        p["rank"] = i + 1

    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_citations": author.get("citedby", 0),
        "h_index": author.get("hindex", 0),
        "i10_index": author.get("i10index", 0),
        "publications": publications,
    }

if __name__ == "__main__":
    print(f"Scholar ID: {SCHOLAR_ID}", file=sys.stderr)

    try:
        data = fetch_with_scholarly()
        with open("publications.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(
            f"\nDone: {len(data['publications'])} publications | "
            f"{data['total_citations']} citations | "
            f"h={data['h_index']} | i10={data['i10_index']}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"\nScholarly fetch failed: {e}", file=sys.stderr)
        existing = load_existing()
        if existing:
            # Stamp as cached so the UI can show it
            existing["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "_CACHED"
            with open("publications.json", "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            print("Kept existing cached data.", file=sys.stderr)
            sys.exit(0)   # don't fail the CI — cached data is acceptable
        else:
            print("No fallback data available.", file=sys.stderr)
            sys.exit(1)
