import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

import common  # noqa: E402
from common import (clean_text, canonical_link, item_id, matches_keywords, is_excluded_technical,  # noqa: E402
                    match_region, load_keywords, load_regions, parse_date_from_text)
import scrapers  # noqa: E402
from fetch import process_items  # noqa: E402
from send_newsletter import select_items  # noqa: E402
from recipients import _parse_themes_cell  # noqa: E402
from health import health_problems  # noqa: E402
from email_render import build_email_html, build_email_text  # noqa: E402

KW, RG = load_keywords(), load_regions()
TODAY = datetime(2026, 10, 5, tzinfo=timezone.utc)


def test_clean_text_html_and_double_encoding():
    assert clean_text("<p>Hello &amp; <b>world</b></p>") == "Hello & world"
    assert clean_text("&lt;span&gt;Hi&lt;/span&gt; [email protected]") == "Hi"


def test_canonical_link_strips_tracking():
    a = canonical_link("https://Example.org/a/?utm_source=x&id=2#frag")
    assert a == canonical_link("https://example.org/a?id=2")
    assert item_id("https://example.org/a?utm_x=1") == item_id("https://example.org/a")


@pytest.mark.parametrize("text,theme", [
    ("The CIA recruits a new spy in Moscow", "intelligence"),
    ("Les armées françaises face à la guerre en Ukraine", "military"),
    ("Subsea cables and the Strait of Hormuz", "energy_industry"),
    ("Gas pipeline politics in Europe", "energy_industry"),
])
def test_theme_matches(text, theme):
    assert theme in matches_keywords(text, KW)


def test_no_false_positives():
    assert "military" not in matches_keywords("Why every think tank loves a podcast", KW)
    assert matches_keywords("Man City found guilty on charges", KW) == []


def test_technical_excluded():
    assert is_excluded_technical("Sponsored content: our new radar", KW)


def test_region():
    assert match_region("Beijing and Taiwan tensions", RG) == "china"
    assert match_region("Nothing geographic here", RG) == "other"
    assert match_region("The US Army budget", RG) == "us"


def test_dates():
    assert parse_date_from_text("Published 21 September 2026") == "2026-09-21"
    assert parse_date_from_text("publié le 3 mars 2026") == "2026-03-03"


def test_process_items_dedup_future_and_trust():
    src = {"name": "S", "region": "eu"}
    raw = [
        {"title": "Russian spy network exposed", "link": "https://x.org/1?utm_a=1", "date": "2026-10-01", "summary": ""},
        {"title": "Russian spy network exposed", "link": "https://x.org/1", "date": "2026-10-01", "summary": ""},
        {"title": "Cooking tips", "link": "https://x.org/2", "date": "2026-10-01", "summary": ""},
        {"title": "Spy conference", "link": "https://x.org/3", "date": "2027-05-01", "summary": ""},
    ]
    kept, stats, _ = process_items(src, raw, KW, RG, set(), TODAY)
    assert [k["link"] for k in kept] == ["https://x.org/1", "https://x.org/3"]
    assert kept[1]["date"] <= "2026-10-06"
    trusted = dict(src, default_themes=["intelligence"])
    kept, _, _ = process_items(trusted, raw[2:3], KW, RG, set(), TODAY)
    assert kept and kept[0]["themes"] == ["intelligence"]


def test_select_items_window_and_cap():
    now = TODAY
    items = [{"id": str(i), "source": "A", "themes": ["military"], "date": "2026-10-01",
              "fetched_at": (now - timedelta(days=1)).isoformat()} for i in range(9)]
    items.append({"id": "old", "source": "B", "themes": ["military"], "date": "2026-01-01",
                  "fetched_at": (now - timedelta(days=60)).isoformat()})
    kept, over = select_items("military", items, None, now)
    assert len(kept) == 6 and over == 3 and all(i["source"] == "A" for i in kept)


def test_recipients_parsing():
    assert _parse_themes_cell("Renseignement, Énergie & Infrastructures") == ["intelligence", "energy_industry"]
    assert _parse_themes_cell("Renseignement, Me désabonner") == []


def test_health():
    h = {"A": {"consecutive_failures": 4, "last_error": "boom"},
         "B": {"latest_item_date": "2020-01-01"},
         "C": {"latest_item_date": "2020-01-01"}}
    src = [{"name": "A"}, {"name": "B"}, {"name": "C", "enabled": False}]
    names = [n for n, _ in health_problems(h, src)]
    assert names == ["A", "B"]


