r"""#59 的 fixture：抓六行任务的**到达页**（零模型，与 `probe_r104_fixture.py` 同套路）。

为什么要抓而不是手写：#52 的教训是"手写快照只能表达我以为的形状"。#59 的规则要用到达页上的
真实 title/正文/动作表来钉（尤其 r126/r142 那种"goal 的短语在到达页上根本不存在"的关键事实），
所以页面必须来自现场。历史（哪一拍点的、label、page_changed、落地 URL）不进 fixture ——
那是从 `logs/real-1011-b24-*/r1xx.jsonl` 的 step 事件里**照抄**出来的，见 tests/test_skills.py。

只在没有批次在跑时使用（驱动自有 headless Chrome `:9222`）。
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast import skills as S                       # noqa: E402

FIX = r"C:\Users\Administrator\openjev-ultrafast\m2\fixtures"
# tid → 到达 URL（全部取自 b24 报告的 final_url，不手写）
B24 = r"C:\Users\Administrator\openjev-ultrafast\reports\real-1011-b24-ipc58-1011-015958.json"
ROWS = ["r123", "r124", "r126", "r134", "r142", "r148"]


def arrival_urls():
    rep = json.load(open(B24, encoding="utf-8"))
    out = {}
    for x in rep["results"]:
        r = x.get("result")
        if isinstance(r, dict):
            out[x["task_id"]] = str((r.get("evidence") or {}).get("final_url") or "")
    return out


def capture(tid, url):
    b = Browser(url)
    try:
        p = None
        for _ in range(10):
            try:
                p = b.observe(screenshot=False)
            except StalePage:
                time.sleep(0.5)
                continue
            if str((p or {}).get("title") or "").strip() and str((p or {}).get("text") or "").strip():
                break
            time.sleep(0.6)
        acts = S.indexed_actions((p or {}).get("actions") or [])
        title = str((p or {}).get("title") or "")
        text = str((p or {}).get("text") or "")
        path = os.path.join(FIX, "%s_arrival.json" % tid)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(p, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print("  %-6s title=%-46r text=%-6d acts=%-3d -> %s (%d B)" % (
            tid, title[:46], len(text), len(acts), os.path.basename(path),
            os.path.getsize(path)))
        return bool(title.strip() and text.strip())
    finally:
        b.close()


def main():
    os.makedirs(FIX, exist_ok=True)
    u = arrival_urls()
    bad = []
    for tid in ROWS:
        url = u.get(tid, "")
        if not url.startswith("http"):
            print("  %-6s 没有到达 URL，跳过" % tid)
            bad.append(tid)
            continue
        ok = capture(tid, url)
        if not ok:
            bad.append(tid)
        time.sleep(1.0)
    print("空页/失败 = %s" % (bad or "无"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
