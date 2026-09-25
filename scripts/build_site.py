"""
Generate the static site (docs/index.html) from data/items.json and
data/newsletter_log.json. GitHub Pages serves /docs directly -- no build
step needed on GitHub's end.

Supports URL query params for pre-filtering on load, e.g.
  index.html?region=eu           -> opens with EU pre-selected
  index.html?region=eu&theme=energy_industry  -> EU + Energy pre-selected
This is what lets the emailed "view on site" links land pre-filtered.

Run manually: python scripts/build_site.py
"""
import sys
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import (
    load_items, load_newsletter_log, DOCS_DIR,
    REGION_ORDER, REGION_LABELS, source_region_of, SOURCE_PERSPECTIVE,
)
import os

THEME_LABELS = {
    "defense": "Défense",
    "competitive_intelligence": "Intelligence économique",
    "intelligence": "Renseignement",
    "weapons_industry": "Industrie de l'armement",
    "energy_industry": "Énergie",
}

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Veille Stratégique</title>
<style>
  :root {{
    --bg: #0f1115; --card: #171a21; --text: #e8e9ec; --muted: #9099a8;
    --accent: #5b8def; --border: #262a33;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); margin: 0; padding: 0 16px 60px;
  }}
  header {{ max-width: 900px; margin: 0 auto; padding: 32px 0 16px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-size: 14px; }}
  .tabs {{ max-width: 900px; margin: 24px auto 0; display: flex; gap: 4px; border-bottom: 1px solid var(--border); }}
  .tab-btn {{
    background: none; border: none; color: var(--muted); padding: 10px 16px;
    font-size: 14px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
  }}
  .tab-btn.active {{ color: var(--text); border-bottom-color: var(--accent); }}
  .filter-group-label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; margin: 18px auto 6px; max-width: 900px; }}
  .filters {{ max-width: 900px; margin: 0 auto; display: flex; flex-wrap: wrap; gap: 8px; }}
  .filter-btn {{
    background: var(--card); border: 1px solid var(--border); color: var(--text);
    padding: 6px 12px; border-radius: 20px; font-size: 13px; cursor: pointer;
  }}
  .filter-btn.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  main {{ max-width: 900px; margin: 24px auto; }}
  .item {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px; margin-bottom: 12px;
  }}
  .item a {{ color: var(--text); text-decoration: none; font-size: 16px; font-weight: 600; }}
  .item a:hover {{ color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: 12.5px; margin-top: 6px; }}
  .tag {{
    display: inline-block; background: #1f2937; color: #93c5fd; font-size: 11px;
    padding: 2px 8px; border-radius: 10px; margin-right: 6px;
  }}
  .perspective {{ font-size: 11px; font-weight: 700; letter-spacing: 0.02em; margin-right: 6px; }}
  .summary {{ color: #c3c7d1; font-size: 13.5px; margin-top: 8px; line-height: 1.4; }}
  footer {{ max-width: 900px; margin: 40px auto; color: var(--muted); font-size: 12px; }}

  .edition {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px 20px; margin-bottom: 14px;
  }}
  .edition-head {{
    display: flex; align-items: center; justify-content: space-between; cursor: pointer;
  }}
  .edition-title {{ font-size: 15px; font-weight: 600; }}
  .edition-count {{ color: var(--muted); font-size: 13px; }}
  .edition-body {{ display: none; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border); }}
  .edition.open .edition-body {{ display: block; }}
  .edition-item {{ padding: 8px 0; border-bottom: 1px solid #23262f; }}
  .edition-item:last-child {{ border-bottom: none; }}
  .edition-item a {{ color: var(--text); text-decoration: none; font-size: 14px; }}
  .edition-item a:hover {{ color: var(--accent); }}
  .edition-item .meta {{ font-size: 11.5px; margin-top: 3px; }}
  .empty {{ color: var(--muted); font-size: 14px; padding: 24px 0; }}
</style>
</head>
<body>
<header>
  <h1>🛰 Veille Stratégique</h1>
  <div class="sub">{count} publications suivies · Défense · Renseignement · Intelligence économique · Énergie & armement · Généré le {generated}</div>
</header>

<div class="tabs">
  <button class="tab-btn active" data-view="items">Toutes les publications</button>
  <button class="tab-btn" data-view="newsletters">Éditions envoyées ({edition_count})</button>
</div>

<div id="view-items">
  <div class="filter-group-label">Zone</div>
  <div class="filters" id="region-filters">
    <button class="filter-btn active" data-region="all">Tout</button>
    {region_buttons}
  </div>
  <div class="filter-group-label">Secteur</div>
  <div class="filters" id="theme-filters">
    <button class="filter-btn active" data-theme="all">Tout</button>
    {theme_buttons}
  </div>
  <main id="items">
{items_html}
  </main>
</div>

<div id="view-newsletters" style="display:none;">
  <main>
{newsletters_html}
  </main>
</div>

<footer>Veille personnelle · sources et mots-clés configurables dans le dépôt GitHub.</footer>
<script>
  const params = new URLSearchParams(window.location.search);
  const initialRegion = params.get('region') || 'all';
  const initialTheme = params.get('theme') || 'all';

  const regionButtons = document.querySelectorAll('#region-filters .filter-btn');
  const themeButtons = document.querySelectorAll('#theme-filters .filter-btn');
  const items = document.querySelectorAll('.item');

  let activeRegion = initialRegion;
  let activeTheme = initialTheme;

  function applyFilters() {{
    items.forEach(it => {{
      const regionOk = (activeRegion === 'all' || it.dataset.region === activeRegion);
      const themeOk = (activeTheme === 'all' || it.dataset.themes.includes(activeTheme));
      it.style.display = (regionOk && themeOk) ? '' : 'none';
    }});
  }}

  regionButtons.forEach(btn => {{
    if (btn.dataset.region === initialRegion) {{ regionButtons.forEach(b => b.classList.remove('active')); btn.classList.add('active'); }}
    btn.addEventListener('click', () => {{
      regionButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeRegion = btn.dataset.region;
      applyFilters();
    }});
  }});

  themeButtons.forEach(btn => {{
    if (btn.dataset.theme === initialTheme) {{ themeButtons.forEach(b => b.classList.remove('active')); btn.classList.add('active'); }}
    btn.addEventListener('click', () => {{
      themeButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeTheme = btn.dataset.theme;
      applyFilters();
    }});
  }});

  applyFilters();

  // Top-level tabs
  const tabButtons = document.querySelectorAll('.tab-btn');
  const views = {{ items: document.getElementById('view-items'), newsletters: document.getElementById('view-newsletters') }};
  tabButtons.forEach(btn => btn.addEventListener('click', () => {{
    tabButtons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    Object.entries(views).forEach(([key, el]) => {{ el.style.display = (key === btn.dataset.view) ? '' : 'none'; }});
  }}));

  // Expand/collapse newsletter editions
  document.querySelectorAll('.edition-head').forEach(head => {{
    head.addEventListener('click', () => head.closest('.edition').classList.toggle('open'));
  }});
</script>
</body>
</html>
"""

ITEM_TEMPLATE = """<div class="item" data-themes="{themes_raw}" data-region="{region}">
  <a href="{link}" target="_blank" rel="noopener"><span class="perspective" style="color:{persp_color};">[{persp_code}]</span>{title}</a>
  <div class="meta">{source} · {date} · {tags}</div>
  {summary_html}
</div>
"""

EDITION_TEMPLATE = """<div class="edition">
  <div class="edition-head">
    <div class="edition-title">📬 {date_display}</div>
    <div class="edition-count">{item_count} publications{overflow_note}</div>
  </div>
  <div class="edition-body">
{items_html}
  </div>
</div>
"""

EDITION_ITEM_TEMPLATE = """<div class="edition-item">
  <a href="{link}" target="_blank" rel="noopener">{title}</a>
  <div class="meta">{source} · {date}</div>
</div>
"""


def render_items(items):
    html = []
    for it in items:
        tags = " ".join(f'<span class="tag">{THEME_LABELS.get(t, t)}</span>' for t in it.get("themes", []))
        summary = it.get("summary", "").strip()
        summary_html = f'<div class="summary">{summary[:280]}</div>' if summary else ""
        persp_code, persp_color = SOURCE_PERSPECTIVE.get(source_region_of(it), SOURCE_PERSPECTIVE["other"])
        html.append(ITEM_TEMPLATE.format(
            themes_raw=",".join(it.get("themes", [])),
            region=it.get("subject_region", "other"),
            link=it["link"],
            title=it["title"],
            source=it["source"],
            date=it.get("date") or "date inconnue",
            tags=tags,
            summary_html=summary_html,
            persp_code=persp_code,
            persp_color=persp_color,
        ))
    return "\n".join(html) if html else '<div class="empty">Aucune publication pour le moment.</div>'


def render_theme_buttons(items):
    present = set()
    for it in items:
        present.update(it.get("themes", []))
    buttons = []
    for theme in THEME_LABELS:
        if theme in present:
            buttons.append(f'<button class="filter-btn" data-theme="{theme}">{THEME_LABELS[theme]}</button>')
    return "\n  ".join(buttons)


def render_region_buttons(items):
    present = set(it.get("subject_region", "other") for it in items)
    buttons = []
    for region in REGION_ORDER:
        if region in present:
            buttons.append(f'<button class="filter-btn" data-region="{region}">{REGION_LABELS[region]}</button>')
    return "\n  ".join(buttons)


def render_newsletters(log, items_by_id):
    if not log:
        return '<div class="empty">Aucune édition envoyée pour le moment.</div>'

    html = []
    for entry in log:
        try:
            dt = datetime.fromisoformat(entry["date"])
            date_display = dt.strftime("%d/%m/%Y à %H:%M")
        except (KeyError, ValueError):
            date_display = entry.get("date", "date inconnue")

        overflow = entry.get("overflow_count", 0)
        overflow_note = f" (+{overflow} non affichées)" if overflow else ""

        edition_items = []
        for iid in entry.get("item_ids", []):
            it = items_by_id.get(iid)
            if not it:
                continue
            edition_items.append(EDITION_ITEM_TEMPLATE.format(
                link=it["link"],
                title=it["title"],
                source=it["source"],
                date=it.get("date") or "",
            ))

        html.append(EDITION_TEMPLATE.format(
            date_display=date_display,
            item_count=entry.get("item_count", len(edition_items)),
            overflow_note=overflow_note,
            items_html="\n".join(edition_items) if edition_items else '<div class="empty">Détails indisponibles.</div>',
        ))
    return "\n".join(html)


def main():
    items = load_items()
    log = load_newsletter_log()
    items_by_id = {it["id"]: it for it in items}

    os.makedirs(DOCS_DIR, exist_ok=True)
    html = PAGE_TEMPLATE.format(
        count=len(items),
        generated=datetime.now().strftime("%d/%m/%Y %H:%M"),
        theme_buttons=render_theme_buttons(items),
        region_buttons=render_region_buttons(items),
        items_html=render_items(items),
        edition_count=len(log),
        newsletters_html=render_newsletters(log, items_by_id),
    )
    out_path = os.path.join(DOCS_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Site written to {out_path} ({len(items)} items, {len(log)} newsletter editions)")


if __name__ == "__main__":
    main()
