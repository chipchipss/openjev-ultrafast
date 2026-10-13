r"""把 r104 的**结果页**抓成离线 fixture（零模型，之后单测再也不碰浏览器）。

为什么要抓：`m2/probe_r104_shape.py` 只在控制台打了形状，读数无法进仓；而 `first_result`
的选行规则要改，改前/改后必须**对着同一张真实动作表**判定，否则每次重跑网络页都在变。
注意两点（都是这台仪器自己教出来的错）：
  - PubMed 的结果由 JS 填：`observe` 一非空就返回 = 在结果出现之前读数（只剩 19 条页壳）。
    这里轮询到**真的出现引文行**才收。
  - 引文行的 href 是**相对**的（`/36970626/`），早先用绝对 host 正则去认，命中 0 条。
只在没有批次在跑时使用（它驱动自有 headless Chrome `:9222`）。
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

# 真实轨迹里 search_submit 落地的那一页（b18 r104 第 2 拍 post-action url）。
URL = "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target"
GOAL = "Search PubMed for 'CRISPR off-target' and open the first research article page."
# 引文行：相对 `/36970626/` 或绝对 `pubmed.ncbi.nlm.nih.gov/36970626`
ARTICLE = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov)?/(\d{7,9})/?$|^/\d{7,9}/?$", re.I)
FIXTURE = r"C:\Users\Administrator\openjev-ultrafast\m2\fixtures\r104_pubmed_results.json"


def main():
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
        if any(ARTICLE.match(str(a.get("href") or "").strip()) for _, a in acts):
            break
        time.sleep(0.6)
    acts = S.indexed_actions((p or {}).get("actions") or [])
    arts = [(i, a) for i, a in acts if ARTICLE.match(str(a.get("href") or "").strip())]
    print("tries=%d elapsed=%.1fs n_indexed=%d article_rows=%d title=%r text_len=%d" % (
        tries, time.time() - t0, len(acts), len(arts),
        str((p or {}).get("title") or "")[:50], len(str((p or {}).get("text") or ""))))
    print("---- 引文行（位置号 / label / href）----")
    for i, a in arts[:6]:
        print("   %-4s %-70s %s" % (i, str(a.get("label") or "")[:70],
                                    str(a.get("href") or "")[:40]))
    print("---- first_result 现在会发什么 ----")
    hist = [
        {"kind": "fill", "skill": "search_type", "action": "Search",
         "outcome": {"url_changed": False}},
        {"kind": "click", "skill": "search_submit", "choice": "e11",
         "outcome": {"url_changed": True}},
    ]
    d = S.first_result(p, GOAL, hist)
    pick = None
    if d:
        node = dict(acts).get(str(d.get("target") or "")) or {}
        pick = (d.get("choice"), d.get("operation"), d.get("target"),
                str(node.get("label") or "")[:48], str(node.get("href") or "")[:48])
    print(pick if pick else "None")
    if p is None or not arts:
        print("NOT SAVED: no article row observed")
        b.close()
        return 1
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print("saved %s (%d bytes, %d actions)" % (
        FIXTURE, os.path.getsize(FIXTURE), len(p.get("actions") or [])))
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
