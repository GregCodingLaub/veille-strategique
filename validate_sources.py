"""
Check every enabled source in sources.yaml: does it answer, and how many
items would survive the keyword filter right now?

Run it after adding a source, or when a newsletter looks thin.
Usage: python scripts/validate_sources.py [name fragment]
Exit code 1 if at least one source fails or returns nothing.
"""
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_sources, load_keywords, load_regions  # noqa: E402
from fetch import fetch_source, process_items  # noqa: E402


def main():
    only = sys.argv[1].lower() if len(sys.argv) > 1 else None
    keywords, regions = load_keywords(), load_regions()
    today = datetime.now(timezone.utc)
    session = requests.Session()
    ok = fail = 0
    for src in load_sources():
        if only and only not in src["name"].lower():
            continue
        if src.get("enabled", True) is False:
            print(f"[SKIP] {src['name']:45s} disabled")
            continue
        try:
            raw = fetch_source(session, src)
            if not raw:
                raise ValueError("0 entries: feed empty or page structure changed")
            kept, _, latest = process_items(src, raw, keywords, regions, set(), today)
            print(f"[OK]   {src['name']:45s} {len(raw):3d} fetched, {len(kept):3d} relevant, newest {latest or '?'}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {src['name']:45s} {e}")
            fail += 1
    print(f"\n{ok} working, {fail} broken.")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
