"""
Fetch all sources, filter for relevance, merge into data/items.json, and
record how each source behaved in data/source_health.json.

Run manually:  python scripts/fetch.py
Run by CI:     called daily from .github/workflows/veille.yml

Exit code is always 0 even if some sources fail -- a broken source must not
break the whole pipeline. Failures are printed, summarised in the GitHub
Actions run summary, and tracked in data/source_health.json, which the weekly
run turns into an alert email when a source has been broken or silent for too
long (see send_newsletter.py).

Optional per-source keys in sources.yaml (besides name/type/url/region):
  enabled: false           keep the entry but do not fetch it
  verify_ssl: false        skip TLS verification (broken certificate chains)
  allowed_domains: [..]    (bluesky) keep only links to these domains
  parser: <name>           (scrape) parser function in scrapers.py
  max_pages: N             (scrape) pages to read, if the parser supports it
  default_themes: [..]     themes always given to this source's items. The
                           source is then trusted: no keyword needed, and the
                           exclude_technical filter is not applied.
  initial_limit: N         on the very first fetch of a source, keep only its
                           N most recent items (default 10) so a new source
                           does not flood the next newsletter with its backlog.
  require_report: true     (noisy sources) keep only items whose text looks
                           like a report/study/analysis.
"""
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    load_sources, load_keywords, load_regions, load_items, save_items,
    load_health, save_health, item_id, legacy_item_id, canonical_link,
    clean_text, truncate, matches_keywords, is_excluded_technical,
    looks_like_a_report, match_region, now_utc_iso,
    SOURCE_TO_SUBJECT_REGION, THEME_ORDER,
)
from scrapers import PARSERS  # noqa: E402
from bluesky import fetch_bluesky  # noqa: E402

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_INITIAL_LIMIT = 10
SUMMARY_MAX = 600


def fetch_rss(session, url, verify_ssl=True):
    """Return list of {title, link, date, summary} from an RSS/Atom feed."""
    resp = session.get(url, timeout=25, headers={"User-Agent": USER_AGENT}, verify=verify_ssl)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    items = []
    for entry in parsed.entries:
        date = None
        for attr in ("published_parsed", "updated_parsed"):
            if getattr(entry, attr, None):
                date = datetime(*getattr(entry, attr)[:6]).strftime("%Y-%m-%d")
                break
        items.append({
            "title": getattr(entry, "title", ""),
            "link": getattr(entry, "link", ""),
            "date": date,
            "summary": getattr(entry, "summary", ""),
        })
    return items


def fetch_scrape(session, src):
    parser_fn = PARSERS.get(src.get("parser"))
    if not parser_fn:
        raise ValueError(f"No parser function named '{src.get('parser')}' in scrapers.py")
    return parser_fn(session, src["url"], src)


def fetch_source(session, src):
    kind = src["type"]
    if kind == "rss":
        return fetch_rss(session, src["url"], verify_ssl=src.get("verify_ssl", True))
    if kind == "scrape":
        return fetch_scrape(session, src)
    if kind == "bluesky":
        return fetch_bluesky(session, src["url"], allowed_domains=src.get("allowed_domains"))
    raise ValueError(f"Unknown source type: {kind}")


def process_items(src, raw_items, keywords, regions, known_ids, today):
    """Clean, filter and classify the raw items of ONE source.
    Returns (kept_items, stats). Pure function (no network, no disk)."""
    source_defaults = [t for t in (src.get("default_themes") or []) if t in THEME_ORDER]
    kept, seen_here = [], set()
    stats = {"duplicate": 0, "irrelevant": 0, "technical": 0, "not_report": 0, "invalid": 0}
    latest_date = None

    for raw in raw_items:
        title = clean_text(raw.get("title"))
        link = (raw.get("link") or "").strip()
        if not link or not title:
            stats["invalid"] += 1
            continue
        date = raw.get("date")
        # An event announcement can carry a future date: never show the future.
        if date and date > (today + timedelta(days=1)).strftime("%Y-%m-%d"):
            date = today.strftime("%Y-%m-%d")
        if date and (latest_date is None or date > latest_date):
            latest_date = date

        iid = item_id(link)
        if iid in known_ids or legacy_item_id(link) in known_ids or iid in seen_here:
            stats["duplicate"] += 1
            continue
        seen_here.add(iid)

        summary = truncate(clean_text(raw.get("summary")), SUMMARY_MAX)
        if summary.lower() == title.lower():
            summary = ""
        text = f"{title} {summary}"

        if src.get("require_report") and not looks_like_a_report(text):
            stats["not_report"] += 1
            continue

        # A parser may classify an item itself (raw["themes_hint"], e.g. IRSEM
        # categories): that item is then trusted like a default_themes source.
        default_themes = source_defaults + [t for t in (raw.get("themes_hint") or [])
                                            if t in THEME_ORDER and t not in source_defaults]
        trusted = bool(default_themes)
        themes = matches_keywords(text, keywords)
        if not trusted and themes and is_excluded_technical(text, keywords):
            stats["technical"] += 1
            continue
        for t in default_themes:
            if t not in themes:
                themes.append(t)
        themes = [t for t in THEME_ORDER if t in themes]
        if not themes:
            stats["irrelevant"] += 1
            continue

        subject_region = match_region(text, regions)
        if subject_region == "other":
            # No explicit region keyword: best guess is the publisher's own region.
            subject_region = SOURCE_TO_SUBJECT_REGION.get(src.get("region", "other"), "other")

        kept.append({
            "id": iid,
            "title": title,
            "link": canonical_link(link) if link.startswith("http") else link,
            "date": date or today.strftime("%Y-%m-%d"),
            "summary": summary,
            "source": src["name"],
            "source_region": src.get("region", "other"),  # institution's home base
            "subject_region": subject_region,              # what the article is ABOUT
            "themes": themes,
            "fetched_at": now_utc_iso(),
        })
    return kept, stats, latest_date


