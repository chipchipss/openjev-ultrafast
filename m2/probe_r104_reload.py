"""r104 zoom: reload the pubmed results page in the live browser (JS challenge had
expired the session); after Page.reload, measure the indexed shape. Zero model."""
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
URL = "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"
ARTICLE = re.compile(r"/\d{7,9}/?$", re.I)


def observe(b, tries=10, want_article=True):
    p = None
    t0 = time.time()
    while time.time() - t0 < 25:
        try:
            p = b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.6)
            continue
        acts = S.indexed_actions(p.get("actions") or [])
        if not want_article or any(ARTICLE.search(str(a.get("href") or "")) for _, a in acts):
            return p
        time.sleep(0.7)
    return p


print("=== A. first load (this is what the agent sees) ===")
b = Browser(URL)
try:
    p = observe(b)
    acts = S.indexed_actions((p or {}).get("actions") or [])
    print("url=%s title=%r indexed=%d" % ((p or {}).get("url"),
          str((p or {}).get("title") or "")[:44], len(acts)))
    arts = [(i, a) for i, a in acts if ARTICLE.search(str(a.get("href") or ""))]
    print("article links indexed=%d" % len(arts))

    print("=== B. reload once (does the challenge clear) ===")
    b.reload()
    p2 = observe(b)
    acts2 = S.indexed_actions((p2 or {}).get("actions") or [])
    print("url=%s title=%r indexed=%d" % ((p2 or {}).get("url"),
          str((p2 or {}).get("title") or "")[:44], len(acts2)))
    arts2 = [(i, a) for i, a in acts2 if ARTICLE.search(str(a.get("href") or ""))]
    print("article links indexed=%d" % len(arts2))
    if arts2:
        print("---- 全部索引项 (first 40) ----")
        for i, a in acts2[:40]:
            print("   %-4s %-7s %-46s %s" % (i, a.get("kind"), str(a.get("label") or "")[:46],
                                             str(a.get("href") or "")[:56]))
        hist = [
            {"kind": "fill", "skill": "search_type", "action": "Search",
             "outcome": {"url_changed": False}},
            {"kind": "click", "skill": "search_submit", "choice": "e12",
             "outcome": {"url_changed": True}},
        ]
        d = S.first_result(p2, GOAL, hist)
        print("first_result ->",
              ("%s choice=%s label=%r" % (d.get("operation"), d.get("choice"),
                                          str({c: a for c, a in acts2}.get(str(d.get("target")), {}).get("label") or "")[:50]))
              if d else "None")
finally:
    b.close()
