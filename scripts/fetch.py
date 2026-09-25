"""
Fetch all sources, filter for relevance, merge into data/items.json.

Run manually:  python scripts/fetch.py
Run by CI:     called from .github/workflows/veille.yml

Exit code is always 0 even if some sources fail -- a broken source should
not break the whole pipeline. Failures are printed so they show up in the
GitHub Actions log.
"""
import sys
import time
import traceback
from datetime import datetime, timezone

import feedparser
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import (
    load_sources, load_keywords, load_items, save_items,
    item_id, matches_keywords,
)
from scrapers import PARSERS
from bluesky import fetch_bluesky

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch_rss(session, url, verify_ssl=True):
    """Return list of {title, link, date, summary} from an RSS/Atom feed."""
    resp = session.get(url, timeout=20, headers={"User-Agent": USER_AGENT}, verify=verify_ssl)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    items = []
    for entry in parsed.entries:
        date = None
        if getattr(entry, "published_parsed", None):
            date = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
        elif getattr(entry, "updated_parsed", None):
            date = datetime(*entry.updated_parsed[:6]).strftime("%Y-%m-%d")
        items.append({
            "title": getattr(entry, "title", "").strip(),
            "link": getattr(entry, "link", "").strip(),
            "date": date,
            "summary": getattr(entry, "summary", "")[:500],
        })
    return items


def fetch_scrape(session, url, parser_name):
    parser_fn = PARSERS.get(parser_name)
    if not parser_fn:
        raise ValueError(f"No parser function named '{parser_name}' in scrapers.py")
    return parser_fn(session, url)


def main():
    sources = load_sources()
    keywords = load_keywords()
    existing = load_items()
    existing_ids = {it["id"] for it in existing}

    session = requests.Session()
    all_new = []
    errors = []

    for src in sources:
        name = src["name"]
        try:
            if src["type"] == "rss":
                raw_items = fetch_rss(session, src["url"], verify_ssl=src.get("verify_ssl", True))
            elif src["type"] == "scrape":
                raw_items = fetch_scrape(session, src["url"], src.get("parser"))
            elif src["type"] == "bluesky":
                raw_items = fetch_bluesky(session, src["url"])
            else:
                raise ValueError(f"Unknown source type: {src['type']}")

            kept = 0
            for raw in raw_items:
                if not raw.get("link") or not raw.get("title"):
                    continue
                iid = item_id(raw["link"])
                if iid in existing_ids:
                    continue  # already have it
                text = f"{raw['title']} {raw.get('summary', '')}"
                themes = matches_keywords(text, keywords)
                if not themes:
                    continue  # not relevant to our strategic themes
                all_new.append({
                    "id": iid,
                    "title": raw["title"],
                    "link": raw["link"],
                    "date": raw.get("date"),
                    "summary": raw.get("summary", ""),
                    "source": name,
                    "region": src.get("region", "other"),
                    "themes": themes,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
                existing_ids.add(iid)
                kept += 1

            print(f"[OK]   {name}: {len(raw_items)} fetched, {kept} new & relevant")

        except Exception as e:
            errors.append((name, str(e)))
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

        time.sleep(1)  # be polite between requests

    merged = existing + all_new
    save_items(merged)

    print(f"\n{len(all_new)} new relevant items added. Total archive: {len(merged)} items.")
    if errors:
        print(f"\n{len(errors)} source(s) failed this run:")
        for name, err in errors:
            print(f"  - {name}: {err}")


if __name__ == "__main__":
    main()
