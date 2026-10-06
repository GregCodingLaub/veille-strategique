"""
Send the three weekly newsletters (one per theme) through Resend.

Two modes
  OFFICIAL (default; the Monday cron and manual runs with "official_send")
      Sends each theme to the owner AND to the peers who picked it. Every
      peer gets an individual message (nobody sees anybody else's address).
      On success the theme's "last sent" date (data/state.json) and the
      edition log (data/newsletter_log.json) are updated, immediately, so a
      crash on theme 3 never makes themes 1-2 go out twice.
      A theme with no new item is SKIPPED (no empty email) and does not
      count as an edition.
  TEST (--test; manual runs by default)
      Sends only to RESEND_TO_EMAIL, subject prefixed [TEST], and touches
      neither state.json nor newsletter_log.json: run it as often as needed.

Environment (GitHub Actions secrets)
  Transport (one of the two; SMTP wins when SMTP_USER and SMTP_PASSWORD are set):
    SMTP_USER, SMTP_PASSWORD   e.g. a dedicated Gmail account + its "app password".
    SMTP_FROM_NAME             display name (default "Veille stratégique").
    SMTP_HOST, SMTP_PORT       default smtp.gmail.com, 465 (SSL).
    RESEND_API_KEY             Resend API key (needs a verified domain for peers).
  Neither configured -> dry run (prints, sends nothing).
  OWNER_EMAIL         (or RESEND_TO_EMAIL) the owner's address, always receives every edition.
  RESEND_FROM_EMAIL   sender. "onboarding@resend.dev" only delivers to the
                      Resend account owner: with it, peers are NOT contacted
                      (a warning is printed). Verify a domain on Resend to
                      write to peers.
  SITE_URL            GitHub Pages URL (links to the site, pre-filtered).
  RECIPIENTS_CSV_URL  published Google Sheet CSV of peers (see recipients.py).
  SIGNUP_FORM_URL     the signup form: used as the unsubscribe / change-my-themes
                      link in the footer and in the List-Unsubscribe header.

After the sends, a short "sources to check" email goes to the owner when the
health file shows a broken or silent source (see health.py).

Exit code: 1 if any send failed, so the run is visibly red; the workflow
still commits whatever state was saved.
"""
import os
import smtplib
import ssl
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    load_items, load_state, save_state, load_newsletter_log, append_newsletter_log,
    load_health, load_sources, load_keywords, primary_theme, edition_number,
    THEME_ORDER, THEME_LABELS,
)
from dedupe import cluster, representative  # noqa: E402
from email_render import build_email_html, build_email_text, date_fr  # noqa: E402
from health import health_problems  # noqa: E402
from recipients import load_peer_recipients  # noqa: E402

RESEND_BATCH_URL = "https://api.resend.com/emails/batch"
RESEND_URL = "https://api.resend.com/emails"
MIN_HOURS_BETWEEN = 20     # duplicate guard (official only): same theme twice within 20h
MAX_PER_SOURCE = 6         # cap per source in one edition
FIRST_EDITION_DAYS = 21    # window when a theme was never sent / was sent long ago
DAILY_LIMIT_WARNING = 90   # Resend free tier: 100 emails/day

DEFAULT_SITE_URL = "https://gregcodinglaub.github.io/veille-strategique/"


def hours_since(iso):
    if not iso:
        return None
    then = datetime.fromisoformat(iso)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def select_items(theme, items, last_sent, now):
    """New items of `theme` since the last official send (at most
    FIRST_EDITION_DAYS back), newest first, capped per source.
    Returns (kept, overflow)."""
    floor = (now - timedelta(days=FIRST_EDITION_DAYS)).isoformat()
    since = max(last_sent, floor) if last_sent else floor
    new = [it for it in items
           if theme in (it.get("themes") or []) and (it.get("fetched_at") or "") > since]
    new.sort(key=lambda it: (it.get("date") or "", it.get("fetched_at") or ""), reverse=True)
    counts, kept, overflow = {}, [], 0
    for it in new:
        n = counts.get(it["source"], 0)
        if n < MAX_PER_SOURCE:
            kept.append(it)
            counts[it["source"]] = n + 1
        else:
            overflow += 1
    return kept, overflow


