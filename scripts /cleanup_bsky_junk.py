"""
ONE-TIME CLEANUP: removes junk items left over from an old bug in
bluesky.py, where text-only posts (no real link, just thread fragments or
announcements) got a fake "link" invented -- a permalink back to the post
itself on bsky.app. That fallback was removed, but it doesn't retroactively
clean up what it already added to data/items.json.

This script finds and removes any item whose link points to bsky.app
itself (the signature of that old bug), rather than a real article page.

Usage:
  python scripts/cleanup_bsky_junk.py            dry run -- lists what
                                                  WOULD be removed, changes
                                                  nothing
  python scripts/cleanup_bsky_junk.py --apply     actually removes them and
                                                  saves data/items.json

After running with --apply, push the updated data/items.json to GitHub
(same pencil-icon-and-paste method, or git push if you're set up for it)
so the live site/archive reflects the cleanup too.
"""
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import load_items, save_items

JUNK_SIGNATURE = "bsky.app/profile/"


def main():
    apply = "--apply" in sys.argv

    items = load_items()
    junk = [it for it in items if JUNK_SIGNATURE in it.get("link", "")]
    keep = [it for it in items if JUNK_SIGNATURE not in it.get("link", "")]

    if not junk:
        print("No junk items found -- archive is already clean.")
        return

    print(f"Found {len(junk)} junk item(s) out of {len(items)} total:\n")
    for it in junk:
        print(f"  - [{it.get('source', '?')}] {it.get('title', '(no title)')}")
        print(f"    {it.get('link', '')}")

    if not apply:
        print(f"\nDry run only -- nothing changed. {len(items)} items still in archive.")
        print("Re-run with --apply to actually remove these.")
        return

    save_items(keep)
    print(f"\nRemoved {len(junk)} item(s). {len(keep)} item(s) remain in the archive.")
    print("Now push the updated data/items.json to GitHub for this to take effect live.")


if __name__ == "__main__":
    main()
