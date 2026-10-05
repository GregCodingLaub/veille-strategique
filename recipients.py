"""
Peer recipients for the newsletter, loaded from a Google Form + Sheet.

Setup (one-time, ~5 minutes, no coding):
  1. Create a Google Form with three fields:
       - "Nom"    (short answer)
       - "Email"  (short answer)
       - "Thèmes" (checkboxes) with exactly these three options:
           Renseignement
           Défense & Industrie militaire
           Énergie & Infrastructures
           Me désabonner      (optional but needed for unsubscribing: ticking
                               it removes the person from every list)
  2. In the Form's "Responses" tab, click the Sheets icon to create a
     linked Google Sheet.
  3. Open that Sheet -> File -> Share -> Publish to web -> choose the
     response sheet/tab -> format "Comma-separated values (.csv)" -> Publish.
  4. Copy the published URL (ends in "output=csv"). Set it as the
     RECIPIENTS_CSV_URL secret in the GitHub repo (Settings -> Secrets and
     variables -> Actions).
  5. Put the Form's normal "fill it in" URL (Form -> Send -> link icon) in
     the SIGNUP_FORM_URL secret -- this is what the "S'abonner" button on
     the site links to.

If RECIPIENTS_CSV_URL isn't set, this module just returns no peers --
the newsletter keeps working exactly as before, sent only to
RESEND_TO_EMAIL.

The published CSV is public-but-unlisted (anyone with the exact link can
read it), which is the normal/expected behavior of Google's "publish to
web" -- fine for a peer mailing list, not for sensitive data.
"""
import csv
import io
import os

import requests

from common import THEME_ORDER

# Exact checkbox labels used in the Google Form, mapped to this codebase's
# internal theme keys. Keep these in sync if you reword the Form options.
THEME_LABEL_TO_KEY = {
    "renseignement": "intelligence",
    "défense & industrie militaire": "military",
    "defense & industrie militaire": "military",  # no-accent fallback
    "énergie": "energy_industry",
    "energie": "energy_industry",  # no-accent fallback
    "énergie & infrastructures": "energy_industry",
    "energie & infrastructures": "energy_industry",
}
UNSUBSCRIBE_MARKERS = ("désabonner", "desabonner", "unsubscribe")


def _parse_themes_cell(raw):
    """A Google Forms checkbox answer lands in one cell as a comma-separated
    string, e.g. "Renseignement, Énergie". Match each piece against the
    known labels (case-insensitive) rather than trusting exact formatting."""
    if not raw:
        return []
    keys = []
    for piece in raw.split(","):
        label = piece.strip().lower()
        if any(m in label for m in UNSUBSCRIBE_MARKERS):
            return []  # "Me désabonner" ticked: no theme at all
        key = THEME_LABEL_TO_KEY.get(label)
        if key and key not in keys:
            keys.append(key)
    return keys


def _find_column(fieldnames, *candidates):
    """Case-insensitive, accent-tolerant match of a CSV header to one of the
    expected column names (Google Forms uses the exact question text as the
    header, so this is forgiving of small rewordings)."""
    low = {fn.lower().strip(): fn for fn in (fieldnames or [])}
    for cand in candidates:
        if cand in low:
            return low[cand]
    return None


def load_peer_recipients():
    """Returns {theme_key: [email, ...]} for all peers who checked that
    theme, deduplicated (last submission per email wins, so people can
    resubmit the form to update their preferences). Empty dict -- not an
    error -- if RECIPIENTS_CSV_URL isn't configured or the sheet is empty."""
    csv_url = os.environ.get("RECIPIENTS_CSV_URL")
    if not csv_url:
        return {}

    try:
        resp = requests.get(csv_url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: could not fetch RECIPIENTS_CSV_URL ({e}). Skipping peer recipients this run.")
        return {}

    reader = csv.DictReader(io.StringIO(resp.text))
    email_col = _find_column(reader.fieldnames, "email", "e-mail", "adresse email", "adresse e-mail")
    themes_col = _find_column(reader.fieldnames, "thèmes", "themes", "theme", "thème")

    if not email_col or not themes_col:
        print(
            f"WARNING: RECIPIENTS_CSV_URL doesn't have the expected columns "
            f"(found: {reader.fieldnames}). Skipping peer recipients this run."
        )
        return {}

    # email -> set of theme keys. A dict (not a list of rows) so a later
    # resubmission from the same address overwrites their earlier answer.
    by_email = {}
    for row in reader:
        email = (row.get(email_col) or "").strip().lower()
        if not email or "@" not in email:
            continue
        by_email[email] = set(_parse_themes_cell(row.get(themes_col)))

    peers_by_theme = {t: [] for t in THEME_ORDER}
    for email, themes in by_email.items():
        for t in themes:
            if t in peers_by_theme:
                peers_by_theme[t].append(email)

    return peers_by_theme
