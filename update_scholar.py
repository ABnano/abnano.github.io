#!/usr/bin/env python3
"""
Fetch publication data from Google Scholar and update publications.json.
Strategy: try scholarly first (most complete), fall back to direct HTML scrape.
Runs daily in GitHub Actions.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

SCHOLAR_ID = os.environ.get("SCHOLAR_ID", "J5UZz7sAAAAJ")
SCHOLAR_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en&view_op=list_works&sortby=citations&pagesize=100"

BADGE_MAP = {
    "surface potential tuned":                ["Hot Article"],
    "deep learning enabled perceptive":       ["Hot Article"],
    "deep learning enabled early predicting": ["Hot Article"],
    "programmable polymeric-interface":       ["Journal Cover"],
    "programmable polymeric‑interface":  ["Journal Cover"],
    "ai-enabled wearable sensor for real":    ["Invited"],
}

def assign_badges(title: str, existing_badges: list) -> list:
    if existing_badges:
        return existing_badges
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
    if not existing:
        return {}
    return {p["title"].lower(): p.get("badges", []) for p in existing.get("publications", [])}

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Strategy 1: scholarly library ──────────────────────────────────────────
def fetch_via_scholarly(badge_lookup: dict) -> dict:
    from scholarly import scholarly
    print("Trying scholarly (direct, no proxy)...", file=sys.stderr)
    author = scholarly.search_author_id(SCHOLAR_ID)
    author = scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])
    print(f"  {author.get('name')} | {author.get('citedby')} citations | h={author.get('hindex')}", file=sys.stderr)

    publications = []
    pubs = author.get("publications", [])
    for i, pub in enumerate(pubs):
        try:
            filled = scholarly.fill(pub)
            bib = filled.get("bib", {})
            title = bib.get("title", "")
            citations = filled.get("num_citations", 0)
            url = filled.get("pub_url") or filled.get("eprint_url") or ""
            badges = assign_badges(title, badge_lookup.get(title.lower(), []))
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
            print(f"  [{i+1}/{len(pubs)}] {title[:55]}... ({citations})", file=sys.stderr)
            if i > 0 and i % 5 == 0:
                time.sleep(1)
        except Exception as e:
            print(f"  Warning pub {i}: {e}", file=sys.stderr)

    publications.sort(key=lambda x: x["citations"], reverse=True)
    for i, p in enumerate(publications):
        p["rank"] = i + 1

    return {
        "updated": now_utc(),
        "total_citations": author.get("citedby", 0),
        "h_index": author.get("hindex", 0),
        "i10_index": author.get("i10index", 0),
        "publications": publications,
    }

# ── Strategy 2: direct HTML scrape ─────────────────────────────────────────
def fetch_via_scrape(badge_lookup: dict) -> dict:
    import requests
    from html import unescape

    print("Trying direct HTML scrape...", file=sys.stderr)
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(SCHOLAR_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # Extract summary metrics
    def find_metric(label):
        pat = rf'<td class="gsc_rsb_std">(\d+)</td>\s*<td[^>]*>(\d+)</td>\s*</tr>\s*<tr[^>]*>\s*<td[^>]*>{re.escape(label)}'
        m = re.search(pat, html)
        if m:
            return int(m.group(1))
        # simpler fallback
        m2 = re.search(rf'{re.escape(label)}.*?<td[^>]*>(\d+)</td>', html, re.DOTALL)
        return int(m2.group(1)) if m2 else 0

    # Citations, h-index, i10-index are in a stats table
    cit_matches = re.findall(r'<td class="gsc_rsb_std">(\d+)</td>', html)
    total_cit = int(cit_matches[0]) if len(cit_matches) >= 1 else 0
    h_index   = int(cit_matches[2]) if len(cit_matches) >= 3 else 0
    i10_index = int(cit_matches[4]) if len(cit_matches) >= 5 else 0
    print(f"  Citations={total_cit}, h={h_index}, i10={i10_index}", file=sys.stderr)

    # Extract publications
    pub_blocks = re.findall(
        r'<tr class="gsc_a_tr">(.*?)</tr>',
        html, re.DOTALL
    )
    publications = []
    for i, block in enumerate(pub_blocks):
        title_m   = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', block, re.DOTALL)
        authors_m = re.search(r'class="gs_gray">(.*?)</div>', block, re.DOTALL)
        journal_m = re.findall(r'class="gs_gray">(.*?)</div>', block, re.DOTALL)
        cite_m    = re.search(r'class="gsc_a_ac[^"]*">(?:Cited by )?(\d*)</a>', block)
        year_m    = re.search(r'class="gsc_a_y"[^>]*><span[^>]*>(\d{4})</span>', block)
        link_m    = re.search(r'href="(/citations\?view_op=view_citation[^"]+)"', block)

        title   = unescape(re.sub(r'<[^>]+>', '', title_m.group(1))).strip() if title_m else ""
        authors = unescape(re.sub(r'<[^>]+>', '', journal_m[0])).strip() if journal_m else ""
        journal = unescape(re.sub(r'<[^>]+>', '', journal_m[1])).strip() if len(journal_m) > 1 else ""
        cites   = int(cite_m.group(1)) if cite_m and cite_m.group(1) else 0
        year    = year_m.group(1) if year_m else ""
        url     = ("https://scholar.google.com" + unescape(link_m.group(1))) if link_m else ""
        badges  = assign_badges(title, badge_lookup.get(title.lower(), []))

        if title:
            publications.append({
                "rank": i + 1,
                "title": title,
                "authors": authors,
                "journal": journal,
                "year": year,
                "citations": cites,
                "url": url,
                "badges": badges,
            })
            print(f"  [{i+1}] {title[:55]}... ({cites})", file=sys.stderr)

    publications.sort(key=lambda x: x["citations"], reverse=True)
    for i, p in enumerate(publications):
        p["rank"] = i + 1

    return {
        "updated": now_utc(),
        "total_citations": total_cit,
        "h_index": h_index,
        "i10_index": i10_index,
        "publications": publications,
    }

# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Scholar ID: {SCHOLAR_ID}", file=sys.stderr)
    existing   = load_existing()
    badge_lookup = existing_badge_map(existing)
    data = None

    # Try scholarly first, fall back to direct scrape
    for strategy_name, strategy_fn in [
        ("scholarly", lambda: fetch_via_scholarly(badge_lookup)),
        ("html-scrape", lambda: fetch_via_scrape(badge_lookup)),
    ]:
        try:
            data = strategy_fn()
            if data and data.get("publications"):
                print(f"\nSuccess via {strategy_name}: {len(data['publications'])} pubs | {data['total_citations']} cites", file=sys.stderr)
                break
        except Exception as e:
            print(f"{strategy_name} failed: {e}", file=sys.stderr)

    if data and data.get("publications"):
        with open("publications.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved publications.json: {len(data['publications'])} publications, {data['total_citations']} citations, h={data['h_index']}, i10={data['i10_index']}", file=sys.stderr)
    else:
        print("All strategies failed — keeping existing cached data.", file=sys.stderr)
        if existing:
            existing["updated"] = now_utc() + "_CACHED"
            with open("publications.json", "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        sys.exit(0)  # don't break CI on cache hit
