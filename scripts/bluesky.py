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

Many institutions use their own domain as their Bluesky handle (e.g.
csis.org, sipri.org, carnegieendowment.org) -- if unsure, search
"<institution> bsky.app" to find their real handle.
"""
API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def fetch_bluesky(session, handle, limit=30):
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
        external = embed.get("external") or {}
        link = external.get("uri")
        title = external.get("title") or (text[:120] if text else None)
        summary = external.get("description") or text

        if not link:
            # No shared link card -- fall back to a permalink for the post itself.
            uri = post.get("uri", "")
            rkey = uri.rsplit("/", 1)[-1] if uri else None
            author_handle = post.get("author", {}).get("handle", handle)
            link = f"https://bsky.app/profile/{author_handle}/post/{rkey}" if rkey else None

        if not link or not title:
            continue

        items.append({
            "title": title,
            "link": link,
            "date": date,
            "summary": (summary or "")[:500],
        })

    return items
