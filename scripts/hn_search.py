#!/usr/bin/env python3
"""Search Hacker News Algolia API for agent-related articles in a specific date range."""

import json
import sys
import requests

QUERIES = [
    ("agent-friendly open source", "agent-friendly+open+source"),
    ("MCP integration AI agent", "MCP+integration+AI+agent"),
    ("open source agent API", "open+source+agent+API"),
    ("machine readable license", "machine+readable+license"),
    ("OpenCode ecosystem toolkit", "OpenCode+ecosystem+toolkit"),
    ("Apache FSF Eclipse license proposal", "Apache+FSF+Eclipse+license+proposal"),
    ("AI agent open source", "AI+agent+open+source"),
    ("broad agent search (all)", "agent"),
]

BASE_URL = "https://hn.algolia.com/api/v1/search"
DATE_FILTER = "created_at_i:1741468800+TO+1742073600"  # 2026-05-09 to 2026-05-16


def search_hn(query_name: str, query_string: str) -> dict:
    url = f"{BASE_URL}?query={query_string}&tags=story&numericFilters={DATE_FILTER}&hitsPerPage=20"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "query": query_name}


def main():
    all_results = {}
    for name, q in QUERIES:
        data = search_hn(name, q)
        all_results[name] = data
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Query: {name}", file=sys.stderr)
        if "error" in data:
            print(f"  ERROR: {data['error']}", file=sys.stderr)
            continue
        print(f"  Total hits: {data.get('nbHits', 0)}", file=sys.stderr)
        for hit in data.get("hits", []):
            title = hit.get("title", "N/A")
            url_hit = hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID')}")
            created = hit.get("created_at", "N/A")
            points = hit.get("points", 0)
            num_comments = hit.get("num_comments", 0)
            print(f"\n  [{points}pts / {num_comments}comments] {title}", file=sys.stderr)
            print(f"    URL: {url_hit}", file=sys.stderr)
            print(f"    Date: {created}", file=sys.stderr)

    # Output full JSON for programmatic use
    with open("/tmp/hn_search_results.json", "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print("\nFull results saved to /tmp/hn_search_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
