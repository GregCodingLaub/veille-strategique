"""
Custom scrapers for sources with NO usable RSS feed.

Each parser is a function  parser(session, url, options) -> list of dicts
  [{title, link, date, summary}, ...]
where `url` and `options` come from the source's entry in sources.yaml
(`options` is the whole entry, so a parser can read extra keys such as
`max_pages`). `date` is "YYYY-MM-DD" if known, else None. Titles and summaries
are cleaned by fetch.py, parsers may return them raw.

To add a non-RSS source:
  1. Write a parser here and register it in PARSERS at the bottom.
  2. In sources.yaml: type: scrape, parser: <name>.
  3. Run  python scripts/validate_sources.py  to check it returns items.

These parsers depend on the sites' current HTML. They are deliberately
written around stable things (URL patterns of publications, dates written in
the page text) rather than CSS class names, which change more often. If a
source stops returning items, inspect the page and adjust (normal
maintenance cost of scraping).
"""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from common import parse_date_from_text, clean_text, fold, http_get

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_soup(session, url, lang="en-US,en;q=0.9"):
    resp = http_get(session, url, lang=lang, accept="text/html,application/xhtml+xml")
    return BeautifulSoup(resp.text, "html.parser")


def _card_of(anchor, max_up=5):
    """The smallest ancestor of `anchor` that looks like one listing card
    (article / list item / views-row), else a few levels up."""
    node = anchor
    for _ in range(max_up):
        parent = node.parent
        if parent is None or parent.name in ("body", "html", "main", "section", "ul", "ol"):
            break
        node = parent
        if node.name in ("article", "li") or "views-row" in (node.get("class") or []):
            break
    return node


def _best_text(anchors):
    """Longest visible text among several anchors pointing to the same page
    (image link, title link and 'read more' link often coexist)."""
    texts = [clean_text(a.get_text(" ", strip=True)) for a in anchors]
    texts = [t for t in texts if t]
    return max(texts, key=len) if texts else ""


def _summary_of(card, title):
    for p in card.find_all("p"):
        txt = clean_text(p.get_text(" ", strip=True))
        if len(txt) >= 40 and txt != title:
            return txt
    return ""


# ----------------------------------------------------------------------------
# IFRI (works for the FR and EN sites and for the centres' listing pages)
# ----------------------------------------------------------------------------
_IFRI_NOT_PUBLICATION = {
    "experts", "expert", "events", "event", "evenements", "evenement", "about",
    "centers", "centres", "contact", "programs", "programmes", "people",
    "search", "recherche", "node", "user", "taxonomy", "tags",
    "center-energy-climate", "centre-energie-climat",
}


def ifri(session, url, options=None):
    """IFRI publications. A publication URL looks like /en/memos/<slug>,
    /en/studies/<slug>, /en/papers/<slug> or /fr/notes-de-lifri/<slug>;
    the date is written in the card text ("21 September 2026")."""
    soup = _get_soup(session, url, "fr-FR,fr;q=0.9,en;q=0.8")
    by_href = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        parts = urlsplit(href)
        if not parts.netloc.endswith("ifri.org"):
            continue
        segs = [s for s in parts.path.split("/") if s]
        if len(segs) != 3 or segs[0] not in ("en", "fr"):
            continue
        if segs[1] in _IFRI_NOT_PUBLICATION or len(segs[2]) < 12:
            continue
        by_href.setdefault(href.split("#")[0], []).append(a)

    items = []
    for href, anchors in by_href.items():
        title = _best_text(anchors)
        if len(title) < 12:
            continue
        card = _card_of(anchors[0])
        date = parse_date_from_text(card.get_text(" ", strip=True))
        time_tag = card.find("time")
        if not date and time_tag and time_tag.get("datetime"):
            date = time_tag["datetime"][:10]
        items.append({"title": title, "link": href, "date": date,
                      "summary": _summary_of(card, title)})
    return items


