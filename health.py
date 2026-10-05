"""Turns data/source_health.json into a short list of problems for the owner."""
from datetime import datetime, timezone

FAIL_RUNS = 3          # consecutive failed runs before alerting
EMPTY_RUNS = 3         # consecutive runs returning zero entries
DEFAULT_STALE_DAYS = 90  # newest item older than this -> "silent source"


def _days_since(date_str):
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - d).days


def health_problems(health, sources):
    """List of (source name, problem text). Disabled sources are ignored.
    Per-source option `stale_after_days` overrides the default (e.g. a quarterly
    journal)."""
    out = []
    for src in sources:
        if src.get("enabled", True) is False:
            continue
        h = health.get(src["name"])
        if not h:
            continue
        if h.get("consecutive_failures", 0) >= FAIL_RUNS:
            out.append((src["name"], f"en erreur depuis {h['consecutive_failures']} passages : {h.get('last_error')}"))
        elif h.get("consecutive_empty_runs", 0) >= EMPTY_RUNS:
            out.append((src["name"], f"renvoie 0 entrée depuis {h['consecutive_empty_runs']} passages (page ou flux modifié ?)"))
        else:
            age = _days_since(h.get("latest_item_date"))
            limit = src.get("stale_after_days", DEFAULT_STALE_DAYS)
            if age is not None and age > limit:
                out.append((src["name"], f"aucune publication depuis {age} jours (dernière : {h['latest_item_date']})"))
    return out
