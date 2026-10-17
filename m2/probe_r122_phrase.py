"""r122 zoom: on www.rfc-editor.org, does the 'RFC 9110' phrase ever appear in an
indexed action (start page, scrolled pages, and the site-search results page the
n004 path uses)? Zero model calls."""
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

GOAL = "Open RFC 9110, 'HTTP Semantics'."
START = "https://www.rfc-editor.org/"
SEARCH = "https://www.rfc-editor.org/search/?q=RFC+9110"


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


def dump(b, p, label):
    idx = S.indexed_actions(p.get("actions") or [])
    hits = [(i, a) for i, a in idx
            if "9110" in (str(a.get("label")) + str(a.get("href"))).lower()
            or "http semantics" in str(a.get("label")).lower()]
    print("[%s] url=%s y=%s indexed=%d hits=%d"
          % (label, p.get("url"), (p.get("scroll") or {}).get("y"), len(idx), len(hits)))
    for i, a in hits[:6]:
        print("    e%s %s %r -> %s" % (i, a.get("kind"), str(a.get("label") or "")[:50],
                                       str(a.get("href") or "")[:60]))
    et = S.explicit_target(p, GOAL, [])
    print("    explicit_target ->",
          ("%s %s label=%r" % (et.get("choice"), et.get("operation"),
                               str({c: a for c, a in idx}.get(str(et.get("target")), {}).get("label") or "")[:40]))
          if isinstance(et, dict) else et)
    st = S.search_type(p, GOAL, [])
    print("    search_type ->",
          ("%s %s" % (st.get("choice"), st.get("text"))) if isinstance(st, dict) else st)


print("=== A. start page ===")
b = Browser(START)
try:
    p = observe(b)
    dump(b, p, "start")
    print("=== B. scroll_down x1 (product scroll control) ===")
    ctl = S._scroll_ctl(p, "down")
    if ctl:
        b.act(ctl, p)
        p2 = observe(b)
        dump(b, p2, "scrolled1")
        ctl2 = S._scroll_ctl(p2, "down")
        if ctl2:
            b.act(ctl2, p2)
            p3 = observe(b)
            dump(b, p3, "scrolled2")
finally:
    b.close()

print("=== C. site search results (the n004 path) ===")
b = Browser(SEARCH)
try:
    p = observe(b)
    dump(b, p, "search")
    idx = S.indexed_actions(p.get("actions") or [])
    print("---- all indexed ----")
    for i, a in idx[:40]:
        print("   %-4s %-7s %-46s %s" % (i, a.get("kind"), str(a.get("label") or "")[:46],
                                         str(a.get("href") or "")[:52]))
finally:
    b.close()
