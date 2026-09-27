"""Shared helpers used by fetch.py, build_site.py, send_newsletter.py."""
import hashlib
import json
import os
import re
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "sources.yaml")
KEYWORDS_PATH = os.path.join(ROOT, "keywords.yaml")
REGIONS_PATH = os.path.join(ROOT, "regions.yaml")
ITEMS_PATH = os.path.join(ROOT, "data", "items.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
NEWSLETTER_LOG_PATH = os.path.join(ROOT, "data", "newsletter_log.json")
DOCS_DIR = os.path.join(ROOT, "docs")

# Order defines both matching priority (first match wins) and display order
# in the email/website. Keep in sync with regions.yaml's section names.
REGION_ORDER = ["france", "eu", "us", "china", "middle_east_africa", "other"]
REGION_LABELS = {
    "france": "France",
    "eu": "Union Européenne",
    "us": "États-Unis",
    "china": "Chine",
    "middle_east_africa": "Moyen-Orient & Afrique",
    "other": "Autres",
}

# One newsletter per theme. Keep in sync with keywords.yaml's theme keys.
THEME_ORDER = ["intelligence", "military", "energy_industry"]
THEME_LABELS = {
    "intelligence": "Renseignement",
    "military": "Défense & Industrie militaire",
    "energy_industry": "Énergie",
}

# Maps a SOURCE's own region code (sources.yaml's short "fr"/"eu"/"us")
# to the matching SUBJECT region key (regions.yaml's "france"/"eu"/"us"/...).
# Used as a fallback when an article's text has no explicit region keyword.
SOURCE_TO_SUBJECT_REGION = {
    "fr": "france",
    "eu": "eu",
    "us": "us",
    "other": "other",
}


def load_sources():
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_keywords():
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_regions():
    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_items():
    if not os.path.exists(ITEMS_PATH):
        return []
    with open(ITEMS_PATH, "r", encoding="utf-8") as f:
        raw = f.read()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # A previous manual edit (through GitHub's web editor, especially on
        # a large file) can leave behind a stray trailing comma. Rather than
        # letting this take down the entire weekly pipeline, try a
        # conservative auto-repair (strip a comma right before a closing
        # ] or }) before giving up.
        print(f"WARNING: data/items.json has invalid JSON ({e}). Attempting auto-repair...")
        repaired = re.sub(r',(\s*[\]}])', r'\1', raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"data/items.json is corrupted and could not be auto-repaired: {e}\n"
                f"Run 'python scripts/fix_json.py' locally, or check line {e.lineno} "
                f"by hand, then push the corrected file."
            ) from e
        print("Auto-repair succeeded. Saving the corrected file so this doesn't recur.")
        save_items(data)
        return data


def save_items(items):
    os.makedirs(os.path.dirname(ITEMS_PATH), exist_ok=True)
    # newest first
    items = sorted(items, key=lambda x: x.get("date") or "", reverse=True)
    with open(ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_state():
    """State is per-theme: {"last_newsletter_sent": {"intelligence": "...",
    "military": "...", "energy_industry": "..."}}. Each value is an ISO
    date string or None if that newsletter has never been sent.

    Handles migrating the old single-newsletter format automatically: if
    last_newsletter_sent is a plain string (or missing), it's converted to
    a per-theme dict, using that old date as the starting point for every
    theme so the transition doesn't cause an immediate re-send of all three."""
    if not os.path.exists(STATE_PATH):
        return {"last_newsletter_sent": {t: None for t in THEME_ORDER}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    last_sent = state.get("last_newsletter_sent")
    if not isinstance(last_sent, dict):
        # Old format (a single date, or missing) -- migrate.
        state["last_newsletter_sent"] = {t: last_sent for t in THEME_ORDER}
    else:
        # Make sure every current theme has a key, even if new since the
        # last run (e.g. a theme added after this file was created).
        for t in THEME_ORDER:
            state["last_newsletter_sent"].setdefault(t, None)
    return state


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def item_id(link):
    """Stable unique id for an item, used for deduplication."""
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


def load_newsletter_log():
    if not os.path.exists(NEWSLETTER_LOG_PATH):
        return []
    with open(NEWSLETTER_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def append_newsletter_log(entry):
    """Add one sent-edition record. Newest first."""
    log = load_newsletter_log()
    log.insert(0, entry)
    os.makedirs(os.path.dirname(NEWSLETTER_LOG_PATH), exist_ok=True)
    with open(NEWSLETTER_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _whole_word_match(keyword, text_low):
    """True if `keyword` appears in `text_low` as a whole word/phrase, not
    as a fragment inside a longer word (e.g. 'cia' must not match inside
    'social'). Word boundaries handle accented French text correctly too."""
    pattern = r'(?<![^\W_])' + re.escape(keyword.lower()) + r'(?![^\W_])'
    return re.search(pattern, text_low) is not None


def matches_keywords(text, keywords_by_theme):
    """Return a list of matched theme names for a given text (title+summary).
    The special 'exclude_technical' key is never returned as a theme -- see
    is_excluded_technical() for how it's used instead."""
    text_low = (text or "").lower()
    matched = []
    for theme, words in keywords_by_theme.items():
        if theme == "exclude_technical":
            continue
        for w in words:
            if _whole_word_match(w, text_low):
                matched.append(theme)
                break
    return matched


def is_excluded_technical(text, keywords_by_theme):
    """True if the text matches any exclude_technical keyword -- meaning
    it should be dropped even if it also matched a real theme (too
    technical/scientific rather than strategic/policy analysis)."""
    text_low = (text or "").lower()
    for w in keywords_by_theme.get("exclude_technical", []):
        if _whole_word_match(w, text_low):
            return True
    return False


# Words that signal "this is an actual report/study/analysis", not a
# passing remark, event plug, or news blurb. Used as an extra quality gate
# specifically for Bluesky-sourced items (see fetch.py) -- RSS/scrape
# sources are already real articles by nature, so this only applies where
# "is this substantial enough to include" is a real question.
REPORT_INDICATORS = [
    "report", "rapport", "study", "étude", "analysis", "analyse",
    "paper", "policy brief", "note de synthèse", "briefing", "assessment",
    "évaluation", "index", "tracker", "database", "guide", "handbook",
    "white paper", "working paper", "policy paper", "publication",
]


def looks_like_a_report(text):
    """True if the text contains language suggesting it's pointing to a
    substantial document, not just a passing social-media remark."""
    text_low = (text or "").lower()
    return any(_whole_word_match(w, text_low) for w in REPORT_INDICATORS)


def match_region(text, regions_by_name):
    """Return the single best-matching subject region for a text (title+
    summary), checked in REGION_ORDER priority. Falls back to 'other' if
    nothing matches -- every item gets exactly one subject region."""
    text_low = (text or "").lower()
    for region in REGION_ORDER:
        if region == "other":
            continue
        for w in regions_by_name.get(region, []):
            if _whole_word_match(w, text_low):
                return region
    return "other"


def source_region_of(item):
    """The publishing institution's own home base (for the small perspective
    tag), with a fallback for items fetched before this field existed."""
    return item.get("source_region") or item.get("region") or "other"


# Small colored "perspective" tag shown next to each item, indicating where
# the PUBLISHING institution is based -- distinct from subject_region (what
# the article is about), which drives the main region grouping. Shared
# between the email and the website so the two stay visually consistent.
SOURCE_PERSPECTIVE = {
    "fr": ("FR", "#60a5fa"),      # blue
    "eu": ("EU", "#a78bfa"),      # violet
    "us": ("US", "#f87171"),      # red
    "other": ("—", "#9ca3af"),    # gray
}
