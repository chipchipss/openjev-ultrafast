r"""#59 的射程审计：把 `link_followed_arrival` 的判据**照 b24 全部 50 行、逐拍**重放一遍。

为什么要这个：这一档会发 DONE，发错的地方就是"把没走完的路说成走完了"。六行的正例
已经在 `tests/test_skills.py` 用真实到达页钉住，但**它会不会在别的行也开火**只能拿现场
历史量。b24 是改前的批次（50 行、45 PASS），它的 step 事件里有每一拍的动作标签、
拍后 URL 与 `page_changed`——正好是这条判据要读的全部三个输入（判据不看页面正文）。

重放口径（与 `skills.link_followed_arrival` 的入参逐项对齐）：
  history  = 这一拍之前的最后一个真实动作（`kind`/`action`/`url`=**拍前**页）
  page.url = 这一拍的**拍后** URL
拍前 URL 从任务的 `domain`（起点）往后串起来。第 k 拍喂的是"第 k-1 拍刚做完"的状态。

零模型、只读，跑在任何批次之外（不动 jev_ultrafast/*）。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Administrator\openjev-ultrafast")

from jev_ultrafast import skills as S                         # noqa: E402

B24 = r"C:\Users\Administrator\openjev-ultrafast\reports\real-1011-b24-ipc58-1011-015958.json"
LOGDIR = r"C:\Users\Administrator\openjev-ultrafast\logs\real-1011-b24-ipc58-1011-015958"
TASKS = r"C:\Users\Administrator\AppData\Local\Temp\tasks_b19_50.jsonl"


def rows():
    rep = json.load(open(B24, encoding="utf-8"))
    tasks = {}
    for l in open(TASKS, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            tasks[r["task_id"]] = r
    out = []
    for x in rep["results"]:
        tid = x["task_id"]
        t = tasks.get(tid)
        if not t:
            continue
        p = os.path.join(LOGDIR, "%s.jsonl" % tid)
        if not os.path.exists(p):
            continue
        steps = []
        for line in open(p, encoding="utf-8"):
            e = json.loads(line)
            if e.get("event") == "step":
                steps.append(e)
        out.append((tid, t, steps))
    return out


def replay(tid, task, steps):
    """逐拍喂判据，返回所有会开火的拍号（1 基）。

    历史条目按 **结算之后** 的形状造（`agent.py:596-608`）：`url` 是那一拍的落地页、
    `url_from` 是出发页、换没换页写在 `outcome.url_changed` 上。第一版审计抄错了这张表，
    与实盘复跑同因。
    """
    goal = task["goal"]
    fires = []
    prev_url = task["domain"] if "://" in task.get("domain", "") else \
        "https://" + task["domain"]
    hist = []
    for i, s in enumerate(steps, 1):
        # 第 i 拍**之前**的状态：hist 里最后一条 = 第 i-1 拍（已结算）
        if hist:
            h = dict(hist[-1])
            page = {"url": prev_url}
            d = S.link_followed_arrival(page, goal, [h])
            if d is not None:
                fires.append(i)
        kind = "wait" if (s.get("action") or "").lower().startswith("wait") else (
            "scroll" if "scroll" in str(s.get("action") or "").lower() else "click")
        landed = s.get("url") or prev_url
        hist.append({
            "step": i,
            "kind": kind,
            "action": s.get("action"),
            "url": landed,
            "url_from": prev_url,
            "page_changed": s.get("page_changed"),
            "outcome": {"url_changed": bool(s.get("page_changed")) and landed != prev_url,
                        "page_changed": s.get("page_changed")},
            "skill": s.get("skill"),
        })
        prev_url = landed
    # 最后一拍**之后**还要评估一次（记作 n+1）：一行如果在第 1 拍点中就结束
    # （b25 的那 8 行正是如此），到达时刻落在最后一条 step 之后；只数"拍与拍之间"
    # 会一根都数不到——那是审计的洞，不是产品的洞。
    if hist:
        d = S.link_followed_arrival({"url": prev_url}, goal, [dict(hist[-1])])
        if d is not None:
            fires.append(len(steps) + 1)
    return fires, len(steps)


def main():
    """argv[1] = 批次报告路径（默认 b24）。历史条目从该批的 trace 逐拍重建。"""
    report = sys.argv[1] if len(sys.argv) > 1 else B24
    logdir = os.path.splitext(os.path.basename(report))[0]
    cand = os.path.join(os.path.dirname(LOGDIR), logdir)
    base = cand if os.path.isdir(cand) else LOGDIR
    rep = json.load(open(report, encoding="utf-8"))
    rows = []
    tasks = {json.loads(l)["task_id"]: json.loads(l)
             for l in open(TASKS, encoding="utf-8") if l.strip()}
    for x in rep["results"]:
        tid = x["task_id"]
        t = tasks.get(tid)
        p = os.path.join(base, "%s.jsonl" % tid)
        if not t or not os.path.exists(p):
            continue
        steps = [json.loads(l) for l in open(p, encoding="utf-8")]
        steps = [e for e in steps if e.get("event") == "step"]
        rows.append((tid, t, steps))
    print("批次 = %s（%d 行有 trace）" % (os.path.basename(report), len(rows)))
    fired = 0
    for tid, task, steps in rows:
        fires, n = replay(tid, task, steps)
        if fires:
            fired += 1
            print("  %-6s 开火拍=%-8s 总拍=%-3d %-9s %s" % (
                tid, fires, n, task["category"], task["goal"][:58]))
    print("会开火的行数 = %d / %d" % (fired, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
