"""
Builds the weekly newsletter: an HTML email (table layout, inline CSS, so it
renders in Gmail / Outlook / Apple Mail) and its plain-text twin.

Design notes
  - Light "paper" layout by default, switched to a dark palette through
    prefers-color-scheme where the mail client supports it.
  - Each newsletter has its own accent colour (THEME_COLORS), shown as a band
    on top of the masthead and on the button.
  - A stacked bar shows at a glance where the week's publications come from
    (by subject zone); the zone sections below use the same colours.
  - Titles are serif (Georgia), body text is sans-serif: both are web-safe.
  - Everything that comes from the feeds is HTML-escaped.

No network, no disk access here: pure functions, easy to test.
"""
from html import escape
from urllib.parse import urlencode

from common import (
    REGION_ORDER, REGION_LABELS, REGION_COLORS, THEME_LABELS, THEME_COLORS,
    SOURCE_PERSPECTIVE, source_region_of, truncate,
)

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]
SUMMARY_IN_EMAIL = 230

SERIF = "Georgia,'Times New Roman',Times,serif"
SANS = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"


def date_fr(dt):
    return f"{dt.day} {MONTHS_FR[dt.month - 1]} {dt.year}"


def short_date_fr(iso):
    """'2026-10-03' -> '3 oct.'; anything unparsable -> ''."""
    try:
        y, m, d = (int(x) for x in iso[:10].split("-"))
        return f"{d} {MONTHS_FR[m - 1][:4]}." if len(MONTHS_FR[m - 1]) > 4 else f"{d} {MONTHS_FR[m - 1]}"
    except (ValueError, IndexError, TypeError, AttributeError):
        return ""


def group_by_region(items):
    groups = {r: [] for r in REGION_ORDER}
    for it in items:
        region = it.get("subject_region") or "other"
        groups[region if region in groups else "other"].append(it)
    for lst in groups.values():
        lst.sort(key=lambda it: it.get("date") or "", reverse=True)
    return groups


def site_link(site_url, **params):
    if not site_url:
        return ""
    sep = "&" if "?" in site_url else "?"
    return site_url + sep + urlencode(params)


def _zone_bar(groups, total):
    cells = []
    for r in REGION_ORDER:
        n = len(groups[r])
        if not n:
            continue
        pct = max(n * 100.0 / total, 2.0)
        cells.append(
            f'<td width="{pct:.1f}%" height="8" style="background:{REGION_COLORS[r]};'
            f'font-size:0;line-height:0;" title="{escape(REGION_LABELS[r])}">&nbsp;</td>'
        )
    legend = []
    for r in REGION_ORDER:
        n = len(groups[r])
        if not n:
            continue
        legend.append(
            f'<span style="display:inline-block;margin:0 14px 4px 0;white-space:nowrap;">'
            f'<span style="display:inline-block;width:9px;height:9px;background:{REGION_COLORS[r]};'
            f'margin-right:5px;"></span>{escape(REGION_LABELS[r])}&nbsp;{n}</span>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;"><tr>' + "".join(cells) + "</tr></table>"
        f'<div class="t-meta" style="font:12px/1.4 {SANS};color:#5b6675;margin-top:8px;">'
        + "".join(legend) + "</div>"
    )


def _item_row(it):
    code, colour, tint = SOURCE_PERSPECTIVE.get(source_region_of(it), SOURCE_PERSPECTIVE["other"])
    title = escape(it["title"])
    link = escape(it["link"], quote=True)
    summary = truncate(it.get("summary") or "", SUMMARY_IN_EMAIL)
    summary_html = (
        f'<div class="t-body" style="font:14px/1.55 {SANS};color:#445063;margin:5px 0 0;">'
        f'{escape(summary)}</div>' if summary else ""
    )
    chip = (
        f'<span style="display:inline-block;background:{tint};color:{colour};font:700 10px/1 {SANS};'
        f'padding:3px 5px;border-radius:3px;margin-right:7px;vertical-align:1px;">{escape(code)}</span>'
    )
    when = short_date_fr(it.get("date"))
    meta = f'{chip}{escape(it["source"])}' + (f" &nbsp;·&nbsp; {when}" if when else "")
    return f"""
<tr><td class="rule" style="padding:15px 0 14px;border-top:1px solid #e5e9ee;">
  <a class="t-title" href="{link}" style="font:700 17px/1.35 {SERIF};color:#101a2b;text-decoration:none;">{title}</a>
  {summary_html}
  <div class="t-meta" style="font:12px/1.4 {SANS};color:#6b7686;margin-top:7px;">{meta}</div>
</td></tr>"""