def test_email_escapes_feed_content():
    it = {"id": "1", "title": "<script>alert(1)</script>", "link": 'https://x.org/"onmouseover=1',
          "source": "S<b>", "date": "2026-10-01", "summary": "a & b", "subject_region": "eu",
          "source_region": "eu", "themes": ["intelligence"]}
    html = build_email_html("intelligence", [it], edition=1, today=TODAY)
    assert "<script>alert" not in html and '"onmouseover' not in html
    assert "Aucune" not in html
    assert "<script>" in build_email_text("intelligence", [it], edition=1, today=TODAY)


HTML_IFRI = """<ul><li><a href="/en/memos/a-long-memo-slug"><img></a>
<a href="/en/memos/a-long-memo-slug">Gas and geopolitics in the Mediterranean</a><p>21 September 2026</p>
<p>A long enough description of the memo goes here for the summary.</p></li>
<li><a href="/en/experts/someone-name-here">Someone</a></li></ul>"""


class FakeSession:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kw):
        class R:
            status_code = 200
            def raise_for_status(s): pass
        r = R()
        r.text = self.pages.get(url.split("?")[0] if "page=" not in url else url, self.pages.get(url, ""))
        return r


def test_scraper_ifri():
    s = FakeSession({"https://www.ifri.org/en/center-energy-climate": HTML_IFRI})
    out = scrapers.ifri(s, "https://www.ifri.org/en/center-energy-climate", {})
    assert len(out) == 1 and out[0]["date"] == "2026-09-21"


def test_scraper_csis_and_cia():
    csis = '<article><a href="/analysis/critical-minerals-and-chokepoints">Critical minerals and chokepoints</a><p>April 2, 2026</p></article><a href="/events/x-y">Event</a>'
    s = FakeSession({"https://www.csis.org/programs/p": csis})
    out = scrapers.csis_program(s, "https://www.csis.org/programs/p", {"max_pages": 1})
    assert len(out) == 1 and out[0]["link"].endswith("/analysis/critical-minerals-and-chokepoints")
    cia = ('<a href="/resources/csi/studies-in-intelligence/studies-in-intelligence-vol-70-no-3-extracts-september-2026/">'
           'Studies in Intelligence Vol. 70, No. 3 (Extracts, September 2026)</a>'
           '<a href="/resources/csi/studies-in-intelligence/studies-in-intelligence-guide-for-authors/">Guide for authors</a>')
    s = FakeSession({"https://www.cia.gov/resources/csi/studies-in-intelligence/": cia})
    out = scrapers.cia_csi(s, "https://www.cia.gov/resources/csi/studies-in-intelligence/", {})
    assert len(out) == 1 and out[0]["date"] == "2026-09-01"


def test_scraper_irsem():
    html = """
    <div class="grid">
      <div class="card"><a href="/publications/sahel-au-centre-du-djihadisme-mondial">
        <span>Défense</span> <span>Sécurité</span> <span>1 min de lecture</span>
        <span>Sahel au centre du djihadisme mondial</span>
        <span>Etude 138 - 09/2026</span><span>Sahel au centre du djihadisme mondial</span>
        <span>Alexandre Lauret</span></a></div>
      <div class="card"><a href="/publications/sante-mentale"><span>Société Défense</span>
        <span>2h44min de lecture</span><span>Santé mentale et guerre de haute intensité</span>
        <span>ETUDE 137 - 14/09/2026</span></a></div>
      <div class="card"><a href="/publications/droit-des-conflits"><span>Droit</span>
        <span>3 min de lecture</span><span>Le droit des conflits armés</span><span>Publication - 06/2026</span></a></div>
      <div class="card"><a href="/publications/reseaux-electriques"><span>Énergie</span>
        <span>2 min de lecture</span><span>Réseaux électriques et conflits</span><span>Brève stratégique 93 - 09/2026</span></a></div>
      <a href="/publications?page=2">2</a><a href="/equipe/someone">x</a>
    </div>"""
    s = FakeSession({"https://www.irsem.fr/publications": html})
    opts = {"max_pages": 1, "skip_categories": ["droit", "société"]}
    out = scrapers.irsem(s, "https://www.irsem.fr/publications", opts)
    assert [o["title"] for o in out] == ["Sahel au centre du djihadisme mondial", "Réseaux électriques et conflits"]
    assert out[0]["date"] == "2026-09-01" and out[0]["themes_hint"] == ["military"]
    assert out[1]["themes_hint"] == ["energy_industry"]
    assert "Etude 138" in out[0]["summary"]
    src = {"name": "IRSEM", "region": "fr"}
    kept, _, _ = process_items(src, out, KW, RG, set(), TODAY)
    assert len(kept) == 2 and kept[0]["themes"] == ["military"]


