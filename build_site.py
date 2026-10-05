"""
Generate the static site (docs/index.html) from data/items.json and
data/newsletter_log.json. GitHub Pages serves /docs directly.

Pre-filter through the URL, which is what the "Voir sur le site" links of the
emails use:  index.html?region=eu&theme=energy_industry

Optional env var:
  SIGNUP_FORM_URL  link of the "S'abonner" button (peer signup form).

Everything coming from the feeds is HTML-escaped. Items are written in the
page itself (readable without JavaScript); the script only filters them.
"""
import os
import sys
from datetime import datetime, timezone
from html import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    load_items, load_newsletter_log, DOCS_DIR, truncate,
    REGION_ORDER, REGION_LABELS, REGION_COLORS, THEME_ORDER, THEME_LABELS,
    THEME_SHORT_LABELS, THEME_COLORS, SOURCE_PERSPECTIVE, source_region_of,
)
from email_render import date_fr, short_date_fr  # noqa: E402

CSS = """
:root{--bg:#eceff3;--paper:#fff;--ink:#101a2b;--body:#445063;--muted:#6b7686;--rule:#e1e6ec;
  --masthead:#0f1b2a;--chip:#f1f4f7;--accent:#0e7490}
@media (prefers-color-scheme:dark){:root{--bg:#0c1017;--paper:#141a24;--ink:#f1f4f8;--body:#b7c1cf;
  --muted:#8b97a8;--rule:#252e3c;--masthead:#0a111b;--chip:#1c2431}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--body);font:15px/1.55 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
a{color:inherit}
.masthead{background:var(--masthead);color:#fff;border-top:6px solid var(--accent)}
.wrap{max-width:860px;margin:0 auto;padding:0 20px}
.masthead .wrap{padding-top:30px;padding-bottom:26px;display:flex;gap:16px;justify-content:space-between;flex-wrap:wrap;align-items:flex-end}
h1{font:700 32px/1.15 Georgia,"Times New Roman",serif;margin:0}
.sub{color:#9fb0c4;font-size:14px;margin-top:8px;max-width:520px}
.btn{display:inline-block;background:#fff;color:#0f1b2a;text-decoration:none;font-weight:700;font-size:14px;padding:10px 18px;border-radius:6px}
.btn:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid #5aa9ff;outline-offset:2px}
.tabs{background:var(--paper);border-bottom:1px solid var(--rule);position:sticky;top:0;z-index:5}
.tabs .wrap{display:flex;gap:4px}
.tab{background:none;border:0;border-bottom:3px solid transparent;color:var(--muted);font:600 14px inherit;padding:14px 14px 11px;cursor:pointer}
.tab[aria-selected=true]{color:var(--ink);border-bottom-color:var(--accent)}
.panel{padding:22px 0 60px}
.tools{display:grid;gap:12px;margin-bottom:18px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.row .lab{font-size:13px;color:var(--muted);min-width:56px}
.chip{background:var(--chip);border:1px solid var(--rule);color:var(--body);border-radius:999px;padding:5px 12px;font:13px inherit;cursor:pointer}
.chip[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip .dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px}
input[type=search],select{font:14px inherit;padding:8px 10px;border-radius:6px;border:1px solid var(--rule);background:var(--paper);color:var(--ink)}
input[type=search]{flex:1;min-width:200px}
.count{font-size:13px;color:var(--muted);margin:4px 0 6px}
.item{background:var(--paper);border-left:4px solid var(--zone);padding:15px 18px 14px;margin-bottom:10px}
.item h2{font:700 18px/1.35 Georgia,"Times New Roman",serif;margin:0}
.item h2 a{color:var(--ink);text-decoration:none}
.item h2 a:hover{text-decoration:underline}
.item p{margin:6px 0 0;font-size:14.5px}
.meta{font-size:12.5px;color:var(--muted);margin-top:8px;display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
.persp{font-weight:700;font-size:10.5px;padding:3px 5px;border-radius:3px}
.tag{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--tc);color:var(--tc)}
.zone{font-size:12px}
.more{display:block;margin:18px auto;padding:10px 22px}
.empty{padding:30px 0;color:var(--muted)}
.edition{background:var(--paper);border-left:4px solid var(--tc);margin-bottom:10px}
.edition summary{cursor:pointer;padding:14px 18px;list-style:none;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.edition summary::-webkit-details-marker{display:none}
.edition b{font:700 17px Georgia,serif;color:var(--ink)}
.edition .body{padding:0 18px 14px;border-top:1px solid var(--rule)}
.edition .body div{padding:8px 0;border-bottom:1px solid var(--rule);font-size:14px}
.edition .body div:last-child{border:0}
footer{color:var(--muted);font-size:12.5px;padding-bottom:40px}
.hidden{display:none!important}
@media (max-width:560px){h1{font-size:26px}.item{padding:13px 14px}}
"""