def _region_section(region, items, theme, site_url):
    colour = REGION_COLORS[region]
    rows = "".join(_item_row(it) for it in items)
    more = ""
    if site_url:
        more = (
            f'<a href="{escape(site_link(site_url, region=region, theme=theme), quote=True)}" '
            f'style="font:12px {SANS};color:{colour};text-decoration:none;">Voir sur le site</a>'
        )
    return f"""
<tr><td style="padding:30px 32px 0;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
    <tr>
      <td width="12" style="border-left:4px solid {colour};font-size:0;">&nbsp;</td>
      <td class="t-title" style="font:700 20px/1.2 {SERIF};color:#101a2b;">{escape(REGION_LABELS[region])}
        <span class="t-meta" style="font:13px {SANS};color:#6b7686;font-weight:400;">&nbsp;{len(items)}</span></td>
      <td align="right">{more}</td>
    </tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin-top:10px;">
    {rows}
  </table>
</td></tr>"""


def preheader(theme, items):
    n = len(items)
    top = items[0]["title"] if items else ""
    return f"{n} publication{'s' if n > 1 else ''} cette semaine. À la une : {truncate(top, 90)}"


def build_email_html(theme, items, *, edition, today, overflow=0, site_url=None,
                     unsubscribe_url=None, test=False):
    accent = THEME_COLORS[theme]
    groups = group_by_region(items)
    total = len(items)
    n_sources = len({it["source"] for it in items})
    n_zones = sum(1 for r in REGION_ORDER if groups[r])

    sections = "".join(
        _region_section(r, groups[r], theme, site_url) for r in REGION_ORDER if groups[r]
    )
    if not sections:
        sections = (f'<tr><td class="t-body" style="padding:30px 32px;font:15px/1.6 {SANS};color:#445063;">'
                    "Aucune nouvelle publication pertinente cette semaine.</td></tr>")

    test_banner = ""
    if test:
        test_banner = (f'<tr><td style="background:#fff3cd;color:#7a5b00;font:13px {SANS};padding:8px 32px;">'
                       "Envoi de TEST : rien n'a été envoyé aux abonnés et le calendrier n'est pas modifié.</td></tr>")

    overflow_note = ""
    if overflow:
        overflow_note = (f'<tr><td class="t-meta" style="padding:18px 32px 0;font:12px/1.5 {SANS};color:#6b7686;">'
                         f"+ {overflow} autres publications non affichées (limite par source) : "
                         "elles sont sur le site.</td></tr>")

    button = ""
    if site_url:
        button = f"""
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px;"><tr>
  <td style="background:{accent};border-radius:6px;">
    <a href="{escape(site_link(site_url, theme=theme), quote=True)}"
       style="display:inline-block;padding:11px 20px;font:700 14px {SANS};color:#ffffff;text-decoration:none;">
       Consulter l'archive complète</a>
  </td></tr></table>"""

    unsub = ""
    if unsubscribe_url:
        unsub = (f' Pour modifier vos thèmes ou vous désabonner : '
                 f'<a href="{escape(unsubscribe_url, quote=True)}" style="color:#6b7686;">formulaire d\'inscription</a>.')

    return f"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>Veille stratégique : {escape(THEME_LABELS[theme])}</title>
