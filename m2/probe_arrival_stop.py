r"""#59 动手前的量：到站之后为什么不停——**到达页上的目标词长什么样**（零模型）。

b24 六行的 trace 签名一模一样：第 1 拍 `explicit_target` 到站，紧接着 `scroll_to_named_target`
连滚 3–4 拍（r148 滚到 15 拍、还重试了 5 次 DONE）。要修得先回答一个问题：
**到达页上那个 goal 引号里的短语，到底是以什么身份存在的** —— 是标题？正文一行？还是根本不存在？
不同答案对应完全不同的修法（放宽 `goal_reached` / 让 scroll 认输 / 都不许动）。

题面与到站 URL 一律从产物里取，不手写：
  goal ← `m2/tasks_real.jsonl`，到站 URL ← b24 报告里的 `final_url`。
每一行打印四件事，全部用产品自己的读法：
  1) `goal_phrases(goal)` 抽到的短语；2) 短语在不在 title 里；3) 在不在正文里（几次）；
  4) 在不在**可点元素**的 label 里（那就是 scroll 永远找不到的东西）。
只在没有批次在跑时使用（驱动自有 headless Chrome `:9222`）。
"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast.browser import Browser, StalePage       # noqa: E402
from jev_ultrafast import skills as S                       # noqa: E402

TASKS = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_real.jsonl"
B24 = r"C:\Users\Administrator\openjev-ultrafast\reports\real-1011-b24-ipc58-1011-015958.json"
ROWS = ["r142", "r123", "r124", "r134", "r148", "r126"]


def goals_by_id():
    out = {}
    for line in open(TASKS, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        out[r["task_id"]] = r["goal"]
    return out


def arrival_urls():
    rep = json.load(open(B24, encoding="utf-8"))
    out = {}
    for x in rep["results"]:
        r = x.get("result")
        if isinstance(r, dict):
            out[x["task_id"]] = str((r.get("evidence") or {}).get("final_url") or "")
    return out


def main():
    g, u = goals_by_id(), arrival_urls()
    for tid in ROWS:
        goal, url = g.get(tid, ""), u.get(tid, "")
        print("== %s  %s" % (tid, url[:76]))
        print("   goal: %s" % goal[:100])
        phrases = S.goal_phrases(goal)
        print("   goal_phrases = %s" % (phrases,))
        b = None
        try:
            b = Browser(url)
            p = None
            for _ in range(8):
                try:
                    p = b.observe(screenshot=False)
                except StalePage:
                    import time
                    time.sleep(0.5)
                    continue
                if S.indexed_actions(p.get("actions") or []):
                    break
                import time
                time.sleep(0.5)
        except Exception as e:
            print("   NAV ERROR %r" % (e,))
            if b:
                b.close()
            continue
        title = str((p or {}).get("title") or "")
        text = str((p or {}).get("text") or "")
        labels = [str(a.get("label") or "") for _, a in S.indexed_actions((p or {}).get("actions") or [])]
        print("   title=%r" % title[:70])
        for ph in phrases:
            in_title = ph.lower() in title.lower()
            n_text = len(re.findall(re.escape(ph.lower()), text.lower()))
            hit_labels = [l for l in labels if ph.lower() in l.lower()]
            print("   短语 %-34r title?%-5s 正文出现 %d 次  可点元素里有 %d 个 %s" % (
                ph[:34], in_title, n_text, len(hit_labels),
                (hit_labels[:1] and "-> %r" % hit_labels[0][:30]) or ""))
        d = S.goal_reached(p, goal, [])
        print("   goal_reached -> %s" % ((d or {}).get("operation") or "None"))
        print("   text 头 160 字 = %r" % text[:160])
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
