"""Shared helpers used by fetch.py, build_site.py, send_newsletter.py."""
import hashlib
import html as html_lib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "sources.yaml")
KEYWORDS_PATH = os.path.join(ROOT, "keywords.yaml")
REGIONS_PATH = os.path.join(ROOT, "regions.yaml")
ITEMS_PATH = os.path.join(ROOT, "data", "items.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
NEWSLETTER_LOG_PATH = os.path.join(ROOT, "data", "newsletter_log.json")
HEALTH_PATH = os.path.join(ROOT, "data", "source_health.json")
DOCS_DIR = os.path.join(ROOT, "docs")

# Order = display order in the email/website AND tie-break order when an item
# matches several regions equally. Keep in sync with regions.yaml.
REGION_ORDER = [
    "france", "eu", "us", "russia_eurasia", "china",
    "asia_pacific", "middle_east_africa", "other",
]
REGION_LABELS = {
    "france": "France",
    "eu": "Europe",
    "us": "États-Unis",
    "russia_eurasia": "Russie & Eurasie",
    "china": "Chine",
    "asia_pacific": "Indo-Pacifique",
    "middle_east_africa": "Moyen-Orient & Afrique",
    "other": "Autres",
}
# Categorical colours for the "by zone" bar (email + site). Muted, distinct.
REGION_COLORS = {
    "france": "#2f6fdb",
    "eu": "#7c5cd6",
    "us": "#d6455d",
    "russia_eurasia": "#8a5a44",
    "china": "#d9822b",
    "asia_pacific": "#1a9e8f",
    "middle_east_africa": "#b8a000",
    "other": "#8a96a3",
}

# One newsletter per theme. Keep in sync with keywords.yaml's theme keys.
THEME_ORDER = ["intelligence", "military", "energy_industry"]
THEME_LABELS = {
    "intelligence": "Renseignement & Intelligence économique",
    "military": "Défense & Industrie militaire",
    "energy_industry": "Énergie & Infrastructures",
}
THEME_SHORT_LABELS = {
    "intelligence": "Renseignement",
    "military": "Défense",
    "energy_industry": "Énergie & Infra.",
}
# Accent colour of each newsletter (masthead band, section rules, links).
THEME_COLORS = {
    "intelligence": "#0e7490",
    "military": "#4d6b2f",
    "energy_industry": "#b45309",
}

# Maps a SOURCE's own region code to the matching SUBJECT region key. Used as
# a fallback when an article's text has no explicit region keyword.
SOURCE_TO_SUBJECT_REGION = {
    "fr": "france",
    "eu": "eu",
    "us": "us",
    "other": "other",
}

# Small perspective tag: where the PUBLISHING institution is based.
# (label, text colour, tint background)
SOURCE_PERSPECTIVE = {
    "fr": ("FR", "#1d4ed8", "#e6eefc"),
    "eu": ("EU", "#6d28d9", "#efe8fb"),
    "us": ("US", "#b91c1c", "#fbe9e9"),
    "other": ("—", "#52606d", "#eceff2"),
}

# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; VeilleStrategique/1.0; +https://github.com)",
    "feedparser/6.0.11 +https://github.com/kurtmckee/feedparser/",
    "curl/8.5.0",
]
_BLOCKED = (403, 406, 429, 503)


def http_get(session, url, timeout=25, verify=True, accept="*/*", lang="en-US,en;q=0.9"):
    """GET with fallbacks. Cloud IPs (GitHub Actions) are often refused by
    bot protections that decide on the User-Agent: on 403/406/429/503 the
    request is retried with other identities (browser, honest bot, feed reader,
    curl). Raises requests.HTTPError if every one is refused."""
    resp = None
    for i, ua in enumerate(_USER_AGENTS):
        resp = session.get(url, timeout=timeout, verify=verify,
                           headers={"User-Agent": ua, "Accept": accept, "Accept-Language": lang})
        if resp.status_code not in _BLOCKED:
            break
        if i < len(_USER_AGENTS) - 1:
            time.sleep(1.5)
    resp.raise_for_status()
    return resp


