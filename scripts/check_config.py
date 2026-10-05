"""
Offline consistency check of the configuration (no network). Run by the
check workflow on every push, and by hand after editing a YAML file.
Exit code 1 lists every problem found.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    load_sources, load_keywords, load_regions, THEME_ORDER, REGION_ORDER,
    THEME_LABELS, THEME_COLORS, THEME_SHORT_LABELS, REGION_LABELS, REGION_COLORS,
)
from scrapers import PARSERS  # noqa: E402

SOURCE_TYPES = {"rss", "scrape", "bluesky"}
SOURCE_REGIONS = {"fr", "eu", "us", "other"}


def problems():
    out = []
    kw = load_keywords()
    for t in THEME_ORDER:
        if not kw.get(t):
            out.append(f"keywords.yaml: theme '{t}' missing or empty")
        for d in (THEME_LABELS, THEME_COLORS, THEME_SHORT_LABELS):
            if t not in d:
                out.append(f"common.py: theme '{t}' lacks a label/colour")
    for t in kw:
        if t not in THEME_ORDER and t != "exclude_technical":
            out.append(f"keywords.yaml: unknown theme '{t}' (not in THEME_ORDER)")
    reg = load_regions()
    for r in REGION_ORDER:
        if r != "other" and not reg.get(r):
            out.append(f"regions.yaml: region '{r}' missing or empty")
        if r not in REGION_LABELS or r not in REGION_COLORS:
            out.append(f"common.py: region '{r}' lacks a label/colour")
    for r in reg:
        if r not in REGION_ORDER:
            out.append(f"regions.yaml: unknown region '{r}'")

    seen = set()
    for s in load_sources():
        n = s.get("name")
        if not n or not s.get("url") or s.get("type") not in SOURCE_TYPES:
            out.append(f"sources.yaml: incomplete entry {n or s}")
            continue
        if n in seen:
            out.append(f"sources.yaml: duplicate name '{n}'")
        seen.add(n)
        if s.get("region") not in SOURCE_REGIONS:
            out.append(f"sources.yaml: '{n}' region must be one of {sorted(SOURCE_REGIONS)}")
        if s["type"] == "scrape" and s.get("parser") not in PARSERS:
            out.append(f"sources.yaml: '{n}' parser '{s.get('parser')}' not in scrapers.py")
        for t in s.get("default_themes") or []:
            if t not in THEME_ORDER:
                out.append(f"sources.yaml: '{n}' default_themes has unknown theme '{t}'")
        if s.get("enabled") not in (None, True, False):
            out.append(f"sources.yaml: '{n}' enabled must be true/false")
    return out


if __name__ == "__main__":
    p = problems()
    for line in p:
        print("PROBLEM:", line)
    print("Configuration OK." if not p else f"\n{len(p)} problem(s).")
    sys.exit(1 if p else 0)