def cap_per_source(items):
    """Newest first, at most MAX_PER_SOURCE per source. Returns (kept, overflow)."""
    items = sorted(items, key=lambda it: (it.get("date") or "", it.get("fetched_at") or ""), reverse=True)
    counts, kept, overflow = {}, [], 0
    for it in items:
        n = counts.get(it["source"], 0)
        if n < MAX_PER_SOURCE:
            kept.append(it)
            counts[it["source"]] = n + 1
        else:
            overflow += 1
    return kept, overflow


def plan_editions(items, state, log, now, keywords):
    """Decide what goes in which newsletter, once for all three.

    - each item belongs to ONE newsletter (its primary theme: most keyword hits,
      or the theme its source vouches for), so a story is never in two editions;
    - items about the same story (same or another source, French or English) are
      merged: one entry, with "aussi : <other sources>";
    - a story already sent in the last 14 days is not sent again.
    Returns {theme: (items, overflow)}."""
    floor = (now - timedelta(days=FIRST_EDITION_DAYS)).isoformat()
    since = {}
    for t in THEME_ORDER:
        last = state["last_newsletter_sent"].get(t)
        since[t] = max(last, floor) if last else floor

    eligible = []
    for it in items:
        prim = primary_theme(it, keywords)
        if prim and (it.get("fetched_at") or "") > since[prim]:
            eligible.append((it, prim))

    by_id = {it["id"]: it for it in items}
    recent = (now - timedelta(days=14)).isoformat()
    already = [by_id[i] for e in log if (e.get("date") or "") > recent
               for i in e.get("item_ids", []) if i in by_id]
    already_ids = {it["id"] for it in already}

    prim_of = {it["id"]: p for it, p in eligible}
    pool = [it for it, _ in eligible] + [it for it in already if it["id"] not in prim_of]
    plan = {t: [] for t in THEME_ORDER}
    for group in cluster(pool):
        if any(it["id"] in already_ids for it in group):
            continue                       # story already covered by a recent edition
        rep = representative(group)
        also = sorted({it["source"] for it in group if it["source"] != rep["source"]})
        entry = dict(rep, also=also)
        plan[prim_of[rep["id"]]].append(entry)
    return {t: cap_per_source(plan[t]) for t in THEME_ORDER}


def _post(url, api_key, payload, attempts=2):
    last = None
    for i in range(attempts):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload, timeout=30)
            if r.status_code < 300:
                return True, r.text
            last = f"{r.status_code} {r.text[:300]}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (i + 1))
    return False, last


def smtp_settings():
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not (user and pw):
        return None
    return {"user": user, "password": pw,
            "name": os.environ.get("SMTP_FROM_NAME") or "Veille stratégique",
            "host": os.environ.get("SMTP_HOST") or "smtp.gmail.com",
            "port": int(os.environ.get("SMTP_PORT") or 465)}


def to_mime(msg, sender):
    """Resend-style payload dict -> email.message.EmailMessage."""
    m = EmailMessage()
    m["From"] = sender
    m["To"] = ", ".join(msg["to"])
    m["Subject"] = msg["subject"]
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].rstrip(">"))
    if msg.get("reply_to"):
        m["Reply-To"] = msg["reply_to"]
    for k, v in (msg.get("headers") or {}).items():
        m[k] = v
    m.set_content(msg.get("text") or "")
    if msg.get("html"):
        m.add_alternative(msg["html"], subtype="html")
    return m


def send_smtp(cfg, messages):
    """Send over one SSL connection (re-opened once if the server drops it).
    Returns (n_sent, [errors])."""
    sender = formataddr((cfg["name"], cfg["user"]))
    sent, errors = 0, []
    server = None
    try:
        for msg in messages:
            for attempt in (1, 2):
                try:
                    if server is None:
                        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30,
                                                  context=ssl.create_default_context())
                        server.login(cfg["user"], cfg["password"])
                    server.send_message(to_mime(msg, sender))
                    sent += 1
                    break
                except smtplib.SMTPServerDisconnected:
                    server = None
                    if attempt == 2:
                        errors.append(f"{msg['to']}: connection lost")
                except smtplib.SMTPAuthenticationError as e:
                    errors.append(f"login refused ({e.smtp_code}): check SMTP_USER / app password")
                    return sent, errors
                except (smtplib.SMTPException, OSError) as e:
                    errors.append(f"{msg['to']}: {e}")
                    break
            time.sleep(0.4)
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
    return sent, errors


