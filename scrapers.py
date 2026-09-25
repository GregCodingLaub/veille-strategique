"""
Custom scrapers for sources with NO usable RSS feed.

Each function takes a `requests.Session` and the source's `url` (from
sources.yaml) and returns a list of dicts: [{title, link, date, summary}, ...]
`date` should be an ISO string "YYYY-MM-DD" if known, else None.

To add a new non-RSS source:
  1. Write a new function here, name it something short (e.g. `irsem2`).
  2. In sources.yaml, set type: scrape and parser: <function name>.
  3. Run `python scripts/validate_sources.py` to check it actually returns items.

NOTE: These scrapers depend on the site's current HTML structure. If a
source stops returning items, the site is likely redesigned — inspect
the page and update the CSS selectors below. This is the normal
maintenance cost of scraping (see README).
"""
from bs4 import BeautifulSoup


def ifri(session, url):
    """IFRI has no RSS feed; parse the publications listing page."""
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    # IFRI publication listing items are article/teaser blocks with a title
    # link. Structure may shift over time -- this targets the common
    # Drupal "views-row" teaser pattern.
    for row in soup.select(".views-row, article"):
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True)
        if not title or len(title) < 8:
            continue
        href = link_tag["href"]
        if href.startswith("/"):
            href = "https://www.ifri.org" + href

        date_tag = row.find("time")
        date = date_tag.get("datetime", "")[:10] if date_tag else None

        summary_tag = row.find("p")
        summary = summary_tag.get_text(strip=True) if summary_tag else ""

        items.append({
            "title": title,
            "link": href,
            "date": date,
            "summary": summary,
        })

    return items


# Registry: maps the "parser" name used in sources.yaml to the function above.
PARSERS = {
    "ifri": ifri,
}
