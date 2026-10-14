r"""#70 Tier 3 的成批对照 + #83 的第一份读数。

判据来自 `m2/real-log.md` 的预登记（跑之前写死的那一条）：
**零行为重构之后的一批，翻动的行必须全部落在"同 build 本来就会抖"的集合里**，
那个集合是今晚夜间档三轮（同一 build，69/69/70）的翻动并集，不是猜的。

第二个用途才是这批真正的新东西：`meta.stuck` 是 Tier 3 第三步装的仪器，
`entries_at_start > 0` 就是"这一题带着上一题的抑制笔记进场"。
这一步只读数，不下结论 —— 复位与否是行为变更，归 #83。

两个仪器坑（都在这份脚本里踩过，写下来免得下次再踩）：
1. 行是 `{"task_id":…, "result":{…}}` 的包装。第一版忘了剥包装就读 `failure_class`，
   于是环境类翻动（r127：基线三轮全是 `blocked_by_egress`，这一批 sqlite.org 通了）被当成
   "代码改动之外的翻动"，判据报"应当回滚"。**判据自己读错形状**，不是产品回归。
2. 翻动要先按 `failure_class` 分家：系统类（egress / bot wall / 上游错误页 / observe 失败）
   的成败由环境决定，不许拿来算代码的账。

运行：python m2/tier3_batch_audit.py <批报告.json> [--baseline reports/nightly-1013-2115-r1-*.json ...]
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: 同 build 三轮的翻动并集（`m2/real-log.md` 的夜间档那节，逐行核对出来的 6 行）。
SAME_BUILD_CHURN = {"r129", "r157", "r158", "r161", "r178", "r187"}


def results_of(path):
    """返回 {task_id: 内层 result}；内层才是 evaluator 的 TaskResult。"""
    d = json.load(io.open(path, encoding="utf-8"))
    # error 行的 result 是字符串 "ERROR"（不是 TaskResult），原样留着，由调用方分辨。
    return {r["task_id"]: (r.get("result") if isinstance(r.get("result"), dict)
                           else (r.get("result") or "")) for r in d["results"]}, d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--baseline", nargs="*", default=None)
    args = ap.parse_args()

    base_paths = args.baseline or sorted(
        glob.glob(str(REPO / "reports" / "nightly-1013-2115-r*.json")))
    bases = {}
    for p in base_paths:
        res, d = results_of(p)
        bases[Path(p).name] = res
        s = d["summary"]
        print("基线 %-46s pass=%s fp=%s error=%s unknown=%s"
              % (Path(p).name, s["pass"], s["quadrants"].get("false_positive", 0),
                 s["error"], s["unknown"]))

    cur, d = results_of(args.batch)
    s = d["summary"]
    print("对照 %-46s pass=%s error=%s unknown=%s"
          % (Path(args.batch).name, s["pass"], s["error"], s["unknown"]))
    print("     象限：%s" % s["quadrants"])
    fp = s["quadrants"].get("false_positive", 0)
    if fp:
        print("硬线 fp=0 破了。")
        return 2

    gain, lost, env, outside = [], [], [], []
    broken = []
    for tid, r in cur.items():
        if not isinstance(r, dict):
            # error 行的 `result` 是字符串 "ERROR"（r139 那族 `agent_init_failed_after_cdp_reset`），
            # 不是 TaskResult。第一版在这里直接 AttributeError —— 审计崩掉比读数错更难看。
            broken.append((tid, r))
            continue
        vals = {name: (br.get(tid) or {}).get("result") for name, br in bases.items()}
        now = r.get("result")
        if all(v == now for v in vals.values()):
            continue
        base_rows = [br.get(tid) for br in bases.values() if br.get(tid)]
        modes = sorted({b.get("failure_mode") for b in base_rows if b.get("failure_mode")})
        classes = {b.get("failure_class") for b in base_rows}
        pair = (tid, "/".join(sorted({v for v in vals.values() if v})) or "-", now or "-",
                ",".join(modes) or "-")
        (gain if now == "PASS" else lost).append(pair)
        if classes and classes <= {"system"}:
            env.append(tid)                       # 环境的账，不是代码的账
            continue
        if tid not in SAME_BUILD_CHURN:
            outside.append(tid)

    def show(tag, rows):
        print("%s %d 行：%s" % (tag, len(rows),
                              [("%s[%s→%s 基线档%s]" % x) for x in rows] or "无"))
    show("GAIN", gain)
    show("LOST", lost)
    print("其中**环境类**（基线全是 system 档，成败随站点/代理，不记在代码头上）：%s" % (env or "无"))
    print("error 行（result 不是 TaskResult）：%s" % ([b[0] for b in broken] or "无"))
    print("非环境翻动 %d 行，其中不在同 build 抖动集合里的：%s"
          % (len(gain) + len(lost) - len(env), outside or "无"))

    # #83 的第一份读数
    carry = [(tid, (r.get("meta") or {}).get("stuck")) for tid, r in cur.items()
             if isinstance(r, dict) and (r.get("meta") or {}).get("stuck")]
    with_entries = [c for c in carry if c[1].get("entries_at_start", 0) > 0]
    notes = sum(c[1].get("notes", 0) for c in carry)
    supp = sum(c[1].get("suppressed", 0) for c in carry)
    cross = sum(c[1].get("cross_task", 0) for c in carry)
    print("meta.stuck 有值的行：%d/%d；进场带笔记的行：%d（最多 %d 条）；"
          "本批 notes=%d suppressed=%d cross_task=%d"
          % (len(carry), len(cur), len(with_entries),
             max([c[1]["entries_at_start"] for c in with_entries], default=0),
             notes, supp, cross))
    print("  （只登记读数。复位是行为变更，归 #83。）")

    if outside:
        print("判据不通过：出现同 build 抖动集合之外的**非环境**翻动行 ⇒ 按预登记应当回滚并记账。")
        return 1
    print("判据通过：非环境翻动全部在同 build 抖动集合内（6 行那一族）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
