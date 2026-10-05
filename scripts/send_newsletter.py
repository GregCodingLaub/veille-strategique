"""
Send THREE separate weekly digest emails via Resend (https://resend.com,
free tier) -- one per theme (Renseignement, Défense & Industrie militaire,
Énergie) -- instead of one combined newsletter. Each is self-contained and
grouped by subject region (France, EU, US, China, Middle East & Africa).
An item relevant to more than one theme can appear in more than one
newsletter -- that's expected, since each is independent.

Every sent edition is logged to data/newsletter_log.json (now tagged with
its theme) so the website's "past editions" dashboard can show/filter them.

Two modes:

  OFFICIAL (default, used by the Monday cron): always sends, whatever
  happened before. Each theme's last-sent date (data/state.json) is only
  used to pick which items are new, plus a duplicate guard: if that theme
  was officially sent less than MIN_HOURS_BETWEEN hours ago (e.g. someone
  re-ran a finished workflow), it is skipped. Peers are Bcc'd, the state
  and the edition log are updated.

  TEST (--test, used by manual workflow runs): sends ONLY to
  RESEND_TO_EMAIL, never to peers, subject prefixed "[TEST]". Contains
  exactly what the next official send would contain, and touches neither
  data/state.json nor data/newsletter_log.json, so it can be run as often
  as you like without affecting the Monday edition.

Requires environment variables (set as GitHub Actions secrets):
  RESEND_API_KEY    - your Resend API key
  RESEND_TO_EMAIL   - the email address to send the digests to (you).
                       Stays the single visible "To:" address.
  RESEND_FROM_EMAIL - sender address. If you haven't verified your own domain
                       on Resend, use "onboarding@resend.dev" (works out of the box).
  SITE_URL          - optional. Your GitHub Pages URL. When set, each
                       region section links to that region+theme
                       pre-filtered on the live site.
  RECIPIENTS_CSV_URL - optional. A published Google Sheet CSV of peer
                       signups (see recipients.py for the one-time setup).
                       Each theme's edition is Bcc'd to whichever peers
                       picked that theme, so peers never see each other's
                       (or your) address. Unset -> behaves exactly as
                       before, sent only to RESEND_TO_EMAIL.

If RESEND_API_KEY is not set, this script just prints what it WOULD send
for each theme and exits -- safe to run locally without secrets configured.

Usage:
  python scripts/send_newsletter.py            official send (all themes, peers in Bcc)
  python scripts/send_newsletter.py --test      test send to RESEND_TO_EMAIL only,
                                                 no state/log change
Neither mode sends anything without RESEND_API_KEY set (dry run instead).
"""
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import (
    load_items, load_state, save_state, append_newsletter_log,
    REGION_ORDER, REGION_LABELS, source_region_of, SOURCE_PERSPECTIVE,
    THEME_ORDER, THEME_LABELS,
)
from recipients import load_peer_recipients

MIN_HOURS_BETWEEN = 20  # duplicate guard only (official mode): refuse a second
                         # official send of the same theme within 20h. Does NOT
                         # delay the weekly edition.
MAX_PER_SOURCE = 6     # cap items from any single source in one email edition

# Fallback site link used if the SITE_URL secret isn't set in GitHub, so the
# email always links to the site regardless of whether that secret exists.
# Set the real SITE_URL secret to override this if your Pages URL differs.
DEFAULT_SITE_URL = "https://gregcodinglaub.github.io/veille-strategique/"


def hours_since(iso_date_str):
    if not iso_date_str:
        return None
    then = datetime.fromisoformat(iso_date_str)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


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


def group_by_region(items):
    """{region: [items]} for a SINGLE theme's items -- no theme sub-grouping
    needed since the whole newsletter is already one theme."""
    groups = {r: [] for r in REGION_ORDER}
    for it in items:
        region = it.get("subject_region", "other")
        if region not in groups:
            region = "other"
        groups[region].append(it)
    return groups


def render_item_row(it):
    code, color = SOURCE_PERSPECTIVE.get(source_region_of(it), SOURCE_PERSPECTIVE["other"])
    tag = (
        f'<span style="display:inline-block;color:{color};font-size:11px;'
        f'font-weight:700;letter-spacing:0.02em;margin-right:6px;">[{code}]</span>'
    )
    return f"""
    <div style="padding:14px 0;border-bottom:1px solid #2a2a2a;">
      <a href="{it['link']}" style="font-size:15px;font-weight:600;color:#f5f5f5;text-decoration:none;line-height:1.4;">{tag}{it['title']}</a>
      <div style="color:#8a8a8a;font-size:12px;margin-top:5px;">{it['source']} · {it.get('date') or ''}</div>
    </div>"""


