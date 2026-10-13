r"""smoke tier 2 的取题器：**一个 task_id 只准有一种断言**（#73）。

为什么要单独一个脚本，而不是让 `scripts/smoke.ps1` 自己扫：
扫文件的逻辑一旦放在 shell 里就没法离线测，而它今天的行为是"**目录顺序决定语义**"——

| 文件 | x001 的 `success_assertion` | 死页（`example.invalid` 按设计不存在）上 |
|---|---|---|
| `m1/tasks-laya-19.jsonl` | `all_of[text_not_contains "booked", …]` | **PASS**（"没宣称订到票"在 chrome-error 页恒真） |
| `m1/tasks-reachable.jsonl` | `any_of[text_contains "not available", …]` | FAIL（页面上根本没有那句话） |

`Get-ChildItem @("m1","m2")` 的返回顺序决定 smoke 拿到哪一份，两份都是合法的 jsonl，
谁都看不出来。安全档的读数因此可以**在一次目录改名之后换含义**——这就是"x001 有两种语义"。

规则定成这样（不是"挑一个"，是"不许猜"）：
1. **钉住一个来源**（默认 `m1/tasks-laya-19.jsonl`，与 19 行冻结尺子同一把）；钉住的文件里有的 id
   一律用它，别的文件里的同 id 定义只有在**断言完全相同**时才允许并存。
2. 同一个 id 在不同文件里出现且**断言不同** ⇒ **拒绝出题并退出 2**，把两份定义都打出来。
   沉默地取第一份是这次要消灭的动作。
3. 出题时把每行的**出处**打进 stdout，报告里出问题可以追到文件。

评测语义不在这里（`m2/smoke_gate.py` 读报告），这个脚本只管"tier 2 跑的是哪 5 行、出自哪个文件"。
"""
import argparse
import io
import json
import os
import sys

DEFAULT_IDS = ["s005", "n004", "x001", "x002", "r142"]
DEFAULT_PIN = r"C:\Users\Administrator\openjev-ultrafast\m1\tasks-laya-19.jsonl"


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rel(path):
    """仓内路径打成相对形式（报告里能追到出处）；仓外（夹具临时目录）原样返回。"""
    try:
        return os.path.relpath(path, ROOT).replace(os.sep, "/")
    except ValueError:
        return path


def _load(path):
    rows = []
    with io.open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("task_id"):
                rows.append(r)
    return rows


def collect(paths, ids, pinned):
    """返回 (每 id 选中的一行, 冲突列表, 遮蔽列表)。冲突非空时调用方必须**不出题**。

    - 出现在**钉住文件**里的 id 就是权威：别的文件里同 id 的不同断言记为 `shadowed`（打出来，
      不再由目录顺序决定语义）。
    - 没被钉住的 id 如果在两个文件里断言不同 ⇒ `conflicts`（没有权威可挑，拒绝出题）。
    """
    chosen, seen, conflicts, shadowed = {}, {}, [], []
    for path in paths:
        if not os.path.exists(path):
            continue
        for r in _load(path):
            tid = r["task_id"]
            if tid not in ids:
                continue
            prev = seen.get(tid)
            if prev is None:
                seen[tid] = (path, r)
                chosen[tid] = (path, r)
                continue
            same = json.dumps(prev[1].get("success_assertion"), sort_keys=True,
                              ensure_ascii=False) == json.dumps(
                r.get("success_assertion"), sort_keys=True, ensure_ascii=False)
            if same or prev[0] == path:
                continue
            if os.path.abspath(prev[0]) == os.path.abspath(pinned):
                shadowed.append({"task_id": tid, "kept": prev[0], "shadowed": path})
            else:
                conflicts.append({"task_id": tid,
                                  "first": {"file": prev[0],
                                            "assertion": prev[1].get("success_assertion")},
                                  "second": {"file": path,
                                             "assertion": r.get("success_assertion")}})
    return chosen, conflicts, shadowed


def main(argv=None):
    ap = argparse.ArgumentParser(description="smoke tier 2 取题器（一个 id 一种断言）")
    ap.add_argument("--out", required=True, help="把选中的行写到这里")
    ap.add_argument("--ids", default=",".join(DEFAULT_IDS))
    ap.add_argument("--pin", default=DEFAULT_PIN,
                    help="钉住的题集文件（默认与 19 行冻结尺子同一把）")
    ap.add_argument("--scan", default=r"C:\Users\Administrator\openjev-ultrafast\m1,"
                                      r"C:\Users\Administrator\openjev-ultrafast\m2",
                    help="允许补题的目录，逗号分隔")
    args = ap.parse_args(list(argv) if argv is not None else sys.argv[1:])

    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    paths = [args.pin]
    for d in [x.strip() for x in args.scan.split(",") if x.strip()]:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("tasks") and name.endswith(".jsonl"):
                p = os.path.join(d, name)
                if p not in paths:
                    paths.append(p)

    chosen, conflicts, shadowed = collect(paths, ids, args.pin)
    if conflicts:
        print("拒绝出题：同一个 task_id 在两个文件里断言不同（#73 要消灭的就是"
              "'按目录顺序悄悄取第一份'）：")
        for c in conflicts:
            print("  %s  %s != %s" % (c["task_id"], c["first"]["file"], c["second"]["file"]))
            print("     first : %s" % json.dumps(c["first"]["assertion"], ensure_ascii=False)[:160])
            print("     second: %s" % json.dumps(c["second"]["assertion"], ensure_ascii=False)[:160])
        return 2

    for sh in shadowed:
        print("  注意：`%s` 在 %s 里还有一份**不同**的断言；按钉住的那份出题（%s）。"
              "语义不再由文件顺序决定 —— #73"
              % (sh["task_id"], _rel(sh["shadowed"]), _rel(sh["kept"])))

    missing = [i for i in ids if i not in chosen]
    if missing:
        print("拒绝出题：这些 id 没在任何题集里找到：%s" % ",".join(missing))
        return 2

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for tid in ids:
            path, row = chosen[tid]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print("  %-6s <- %s  assertion=%s" % (
                tid, _rel(path),
                json.dumps(row.get("success_assertion"), ensure_ascii=False)[:70]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
