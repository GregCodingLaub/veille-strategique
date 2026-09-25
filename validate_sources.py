"""
Check every source in sources.yaml and report whether it actually works.

Run this:
  - once right after setup
  - any time you add a new source
  - if the digest suddenly looks thin (a source may have broken)

Usage: python scripts/validate_sources.py
"""
import sys
import requests
import feedparser

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import load_sources
from scrapers import PARSERS

USER_AGENT = "veille-strategique/1.0 (personal research monitoring bot)"


def check_rss(url):
    resp = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Not a valid feed (bozo error: {parsed.bozo_exception})")
    if not parsed.entries:
        raise ValueError("Feed parsed but contains 0 entries")
    return len(parsed.entries)


def check_scrape(url, parser_name):
    parser_fn = PARSERS.get(parser_name)
    if not parser_fn:
        raise ValueError(f"No parser named '{parser_name}' defined in scrapers.py")
    session = requests.Session()
    items = parser_fn(session, url)
    if not items:
        raise ValueError("Parser ran but returned 0 items -- site structure may have changed")
    return len(items)


def main():
    sources = load_sources()
    ok, fail = 0, 0

    for src in sources:
        name = src["name"]
        try:
            if src["type"] == "rss":
                n = check_rss(src["url"])
            elif src["type"] == "scrape":
                n = check_scrape(src["url"], src.get("parser"))
            else:
                raise ValueError(f"Unknown type '{src['type']}'")
            print(f"[OK]   {name:45s} {n} items found")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {name:45s} {e}")
            fail += 1

    print(f"\n{ok} working, {fail} broken, out of {len(sources)} sources.")
    if fail:
        print("Fix or remove broken sources in sources.yaml before relying on them.")
        sys.exit(1)


if __name__ == "__main__":
    main()