def test_smtp_transport(monkeypatch):
    import smtplib
    import send_newsletter as sn

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            self.host = host
        def login(self, user, pw):
            if pw == "bad":
                raise smtplib.SMTPAuthenticationError(535, b"nope")
        def send_message(self, m):
            sent.append(m)
        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(sn.time, "sleep", lambda s: None)
    cfg = {"user": "veille@gmail.com", "password": "ok", "name": "Veille stratégique",
           "host": "smtp.gmail.com", "port": 465}
    msgs = sn.build_messages("Objet é", "<p>Salut</p>", "Salut", "veille@gmail.com", "moi@x.org",
                             ["a@x.org", "b@x.org"], "moi@x.org", "https://forms.gle/abc")
    n, errs = sn.send_smtp(cfg, msgs)
    assert n == 3 and not errs
    assert [m["To"] for m in sent] == ["moi@x.org", "a@x.org", "b@x.org"]
    assert "List-Unsubscribe" not in sent[0] and sent[1]["List-Unsubscribe"] == "<https://forms.gle/abc>"
    assert sent[1].is_multipart() and "veille@gmail.com" in sent[1]["From"]
    n, errs = sn.send_smtp(dict(cfg, password="bad"), msgs)
    assert n == 0 and "login refused" in errs[0]


def test_http_get_retries_other_identities(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    seen = []

    class R:
        def __init__(self, code): self.status_code = code
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class S:
        def get(self, url, **kw):
            seen.append(kw["headers"]["User-Agent"])
            return R(403 if len(seen) < 3 else 200)

    assert common.http_get(S(), "https://x.org").status_code == 200
    assert len(seen) == 3 and len(set(seen)) == 3

    class Always403:
        def get(self, url, **kw): return R(403)
    with pytest.raises(RuntimeError):
        common.http_get(Always403(), "https://x.org")


def test_bluesky_pagination_and_short_domain():
    import bluesky

    def post(uri, day):
        return {"post": {"record": {"createdAt": f"2026-10-{day}T10:00:00Z",
                "embed": {"$type": "app.bsky.embed.external", "external": {"uri": uri, "title": "T " + uri}}}}}

    pages = [{"feed": [post("https://reut.rs/a", "06"), post("https://other.com/x", "06")], "cursor": "c1"},
             {"feed": [post("https://reut.rs/b", "05")]}]

    class S:
        def __init__(self): self.calls = []
        def get(self, url, params=None, **kw):
            self.calls.append(params)
            class R:
                def raise_for_status(s): pass
                def json(s, d=pages[len(self.calls) - 1]): return d
            return R()

    s = S()
    out = bluesky.fetch_bluesky(s, "reuters.com", limit=100, allowed_domains=["reuters.com", "reut.rs"], max_pages=3)
    assert [o["link"] for o in out] == ["https://reut.rs/a", "https://reut.rs/b"]
    assert s.calls[1]["cursor"] == "c1" and s.calls[0]["limit"] == 100


def test_source_require_and_exclude_filters():
    src = {"name": "Mont", "region": "fr", "require_any": ["énergie", "défense", "Chine"],
           "exclude_any": ["cohésion sociale", "démocratie"]}
    raw = [
        {"title": "Défense européenne : le réarmement", "link": "https://m.org/1", "date": "2026-10-01", "summary": ""},
        {"title": "Cohésion sociale et défense du modèle français", "link": "https://m.org/2", "date": "2026-10-01", "summary": ""},
        {"title": "Quelle vie démocratique pour les jeunes ?", "link": "https://m.org/3", "date": "2026-10-01", "summary": ""},
        {"title": "Réformer l'école", "link": "https://m.org/4", "date": "2026-10-01", "summary": ""},
        {"title": "Énergie : la Chine et les minerais critiques", "link": "https://m.org/5", "date": "2026-10-01", "summary": ""},
    ]
    kept, stats, _ = process_items(src, raw, KW, RG, set(), TODAY)
    assert [k["link"] for k in kept] == ["https://m.org/1", "https://m.org/5"]
    assert stats["filtered"] == 3