# ----------------------------------------------------------------------------
# CSIS programs / projects (no RSS feed; listing is on the program page)
# ----------------------------------------------------------------------------
def csis_program(session, url, options=None):
    """Publications of a CSIS program or project page, following the pager
    (?page=1, 2, ...) up to `max_pages` pages (default 3). Only analysis
    pieces (/analysis/...) are kept: events, podcasts and audio briefs are
    announcements or duplicates of an analysis."""
    max_pages = int((options or {}).get("max_pages", 3))
    items, seen = [], set()
    for page in range(max_pages):
        page_url = url if page == 0 else f"{url}{'&' if '?' in url else '?'}page={page}"
        try:
            soup = _get_soup(session, page_url)
        except Exception:  # noqa: BLE001
            if page == 0:
                raise          # first page unreachable: real failure
            break              # a deeper page refused: keep what we already have
        by_href = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"]).split("#")[0].split("?")[0]
            parts = urlsplit(href)
            if not parts.netloc.endswith("csis.org"):
                continue
            segs = [s for s in parts.path.split("/") if s]
            if len(segs) != 2 or segs[0] != "analysis":
                continue
            by_href.setdefault(href, []).append(a)

        new_on_page = 0
        for href, anchors in by_href.items():
            if href in seen:
                continue
            title = _best_text(anchors)
            if len(title) < 12:
                continue
            seen.add(href)
            new_on_page += 1
            card = _card_of(anchors[0])
            items.append({
                "title": title, "link": href,
                "date": parse_date_from_text(card.get_text(" ", strip=True)),
                "summary": _summary_of(card, title),
            })
        if new_on_page == 0:
            break  # past the last page
    return items


# ----------------------------------------------------------------------------
# CIA - Studies in Intelligence (one entry per published issue)
# ----------------------------------------------------------------------------
_CIA_ISSUE = re.compile(r"\bno\.?\s*\d+", re.I)


def cia_csi(session, url, options=None):
    """One item per issue of "Studies in Intelligence". The listing shows the
    newest issues first, with the issue title ("Studies in Intelligence Vol.
    70, No. 3 (Extracts, September 2026)"). Special editions without an issue
    number (e.g. the Guide for Authors) are skipped. The listing gives only
    month + year, so the date is the first of that month."""
    soup = _get_soup(session, url)
    by_href = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"]).split("#")[0].split("?")[0]
        parts = urlsplit(href)
        if not parts.netloc.endswith("cia.gov") or parts.path.lower().endswith(".pdf"):
            continue
        slug = parts.path.rstrip("/").rsplit("/", 1)[-1]
        if "/studies-in-intelligence/" not in parts.path or not slug.startswith("studies-in-intelligence"):
            continue
        by_href.setdefault(href, []).append(a)

    items = []
    for href, anchors in by_href.items():
        title = _best_text(anchors)
        if not _CIA_ISSUE.search(title) or "guide for authors" in title.lower():
            continue
        items.append({
            "title": title,
            "link": href,
            "date": parse_date_from_text(title, month_only=True),
            "summary": "Nouveau numéro de la revue du Center for the Study of Intelligence "
                       "(CIA) : sommaire et PDF sur la page du numéro.",
        })
    return items


# ----------------------------------------------------------------------------
# IRSEM (no RSS feed; listing at /publications, pager ?page=2, ?page=3 ...)
# ----------------------------------------------------------------------------
# A card reads, in text order:
#   "<categories> <N min de lecture> <title> <type N - date> <title> <authors>"
#   e.g. "Défense Sécurité 1 min de lecture Sahel au centre du djihadisme mondial
#         Etude 138 - 09/2026 Sahel au centre du djihadisme mondial A. Lauret"
# The parser cuts that string at the reading time and at the type/date label.
_IRSEM_DATE = re.compile(r"\b(?:(\d{1,2})/)?(\d{1,2})/(20\d{2})\b")
_IRSEM_TYPE = re.compile(
    r"\b(étude|etude|brève stratégique|breve strategique|note de recherche|note stratégique|"
    r"note strategique|veille stratégique|veille strategique|livre|enquête|enquete|"
    r"rapport|publication)\b(?:\s*(?:n°\s*)?(\d+))?\s*-?\s*(?=\d{1,2}/)", re.I)
