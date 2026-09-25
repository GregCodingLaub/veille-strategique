"""
Send the bi-weekly digest email via Resend (https://resend.com, free tier).

Cadence logic: sends only if >= MIN_DAYS_BETWEEN days have passed since the
last successful send (tracked in data/state.json). This is self-healing --
if a run is skipped or fails, the next run will still send on schedule
rather than drifting. First-ever run sends immediately and sets the baseline.

Requires environment variables (set as GitHub Actions secrets):
  RESEND_API_KEY   - your Resend API key
  RESEND_TO_EMAIL  - the email address to send the digest to (you)
  RESEND_FROM_EMAIL- sender address. If you haven't verified your own domain
                     on Resend, use "onboarding@resend.dev" (works out of the box).

If RESEND_API_KEY is not set, this script just prints what it WOULD send
and exits -- safe to run locally without secrets configured.
"""
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import load_items, load_state, save_state

MIN_DAYS_BETWEEN = 13  # slightly under 14 to tolerate schedule jitter
MAX_PER_SOURCE = 6     # cap items from any single source in one email edition

THEME_LABELS = {
    "defense": "Défense",
    "competitive_intelligence": "Intelligence économique",
    "intelligence": "Renseignement",
    "weapons_industry": "Industrie de l'armement",
    "energy_industry": "Énergie",
}


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


def build_email_html(items, overflow_count=0):
    rows = []
    for it in items:
        tags = ", ".join(THEME_LABELS.get(t, t) for t in it.get("themes", []))
        rows.append(f"""
        <div style="margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid #333;">
          <a href="{it['link']}" style="font-size:16px;font-weight:600;color:#fff;text-decoration:none;">{it['title']}</a>
          <div style="color:#999;font-size:12px;margin-top:4px;">{it['source']} · {it.get('date') or ''} · {tags}</div>
        </div>""")
    body = "\n".join(rows) if rows else "<p>Aucune nouvelle publication pertinente cette quinzaine.</p>"
    overflow_note = ""
    if overflow_count:
        overflow_note = (
            f'<p style="color:#999;font-size:12px;">+{overflow_count} autres publications '
            f'(limite de {MAX_PER_SOURCE}/source dans cet e-mail) — voir le site pour la liste complète.</p>'
        )
    return f"""
    <div style="background:#111;color:#eee;font-family:Helvetica,Arial,sans-serif;padding:24px;">
      <h2 style="margin-top:0;">🛰 Veille Stratégique — {datetime.now().strftime('%d/%m/%Y')}</h2>
      <p style="color:#999;font-size:13px;">{len(items)} publications affichées ci-dessous.</p>
      {body}
      {overflow_note}
    </div>"""


def main():
    state = load_state()
    last_sent = state.get("last_newsletter_sent")
    elapsed = days_since(last_sent)

    if elapsed is not None and elapsed < MIN_DAYS_BETWEEN:
        print(f"Last newsletter sent {elapsed} day(s) ago (< {MIN_DAYS_BETWEEN}). Skipping.")
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

    html = build_email_html(capped_items, overflow_count=overflow)

    if not api_key or not to_email:
        print("RESEND_API_KEY / RESEND_TO_EMAIL not set -- DRY RUN, not sending.")
        print(f"Would send digest with {len(capped_items)} items (+{overflow} held back) to (unset).")
        return

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_email,
            "to": [to_email],
            "subject": f"Veille Stratégique — {datetime.now().strftime('%d/%m/%Y')} ({len(new_items)} nouveautés)",
            "html": html,
        },
        timeout=20,
    )

    if resp.status_code >= 300:
        print(f"Resend API error {resp.status_code}: {resp.text}")
        sys.exit(1)

    print(f"Newsletter sent with {len(capped_items)} items shown ({overflow} held back).")
    state["last_newsletter_sent"] = datetime.now(timezone.utc).isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