# ----------------------------------------------------------------------------
# Loading / saving
# ----------------------------------------------------------------------------


def load_sources():
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_keywords():
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_regions():
    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _atomic_write_json(path, data):
    """Write JSON through a temp file so a crash can never leave a
    half-written (corrupt) data file behind."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_items():
    if not os.path.exists(ITEMS_PATH):
        return []
    with open(ITEMS_PATH, "r", encoding="utf-8") as f:
        raw = f.read()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # A manual edit through GitHub's web editor can leave a stray trailing
        # comma. Try a conservative auto-repair before giving up.
        print(f"WARNING: data/items.json has invalid JSON ({e}). Attempting auto-repair...")
        repaired = re.sub(r',(\s*[\]}])', r'\1', raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"data/items.json is corrupted and could not be auto-repaired: {e}\n"
                f"Check line {e.lineno} by hand, then push the corrected file."
            ) from e
        print("Auto-repair succeeded. Saving the corrected file so this doesn't recur.")
        save_items(data)
        return data


def save_items(items):
    # newest first
    items = sorted(items, key=lambda x: x.get("date") or "", reverse=True)
    _atomic_write_json(ITEMS_PATH, items)


def load_state():
    """State is per-theme: {"last_newsletter_sent": {"intelligence": "ISO",
    "military": "ISO", "energy_industry": "ISO"}}. A value is an ISO datetime
    or None if that newsletter was never sent. Migrates the old
    single-date format automatically."""
    if not os.path.exists(STATE_PATH):
        return {"last_newsletter_sent": {t: None for t in THEME_ORDER}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    last_sent = state.get("last_newsletter_sent")
    if not isinstance(last_sent, dict):
        state["last_newsletter_sent"] = {t: last_sent for t in THEME_ORDER}
    else:
        for t in THEME_ORDER:
            state["last_newsletter_sent"].setdefault(t, None)
    return state


def save_state(state):
    _atomic_write_json(STATE_PATH, state)


def load_newsletter_log():
    if not os.path.exists(NEWSLETTER_LOG_PATH):
        return []
    with open(NEWSLETTER_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def append_newsletter_log(entry):
    """Add one sent-edition record. Newest first."""
    log = load_newsletter_log()
    log.insert(0, entry)
    _atomic_write_json(NEWSLETTER_LOG_PATH, log)


def load_health():
    if not os.path.exists(HEALTH_PATH):
        return {}
    try:
        with open(HEALTH_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_health(health):
    _atomic_write_json(HEALTH_PATH, health)


def edition_number(theme, log=None):
    """Official edition number of `theme`: number of logged official sends
    of that theme, plus one (the one being prepared)."""
    log = load_newsletter_log() if log is None else log
    return 1 + sum(1 for e in log if e.get("theme") == theme)


# ----------------------------------------------------------------------------
# Text cleaning
# ----------------------------------------------------------------------------

_BOILERPLATE = [
    re.compile(r"\s*The post .{0,200}? appeared first on .{0,120}?\.?\s*$", re.I | re.S),
    re.compile(r"\s*Cet article .{0,200}? est apparu en premier sur .{0,120}?\.?\s*$", re.I | re.S),
    re.compile(r"\s*(Continue reading|Read more|Lire la suite|En savoir plus)\b.{0,40}$", re.I | re.S),
]


def clean_text(raw):
    """HTML (or plain text) -> one line of plain text: tags dropped, entities
    decoded, whitespace collapsed, feed boilerplate removed. Safe to escape
    and display anywhere."""
    if not raw:
        return ""
    text = str(raw)
    # Some feeds double-encode their markup (&lt;span&gt;): decode first.
    if "&lt;" in text or "&#60;" in text:
        text = html_lib.unescape(text)
    if "<" in text and ">" in text:
        # Drop script/style/embedded content wholesale, then the tags.
        text = re.sub(r"(?is)<(script|style|iframe|noscript)\b.*?</\1\s*>", " ", text)
        text = re.sub(r"(?s)<[^>]*>", " ", text)
    # A summary cut in the middle of a tag leaves a dangling "<a href=..."
    text = re.sub(r"<[^<>]*$", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"Sign up here to receive Bellingcat.s biggest investigations by email as soon as they are published\.?", " ", text, flags=re.I)
    text = re.sub(r"\[email\s*protected\]", " ", text, flags=re.I)
    # Drupal feeds: "author.name... Mon, 09/28/2026 - 11:11"
    text = re.sub(r"\S*\.\.\.?\s+[A-Z][a-z]{2}, \d\d/\d\d/\d{4} - \d\d:\d\d", " ", text)
    text = re.sub(r"\b[A-Z][a-z]{2}, \d\d/\d\d/\d{4} - \d\d:\d\d", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for pat in _BOILERPLATE:
        text = pat.sub("", text).strip()
    return text


def truncate(text, limit):
    """Cut at a word boundary and add an ellipsis. No-op if short enough."""
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-– ")
    return (cut or text[:limit]) + "…"


_TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|mc_.*|mkt_tok|ref|ref_src|cmpid|igshid|spm)$", re.I)


def canonical_link(url):
    """Normalise a URL for de-duplication: lower-case host, no fragment, no
    tracking/empty query parameters, no trailing slash."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip()
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if v != "" and not _TRACKING_PARAMS.match(k)
    ]
    path = parts.path.rstrip("/") or ("/" if not parts.netloc else "")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def item_id(link):
    """Stable unique id for an item (hash of its canonical link)."""
    return hashlib.sha256(canonical_link(link).encode("utf-8")).hexdigest()[:16]


