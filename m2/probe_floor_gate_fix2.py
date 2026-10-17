"""t17 probe #2: the three NAMED candidates in depth. Probe #1 measured
page_changed for 9 candidates; the critical ambiguity is rfc 'Subscribe to new
RFCs': page_changed=True but final URL unchanged -- what actually changed?
This probe records URL / title / text length / text head / action count for
BEFORE and AFTER, per candidate, on fresh pages. Zero model calls.
"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast import skills as S                      # noqa: E402

# (url, goal, candidate-label-fragment)
TARGETS = [
    ("https://github.com/",
     "Open the Releases page of the pytorch/pytorch repository.",
     "Open Enter your email"),
    ("https://www.rfc-editor.org/",
     "Open RFC 9110 from the RFC index.",
     "Subscribe to new RFCs"),
    ("https://developer.mozilla.org/zh-CN/",
     "Search MDN for 'fetch' and open the Fetch API reference page.",
     "Web APIs"),
]


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


def brief(p):
    if p is None:
        return "(no page)"
    return ("url=%s\n      title=%r\n      text_len=%s text_head=%r\n      indexed=%s"
            % ((p.get("url") or "")[:70], str(p.get("title") or "")[:50],
               len(p.get("text") or ""), (p.get("text") or "")[:90].replace("\n", " / "),
               len(S.indexed_actions(p.get("actions") or []))))


def run(url, goal, want):
    print("=" * 78)
    print("%s | candidate %r" % (url, want))
    b = Browser(url)
    try:
        p = observe(b)
        if p is None:
            print("  observe failed")
            return
        hit = None
        for i, a in S.indexed_actions(p.get("actions") or []):
            if a.get("kind") == "click" and want.lower() in str(a.get("label") or "").lower():
                hit = (i, a)
                break
        if hit is None:
            print("  candidate not indexed")
            return
        i, a = hit
        print("  BEFORE:\n      " + brief(p))
        b.act(a, p)
        time.sleep(1.5)
        p2 = observe(b, tries=4)
        print("  AFTER:\n      " + brief(p2))
        # did the page state ACTUALLY move toward anything? compare url path + title
        u0 = (p.get("url") or "").split("?")[0].rstrip("/")
        u1 = ((p2 or {}).get("url") or "").split("?")[0].rstrip("/")
        print("  VERDICT: url_changed=%s title_changed=%s" %
              (u0 != u1, (p.get("title") or "") != ((p2 or {}).get("title") or "")))
    finally:
        try:
            b.close()
        except Exception:
            pass


for url, goal, want in TARGETS:
    run(url, goal, want)
print("done")