<style>
  @media (prefers-color-scheme: dark) {{
    .bg-outer {{ background:#0c1017 !important; }}
    .bg-card {{ background:#141a24 !important; }}
    .bg-foot {{ background:#101620 !important; }}
    .t-title {{ color:#f1f4f8 !important; }}
    .t-body {{ color:#b7c1cf !important; }}
    .t-meta {{ color:#8b97a8 !important; }}
    .rule {{ border-top-color:#252e3c !important; }}
  }}
  @media only screen and (max-width:620px) {{
    .wrap {{ width:100% !important; }}
    .pad {{ padding-left:20px !important; padding-right:20px !important; }}
  }}
</style></head>
<body class="bg-outer" style="margin:0;padding:0;background:#eceff3;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{escape(preheader(theme, items))}</div>
<table role="presentation" class="bg-outer" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eceff3;">
<tr><td align="center" style="padding:24px 10px;">
<table role="presentation" class="wrap bg-card" width="640" cellpadding="0" cellspacing="0" border="0"
       style="width:640px;max-width:640px;background:#ffffff;border-collapse:collapse;">
  {test_banner}
  <tr><td style="background:{accent};height:6px;font-size:0;line-height:0;">&nbsp;</td></tr>
  <tr><td style="background:#0f1b2a;padding:28px 32px 26px;" class="pad">
    <div style="font:13px {SANS};color:#9fb0c4;letter-spacing:.04em;">Veille stratégique · n° {edition} · {escape(date_fr(today))}</div>
    <div style="font:700 29px/1.2 {SERIF};color:#ffffff;margin-top:10px;">{escape(THEME_LABELS[theme])}</div>
  </td></tr>
  <tr><td style="padding:24px 32px 4px;" class="pad">
    <div class="t-body" style="font:15px/1.5 {SANS};color:#1d2a3c;margin-bottom:14px;">
      <b style="font-size:22px;font-family:{SERIF};">{total}</b> publication{'s' if total > 1 else ''},
      <b>{n_sources}</b> source{'s' if n_sources > 1 else ''},
      <b>{n_zones}</b> zone{'s' if n_zones > 1 else ''} depuis la dernière édition.
    </div>
    {_zone_bar(groups, total) if total else ''}
  </td></tr>
  {sections}
  {overflow_note}
  <tr><td style="padding:34px 32px 30px;" class="pad">{button}</td></tr>
  <tr><td class="bg-foot pad" style="background:#f5f7f9;padding:20px 32px 26px;">
    <div class="t-meta" style="font:12px/1.6 {SANS};color:#6b7686;">
      Sélection automatique de publications d'instituts, de médias spécialisés et d'organismes publics ;
      chaque lien mène à la source originale. Les pastilles FR, EU et US indiquent le pays de l'institution
      qui publie, la zone (en couleur) indique le sujet traité.{unsub}
    </div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def build_email_text(theme, items, *, edition, today, overflow=0, site_url=None,
                     unsubscribe_url=None, test=False):
    groups = group_by_region(items)
    out = []
    if test:
        out.append("[TEST] Rien n'a été envoyé aux abonnés.\n")
    out.append(f"VEILLE STRATÉGIQUE · n° {edition} · {date_fr(today)}")
    out.append(THEME_LABELS[theme])
    out.append("")
    out.append(f"{len(items)} publication(s) depuis la dernière édition.")
    for r in REGION_ORDER:
        if not groups[r]:
            continue
        out += ["", f"== {REGION_LABELS[r]} ({len(groups[r])}) ==", ""]
        for it in groups[r]:
            out.append(it["title"])
            s = truncate(it.get("summary") or "", SUMMARY_IN_EMAIL)
            if s:
                out.append(s)
            out.append(f'{it["source"]} · {it.get("date") or ""}')
            out.append(it["link"])
            out.append("")
    if overflow:
        out.append(f"+ {overflow} autres publications sur le site.")
    if site_url:
        out.append(f"Archive complète : {site_link(site_url, theme=theme)}")
    if unsubscribe_url:
        out.append(f"Modifier vos thèmes ou vous désabonner : {unsubscribe_url}")
    return "\n".join(out)
