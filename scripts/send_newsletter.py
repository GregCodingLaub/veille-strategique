"""
Send the bi-weekly digest email via Resend (https://resend.com, free tier),
and log every sent edition to data/newsletter_log.json so the website can
show a "past editions" dashboard (see build_site.py).

Cadence logic: sends only if >= MIN_DAYS_BETWEEN days have passed since the
last successful send (tracked in data/state.json). This is self-healing --
if a run is skipped or fails, the next run will still send on schedule
rather than drifting. First-ever run sends immediately and sets the baseline.

Requires environment variables (set as GitHub Actions secrets):
  RESEND_API_KEY    - your Resend API key
  RESEND_TO_EMAIL   - the email address to send the digest to (you)
  RESEND_FROM_EMAIL - sender address. If you haven't verified your own domain
                       on Resend, use "onboarding@resend.dev" (works out of the box).
  SITE_URL          - optional. Your GitHub Pages URL, linked at the bottom
                       of the email ("view full archive online").

If RESEND_API_KEY is not set, this script just prints what it WOULD send
and exits -- safe to run locally without secrets configured.

Usage:
  python scripts/send_newsletter.py            normal run (respects cadence)
  python scripts/send_newsletter.py --force     ignore the day-count check,
                                                 useful for testing locally.
                                                 Still won't send without
                                                 RESEND_API_KEY set.
"""
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import load_items, load_state, save_state, append_newsletter_log

MIN_DAYS_BETWEEN = 6  # slightly under 14 to tolerate schedule jitter
MAX_PER_SOURCE = 6     # cap items from any single source in one email edition

THEME_LABELS = {
    "defense": "Défense",
    "competitive_intelligence": "Intelligence économique",
    "intelligence": "Renseignement",
    "weapons_industry": "Industrie de l'armement",
    "energy_industry": "Énergie",
}
THEME_ORDER = list(THEME_LABELS.keys())


def days_since(iso_date_str):
    if not iso_date_str:
        return None
    then = datetime.fromisoformat(iso_date_str)
    return (datetime.now(timezone.utc) - then).days


def cap_per_source(items, max_per_source):
    """Keep at most `max_per_source` items per source (most recent first,
    since items are already sorted newest-first). Returns (kept, overflow_count)."""
    counts = {}
    kept = []
    overflow = 0
    for it in items:
        src = it["source"]
        counts[src] = counts.get(src, 0)
        if counts[src] < max_per_source:
            kept.append(it)
            counts[src] += 1
        else:
            overflow += 1
    return kept, overflow


def group_by_theme(items):
    """Each item can carry multiple themes; group under its FIRST matched
    theme only, so every item appears exactly once in the email."""
    groups = {t: [] for t in THEME_ORDER}
    for it in items:
        themes = it.get("themes") or []
        primary = next((t for t in THEME_ORDER if t in themes), None)
        if primary:
            groups[primary].append(it)
    return groups


def build_email_html(items, overflow_count=0, site_url=None):
    groups = group_by_theme(items)
    section_blocks = []

    for theme in THEME_ORDER:
        theme_items = groups[theme]
        if not theme_items:
            continue
        rows = []
        for it in theme_items:
            rows.append(f"""
            <div style="padding:14px 0;border-bottom:1px solid #2a2a2a;">
              <a href="{it['link']}" style="font-size:15px;font-weight:600;color:#f5f5f5;text-decoration:none;line-height:1.4;">{it['title']}</a>
              <div style="color:#8a8a8a;font-size:12px;margin-top:5px;">{it['source']} · {it.get('date') or ''}</div>
            </div>""")
        section_blocks.append(f"""
        <div style="margin-bottom:28px;">
          <div style="display:inline-block;background:#1f2937;color:#93c5fd;font-size:11px;
                      font-weight:600;letter-spacing:0.03em;text-transform:uppercase;
                      padding:4px 10px;border-radius:12px;margin-bottom:10px;">
            {THEME_LABELS[theme]} · {len(theme_items)}
          </div>
          {''.join(rows)}
        </div>""")

    body = "\n".join(section_blocks) if section_blocks else (
        "<p style='color:#999;'>Aucune nouvelle publication pertinente cette quinzaine.</p>"
    )

    overflow_note = ""
    if overflow_count:
        overflow_note = (
            f'<p style="color:#777;font-size:12px;margin-top:8px;">'
            f'+{overflow_count} autres publications (limite de {MAX_PER_SOURCE}/source '
            f'par édition) — disponibles sur le site.</p>'
        )

    site_link = ""
    if site_url:
        site_link = (
            f'<p style="margin-top:24px;">'
            f'<a href="{site_url}" style="color:#93c5fd;font-size:13px;text-decoration:none;">'
            f'→ Voir l\'archive complète en ligne</a></p>'
        )

    return f"""
    <div style="background:#0f1115;color:#eee;font-family:-apple-system,Helvetica,Arial,sans-serif;padding:28px;max-width:600px;margin:0 auto;">
      <h2 style="margin:0 0 4px;font-size:20px;">🛰 Veille Stratégique</h2>
      <p style="color:#8a8a8a;font-size:13px;margin:0 0 24px;">{datetime.now().strftime('%d/%m/%Y')} · {len(items)} publications</p>
      {body}
      {overflow_note}
      {site_link}
    </div>"""


def main():
    force = "--force" in sys.argv

    state = load_state()
    last_sent = state.get("last_newsletter_sent")
    elapsed = days_since(last_sent)

    if not force and elapsed is not None and elapsed < MIN_DAYS_BETWEEN:
        print(f"Last newsletter sent {elapsed} day(s) ago (< {MIN_DAYS_BETWEEN}). Skipping.")
        print("(use --force to override for local testing)")
        return

    all_items = load_items()
    new_items = [
        it for it in all_items
        if last_sent is None or it.get("fetched_at", "") > last_sent
    ]
    capped_items, overflow = cap_per_source(new_items, MAX_PER_SOURCE)
    if overflow:
        print(f"Capped digest: {len(capped_items)} shown, {overflow} held back (per-source limit {MAX_PER_SOURCE}).")

    api_key = os.environ.get("RESEND_API_KEY")
    to_email = os.environ.get("RESEND_TO_EMAIL")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    site_url = os.environ.get("SITE_URL")

    html = build_email_html(capped_items, overflow_count=overflow, site_url=site_url)

    if not api_key or not to_email:
        print("RESEND_API_KEY / RESEND_TO_EMAIL not set -- DRY RUN, not sending.")
        print(f"Would send digest with {len(capped_items)} items (+{overflow} held back).")
        return

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_email,
            "to": [to_email],
            "subject": f"Veille Stratégique — {datetime.now().strftime('%d/%m/%Y')} ({len(capped_items)} nouveautés)",
            "html": html,
        },
        timeout=20,
    )

    if resp.status_code >= 300:
        print(f"Resend API error {resp.status_code}: {resp.text}")
        sys.exit(1)

    print(f"Newsletter sent with {len(capped_items)} items shown ({overflow} held back).")

    now_iso = datetime.now(timezone.utc).isoformat()
    state["last_newsletter_sent"] = now_iso
    save_state(state)

    append_newsletter_log({
        "date": now_iso,
        "item_count": len(capped_items),
        "overflow_count": overflow,
        "item_ids": [it["id"] for it in capped_items],
    })


if __name__ == "__main__":
    main()