_IRSEM_READING = re.compile(r"(?:\d+\s*h\s*)?\d+\s*min(?:utes?)?\s+de\s+lecture", re.I)
_IRSEM_LABELS = {"etude": "Étude", "breve strategique": "Brève stratégique",
                 "note strategique": "Note stratégique", "note de recherche": "Note de recherche",
                 "veille strategique": "Veille stratégique", "enquete": "Enquête",
                 "livre": "Livre", "rapport": "Rapport", "publication": "Publication"}
_IRSEM_CATEGORIES = ["Défense", "Sécurité", "Influence", "Stratégie", "Politique", "Énergie",
                     "Société", "Environnement", "Droit", "Espace", "Renseignement", "Histoire"]
# category -> newsletter theme (an item with none of these goes through the keyword filter)
_IRSEM_THEME_HINT = {
    "défense": "military", "sécurité": "military", "stratégie": "military", "influence": "military",
    "renseignement": "intelligence", "énergie": "energy_industry", "espace": "energy_industry",
}


def _irsem_date(text):
    """'14/09/2026' -> 2026-09-14 ; '09/2026' (month only) -> 2026-09-01."""
    m = _IRSEM_DATE.search(text)
    if not m:
        return None
    day, month, year = m.group(1), int(m.group(2)), int(m.group(3))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}-{int(day or 1):02d}"


_IRSEM_TYPE_ANY = re.compile(
    r"\b(étude|etude|brève stratégique|breve strategique|note de recherche|note stratégique|"
    r"note strategique|veille stratégique|veille strategique|livre|enquête|enquete|"
    r"rapport|publication)\b(?:\s*(?:n°\s*)?(\d+))?(?:\s*-?\s*(?:\d{1,2}/)?\d{1,2}/20\d{2})?", re.I)
_IRSEM_AUTHOR_TAIL = re.compile(
    r"(?<=[a-zàâçéèêëîïôûùüÿœ\)\?\!\.»”’'])\s+"
    r"((?:[A-Z]{2,4}\s+)?(?:(?:[A-ZÉÈ]\.\s*|[A-ZÉÈ][\wéèëïôöüçâî\-']+)\s+){1,3}[A-ZÉÈ][\wéèëïôöüçâî\-']+)$")


def _irsem_clean_title(title):
    title = re.sub(r"\s+", " ", title).strip(" -–·|")
    # the card often repeats the title (link text + heading): keep one copy
    probe = title[:25]
    if len(probe) >= 15:
        k = title.find(probe, len(probe))
        if k > 0:
            title = title[:k].strip(" -–·|")
    return title


def _irsem_parse_card(text, fallback_title=""):
    """Split a card's text into (categories, title, type label, date, reading time).
    Order-independent: reading time, type label (+ number), dates and category
    words are located wherever they appear and removed; what is left is the
    title (plus, in the worst case, a trailing author block, which is stripped)."""
    text = re.sub(r"\s+", " ", text).strip()
    reading = _IRSEM_READING.search(text)
    reading_time = ""
    if reading:
        reading_time = re.sub(r"\s*de\s+lecture\s*$", "", reading.group(0), flags=re.I)
        reading_time = re.sub(r"(\d)\s*h\s*(\d)", r"\1 h \2", reading_time)
        reading_time = re.sub(r"(\d)(min)", r"\1 \2", reading_time) + " de lecture"
        text = (text[:reading.start()] + " | " + text[reading.end():]).strip()

    # type label: only trusted when a number or a date follows it (a title can start with "Rapport sur ...")
    label, kind_span = "", None
    for m in _IRSEM_TYPE_ANY.finditer(text):
        if m.group(2) or _IRSEM_DATE.search(m.group(0)):
            name = _IRSEM_LABELS.get(fold(m.group(1)), m.group(1).capitalize())
            label = " ".join(g for g in (name, m.group(2)) if g)
            kind_span = m.span()
            break
    date = _irsem_date(text[kind_span[0]:kind_span[1]]) if kind_span else None
    if kind_span:
        text = text[:kind_span[0]] + " | " + text[kind_span[1]:]
    if not date:
        date = _irsem_date(text)
    # category words sitting before the first separator / at the very start
    head = text.split("|")[0] if "|" in text else ""
    cats = [c for c in _IRSEM_CATEGORIES if re.search(rf"\b{c}\b", head, re.I)]
    text = _IRSEM_DATE.sub(" ", text)
    segs = [x.strip() for x in text.split("|") if x.strip()]
    # drop segments made only of category words
    cat_re = re.compile(r"^(?:\s*(?:" + "|".join(_IRSEM_CATEGORIES) + r")\b)+\s*$", re.I)
    segs = [x for x in segs if not cat_re.match(x)]
    body = max(segs, key=len) if segs else ""
    # a leading category run glued to the title ("Défense Sécurité Titre ...")
    body = re.sub(r"^(?:(?:" + "|".join(_IRSEM_CATEGORIES) + r")\s+)+(?=\S)", "", body, flags=re.I) if reading is None else body
    fb = _irsem_clean_title(fallback_title)
    if fb and 8 <= len(fb) <= 300 and fb.lower() in body.lower() and not _IRSEM_READING.search(fb):
        title = fb                      # the heading element's own text is the best title
    else:
        title = _irsem_clean_title(body)
        title = _IRSEM_AUTHOR_TAIL.sub("", title).strip(" -–·|")
    if len(title) < 8:
        title = fb
    return cats, title, label, date, reading_time


