"""结果页上 `explicit_target` 到底给每一行打了几分？（零模型）

n004 单任务 Fix O 之后仍然在第 3 拍弃权、第 4 拍才点中行。两种可能：
① 那一拍的观测里**没有**结果行（导航后渲染竞态还在，只是变窄）；
② 行在，但**多行同分** → 优势判据（top-second<0.15）不成立 → 地板按设计弃权（Fix L 那一族）。
这里把打分列表原样打出来，用真页面分辨这两种，不再靠推断。

Run:  C:/Users/Administrator/miniconda3/envs/jev/python.exe scripts/probe_n004_score_list.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("HTTPX_PROXY", "http://127.0.0.1:2080")

from jev_ultrafast import skills as S      # noqa: E402
from jev_ultrafast.browser import Browser, StalePage   # noqa: E402

START = "https://www.rfc-editor.org/search/?q=RFC+9110"
GOAL = ("Search the RFC Editor for 'RFC 9110' and open the document page for RFC 9110. "
        "Then report the title.")


def observe(b, tag):
    for attempt in range(6):
        try:
            return b.observe(screenshot=False)
        except StalePage:
            time.sleep(0.3)
    raise SystemExit(f"{tag}: could not observe")


def score_list(page):
    """把 explicit_target 的打分阶梯重放一遍（它就是那些私有 helper 的组合）。"""
    phrases = S.goal_phrases(GOAL)
    out = []
    for index, a in S.indexed_actions(page.get("actions") or []):
        if a.get("kind") != "click" or (a.get("role") or "") == "option":
            continue
        lab = (a.get("label") or "").strip().lower()
        if not lab:
            continue
        lab_n = " ".join(S._tokens(lab))
        best, how = 0.0, ""
        for p in phrases:
            pn = " ".join(S._tokens(p))
            if not pn:
                continue
            if lab_n == pn:
                sc, tag2 = 2.0 + min(len(pn), 40) / 1000.0, "exact"
            elif lab_n.startswith(pn + " "):
                sc, tag2 = 1.5 + min(len(pn), 40) / 1000.0, "prefix"
            elif pn in lab_n:
                sc, tag2 = 1.0 + min(len(pn), 40) / 1000.0, "contains"
            elif p.startswith("/"):
                sc, tag2 = 0.0, "path-zeroed"
            elif len(lab_n) >= 4 and pn.startswith(lab_n + " "):
                sc, tag2 = 0.9, "head-fragment"
            else:
                pc = S._content(p)
                ratio = sum(1 for t in pc if t in set(S._tokens(lab))) / len(pc) if pc else 0
                sc, tag2 = (0.75 + ratio / 10, "ratio") if ratio >= 0.75 else (0.0, "no")
            if sc > best:
                best, how = sc, tag2
        if best > 0:
            out.append((best, a.get("id"), lab[:44], how))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def main():
    b = Browser(START)
    page = observe(b, "results")
    print(f"url={page['url']}\nactions={len(page['actions'])}")
    rows = [a for a in page["actions"] if "9110" in (a.get("label") or "")]
    print(f"labels containing '9110': {len(rows)} -> {[ (a.get('id'), (a.get('label') or '')[:30]) for a in rows ]}")
    print(f"\nphrases from goal: {S.goal_phrases(GOAL)}")
    scored = score_list(page)
    print("\nexplicit_target 打分列表（top 12）：")
    for sc, aid, lab, how in scored[:12]:
        print(f"  {sc:>5.3f}  {aid:<5} {how:<12} {lab!r}")
    if scored:
        margin = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0.0)
        print(f"\ntop={scored[0][0]:.3f} second={scored[1][0] if len(scored)>1 else 0:.3f} "
              f"margin={margin:.3f}  (判据: margin>=0.15 才出手)")
    d = S.explicit_target(page, GOAL, [])
    print(f"explicit_target(...) -> {None if d is None else (d.get('choice'), d.get('confidence'))}")
    r = S.route(page, GOAL, [])
    print(f"route(...)           -> {None if r is None else (r.get('choice'), r.get('skill'))}")
    b.close()


if __name__ == "__main__":
    main()
