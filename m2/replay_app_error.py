r"""#78 的离线重放：拿 **b34 与 b40 两批已提交的产物**，逐行比"改前怎么记 / 改后怎么记"。

为什么用重放而不是等新批：`blocked_by_upstream_error` 的触发条件是**站点自己 5xx**，
而 the-internet 现在（10-13 17:1x，`curl` = HTTP 200）是健康的 ⇒ 任何新批里这一档**预期命中 0 行**。
"它不该乱贴"可以在新批里当负向判据核，"它救回了被吞掉的信号"只能拿**历史上真发生过的 10 行**来证。

页帧的重建只用已入库工件里的事实：
- `title` / `url` 取报告里的 `evidence.final_title` / `final_url`；
- `text` 是否为空取该行 trace 里 `task_result.final_page.text_len`（b40 有；b34 跑在今天那次
  logger 改动**之前**，没这个字段 ⇒ 那 5 行的空页由"同一批同一时刻 `steps=0` + 同一标题"
  与 b40 的实测形状共同支撑，重放里显式标 `inferred`，不假装是原帧）。

`改前`那一列**不是我猜的**，是从 `reports/*.json` 里直接读出来的原始读数。

运行：python m2/replay_app_error.py
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jev_ultrafast import evaluator as E          # noqa: E402

BATCHES = {
    "b34": "reports/real-1012-b34-100-1012-123659.json",
    "b40": "reports/ci-1013-1544-1013-160343.json",
}
TITLE = "Application Error"


def trace_page_len(tag, task_id):
    """从该行 trace 里读 `final_page.text_len`；没有这个字段返回 None（= 改前 logger 没记）。"""
    d = "logs/%s/%s.jsonl" % (tag, task_id)
    if not os.path.exists(d):
        return None
    n = None
    for line in io.open(d, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line or '"task_result"' not in line:
            continue
        fp = (json.loads(line).get("final_page") or {})
        if "text_len" in fp:
            n = fp["text_len"]
    return n


def main():
    for name, path in BATCHES.items():
        rep = json.load(io.open(path, encoding="utf-8"))
        logtag = os.path.basename(path).replace(".json", "")
        hits = []
        for r in rep.get("results") or []:
            x = r.get("result")
            if not isinstance(x, dict):
                continue
            ev = x.get("evidence") or {}
            if str(ev.get("final_title")) != TITLE:
                continue
            hits.append((r["task_id"], x, ev))
        print("=== %s（%s）命中 %d 行" % (name, os.path.basename(path), len(hits)))
        for tid, x, ev in hits:
            tl = trace_page_len(logtag, tid)
            text = "" if tl in (0, None) else "x" * tl
            page = {"url": ev.get("final_url"), "title": ev.get("final_title"),
                    "text": text, "actions": []}
            # 断言必须拿**当时真吃过的那几条 clause**重建。第一版我从 `x["assertion"]` 取，
            # 那个字段在报告里根本不存在 ⇒ 传给评测器的是"零条款的 all_of"，它恒真 ⇒
            # 重放打出"改后 PASS"。这是一把读错的尺子，不是发现：判据没变，变的是仪器。
            clauses = [c.get("clause") for c in (ev.get("assertion_trace") or []) if c.get("clause")]
            spec = {"task_id": tid, "category": "positive", "extensions": {},
                    "success_assertion": {"type": "all_of", "clauses": clauses}}
            v = E.evaluate(spec, page, [], "blocked")
            flag = "" if tl is not None else "  [text_len 未记，空页按 b40 同形状推断]"
            print("  %-6s 改前 %-8s %-18s %-6s steps=%-2s  ⇒  改后 %-8s %-26s %-6s steps=%s%s" % (
                tid, x.get("result"), x.get("failure_mode"), x.get("failure_class"),
                (x.get("meta") or {}).get("steps"),
                v.result, v.failure_mode, v.failure_class,
                (v.meta or {}).get("steps"), flag))
            same = (x.get("result") == v.result
                    and str(x.get("quadrant")) == str(v.quadrant)
                    and (x.get("meta") or {}).get("steps") == (v.meta or {}).get("steps"))
            if not same:
                print("     !! 分数口径被动了（这条必须解释或回滚）：%s/%s vs %s/%s" % (
                    x.get("result"), x.get("quadrant"), v.result, v.quadrant))
        env_before = sum(1 for _, xx, _ in hits if xx.get("failure_class") == "system")
        print("  这批改前被记成环境 = %d 行 / 命中 %d 行 ⇒ 剩下的 %d 行是今晚这道分支救回来的信号" % (
            env_before, len(hits), len(hits) - env_before))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