def update_health(health, name, ok, error, n_raw, n_kept, latest_date):
    h = health.setdefault(name, {})
    h["last_run"] = now_utc_iso()
    h["last_status"] = "ok" if ok else "fail"
    h["last_error"] = None if ok else str(error)[:300]
    h["consecutive_failures"] = 0 if ok else h.get("consecutive_failures", 0) + 1
    if ok:
        h["last_raw_count"] = n_raw
        h["consecutive_empty_runs"] = h.get("consecutive_empty_runs", 0) + 1 if n_raw == 0 else 0
        if latest_date and latest_date > (h.get("latest_item_date") or ""):
            h["latest_item_date"] = latest_date
        if n_kept:
            h["last_new_item_at"] = now_utc_iso()
            h["total_kept"] = h.get("total_kept", 0) + n_kept
    return h


def write_step_summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main():
    sources = load_sources()
    keywords = load_keywords()
    regions = load_regions()
    existing = load_items()
    health = load_health()
    today = datetime.now(timezone.utc)

    # Duplicate detection: ids of archived items, plus the id their link would
    # get today (canonical form), so tracking-parameter variants are caught.
    known_ids = {it["id"] for it in existing}
    known_ids |= {item_id(it["link"]) for it in existing if it.get("link")}
    sources_with_items = {it.get("source") for it in existing}

    session = requests.Session()
    all_new, errors, report = [], [], []

    for src in sources:
        name = src["name"]
        if src.get("enabled", True) is False:
            print(f"[SKIP] {name}: disabled in sources.yaml")
            continue
        try:
            raw_items = fetch_source(session, src)
            kept, stats, latest_date = process_items(src, raw_items, keywords, regions, known_ids, today)

            if name not in sources_with_items and len(kept) > src.get("initial_limit", DEFAULT_INITIAL_LIMIT):
                kept.sort(key=lambda it: it["date"] or "", reverse=True)
                cut = len(kept) - src.get("initial_limit", DEFAULT_INITIAL_LIMIT)
                kept = kept[: src.get("initial_limit", DEFAULT_INITIAL_LIMIT)]
                print(f"       {name}: first fetch, kept the {len(kept)} most recent ({cut} older ones skipped)")

            for it in kept:
                known_ids.add(it["id"])
            all_new.extend(kept)

            update_health(health, name, True, None, len(raw_items), len(kept), latest_date)
            note = ""
            if not raw_items:
                note = "  <-- EMPTY: the source returned nothing"
            print(f"[OK]   {name}: {len(raw_items)} fetched, {len(kept)} new & relevant "
                  f"(dup {stats['duplicate']}, off-topic {stats['irrelevant']}, "
                  f"technical {stats['technical']}){note}")
            report.append((name, "ok" if raw_items else "EMPTY", len(raw_items), len(kept)))

        except Exception as e:  # noqa: BLE001 - a broken source must not stop the others
            errors.append((name, str(e)))
            update_health(health, name, False, e, 0, 0, None)
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()
            report.append((name, "FAIL", 0, 0))

        time.sleep(1)  # be polite between requests

    merged = existing + all_new
    save_items(merged)
    save_health(health)

    print(f"\n{len(all_new)} new relevant items added. Total archive: {len(merged)} items.")
    if errors:
        print(f"\n{len(errors)} source(s) failed this run:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    lines = ["## Fetch summary", "", f"{len(all_new)} new items, archive: {len(merged)}.", "",
             "| Source | Status | Fetched | New |", "|---|---|---|---|"]
    lines += [f"| {n} | {s} | {f} | {k} |" for n, s, f, k in report]
    write_step_summary(lines)


if __name__ == "__main__":
    main()
