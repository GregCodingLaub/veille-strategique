"""
Re-evaluate the whole archive (data/items.json) with the CURRENT rules:

  - titles/summaries cleaned of HTML (no more broken markup on the site)
  - themes recomputed from keywords.yaml (+ the source's default_themes)
  - subject region recomputed; source_region filled in for old items
    that predate those fields
  - junk removed: links to bsky.app posts, items that no longer match any
    theme, technical/promotional items, duplicates (same canonical link or
    same title from the same source)

Item ids are NOT changed (the edition log refers to them).

Usage:
  python scripts/backfill_items.py            dry run: report only
  python scripts/backfill_items.py --apply    write data/items.json
  python scripts/backfill_items.py --apply --drop-source "IRSEM"
        also remove every archived item of that source, so the next fetch
        re-imports it from scratch (use it after fixing a scraper).

Run it after changing keywords.yaml, regions.yaml or a source's default_themes
if you want the existing archive to follow the new rules.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    load_items, save_items, load_sources, load_keywords, load_regions,
    clean_text, truncate, canonical_link, item_id, fold, matches_keywords,
    is_excluded_technical, match_region, SOURCE_TO_SUBJECT_REGION, THEME_ORDER,
)


def rebuild(items, sources, keywords, regions):
    src_by_name = {s["name"]: s for s in sources}
    kept, dropped = [], collections.defaultdict(list)
    seen_links, seen_titles = set(), set()

    for it in items:
        link = (it.get("link") or "").strip()
        if "bsky.app/profile/" in link:
            dropped["bluesky post link (old bug)"].append(it)
            continue

        src = src_by_name.get(it.get("source"), {})
        title = clean_text(it.get("title"))
        summary = truncate(clean_text(it.get("summary")), 600)
        if summary.lower() == title.lower():
            summary = ""
        text = f"{title} {summary}"

        default_themes = [t for t in (src.get("default_themes") or []) if t in THEME_ORDER]
        themes = matches_keywords(text, keywords)
        if not default_themes and themes and is_excluded_technical(text, keywords):
            dropped["technical / promotional"].append(it)
            continue
        for t in default_themes:
            if t not in themes:
                themes.append(t)
        themes = [t for t in THEME_ORDER if t in themes]
        if not themes:
            dropped["matches no theme under current keywords"].append(it)
            continue

        cl = canonical_link(link)
        tkey = (it.get("source"), fold(title))
        if cl in seen_links or tkey in seen_titles:
            dropped["duplicate"].append(it)
            continue
        seen_links.add(cl)
        seen_titles.add(tkey)

        source_region = it.get("source_region") or it.get("region") or src.get("region") or "other"
        region = match_region(text, regions)
        if region == "other":
            region = SOURCE_TO_SUBJECT_REGION.get(source_region, "other")

        new = {k: v for k, v in it.items() if k != "region"}
        new.update({
            "title": title, "summary": summary, "link": link,
            "themes": themes, "source_region": source_region, "subject_region": region,
        })
        kept.append(new)
    return kept, dropped


def main():
    apply = "--apply" in sys.argv
    items = load_items()
    if "--drop-source" in sys.argv:
        name = sys.argv[sys.argv.index("--drop-source") + 1]
        n = len(items)
        items = [it for it in items if it.get("source") != name]
        print(f"--drop-source {name!r}: {n - len(items)} item(s) set aside\n")
    kept, dropped = rebuild(items, load_sources(), load_keywords(), load_regions())

    print(f"Archive: {len(items)} items -> {len(kept)} kept, {len(items) - len(kept)} removed\n")
    for reason, lst in sorted(dropped.items(), key=lambda kv: -len(kv[1])):
        print(f"  removed ({len(lst)}): {reason}")
        for it in lst[:4]:
            print(f"      - [{it.get('source')}] {clean_text(it.get('title'))[:80]}")
    print("\nThemes after:", dict(collections.Counter(t for it in kept for t in it["themes"])))
    print("Regions after:", dict(collections.Counter(it["subject_region"] for it in kept)))

    if not apply:
        print("\nDry run only. Re-run with --apply to write data/items.json.")
        return
    save_items(kept)
    print("\ndata/items.json rewritten.")


if __name__ == "__main__":
    main()
