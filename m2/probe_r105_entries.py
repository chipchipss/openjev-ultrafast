"""r105 zoom: what search/navigation entries does the github marketing homepage offer,
and does the pytorch repo search page answer without login? Zero model calls."""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage               # noqa: E402
from jev_ultrafast import skills as S                              # noqa: E402

GOAL = "Open the Releases page of the pytorch/pytorch repository."


def observe(b, tries=8):
    p = None
    for attempt in range(tries):
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.4 * (attempt + 1))
            continue
        if S.indexed_actions(p.get("actions") or []):
            return p
        time.sleep(0.5 * (attempt + 1))
    return p


def dump(b, p, label, pattern=None):
    idx = S.indexed_actions(p.get("actions") or [])
    hits = [(i, a) for i, a in idx
            if not pattern or pattern in (str(a.get("label")) + str(a.get("href"))).lower()]
    print("[%s] url=%s indexed=%d matches=%d" % (label, p.get("url"), len(idx), len(hits)))
    for i, a in hits[:10]:
        print("    e%s %s %-10s %r -> %s" % (i, a.get("kind"), a.get("role"),
                                             str(a.get("label") or "")[:44],
                                             str(a.get("href") or "")[:56]))
    return idx


print("=== A. github.com/ homepage: all indexed (short) ===")
b = Browser("https://github.com/")
try:
    p = observe(b)
    idx = dump(b, p, "home")
    print("---- all indexed ----")
    for i, a in idx:
        print("   %-4s %-7s %-10s %-44s %s" % (i, a.get("kind"), a.get("role"),
                                               str(a.get("label") or "")[:44],
                                               str(a.get("href") or "")[:44]))
finally:
    b.close()

print("=== B. github search results for pytorch/pytorch (repositories) ===")
b = Browser("https://github.com/search?q=pytorch%2Fpytorch&type=repositories")
try:
    p = observe(b)
    idx = dump(b, p, "search", "pytorch")
finally:
    b.close()

print("=== C. repo page /pytorch/pytorch (what links lead to Releases) ===")
b = Browser("https://github.com/pytorch/pytorch")
try:
    p = observe(b)
    idx = dump(b, p, "repo", "release")
finally:
    b.close()
