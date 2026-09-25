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


def build_email_html(items):
    rows = []
    for it in items:
        tags = ", ".join(THEME_LABELS.get(t, t) for t in it.get("themes", []))
        rows.append(f"""
        <div style="margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid #333;">
          <a href="{it['link']}" style="font-size:16px;font-weight:600;color:#fff;text-decoration:none;">{it['title']}</a>
          <div style="color:#999;font-size:12px;margin-top:4px;">{it['source']} · {it.get('date') or ''} · {tags}</div>
        </div>""")
    body = "\n".join(rows) if rows else "<p>Aucune nouvelle publication pertinente cette quinzaine.</p>"
    return f"""
    <div style="background:#111;color:#eee;font-family:Helvetica,Arial,sans-serif;padding:24px;">
      <h2 style="margin-top:0;">🛰 Veille Stratégique — {datetime.now().strftime('%d/%m/%Y')}</h2>
      <p style="color:#999;font-size:13px;">{len(items)} nouvelles publications depuis le dernier envoi.</p>
      {body}
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

    api_key = os.environ.get("RESEND_API_KEY")
    to_email = os.environ.get("RESEND_TO_EMAIL")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    html = build_email_html(new_items)

    if not api_key or not to_email:
        print("RESEND_API_KEY / RESEND_TO_EMAIL not set -- DRY RUN, not sending.")
        print(f"Would send digest with {len(new_items)} items to (unset).")
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

    print(f"Newsletter sent with {len(new_items)} items.")
    state["last_newsletter_sent"] = datetime.now(timezone.utc).isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
