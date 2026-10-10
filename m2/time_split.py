r"""一批的墙钟分解：任务在跑 vs 任务之间在等什么（#34 M6-A 欠的读数）。

L3 的判据是"100–300 题 ≤30 分钟"。b18/b19/b20 的批墙钟都是 27.7–28.4 min/50 题，
但报告里 `meta.elapsed_ms` 之和只有 ~7 min —— **差出来的 20 分钟才是吞吐的真问题**，
而且它决定了修法完全不同：大头在任务之间的固定开销（重启浏览器、逐任务起进程、等待）
就先砍开销，甚至不必并行；大头在任务本身才需要并行 runner（#35）。

算法：每个 `logs/<批>/<tid>.jsonl` 里的 `timestamp` 是绝对时间，取每行的首末事件；
按首事件排序后，`gap_i = first(i+1) - last(i)` 就是任务 i 结束到任务 i+1 开始之间的空档。
离线，不碰浏览器也不碰 :8090。

用法：python m2/time_split.py <report.json> <logs目录>
"""
from __future__ import annotations

import glob
import json
import os
import sys


def spans_of(log_dir: str) -> list:
    out = []
    for f in glob.glob(os.path.join(log_dir, "*.jsonl")):
        first = last = None
        for line in open(f, encoding="utf-8"):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("timestamp")
            if not isinstance(t, (int, float)):
                continue
            if first is None or t < first:
                first = t
            if last is None or t > last:
                last = t
        if first is not None:
            out.append((os.path.basename(f).split(".")[0], first, last))
    out.sort(key=lambda x: x[1])
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rep_path, log_dir = sys.argv[1], sys.argv[2]
    rep = json.load(open(rep_path, encoding="utf-8"))
    el = {}
    for x in rep["results"]:
        r = x["result"]
        if isinstance(r, dict):
            el[x["task_id"]] = (r.get("meta") or {}).get("elapsed_ms") or 0
    sp = spans_of(log_dir)
    if len(sp) < 2:
        print("rows with trace = %d -- 不够分解" % len(sp))
        return 1
    wall = sp[-1][2] - sp[0][1]
    work = sum(el.get(t, 0) for t, _, _ in sp) / 1000.0      # 秒
    own = sum(last - first for _, first, last in sp)         # 秒
    gaps = []
    for (t1, _, l1), (t2, f2, _) in zip(sp, sp[1:]):
        gaps.append((t1, t2, f2 - l1))
    gsum = sum(g for _, _, g in gaps)
    print("== %s" % os.path.basename(rep_path))
    print("有 trace 的行=%d  批跨度(首事件→末事件)=%.1f min" % (len(sp), wall / 60.0))
    print("  行内 elapsed_ms 之和 = %.1f s = %.1f min（报告自己的口径）" % (work, work / 60.0))
    print("  trace 首末事件跨度之和 = %.1f min" % (own / 60.0))
    print("  任务之间的空档合计 = %.1f min = 批跨度的 %.0f%%" % (
        gsum / 60.0, 100.0 * gsum / wall))
    print("  空档中位=%.1fs 平均=%.1fs 最大=%.1fs" % (
        sorted(g for _, _, g in gaps)[len(gaps) // 2],
        gsum / len(gaps), max(g for _, _, g in gaps)))
    print("\n空档最大的 10 段（前任务 → 后任务）：")
    for t1, t2, g in sorted(gaps, key=lambda x: -x[2])[:10]:
        print("   %-6s → %-6s %6.1fs" % (t1, t2, g))
    slow = sorted(((last - first, t) for t, first, last in sp), reverse=True)[:8]
    print("\ntrace 自身最长的 8 行（秒）：")
    for d, t in slow:
        print("   %-6s %6.1fs  elapsed_ms=%s" % (t, d / 1.0, el.get(t)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
