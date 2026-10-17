"""arxiv /search/physics page (the page r102's step 2 actually lands on) -- what does
its search box and submit produce, and is the b24 landing URL still /search/physics today?
Zero model."""
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

GOAL = "Search arXiv for the paper 'Attention Is All You Need' and open its abstract page."


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


print("=== A. arxiv.org/ step-0: click the Search control the floor picks ===")
b = Browser("https://arxiv.org/")
try:
    p = observe(b)
    idx = S.indexed_actions(p.get("actions") or [])
    e13 = next((a for _, a in idx if a.get("id") == "e13"), None)
    print("e13 =", e13 and (e13.get("kind"), e13.get("label"), e13.get("href")))
    if e13:
        b.act(e13, p)
        p2 = observe(b)
        print("landed: url=%s title=%r" % (p2.get("url"), str(p2.get("title") or "")[:50]))
        idx2 = S.indexed_actions(p2.get("actions") or [])
        fills = [(i, a.get("label"), a.get("role")) for i, a in idx2 if a.get("kind") == "fill"]
        print("fills:", fills)
        st = S.search_type(p2, GOAL, [])
        print("search_type ->", (st.get("choice"), st.get("text")) if st else st)
        if st:
            action = next(a for _, a in idx2 if a.get("id") == st["choice"])
            b.act(action, p2, text=st["text"])
            p3 = observe(b)
            idx3 = S.indexed_actions(p3.get("actions") or [])
            print("after fill: url=%s indexed=%d" % (p3.get("url"), len(idx3)))
            sub = S.search_submit(p3, GOAL, [{"kind": "fill", "action": action.get("label"),
                                              "choice": action.get("id"), "skill": "search_type",
                                              "text": st["text"],
                                              "outcome": {"url_changed": False}}])
            print("search_submit ->",
                  (sub.get("choice"),
                   str({c: a for c, a in idx3}.get(str(sub.get("target")), {}).get("label") or "")[:40])
                  if sub else sub)
            if sub:
                suba = next(a for _, a in idx3 if a.get("id") == sub.get("choice"))
                b.act(suba, p3)
                p4 = observe(b)
                idx4 = S.indexed_actions(p4.get("actions") or [])
                print("after submit: url=%s" % p4.get("url"))
                print("  indexed=%d" % len(idx4))
                import re
                arts = [(i, str(a.get("label") or "")[:44], str(a.get("href") or "")[:56])
                        for i, a in idx4 if re.search(r"/abs/\d{4}\.\d{4,5}", str(a.get("href") or ""))]
                print("  abs-links indexed=%d first=%s" % (len(arts), arts[:4]))
                print("---- first 30 indexed ----")
                for i, a in idx4[:30]:
                    print("   %-4s %-7s %-44s %s" % (i, a.get("kind"),
                          str(a.get("label") or "")[:44], str(a.get("href") or "")[:50]))
finally:
    b.close()
