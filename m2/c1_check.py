"""C1 污染控制检查（v1）。

C1：Benchmark 域 ≠ Training 域。本脚本产出"benchmark 域名足迹"并做可静态验证的
检查；与训练域的不相交断言在拿到训练域清单后启用。

用法（fork 仓库根）：
  python3 -m m2.c1_check --logs logs/r5 --tasks m1/tasks.jsonl
  python3 -m m2.c1_check ... --training-domains training_domains.txt   # 每行一个域

检查项：
  1. 声明域完整性：每个任务的 domain 必须能解析为非空 host，且不得残留
     占位符（含 "<"——tasks_extra.jsonl 未填域时会被这条抓住）。
  2. 域名足迹清单：全量 url（step.url + task_result.final_url）的 host 去重输出——
     这就是 M2 划训练域时必须排除的 benchmark 足迹。
  3. 提供 --training-domains 时：训练域 ∩ 足迹必须为空（C1 硬断言，命中 exit 1）。

已知边界（记档，不在 v1 做）：
  "起始页域校验"当前无法从日志验证——agent 在 act 后会把 history[-1].url 更新为
  **动作后**页面（见 agent.py 的 history[-1].update(url=...)），日志里没有
  动作前的初始页记录。若要校验起始域，需 logger 增加 initial_page 事件（M2 #5 一并做）。
  0 动作任务（如 negative 类直接 BLOCKED）无 step 事件，仅作 info 注明。

退出码：0 = 通过；1 = 声明域违规/占位符泄漏/训练域交集非空。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


def _host(url: str) -> str:
    """url 或裸域名 → host（忽略 www. 前缀）。"""
    s = (url or "").strip()
    if not s:
        return ""
    if "://" in s:
        try:
            h = urlparse(s).hostname or ""
        except ValueError:
            return ""
    else:
        h = s.split("/", 1)[0].split(":", 1)[0]
    return h.removeprefix("www.")


def _load_declared(tasks_path: Path) -> tuple[dict, list[str]]:
    declared: dict[str, str] = {}
    problems: list[str] = []
    with tasks_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            spec = json.loads(line)
            tid = spec["task_id"]
            raw_domain = spec.get("domain", "")
            if "<" in raw_domain or ">" in raw_domain:
                problems.append(f"{tid} (line {lineno}): unfilled placeholder domain "
                                f"{raw_domain!r}")
                continue
            h = _host(raw_domain)
            if not h:
                problems.append(f"{tid} (line {lineno}): domain {raw_domain!r} "
                                f"does not parse to a host")
                continue
            declared[tid] = h
    return declared, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--training-domains", type=Path, default=None)
    args = ap.parse_args()

    declared, decl_problems = _load_declared(args.tasks)
    footprint: dict[str, set] = {}
    info: list[str] = []

    log_tasks = sorted(p.stem for p in args.logs.glob("*.jsonl"))

    for p in sorted(args.logs.glob("*.jsonl")):
        task_id = p.stem
        has_step = False
        urls: list[str] = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            ev = json.loads(ln)
            if ev.get("event") == "step" and ev.get("url"):
                has_step = True
                urls.append(ev["url"])
            elif ev.get("event") == "task_result":
                final = (ev.get("result") or {}).get("evidence", {}).get("final_url")
                if final:
                    urls.append(final)
        if not has_step:
            info.append(f"{task_id} (0-action task, no step events)")
        for u in urls:
            h = _host(u)
            if h:
                footprint.setdefault(h, set()).add(task_id)

    undeclared = [t for t in log_tasks if t not in declared and "<" not in declared.get(t, "")]
    # undeclared = logs 里的任务在 tasks 文件里没有（声明域问题已在 decl_problems 报）

    print(f"tasks declared: {len(declared)} / logs: {len(log_tasks)}")
    print(f"declared-domain problems: {len(decl_problems)}")
    for x in decl_problems:
        print(f"  VIOLATION {x}")
    if info:
        print(f"info (0-action tasks): {len(info)}")
        for s in info:
            print(f"  note {s}")

    print(f"benchmark footprint ({len(footprint)} hosts):")
    for h in sorted(footprint):
        print(f"  {h}  <- {','.join(sorted(footprint[h]))}")

    rc = 0
    if decl_problems:
        print("C1_CHECK: FAIL (declared-domain problems)")
        rc = 1

    missing_decl = [t for t in log_tasks if t not in declared]
    if missing_decl:
        print(f"C1_CHECK: WARN (log tasks missing from tasks file: {missing_decl})")

    if args.training_domains is not None:
        train = {_host(x) for x in
                 args.training_domains.read_text(encoding="utf-8").splitlines()
                 if x.strip() and not x.strip().startswith("#")}
        train.discard("")
        overlap = train & set(footprint)
        if overlap:
            print(f"C1_CHECK: FAIL (training domains overlap benchmark footprint): "
                  f"{sorted(overlap)}")
            rc = 1
        else:
            print(f"C1_CHECK: training domains ({len(train)}) disjoint from footprint "
                  f"({len(footprint)} hosts)")

    if rc == 0:
        print("C1_CHECK: PASS")
    return rc


if __name__ == "__main__":
    sys.exit(main())