def deliver(ctx, messages):
    """Send through the configured transport. Returns (n_sent, [errors])."""
    if ctx["smtp"]:
        return send_smtp(ctx["smtp"], messages)
    return send_messages(ctx["api_key"], messages)


def send_messages(api_key, messages):
    """Send a list of Resend payloads (batches of 100, falling back to single
    sends if a batch is refused). Returns (n_sent, [errors])."""
    sent, errors = 0, []
    for i in range(0, len(messages), 100):
        chunk = messages[i:i + 100]
        ok, info = _post(RESEND_BATCH_URL, api_key, chunk)
        if ok:
            sent += len(chunk)
            continue
        print(f"  batch refused ({info}); retrying one by one")
        for m in chunk:
            ok, info = _post(RESEND_URL, api_key, m)
            if ok:
                sent += 1
            else:
                errors.append(f"{m['to']}: {info}")
            time.sleep(0.6)  # Resend: 2 requests/second
    return sent, errors


def build_messages(subject, html, text, from_email, owner, peers, reply_to, unsubscribe_url):
    def msg(to, with_unsub):
        m = {"from": from_email, "to": [to], "subject": subject, "html": html, "text": text,
             "reply_to": reply_to}
        if with_unsub and unsubscribe_url and unsubscribe_url.startswith("https://"):
            m["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>"}
        return m
    return [msg(owner, False)] + [msg(p, True) for p in peers]