def legacy_item_id(link):
    """Id as computed before canonicalisation (hash of the raw link). Kept so
    items archived by earlier versions are still recognised as duplicates."""
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def fold(text):
    """Lower-case, strip accents, straighten quotes: the form keyword
    matching works on, so 'Défense', 'defense' and 'DÉFENSE' are equal."""
    text = (text or "").replace("’", "'").replace("‘", "'").replace("ʼ", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def parse_date_from_text(text, month_only=False):
    """Find a date written in English or French prose ('21 September 2026',
    'October 1, 2026', '21 septembre 2026'). Returns 'YYYY-MM-DD' or None.
    With month_only=True also accepts 'September 2026' (-> first of month)."""
    t = fold(text)
    names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th|er)?\s+({names})\.?,?\s+(\d{{4}})\b", t)
    if m:
        d, mon, y = int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3))
    else:
        m = re.search(rf"\b({names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", t)
        if m:
            mon, d, y = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
        elif month_only:
            m = re.search(rf"\b({names})\.?,?\s+(\d{{4}})\b", t)
            if not m:
                return None
            mon, d, y = _MONTHS[m.group(1)], 1, int(m.group(2))
        else:
            return None
    try:
        return datetime(y, mon, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# Keyword / region matching
# ----------------------------------------------------------------------------
# Matching is on whole words (so 'cia' never matches inside 'social'), but
# tolerant of plurals ('drone' matches 'drones', 'armée' matches 'armées')
# and of accents/curly quotes, on text that has first been cleaned of HTML.


@lru_cache(maxsize=None)
def _keyword_pattern(keyword):
    kw = fold(keyword).strip()
    if not kw:
        return None
    # Every alphabetic word of the keyword may carry a plural ending, so
    # "guerre hybride" also matches "guerres hybrides".
    pieces = re.split(r"(\s+|-)", kw)
    out = []
    for piece in pieces:
        if not piece:
            continue
        if re.fullmatch(r"\s+|-", piece):
            out.append(r"[\s-]+" if piece != "-" else r"-")
        elif piece[-1].isalpha():
            out.append(re.escape(piece) + r"(?:s|x|es)?")
        else:
            out.append(re.escape(piece))
    return re.compile(r"(?<![a-z0-9])" + "".join(out) + r"(?![a-z0-9])")


def _whole_word_match(keyword, text_low):
    """True if `keyword` appears in the (already folded) text as a whole
    word/phrase, plural-tolerant."""
    pat = _keyword_pattern(keyword)
    return bool(pat and pat.search(fold(text_low)))


def any_term(text, terms):
    """True if one of `terms` appears in `text` (whole words, accent/case
    insensitive, plural-tolerant). Used by the per-source options
    require_any / exclude_any."""
    folded = fold(text)
    for t in terms or []:
        pat = _keyword_pattern(t)
        if pat and pat.search(folded):
            return True
    return False


def matches_keywords(text, keywords_by_theme):
    """Matched theme names for a text (title+summary). 'exclude_technical'
    is never returned as a theme -- see is_excluded_technical()."""
    folded = fold(text)
    matched = []
    for theme, words in keywords_by_theme.items():
        if theme == "exclude_technical":
            continue
        for w in words or []:
            pat = _keyword_pattern(w)
            if pat and pat.search(folded):
                matched.append(theme)
                break
    return matched


def theme_scores(text, keywords_by_theme):
    """{theme: number of distinct keywords found} for a text."""
    folded = fold(text)
    out = {}
    for theme, words in keywords_by_theme.items():
        if theme == "exclude_technical":
            continue
        n = 0
        for w in words or []:
            pat = _keyword_pattern(w)
            if pat and pat.search(folded):
                n += 1
        out[theme] = n
    return out


def primary_theme(item, keywords_by_theme):
    """The ONE newsletter an item belongs to: the theme with the most keyword
    hits, +3 for a theme the source or parser vouches for (item["trusted_themes"]);
    ties go to THEME_ORDER. Only the item's own themes are considered."""
    themes = [t for t in THEME_ORDER if t in (item.get("themes") or [])]
    if not themes:
        return None
    scores = theme_scores(f"{item.get('title', '')} {item.get('summary', '')}", keywords_by_theme)
    trusted = set(item.get("trusted_themes") or [])
    return max(themes, key=lambda t: (scores.get(t, 0) + (3 if t in trusted else 0), -THEME_ORDER.index(t)))


def is_excluded_technical(text, keywords_by_theme):
    """True if the text hits an exclude_technical keyword: too technical,
    promotional or event-announcement to be worth a strategic digest."""
    folded = fold(text)
    for w in keywords_by_theme.get("exclude_technical", []) or []:
        pat = _keyword_pattern(w)
        if pat and pat.search(folded):
            return True
    return False


# Words that signal "this is an actual report/study/analysis". Optional extra
# gate for noisy social-media sources (source option `require_report: true`).
REPORT_INDICATORS = [
    "report", "rapport", "study", "etude", "analysis", "analyse",
    "paper", "policy brief", "note de synthese", "briefing", "assessment",
    "evaluation", "index", "tracker", "database", "guide", "handbook",
    "white paper", "working paper", "policy paper", "publication",
]


def looks_like_a_report(text):
    folded = fold(text)
    return any(_keyword_pattern(w).search(folded) for w in REPORT_INDICATORS)


# "US" is a pronoun in lower case, so it is only recognised in capitals.
_US_TOKEN = re.compile(r"(?<![A-Za-z])(?:US|USA|U\.S\.A?\.?)(?![A-Za-z])")


def region_scores(text, regions_by_name):
    """{region: number of distinct region keywords found} for a text."""
    folded = fold(text)
    scores = {}
    for region in REGION_ORDER:
        if region == "other":
            continue
        hits = 0
        for w in regions_by_name.get(region, []) or []:
            pat = _keyword_pattern(w)
            if pat and pat.search(folded):
                hits += 1
        if region == "us" and _US_TOKEN.search(text or ""):
            hits += 1
        if hits:
            scores[region] = hits
    return scores


def match_region(text, regions_by_name):
    """Single best subject region for a text: the region with the most
    distinct keyword hits (ties resolved by REGION_ORDER). 'other' if none."""
    scores = region_scores(text, regions_by_name)
    if not scores:
        return "other"
    best = max(scores.values())
    for region in REGION_ORDER:
        if scores.get(region) == best:
            return region
    return "other"


def source_region_of(item):
    """The publishing institution's home base (for the small perspective
    tag), with a fallback for items archived before this field existed."""
    return item.get("source_region") or item.get("region") or "other"


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()
