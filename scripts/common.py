"""Shared helpers used by fetch.py, build_site.py, send_newsletter.py."""
import hashlib
import json
import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "sources.yaml")
KEYWORDS_PATH = os.path.join(ROOT, "keywords.yaml")
ITEMS_PATH = os.path.join(ROOT, "data", "items.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
NEWSLETTER_LOG_PATH = os.path.join(ROOT, "data", "newsletter_log.json")
DOCS_DIR = os.path.join(ROOT, "docs")


def load_sources():
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_keywords():
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_items():
    if not os.path.exists(ITEMS_PATH):
        return []
    with open(ITEMS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_items(items):
    os.makedirs(os.path.dirname(ITEMS_PATH), exist_ok=True)
    # newest first
    items = sorted(items, key=lambda x: x.get("date") or "", reverse=True)
    with open(ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"last_newsletter_sent": None}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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


def matches_keywords(text, keywords_by_theme):
    """Return a list of matched theme names for a given text (title+summary)."""
    text_low = (text or "").lower()
    matched = []
    for theme, words in keywords_by_theme.items():
        for w in words:
            if w.lower() in text_low:
                matched.append(theme)
                break
    return matched
