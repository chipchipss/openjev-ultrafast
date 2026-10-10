r"""一个批次的判据读数，一次算齐（离线，不碰浏览器也不碰 :8090，可以在别的批在飞时跑）。

为什么进仓而不是留在 %TEMP%：每一刀的裁决都要问同样六个问题（总分、旧题配对差集、
新行是否守住、这一刀的射程有没有外溢、零云端、墙钟）。b19/b20 连着三次把这些写在临时脚本里，
临时脚本会随磁盘清理消失，而 `m2/real-log.md` 的每个数字都得能重新算出来（纪律⑤）。
L3 要把这套读数变成每次改动都跑的回归，就更不能靠一次性脚本。

用法：
    python m2/batch_audit.py <report.json> [--pair <旧 report.json>] [--log <logs/目录>]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: 旧 21 题 = r101..r122 去掉站点空洞的 r118（b16 起的口径，判据 1 里写死过）
OLD21 = [f"r{i:03d}" for i in range(101, 123) if i != 118]


def load_rows(path: str) -> dict:
    rep = json.load(open(path, encoding="utf-8"))
    out = {}
    for x in rep["results"]:
        r = x["result"]
        out[x["task_id"]] = r if isinstance(r, dict) else {"result": r, "raw_error": True}
    return out, rep["summary"]


def outcome(row: dict):
    return (row.get("result"), row.get("quadrant"), row.get("failure_mode"),
            (row.get("meta") or {}).get("steps"))


def decision_skills(log_dir: str, tid: str) -> list:
    f = os.path.join(log_dir, tid + ".jsonl")
    if not os.path.exists(f):
        return []
    out = []
    for line in open(f, encoding="utf-8"):
        e = json.loads(line)
        if e.get("event") == "decision" and e.get("skill"):
            out.append(e["skill"])
    return out


def step_helpers(log_dir: str):
    c = collections.Counter()
    n = 0
    for f in glob.glob(os.path.join(log_dir, "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            e = json.loads(line)
            if e.get("event") == "step":
                n += 1
                c[str(e.get("text_helper"))] += 1
    return n, dict(c)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--pair")
    ap.add_argument("--log")
    ap.add_argument("--scope", default="",
                    help="这一刀允许开火的技能名=题号集，如 first_result=r103,r104")
    args = ap.parse_args()

    m, s = load_rows(args.report)
    print("== %s" % os.path.basename(args.report))
    print("total=%s pass=%s fail=%s unknown=%s error=%s" % (
        s.get("total"), s.get("pass"), s.get("fail"), s.get("unknown"), s.get("error")))
    print("quadrants=%s" % (s.get("quadrants"),))
    print("failure_modes=%s" % (s.get("failure_modes"),))
    print("非 PASS 行：")
    for t in sorted(m):
        if m[t].get("result") != "PASS":
            print("   %-6s %s" % (t, outcome(m[t])))

    if args.pair:
        p, _ = load_rows(args.pair)
        gain = [t for t in m if t in p and p[t].get("result") != "PASS"
                and m[t].get("result") == "PASS"]
        lost = [t for t in m if t in p and p[t].get("result") == "PASS"
                and m[t].get("result") != "PASS"]
        print("\n配对 %s：GAIN=%s LOST=%s" % (os.path.basename(args.pair), gain, lost))
        for t in sorted(set(p) | set(m)):
            if t not in m or t not in p:
                print("   行缺失 %s" % t)
                continue
            if outcome(p[t]) != outcome(m[t]):
                print("   %-6s 旧=%s 新=%s" % (t, outcome(p[t]), outcome(m[t])))
        old = [t for t in OLD21 if t in m]
        new = [t for t in m if t not in OLD21]
        print("旧 %d 题 pass=%d/%d；新 %d 行 pass=%d/%d" % (
            len(old), sum(m[t].get("result") == "PASS" for t in old), len(old),
            len(new), sum(m[t].get("result") == "PASS" for t in new), len(new)))

    if args.log:
        n, th = step_helpers(args.log)
        print("\nstep 事件=%d text_helper=%s（零云端要求 ⊆ {None, startlux-decision-2b}）" % (n, th))
        ts = [os.path.getmtime(os.path.join(args.log, f)) for f in os.listdir(args.log)]
        print("批墙钟（日志目录首末 mtime）= %.1f min" % ((max(ts) - min(ts)) / 60.0))
        missing = [t for t in m if not os.path.exists(os.path.join(args.log, t + ".jsonl"))]
        if missing:
            print("没有 trace 的行=%s  ← 仪器丢的行，不算产品读数" % missing)
        if args.scope:
            skill, _, ids = args.scope.partition("=")
            allowed = set(ids.split(","))
            fired = {t: decision_skills(args.log, t).count(skill) for t in m}
            fired = {t: c for t, c in fired.items() if c}
            outside = sorted(t for t in fired if t not in allowed)
            print("%s 开火表=%s；射程外开火=%s" % (skill, fired, outside or "[]"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
