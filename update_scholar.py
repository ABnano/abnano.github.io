#!/usr/bin/env python3
"""Fetch publication data from Google Scholar and update publications.json."""
import json
import sys
from datetime import datetime, timezone

SCHOLAR_ID = "J5UZz7sAAAAJ"

def fetch_with_scholarly():
    from scholarly import scholarly, ProxyGenerator
    pg = ProxyGenerator()
    pg.FreeProxies()
    scholarly.use_proxy(pg)

    author = scholarly.search_author_id(SCHOLAR_ID)
    author = scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])

    publications = []
    for i, pub in enumerate(author.get("publications", [])):
        try:
            filled = scholarly.fill(pub)
            bib = filled.get("bib", {})
            publications.append({
                "rank": i + 1,
                "title": bib.get("title", ""),
                "authors": bib.get("author", ""),
                "journal": bib.get("journal") or bib.get("booktitle") or bib.get("publisher") or "",
                "year": str(bib.get("pub_year", "")),
                "citations": filled.get("num_citations", 0),
                "url": filled.get("pub_url") or filled.get("eprint_url") or "",
                "badges": []
            })
        except Exception as e:
            print(f"Warning: could not fill pub {i}: {e}", file=sys.stderr)

    publications.sort(key=lambda x: x["citations"], reverse=True)
    for i, p in enumerate(publications):
        p["rank"] = i + 1

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total_citations": author.get("citedby", 0),
        "h_index": author.get("hindex", 0),
        "i10_index": author.get("i10index", 0),
        "publications": publications
    }

def load_existing():
    try:
        with open("publications.json") as f:
            return json.load(f)
    except Exception:
        return None

if __name__ == "__main__":
    print("Fetching from Google Scholar ...", file=sys.stderr)
    try:
        data = fetch_with_scholarly()
        with open("publications.json", "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Done: {len(data['publications'])} publications, {data['total_citations']} citations", file=sys.stderr)
    except Exception as e:
        print(f"Scholarly fetch failed: {e}", file=sys.stderr)
        existing = load_existing()
        if existing:
            existing["updated"] = datetime.now(timezone.utc).isoformat() + "_CACHED"
            with open("publications.json", "w") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            print("Kept existing cached data.", file=sys.stderr)
        else:
            print("No fallback data available.", file=sys.stderr)
            sys.exit(1)
