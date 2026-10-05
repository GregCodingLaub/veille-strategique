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

from common import parse_date_from_text, clean_text

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_soup(session, url, lang="en-US,en;q=0.9"):
    resp = session.get(
        url, timeout=25,
        headers={"User-Agent": USER_AGENT, "Accept-Language": lang,
                 "Accept": "text/html,application/xhtml+xml"},
    )
    resp.raise_for_status()
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
        soup = _get_soup(session, page_url)
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


# Registry: maps the "parser" name used in sources.yaml to the function above.
PARSERS = {
    "ifri": ifri,
    "csis_program": csis_program,
    "cia_csi": cia_csi,
}