def send_theme(theme, ctx):
    """Handle one theme. Returns True if it went fine (including 'nothing to send')."""
    now = datetime.now(timezone.utc)
    test = ctx["test"]
    state = ctx["state"]
    last_sent = state["last_newsletter_sent"].get(theme)
    elapsed = hours_since(last_sent)
    if not test and elapsed is not None and elapsed < MIN_HOURS_BETWEEN:
        print(f"[{theme}] sent {elapsed:.1f}h ago (< {MIN_HOURS_BETWEEN}h): duplicate guard, skipped.")
        return True

    items, overflow = ctx["plan"].get(theme, ([], 0))
    label = THEME_LABELS[theme]
    if not items:
        print(f"[{theme}] no new item: nothing sent{' (test)' if test else ', not counted as an edition'}.")
        return True

    edition = edition_number(theme, ctx["log"])
    kwargs = dict(edition=edition, today=now, overflow=overflow, site_url=ctx["site_url"],
                  unsubscribe_url=ctx["unsubscribe_url"], test=test)
    html = build_email_html(theme, items, **kwargs)
    text = build_email_text(theme, items, **kwargs)
    subject = (f"{'[TEST] ' if test else ''}Veille stratégique n° {edition} · {label} · "
               f"{len(items)} publication{'s' if len(items) > 1 else ''}")

    if ctx["dry_run"]:
        print(f"[{theme}] DRY RUN (no mail transport / owner address configured): would send {len(items)} items "
              f"(+{overflow} held back) to owner + {len(ctx['peers'].get(theme, []))} peer(s).")
        if ctx.get("dump_dir"):
            os.makedirs(ctx["dump_dir"], exist_ok=True)
            with open(os.path.join(ctx["dump_dir"], f"{theme}.html"), "w", encoding="utf-8") as f:
                f.write(html)
            with open(os.path.join(ctx["dump_dir"], f"{theme}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
        return True

    owner = ctx["owner"]
    all_peers = sorted({e for e in ctx["peers"].get(theme, []) if e.lower() != owner.lower()})
    peers = [] if test else all_peers
    if test:
        print(f"[{theme}] test: {len(all_peers)} peer(s) would receive the official edition (none contacted).")
    if peers and not ctx["can_write_to_peers"]:
        print(f"[{theme}] WARNING: sender is {ctx['from_email']}: Resend only delivers to the account owner "
              f"with it. {len(peers)} peer(s) NOT contacted. Verify a domain on resend.com/domains, or use SMTP_*.")
        peers = []

    messages = build_messages(subject, html, text, ctx["from_email"], owner, peers,
                              owner, ctx["unsubscribe_url"])
    sent, errors = deliver(ctx, messages)
    ctx["emails_sent"] += sent
    if errors:
        for e in errors:
            print(f"[{theme}] FAILED: {e}")
    owner_ok = sent >= 1 and not any(e.startswith(f"['{owner}']") for e in errors)
    print(f"[{theme}] {'TEST ' if test else ''}edition {edition}: {sent}/{len(messages)} message(s) sent, "
          f"{len(items)} items ({overflow} held back).")

    if test or not owner_ok:
        return owner_ok  # a test never moves the calendar; a failed owner send is retried next run

    iso = now.isoformat()
    state["last_newsletter_sent"][theme] = iso
    save_state(state)                      # saved right away, theme by theme
    append_newsletter_log({
        "date": iso, "theme": theme, "edition": edition, "item_count": len(items),
        "overflow_count": overflow, "recipients": len(messages), "item_ids": [it["id"] for it in items],
    })
    ctx["log"] = load_newsletter_log()
    return not errors


def send_health_alert(ctx):
    problems = health_problems(load_health(), load_sources())
    if not problems:
        print("Sources: no problem to report.")
        return
    print(f"Sources: {len(problems)} to check.")
    for name, why in problems:
        print(f"  - {name}: {why}")
    if ctx["dry_run"]:
        return
    rows = "".join(f"<li><b>{name}</b> : {why}</li>" for name, why in problems)
    html = (f"<p>Sources à vérifier dans <code>sources.yaml</code> :</p><ul>{rows}</ul>"
            "<p>Détail : <code>data/source_health.json</code>. Une source peut être mise en pause avec "
            "<code>enabled: false</code>.</p>")
    text = "Sources à vérifier :\n" + "\n".join(f"- {n} : {w}" for n, w in problems)
    msg = {"from": ctx["from_email"], "to": [ctx["owner"]],
           "subject": f"{'[TEST] ' if ctx['test'] else ''}Veille : {len(problems)} source(s) à vérifier",
           "html": html, "text": text}
    n, errs = deliver(ctx, [msg])
    if not n:
        print(f"Health alert not sent: {errs}")


def main():
    test = "--test" in sys.argv
    api_key = os.environ.get("RESEND_API_KEY")
    smtp = smtp_settings()
    owner = os.environ.get("OWNER_EMAIL") or os.environ.get("RESEND_TO_EMAIL")
    from_email = smtp["user"] if smtp else (os.environ.get("RESEND_FROM_EMAIL") or "onboarding@resend.dev")
    dry_run = not ((api_key or smtp) and owner)
    print(f"Transport: {'SMTP (' + smtp['host'] + ')' if smtp else 'Resend' if api_key else 'none (dry run)'}")
    if test:
        print("TEST MODE: owner only; state and edition log untouched.")

    peers = load_peer_recipients()   # also in test mode: only to report who WOULD receive it
    n_peers = len({e for v in peers.values() for e in v})
    if n_peers:
        n_msgs = sum(1 + len(peers.get(t, [])) for t in THEME_ORDER)
        print(f"{n_peers} peer(s) loaded; up to {n_msgs} emails this run.")
        if n_msgs > DAILY_LIMIT_WARNING:
            print(f"WARNING: {n_msgs} emails > Resend free daily limit (100). Reduce the list or upgrade the plan.")

    ctx = {
        "test": test, "dry_run": dry_run, "api_key": api_key, "smtp": smtp, "owner": owner,
        "from_email": from_email, "state": load_state(), "items": load_items(),
        "log": load_newsletter_log(), "peers": peers, "emails_sent": 0,
        "keywords": load_keywords(),
        "site_url": os.environ.get("SITE_URL") or DEFAULT_SITE_URL,
        "unsubscribe_url": os.environ.get("SIGNUP_FORM_URL") or None,
        "can_write_to_peers": not from_email.lower().endswith("@resend.dev"),
        "dump_dir": os.environ.get("NEWSLETTER_DUMP_DIR"),
    }

    ctx["plan"] = plan_editions(ctx["items"], ctx["state"], ctx["log"],
                                datetime.now(timezone.utc), ctx["keywords"])
    all_ok = True
    for theme in THEME_ORDER:
        try:
            all_ok &= bool(send_theme(theme, ctx))
        except Exception:  # noqa: BLE001 - one theme must not stop the others
            traceback.print_exc()
            all_ok = False

    try:
        send_health_alert(ctx)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