JS = """
(function(){
  var p=new URLSearchParams(location.search);
  var st={region:p.get('region')||'all',theme:p.get('theme')||'all',q:'',src:'all',days:0,shown:40};
  var items=[].slice.call(document.querySelectorAll('.item'));
  var PAGE=40;
  function visibleList(){
    var q=st.q.trim().toLowerCase();
    var limit=st.days?new Date(Date.now()-st.days*864e5).toISOString().slice(0,10):'';
    return items.filter(function(it){
      var d=it.dataset;
      if(st.region!=='all'&&d.region!==st.region)return false;
      if(st.theme!=='all'&&d.themes.split(' ').indexOf(st.theme)<0)return false;
      if(st.src!=='all'&&d.source!==st.src)return false;
      if(limit&&(d.date||'')<limit)return false;
      if(q&&d.search.indexOf(q)<0)return false;
      return true;});
  }
  function render(){
    var list=visibleList();
    items.forEach(function(it){it.classList.add('hidden');});
    list.slice(0,st.shown).forEach(function(it){it.classList.remove('hidden');});
    document.getElementById('count').textContent=list.length+' publication'+(list.length>1?'s':'');
    document.getElementById('more').classList.toggle('hidden',list.length<=st.shown);
    document.getElementById('none').classList.toggle('hidden',list.length>0);
    document.querySelectorAll('[data-f]').forEach(function(b){
      b.setAttribute('aria-pressed',String(st[b.dataset.f]===b.dataset.v));});
  }
  document.querySelectorAll('[data-f]').forEach(function(b){
    b.addEventListener('click',function(){st[b.dataset.f]=b.dataset.v;st.shown=PAGE;render();});});
  document.getElementById('q').addEventListener('input',function(e){st.q=e.target.value;st.shown=PAGE;render();});
  document.getElementById('src').addEventListener('change',function(e){st.src=e.target.value;st.shown=PAGE;render();});
  document.getElementById('days').addEventListener('change',function(e){st.days=+e.target.value;st.shown=PAGE;render();});
  document.getElementById('more').addEventListener('click',function(){st.shown+=PAGE;render();});
  var tabs=[].slice.call(document.querySelectorAll('.tab'));
  tabs.forEach(function(t){t.addEventListener('click',function(){
    tabs.forEach(function(x){x.setAttribute('aria-selected',String(x===t));});
    document.getElementById('view-items').classList.toggle('hidden',t.dataset.view!=='items');
    document.getElementById('view-eds').classList.toggle('hidden',t.dataset.view!=='eds');});});
  render();
})();
"""


def e(x):
    return escape(str(x or ""), quote=True)


def render_item(it):
    zone = it.get("subject_region", "other")
    zone = zone if zone in REGION_COLORS else "other"
    code, colour, tint = SOURCE_PERSPECTIVE.get(source_region_of(it), SOURCE_PERSPECTIVE["other"])
    themes = [t for t in THEME_ORDER if t in (it.get("themes") or [])]
    tags = "".join(
        f'<span class="tag" style="--tc:{THEME_COLORS[t]}">{e(THEME_SHORT_LABELS[t])}</span>' for t in themes)
    summary = truncate(it.get("summary") or "", 320)
    search = f"{it['title']} {it.get('summary') or ''} {it['source']}".lower()
    when = it.get("date") or ""
    try:
        y, m, d = (int(x) for x in when.split("-"))
        when_h = date_fr(datetime(y, m, d))
    except ValueError:
        when_h = "date inconnue"
    return (
        f'<article class="item" style="--zone:{REGION_COLORS[zone]}" data-region="{zone}" '
        f'data-themes="{e(" ".join(themes))}" data-source="{e(it["source"])}" data-date="{e(when)}" '
        f'data-search="{e(search)}">'
        f'<h2><a href="{e(it["link"])}" target="_blank" rel="noopener">{e(it["title"])}</a></h2>'
        + (f"<p>{e(summary)}</p>" if summary else "")
        + f'<div class="meta"><span class="persp" style="background:{tint};color:{colour}">{e(code)}</span>'
        f'<span>{e(it["source"])}</span><span>{e(when_h)}</span>'
        f'<span class="zone" style="color:{REGION_COLORS[zone]}">{e(REGION_LABELS[zone])}</span>{tags}</div>'
        "</article>"
    )


