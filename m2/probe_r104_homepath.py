"""pubmed wall attribution: same headless Chrome via the same proxy, but a brand-new
tab on the homepage first (does the challenge only hit the results URL?), then follow
the homepage's own search box path. Zero model."""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage               # noqa: E402
from jev_ultrafast import skills as S                              # noqa: E402

GOAL = "Search PubMed for 'CRISPR off-target' and open the first research article page."


def observe(b, tries=10):
    p = None
    t0 = time.time()
    while time.time() - t0 < 20:
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.6)
            continue
        if S.indexed_actions(p.get("actions") or []):
            return p
        time.sleep(0.7)
    return p


print("=== A. pubmed homepage, fresh tab ===")
b = Browser("https://pubmed.ncbi.nlm.nih.gov/")
try:
    p = observe(b)
    acts = S.indexed_actions((p or {}).get("actions") or [])
    print("url=%s title=%r indexed=%d" % ((p or {}).get("url"),
          str((p or {}).get("title") or "")[:44], len(acts)))
    if acts:
        for i, a in acts[:20]:
            print("   %-4s %-7s %-44s %s" % (i, a.get("kind"), str(a.get("label") or "")[:44],
                                             str(a.get("href") or "")[:44]))
        st = S.search_type(p, GOAL, [])
        print("search_type ->", (st.get("choice"), st.get("text")) if st else st)
        if st:
            action = next(a for _, a in acts if a.get("id") == st["choice"])
            b.act(action, p, text=st["text"])
            p2 = observe(b)
            acts2 = S.indexed_actions((p2 or {}).get("actions") or [])
            print("after fill: title=%r indexed=%d" % (str((p2 or {}).get("title") or "")[:44], len(acts2)))
            sub = S.search_submit(p2, GOAL, [{"kind": "fill", "action": action.get("label"),
                                              "choice": action.get("id"), "skill": "search_type",
                                              "text": st["text"],
                                              "outcome": {"url_changed": False}}])
            print("search_submit ->", (sub.get("choice"), sub.get("operation")) if sub else sub)
            if sub:
                suba = next(a for _, a in acts2 if a.get("id") == sub.get("choice"))
                b.act(suba, p2)
                p3 = observe(b)
                acts3 = S.indexed_actions((p3 or {}).get("actions") or [])
                print("after submit: url=%s title=%r indexed=%d" % (
                    (p3 or {}).get("url"), str((p3 or {}).get("title") or "")[:44], len(acts3)))
                arts = [(i, a) for i, a in acts3
                        if re.search(r"/\d{7,9}/?$", str(a.get("href") or ""))]
                print("article links indexed=%d first=%s" % (
                    len(arts), (arts[0][0], str(arts[0][1].get("label") or "")[:40]) if arts else None))
finally:
    b.close()
