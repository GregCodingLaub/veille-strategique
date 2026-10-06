"""
Same story, several sources: group near-duplicate items so a newsletter shows
the story once.

Two items are "the same story" when their dates are within 10 days and:
  - their titles are near-identical (fuzzy ratio >= 0.85), or
  - they share most of their meaningful words (Jaccard >= 0.55), or
  - (works across French/English) they share at least 3 proper nouns / numbers,
    or 2 of them plus a good overlap of the remaining words.
The rules are deliberately conservative: a wrong merge hides an article,
a missed merge only shows a story twice.
"""
import difflib
import re
from datetime import datetime

from common import fold

_STOP = set("""
avec dans pour sont cette leur leurs plus mais comme entre apres avant vers sous
tout tous toute toutes elle elles nous vous ils est ont ete etre fait faire
the and for with from that this their they have been will what when how why who
into over after before about than more most are was were has had its not new
des les une aux sur par que qui quoi dont
""".split())


def _tokens(title):
    return {t for t in re.findall(r"[a-z0-9]{4,}", fold(title)) if t not in _STOP}


def _proper(title):
    """Capitalised words (not the first one), acronyms and numbers, folded."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9][\wÀ-ÿ'’.-]*", title or "")
    out = set()
    for i, w in enumerate(words):
        core = fold(w).strip("'’.-")
        if len(core) < 3 and not core.isdigit():
            continue
        if core.isdigit() or w.isupper() or (i > 0 and w[0].isupper()):
            out.add(core)
    return out


def _days_apart(a, b):
    try:
        da = datetime.strptime((a.get("date") or "")[:10], "%Y-%m-%d")
        db = datetime.strptime((b.get("date") or "")[:10], "%Y-%m-%d")
    except ValueError:
        return 0
    return abs((da - db).days)


def same_story(a, b):
    if a.get("link") and a.get("link") == b.get("link"):
        return True
    if _days_apart(a, b) > 10:
        return False
    ta, tb = a.get("title") or "", b.get("title") or ""
    fa, fb = fold(ta), fold(tb)
    na, nb = set(re.findall(r"\d+", ta)), set(re.findall(r"\d+", tb))
    if na and nb and na != nb:
        return False      # "Partie 1/2" vs "Partie 2/2", "No. 3" vs "No. 4": different pieces
    if fa == fb:
        return True
    if difflib.SequenceMatcher(None, fa, fb).ratio() >= 0.85:
        return True
    sa, sb = _tokens(ta), _tokens(tb)
    if len(sa) >= 3 and len(sb) >= 3:
        if len(sa & sb) / len(sa | sb) >= 0.55:
            return True
    pa, pb = _proper(ta), _proper(tb)
    shared = pa & pb
    if len(shared) >= 3:
        return True
    if len(shared) >= 2 and sa and sb and len(sa & sb) / len(sa | sb) >= 0.25:
        return True
    return False


def cluster(items):
    """List of groups (lists of items) of the same story. Union-find."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if find(i) != find(j) and same_story(items[i], items[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    return list(groups.values())


def representative(group):
    """The most informative member: longest summary, then the most recent."""
    return max(group, key=lambda it: (len(it.get("summary") or ""), it.get("date") or ""))