def chips(kind, options, extra_all="Tout"):
    out = [f'<button class="chip" data-f="{kind}" data-v="all" aria-pressed="false">{extra_all}</button>']
    for key, label, colour in options:
        dot = f'<span class="dot" style="background:{colour}"></span>' if colour else ""
        out.append(f'<button class="chip" data-f="{kind}" data-v="{key}" aria-pressed="false">{dot}{e(label)}</button>')
    return "".join(out)


def render_editions(log, items_by_id):
    if not log:
        return '<div class="empty">Aucune édition envoyée pour le moment.</div>'
    out = []
    for entry in log:
        theme = entry.get("theme")
        label = THEME_LABELS.get(theme, "Édition")
        try:
            d = date_fr(datetime.fromisoformat(entry["date"]))
        except (KeyError, ValueError):
            d = "date inconnue"
        rows = []
        for iid in entry.get("item_ids", []):
            it = items_by_id.get(iid)
            if it:
                rows.append(f'<div><a href="{e(it["link"])}" target="_blank" rel="noopener">{e(it["title"])}</a>'
                            f'<br><span class="meta">{e(it["source"])} · {e(short_date_fr(it.get("date")))}</span></div>')
        num = f"n° {entry['edition']} · " if entry.get("edition") else ""
        body = "".join(rows) or '<div class="meta">Détail indisponible.</div>'
        out.append(
            f'<details class="edition" style="--tc:{THEME_COLORS.get(theme, "#52606d")}"><summary>'
            f'<b>{e(label)}</b><span class="meta">{e(num)}{e(d)} · {entry.get("item_count", len(rows))} publications</span>'
            f'</summary><div class="body">{body}</div></details>')
    return "".join(out)


def main():
    items = load_items()
    items.sort(key=lambda it: (it.get("date") or "", it.get("fetched_at") or ""), reverse=True)
    log = load_newsletter_log()
    by_id = {it["id"]: it for it in items}
    sources = sorted({it["source"] for it in items})
    present_regions = {it.get("subject_region", "other") for it in items}
    form = os.environ.get("SIGNUP_FORM_URL")
    signup = (f'<a class="btn" href="{e(form)}" target="_blank" rel="noopener">S\'abonner à la newsletter</a>'
              if form else "")
    now = datetime.now(timezone.utc)

    page = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Veille stratégique</title><style>{CSS}</style></head>
<body>
<header class="masthead"><div class="wrap"><div>
  <h1>Veille stratégique</h1>
  <div class="sub">Renseignement, défense et énergie sous l'angle géopolitique : {len(items)} publications suivies dans {len(sources)} sources. Mis à jour le {e(date_fr(now))}.</div>
</div>{signup}</div></header>
<nav class="tabs"><div class="wrap" role="tablist">
  <button class="tab" role="tab" data-view="items" aria-selected="true">Publications</button>
  <button class="tab" role="tab" data-view="eds" aria-selected="false">Éditions envoyées ({len(log)})</button>
</div></nav>
<main class="wrap panel">
<section id="view-items">
  <div class="tools">
    <div class="row"><input id="q" type="search" placeholder="Rechercher un mot, un sujet, une source" aria-label="Rechercher">
      <select id="src" aria-label="Source"><option value="all">Toutes les sources</option>{"".join(f'<option value="{e(s)}">{e(s)}</option>' for s in sources)}</select>
      <select id="days" aria-label="Période"><option value="0">Toute la période</option><option value="7">7 derniers jours</option><option value="30">30 derniers jours</option><option value="90">90 derniers jours</option></select></div>
    <div class="row"><span class="lab">Thème</span>{chips("theme", [(t, THEME_SHORT_LABELS[t], THEME_COLORS[t]) for t in THEME_ORDER])}</div>
    <div class="row"><span class="lab">Zone</span>{chips("region", [(r, REGION_LABELS[r], REGION_COLORS[r]) for r in REGION_ORDER if r in present_regions])}</div>
  </div>
  <div class="count" id="count" aria-live="polite"></div>
  <div id="list">{"".join(render_item(it) for it in items)}</div>
  <div class="empty hidden" id="none">Aucune publication ne correspond à ces filtres. Élargissez la période ou retirez un filtre.</div>
  <button class="chip more hidden" id="more">Afficher plus</button>
</section>
<section id="view-eds" class="hidden">{render_editions(log, by_id)}</section>
</main>
<footer class="wrap">Sélection automatique par mots-clés : les liens mènent aux sources originales. Les pastilles FR, EU et US indiquent le pays de l'institution qui publie ; la couleur de la bordure indique la zone du sujet traité.</footer>
<script>{JS}</script>
</body></html>"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    out = os.path.join(DOCS_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Site written to {out} ({len(items)} items, {len(log)} editions)")


if __name__ == "__main__":
    main()
