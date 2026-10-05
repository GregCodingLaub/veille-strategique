"""
Fetch an institution's posts from Bluesky's public API (no auth needed).

Many think tanks that block simple RSS scraping (Cloudflare bot protection,
broken certs, no feed at all) maintain official Bluesky accounts and post
links to their own publications there. Bluesky's public AppView API is
unauthenticated, stable, and not affected by the target institution's own
site protections -- so this is often more reliable than scraping them
directly.

In sources.yaml, use:
  type: bluesky
  url: "csis.org"     <- this is the Bluesky HANDLE, not a URL despite the
                          field name (kept as `url` so fetch.py's dispatch
                          logic doesn't need a special case).
  allowed_domains:      <- OPTIONAL but recommended. Restricts accepted
    - "csis.org"           links to these domain(s), so a post linking to
                            a co-authored paper hosted elsewhere (an
                            academic journal platform, a news writeup
                            about them, etc.) doesn't get pulled in as if
                            it were the institution's own publication.
                            Omit to accept links to any domain.

Many institutions use their own domain as their Bluesky handle (e.g.
csis.org, sipri.org, carnegieendowment.org) -- if unsure, search
"<institution> bsky.app" to find their real handle.
"""
from urllib.parse import urlparse

API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def fetch_bluesky(session, handle, limit=30, allowed_domains=None):
    resp = session.get(
        API,
        params={"actor": handle, "limit": limit},
        headers={"Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    items = []
    for entry in data.get("feed", []):
        post = entry.get("post", {})
        record = post.get("record", {})
        text = (record.get("text") or "").strip()
        created = record.get("createdAt", "")
        date = created[:10] if created else None

        embed = record.get("embed") or {}
        if embed.get("$type", "").startswith("app.bsky.embed.recordWithMedia"):
            embed = embed.get("media") or {}
        external = embed.get("external") or {}
        link = external.get("uri")
        title = external.get("title")
        summary = external.get("description") or text

        # Only keep posts that share an actual link card (an article, report,
        # or event page). Plain-text posts, replies, and comments without a
        # shared link are just chatter, not publications -- skip them.
        if not link or not title:
            continue

        # If allowed_domains is set, only keep links that actually point
        # back to the institution's own site -- not a co-authored paper on
        # a journal platform, a third-party writeup, an event host, etc.
        domain = urlparse(link).netloc.lower().split(":")[0]
        if domain.endswith("bsky.app"):
            continue  # a link to another Bluesky post is chatter, not a publication
        if allowed_domains:
            # exact domain or sub-domain ("rand.org" must not match "brand.org")
            if not any(domain == a or domain.endswith("." + a) for a in (d.lower() for d in allowed_domains)):
                continue

        items.append({
            "title": title,
            "link": link,
            "date": date,
            "summary": (summary or "")[:500],
        })

    return items
