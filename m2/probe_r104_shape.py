r"""r104（PubMed 结果页）的形状：结果行到底进不进可点击集。

第一发探针（`m2/probe_expansion.py --dump`）只索引到 19 个页面外壳（logo / Advanced /
Save / 翻页），一条引文都没有——但那个 observe 是"索引非空就返回"，对 JS 填结果的页
等于**在结果出现之前**读数。这里改成：先轮询到出现 `/pubmed/<id>` 形态的链接（或到 14s），
再把整张动作表打出来。零模型，自有浏览器，只在没有批次在跑时用。
"""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast.browser import Browser, StalePage      # noqa: E402
from jev_ultrafast import skills as S                     # noqa: E402

URL = "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"
GOAL = "Search PubMed for 'CRISPR off-target' and open the first research article page."
ARTICLE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/\d{7,9}", re.I)

b = Browser(URL)
p = None
t0 = time.time()
tries = 0
while time.time() - t0 < 14:
    tries += 1
    try:
        p = b.observe(screenshot=False)
    except StalePage:
        time.sleep(0.5)
        continue
    acts = S._indexed(p.get("actions") or [])
    if any(ARTICLE.search(str(a.get("href") or "")) for _, a in acts):
        break
    time.sleep(0.6)

acts = S._indexed((p or {}).get("actions") or [])
print("tries=%d elapsed=%.1fs n_indexed=%d title=%r" % (
    tries, time.time() - t0, len(acts), str((p or {}).get("title") or "")[:50]))
arts = [(i, a) for i, a in acts if ARTICLE.search(str(a.get("href") or ""))]
print("article-shaped links=%d  first=%s" % (len(arts), arts[:2] and (
    arts[0][0], str(arts[0][1].get("label") or "")[:60], str(arts[0][1].get("href") or "")[:60])))
print("---- 全部索引项 ----")
for i, a in acts[:60]:
    print("   %-4s %-7s %-46s %s" % (i, a.get("kind"), str(a.get("label") or "")[:46],
                                     str(a.get("href") or "")[:56]))
if p is not None:
    print("---- first_result 会发什么 ----")
    hist = [
        {"kind": "fill", "skill": "search_type", "action": "Search",
         "outcome": {"url_changed": False}},
        {"kind": "click", "skill": "search_submit", "choice": "e12",
         "outcome": {"url_changed": True}},
    ]
    d = S.first_result(p, GOAL, hist)
    print(json.dumps(d, ensure_ascii=False)[:260] if d else "None")
b.close()
