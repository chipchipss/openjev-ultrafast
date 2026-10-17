"""r104 zoom: retry the pubmed homepage + results page after the 403/recaptcha window.
The agent's own batches saw a results page (b23: first_result hit target 26). Zero model."""
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
ARTICLE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/\d{7,9}", re.I)

b = Browser(URL)
p = None
t0 = time.time()
tries = 0
while time.time() - t0 < 20:
    tries += 1
    try:
        p = b.observe(screenshot=False)
    except StalePage:
        time.sleep(0.5)
        continue
    acts = S.indexed_actions(p.get("actions") or [])
    if any(ARTICLE.search(str(a.get("href") or "")) for _, a in acts):
        break
    if str(p.get("title") or "") == "403":
        time.sleep(1.5)
        continue
    time.sleep(0.6)

acts = S.indexed_actions((p or {}).get("actions") or [])
print("tries=%d elapsed=%.1fs n_indexed=%d title=%r url=%s" % (
    tries, time.time() - t0, len(acts), str((p or {}).get("title") or "")[:50],
    (p or {}).get("url")))
arts = [(i, a) for i, a in acts if ARTICLE.search(str(a.get("href") or ""))]
print("article-shaped links=%d  first=%s" % (len(arts), arts[:2] and (
    arts[0][0], str(arts[0][1].get("label") or "")[:60], str(arts[0][1].get("href") or "")[:60])))
print("---- 全部索引项 (first 40) ----")
for i, a in acts[:40]:
    print("   %-4s %-7s %-46s %s" % (i, a.get("kind"), str(a.get("label") or "")[:46],
                                     str(a.get("href") or "")[:56]))
if p is not None and arts:
    hist = [
        {"kind": "fill", "skill": "search_type", "action": "Search",
         "outcome": {"url_changed": False}},
        {"kind": "click", "skill": "search_submit", "choice": "e12",
         "outcome": {"url_changed": True}},
    ]
    d = S.first_result(p, GOAL, hist)
    print("first_result ->",
          ("%s choice=%s label=%r" % (d.get("operation"), d.get("choice"),
                                      str({c: a for c, a in acts}.get(str(d.get("target")), {}).get("label") or "")[:50]))
          if d else "None")
b.close()
