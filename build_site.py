"""
Generate the static site (docs/index.html) from data/items.json.
GitHub Pages serves the /docs folder directly -- no build step needed on GitHub's end.

Run manually: python scripts/build_site.py
"""
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import load_items, DOCS_DIR
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
  .filters {{ max-width: 900px; margin: 20px auto 0; display: flex; flex-wrap: wrap; gap: 8px; }}
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
  .summary {{ color: #c3c7d1; font-size: 13.5px; margin-top: 8px; line-height: 1.4; }}
  footer {{ max-width: 900px; margin: 40px auto; color: var(--muted); font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>🛰 Veille Stratégique</h1>
  <div class="sub">{count} publications suivies · Défense · Renseignement · Intelligence économique · Énergie & armement · Généré le {generated}</div>
</header>
<div class="filters" id="filters">
  <button class="filter-btn active" data-theme="all">Tout</button>
  {theme_buttons}
</div>
<main id="items">
{items_html}
</main>
<footer>Veille personnelle · sources et mots-clés configurables dans le dépôt GitHub.</footer>
<script>
  const buttons = document.querySelectorAll('.filter-btn');
  const items = document.querySelectorAll('.item');
  buttons.forEach(btn => btn.addEventListener('click', () => {{
    buttons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const theme = btn.dataset.theme;
    items.forEach(it => {{
      it.style.display = (theme === 'all' || it.dataset.themes.includes(theme)) ? '' : 'none';
    }});
  }}));
</script>
</body>
</html>
"""

ITEM_TEMPLATE = """<div class="item" data-themes="{themes_raw}">
  <a href="{link}" target="_blank" rel="noopener">{title}</a>
  <div class="meta">{source} · {date} · {tags}</div>
  {summary_html}
</div>
"""


def render_items(items):
    html = []
    for it in items:
        tags = " ".join(f'<span class="tag">{THEME_LABELS.get(t, t)}</span>' for t in it.get("themes", []))
        summary = it.get("summary", "").strip()
        summary_html = f'<div class="summary">{summary[:280]}</div>' if summary else ""
        html.append(ITEM_TEMPLATE.format(
            themes_raw=",".join(it.get("themes", [])),
            link=it["link"],
            title=it["title"],
            source=it["source"],
            date=it.get("date") or "date inconnue",
            tags=tags,
            summary_html=summary_html,
        ))
    return "\n".join(html)


def render_theme_buttons(items):
    present = set()
    for it in items:
        present.update(it.get("themes", []))
    buttons = []
    for theme in THEME_LABELS:
        if theme in present:
            buttons.append(f'<button class="filter-btn" data-theme="{theme}">{THEME_LABELS[theme]}</button>')
    return "\n  ".join(buttons)


def main():
    items = load_items()
    os.makedirs(DOCS_DIR, exist_ok=True)
    html = PAGE_TEMPLATE.format(
        count=len(items),
        generated=datetime.now().strftime("%d/%m/%Y %H:%M"),
        theme_buttons=render_theme_buttons(items),
        items_html=render_items(items),
    )
    out_path = os.path.join(DOCS_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Site written to {out_path} ({len(items)} items)")


if __name__ == "__main__":
    main()