def build_email_html(theme, items, overflow_count=0, site_url=None):
    site_url = site_url or DEFAULT_SITE_URL
    grouped = group_by_region(items)
    region_blocks = []

    for region in REGION_ORDER:
        region_items = grouped[region]
        if not region_items:
            continue

        rows = "".join(render_item_row(it) for it in region_items)
        sep = "&" if "?" in site_url else "?"
        region_link = (
            f'<a href="{site_url}{sep}region={region}&theme={theme}" '
            f'style="color:#93c5fd;font-size:12px;text-decoration:none;font-weight:normal;">'
            f'→ voir sur le site</a>'
        )

        region_blocks.append(f"""
        <div style="margin-bottom:32px;">
          <div style="display:flex;align-items:baseline;justify-content:space-between;
                      border-bottom:2px solid #333;padding-bottom:8px;margin-bottom:16px;">
            <h3 style="margin:0;font-size:17px;color:#fff;">{REGION_LABELS[region]} · {len(region_items)}</h3>
            {region_link}
          </div>
          {rows}
        </div>""")

    body = "\n".join(region_blocks) if region_blocks else (
        "<p style='color:#999;'>Aucune nouvelle publication pertinente cette semaine.</p>"
    )

    overflow_note = ""
    if overflow_count:
        overflow_note = (
            f'<p style="color:#777;font-size:12px;margin-top:8px;">'
            f'+{overflow_count} autres publications (limite de {MAX_PER_SOURCE}/source '
            f'par édition) — disponibles sur le site.</p>'
        )

    sep = "&" if "?" in site_url else "?"
    site_link = (
        f'<p style="margin-top:24px;">'
        f'<a href="{site_url}{sep}theme={theme}" style="color:#93c5fd;font-size:13px;text-decoration:none;">'
        f'→ Voir l\'archive complète en ligne</a></p>'
    )

    theme_label = THEME_LABELS[theme]
    return f"""
    <div style="background:#0f1115;color:#eee;font-family:-apple-system,Helvetica,Arial,sans-serif;padding:28px;max-width:600px;margin:0 auto;">
      <h2 style="margin:0 0 4px;font-size:20px;">🛰 Veille Stratégique — {theme_label}</h2>
      <p style="color:#8a8a8a;font-size:13px;margin:0 0 24px;">newsletter Grégoire Laubry · {datetime.now().strftime('%d/%m/%Y')} · {len(items)} publications</p>
      {body}
      {overflow_note}
      {site_link}
    </div>"""


def send_one_theme(theme, state, test, peers_by_theme):
    last_sent = state["last_newsletter_sent"].get(theme)
    elapsed = hours_since(last_sent)

    if not test and elapsed is not None and elapsed < MIN_HOURS_BETWEEN:
        print(f"[{theme}] Officially sent {elapsed:.1f}h ago (< {MIN_HOURS_BETWEEN}h): duplicate guard, skipping.")
        return

    all_items = load_items()
    new_items = [
        it for it in all_items
        if theme in (it.get("themes") or [])
        and (last_sent is None or it.get("fetched_at", "") > last_sent)
    ]
    capped_items, overflow = cap_per_source(new_items, MAX_PER_SOURCE)
    if overflow:
        print(f"[{theme}] Capped: {len(capped_items)} shown, {overflow} held back (per-source limit {MAX_PER_SOURCE}).")

    api_key = os.environ.get("RESEND_API_KEY")
    to_email = os.environ.get("RESEND_TO_EMAIL")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    site_url = os.environ.get("SITE_URL")

    html = build_email_html(theme, capped_items, overflow_count=overflow, site_url=site_url)
    theme_label = THEME_LABELS[theme]

    if not api_key or not to_email:
        print(f"[{theme}] RESEND_API_KEY / RESEND_TO_EMAIL not set -- DRY RUN, not sending.")
        print(f"[{theme}] Would send {len(capped_items)} items (+{overflow} held back).")
        return

    # Peers who picked this theme via the signup form, minus the owner
    # (in case they also signed up themselves) and de-duplicated.
    # In test mode peers are never contacted.
    peer_emails = [] if test else sorted({
        e for e in peers_by_theme.get(theme, [])
        if e.lower() != to_email.lower()
    })

    subject_prefix = "[TEST] " if test else ""
    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": f"{subject_prefix}Veille Stratégique — {theme_label} — {datetime.now().strftime('%d/%m/%Y')} ({len(capped_items)} nouveautés)",
        "html": html,
    }
    if peer_emails:
        payload["bcc"] = peer_emails

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=20,
    )

    if resp.status_code >= 300:
        print(f"[{theme}] Resend API error {resp.status_code}: {resp.text}")
        return  # don't crash the whole run over one theme's send failure

    peer_note = f" + {len(peer_emails)} peer(s) in Bcc" if peer_emails else ""
    mode_note = "TEST, to owner only; state and log untouched" if test else "official"
    print(f"[{theme}] Sent ({mode_note}) with {len(capped_items)} items shown ({overflow} held back){peer_note}.")

    if test:
        return  # a test must never move the "last official send" marker

    now_iso = datetime.now(timezone.utc).isoformat()
    state["last_newsletter_sent"][theme] = now_iso

    append_newsletter_log({
        "date": now_iso,
        "theme": theme,
        "item_count": len(capped_items),
        "overflow_count": overflow,
        "item_ids": [it["id"] for it in capped_items],
    })


def main():
    test = "--test" in sys.argv
    if test:
        print("TEST MODE: sending to RESEND_TO_EMAIL only; state and edition log will not be modified.")
    state = load_state()
    peers_by_theme = load_peer_recipients()
    total_peers = len({e for emails in peers_by_theme.values() for e in emails})
    if total_peers:
        print(f"Loaded {total_peers} peer recipient(s) across all themes from RECIPIENTS_CSV_URL.")

    for theme in THEME_ORDER:
        send_one_theme(theme, state, test, peers_by_theme)

    if not test:
        save_state(state)


if __name__ == "__main__":
    main()