def irsem(session, url, options=None):
    """IRSEM publications. A publication link is /publications/<slug>; the
    card is the largest ancestor of the link that holds no other publication
    link (no dependency on CSS class names). Options (sources.yaml):
      max_pages            pages to read: base URL, then ?page=2, ?page=3 (default 1)
      skip_categories      IRSEM categories to ignore, e.g. [droit, société]
                           (accent/case-insensitive)
    The IRSEM category labels also give each item its newsletter theme(s)."""
    opts = options or {}
    max_pages = int(opts.get("max_pages", 1))
    skip = {fold(c) for c in (opts.get("skip_categories") or [])}
    items, seen = [], set()
    for page in range(1, max_pages + 1):
        page_url = url if page == 1 else f"{url}{'&' if '?' in url else '?'}page={page}"
        soup = _get_soup(session, page_url, "fr-FR,fr;q=0.9,en;q=0.8")
        by_href = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"]).split("#")[0].split("?")[0].rstrip("/")
            parts = urlsplit(href)
            if not parts.netloc.endswith("irsem.fr"):
                continue
            segs = [x for x in parts.path.split("/") if x]
            if len(segs) != 2 or segs[0] != "publications":
                continue
            by_href.setdefault(href, []).append(a)

        new_on_page = 0
        for href, anchors in by_href.items():
            if href in seen:
                continue
            node = anchors[0]
            while node.parent is not None and node.parent.name not in ("body", "html"):
                inside = {urljoin(url, x["href"]).split("#")[0].split("?")[0].rstrip("/")
                          for x in node.parent.find_all("a", href=True)} & set(by_href)
                if len(inside) > 1:
                    break
                node = node.parent
            seen.add(href)
            new_on_page += 1
            heading = node.find(["h1", "h2", "h3", "h4"])
            fallback = clean_text(heading.get_text(" ", strip=True)) if heading else _best_text(anchors)
            cats, title, label, date, reading_time = _irsem_parse_card(clean_text(node.get_text(" ", strip=True)), fallback)
            if len(title) < 8:
                continue
            if skip and any(fold(c) in skip for c in cats):
                continue
            hints = []
            for c in cats:
                t = _IRSEM_THEME_HINT.get(c.lower())
                if t and t not in hints:
                    hints.append(t)
            # Displayed as small text next to the date: "Étude 138 · 4 min de lecture".
            # IRSEM's own category labels and the authors are not shown.
            items.append({
                "title": title, "link": href, "date": date, "themes_hint": hints,
                "summary": "", "meta": [label, reading_time],
            })
        if new_on_page == 0:
            break
    return items


# Registry: maps the "parser" name used in sources.yaml to the function above.
PARSERS = {
    "ifri": ifri,
    "csis_program": csis_program,
    "cia_csi": cia_csi,
    "irsem": irsem,
}
