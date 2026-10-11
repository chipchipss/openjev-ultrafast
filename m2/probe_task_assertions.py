r"""L3-B：任务有效性核实 = **让产品自己的评测器去核一个真页面**（零模型）。

前两版核实器都不够用，且各自的错都记在 `m2/real-log.md`：
  ① 只看"起点页有没有那条链/那个控件"——搜索族、表单族结构性地看不见（查询词不是链）；
  ② 驱动式（自己填自己点）——这些站的搜索框要按回车、/login 的输入框没有可匹配 label，
     驱动半数是假的"通过"（我那条 `echoed` 判据把"首页正文里本来就有 list"也算成回显）。

所以这一版只问一个**不打折**的问题：
  "我为这行写的断言，是不是被一个真实页面满足？"
做法：navigate 到该行的**见证 URL**（这行题面要求的终点页），observe 之后把页面喂给
`jev_ultrafast.evaluator`——就是跑批时判 PASS/FAIL 的同一份代码。评测器说满足，这行才进
任务集；说不满足，这行直接丢。这不循环：我断言的是终点页的性质，agent 的活是**走到那里**；
见证 URL 是我对站点的假设，CDP + 评测器是证明（"curl 只筛，CDP 才算数"的同一条例）。

只在没有批次在跑时用。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:2080")
os.environ.setdefault("BU_CDP_URL", "http://127.0.0.1:9222")

from jev_ultrafast import evaluator as E                     # noqa: E402
from jev_ultrafast.browser import Browser, StalePage         # noqa: E402

CANDS = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_candidates.jsonl"
OUT = r"C:\Users\Administrator\openjev-ultrafast\m2\tasks_l3_verified.jsonl"
LOG = r"C:\Users\Administrator\openjev-ultrafast\m2\out_task_assertions.txt"


def observe_settled(b, tries=8):
    p = None
    for _ in range(tries):
        try:
            p = b.observe(screenshot=False)
            if str((p or {}).get("title") or "").strip():
                return p
        except StalePage:
            pass
        time_sleep()
    return p


def time_sleep():
    import time
    time.sleep(0.5)


def check(row):
    """navigate 见证 URL → 用**产品评测器本人**判这行的断言。

    `evaluate(spec, final_page, history, status)` 的 status 必须是终态之一
    （`evaluator.py:86`：done/blocked/budget_exceeded/error）；这里报 `done`，
    因为我们主张的是"这个真页面满足这条断言"。
    """
    spec = {"task_id": row["slug"], "success_assertion": row["success_assertion"],
            "category": "positive", "extensions": row.get("extensions") or {}}
    b = Browser(row["witness_url"])
    try:
        page = observe_settled(b)
        v = E.evaluate(spec, page, [], "done")
        return str(getattr(v, "result", "")) == "PASS", page
    finally:
        b.close()


def main():
    import time
    rows = [json.loads(l) for l in open(CANDS, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r.get("witness_url") and r.get("success_assertion")]
    out = open(OUT, "w", encoding="utf-8")
    kept = 0
    for r in rows:
        try:
            ok, page = check(r)
        except Exception as e:
            ok, page = False, {}
            r["err"] = "%s:%s" % (type(e).__name__, str(e)[:70])
        rec = {k: r.get(k) for k in ("cid", "slug", "start_url", "goal", "family",
                                     "success_assertion", "witness_url")}
        rec["witness_ok"] = ok
        rec["witness_title"] = str((page or {}).get("title") or "")[:70]
        rec["witness_url_real"] = str((page or {}).get("url") or "")[:110]
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        kept += 1 if ok else 0
        print("  %-4s %-10s %s  %-58s %s" % (
            r["cid"], r["family"], "✓断言成立" if ok else "✗丢",
            r["witness_url"][:58], rec["witness_title"][:34]))
        time.sleep(0.6)
    out.close()
    print("\n断言成立 %d / %d" % (kept, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
