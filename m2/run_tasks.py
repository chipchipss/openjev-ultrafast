"""M2 Benchmark Runner.

多轮 shadow 运行 + 数据抽取 + M2 验收报告。

用法：
  python3 -m m2.run_tasks \
      --tasks m1/tasks.jsonl m2/tasks_extra.jsonl \
      --rounds 3 \
      --benchmark-domains m2/benchmark_domains.txt \
      --log-dir logs/m2/ \
      --report reports/m2.json \
      --samples-dir samples/

运行位置：fork（runtime 侧 import jev_ultrafast.*；主仓可跑 --dry-run）。

对 #5 原稿的三处缝合修正（核对 #4b 实际代码所得，见 m1/m1-log.md）：
  1. sample_extractor 导入路径 = `m2.sample_extractor`（#4b 落在 m2/，不在
     jev_ultrafast 包内）；
  2. extract_all 签名 = (log_dir, samples_dir, *, tasks, benchmark_domains,
     training_domains)——tasks 必传：pair 的 goal/domain/category 只在任务表里，
     日志中不存在；
  3. _summarize 的 result 归一化：init 失败返回 result="ERROR"（str），
     原 `tr = r.get(...) or {}` 会对 str 调 .get 崩溃——与 m1 runner 同款地雷，
     同款修法（isinstance 守卫）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# 域清单
# ---------------------------------------------------------------------------

def _load_domains(path: Path) -> set[str]:
    """读域清单，每行一个，支持 # 注释。"""
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out


def _task_domain(spec: dict) -> str:
    """从 spec 提取域。去掉 scheme + path，只留 host。"""
    d = spec.get("domain", "")
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split("/")[0].split(":")[0]


# ---------------------------------------------------------------------------
# 单任务单轮
# ---------------------------------------------------------------------------

def _resolve_start_url(spec: dict, override: str | None) -> str:
    if override:
        return override
    domain = spec["domain"]
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def _run_one(
    spec: dict,
    round_idx: int,
    log_dir_round: Path,
    start_url: str,
    api_teacher,
    api_budget,
    screenshot: bool,
) -> dict:
    from jev_ultrafast.agent import Agent
    from jev_ultrafast.evaluator import evaluate
    from jev_ultrafast.logger import Logger

    task_id = spec["task_id"]
    # 每轮每任务的 log 文件名带轮次后缀
    log_name = f"{task_id}_r{round_idx}"
    logger = Logger(task_id=log_name, log_dir=log_dir_round)
    started = time.perf_counter()

    try:
        agent = Agent(
            url=start_url,
            goals=spec["goal"],
            task_spec=spec,
            screenshots=screenshot,
            api_teacher=api_teacher,
            api_budget=api_budget,
        )
    except Exception as e:
        logger.close()
        return {
            "task_id": task_id,
            "round": round_idx,
            "result": "ERROR",
            "error": f"agent_init_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    tb = None
    try:
        for _ in agent.run():
            logger.observe(agent.state, step_budget=agent.step_budget)
    except Exception:
        tb = traceback.format_exc()

    try:
        logger.observe(agent.state, step_budget=agent.step_budget)
    except Exception:
        pass

    status = agent.state.get("status", "error")
    meta = {
        "steps":       len(agent.state.get("history", [])),
        "model_calls": len(agent.state.get("decisions", [])),
        "api_calls":   len(agent.state.get("teacher_decisions", [])),
        "elapsed_ms":  round((time.perf_counter() - started) * 1000),
    }

    try:
        task_result = evaluate(
            spec,
            agent.state.get("page"),
            agent.state.get("history", []),
            status if status in {"done", "blocked", "budget_exceeded", "error"} else "error",
            meta=meta,
        )
    except Exception as e:
        task_result = None
        eval_error = f"{type(e).__name__}: {e}"
    else:
        eval_error = None

    try:
        if task_result is not None:
            logger.finalize(task_result,
                            step_budget=agent.step_budget,
                            final_page=agent.state.get("page"))
    finally:
        agent.close()
        logger.close()

    out = {"task_id": task_id, "round": round_idx, "domain": _task_domain(spec)}
    if tb is not None:
        out["error"] = "agent_loop_raised"
        out["traceback"] = tb
    if eval_error is not None:
        out["error"] = out.get("error") or "evaluate_raised"
        out["eval_error"] = eval_error
    if task_result is not None:
        out["result"] = task_result.to_dict()
    return out


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def _summarize(results: list[dict]) -> dict:
    summary = {
        "total":     len(results),
        "pass":      0, "fail": 0, "unknown": 0, "error": 0,
        "quadrants": {},
        "failure_modes": {},
        "agent_modes": {},
        "system_modes": {},
        "per_round": {},
    }
    for r in results:
        rd = r.get("round", 0)
        summary["per_round"].setdefault(rd, {"pass": 0, "fail": 0, "unknown": 0, "error": 0})

        # 缝合修正3：init 失败的 result 是 str（"ERROR"）——非 dict 一律进 error 桶
        raw = r.get("result")
        if not isinstance(raw, dict):
            summary["error"] += 1
            summary["per_round"][rd]["error"] += 1
            continue
        tr = raw
        res = tr.get("result")
        if res == "PASS":
            summary["pass"] += 1
            summary["per_round"][rd]["pass"] += 1
        elif res == "FAIL":
            summary["fail"] += 1
            summary["per_round"][rd]["fail"] += 1
        elif res == "UNKNOWN":
            summary["unknown"] += 1
            summary["per_round"][rd]["unknown"] += 1
        q = tr.get("quadrant")
        if q:
            summary["quadrants"][q] = summary["quadrants"].get(q, 0) + 1
        fm = tr.get("failure_mode")
        if fm:
            fc = tr.get("failure_class")
            bucket = summary["agent_modes"] if fc == "agent" else summary["system_modes"]
            bucket[fm] = bucket.get(fm, 0) + 1
            summary["failure_modes"][fm] = summary["failure_modes"].get(fm, 0) + 1
    return summary


def _m2_acceptance(summary: dict, extract_manifest: dict | None) -> tuple[bool, list[str]]:
    """M2 四条验收（docs/03 §5.6，双口径 A0.3 修订后）。"""
    notes = []
    ok = True

    dt = summary.get("decision_total")
    cp = (extract_manifest or {}).get("counts", {}).get("c_pairs", 0)

    if dt is not None and dt < 1000:
        ok = False
        notes.append(f"FAIL: decision_total={dt} < 1000")
    if extract_manifest is not None and cp < 200:
        ok = False
        notes.append(f"FAIL: c_pairs={cp} < 200")

    sys_modes = summary.get("system_modes", {})
    bad_sys = {k: v for k, v in sys_modes.items() if k in ("api_unavailable", "crash")}
    if bad_sys:
        ok = False
        notes.append(f"FAIL: system failure_modes present: {bad_sys}")

    if extract_manifest is not None:
        cc = extract_manifest.get("contamination_check", {})
        if cc.get("violations", 0) > 0:
            ok = False
            notes.append(f"FAIL: contamination violations={cc['violations']}")

    return ok, notes


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _load_tasks(paths: list[Path]) -> list[dict]:
    tasks = []
    seen_ids = set()
    for path in paths:
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    spec = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from None
                if spec["task_id"] in seen_ids:
                    raise ValueError(f"duplicate task_id: {spec['task_id']}")
                seen_ids.add(spec["task_id"])
                tasks.append(spec)
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, nargs="+", required=True,
                        help="一个或多个 tasks.jsonl")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--benchmark-domains", type=Path, required=True,
                        help="benchmark 域清单（每行一个）。这些域的输出不进 c_pairs。")
    parser.add_argument("--training-domains", type=Path, default=None,
                        help="训练域白名单（可选）。若给定，仅这些域的输出进 c_pairs。")
    parser.add_argument("--log-dir", type=Path, default=Path("logs/m2"))
    parser.add_argument("--samples-dir", type=Path, default=Path("samples"))
    parser.add_argument("--report", type=Path, default=Path("reports/m2.json"))
    parser.add_argument("--start-url", default=None)
    parser.add_argument("--task-delay", type=float, default=5.0)
    parser.add_argument("--round-delay", type=float, default=10.0)
    parser.add_argument("--teacher-limit", type=int, default=10000)
    parser.add_argument("--recovery-limit", type=int, default=500)
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--skip-extract", action="store_true",
                        help="跳过 sample_extractor 阶段")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tasks = _load_tasks(args.tasks)
    if not tasks:
        print("No tasks found.", file=sys.stderr)
        return 2

    benchmark_domains = _load_domains(args.benchmark_domains)
    training_domains = _load_domains(args.training_domains) if args.training_domains else None

    # 域分布
    domain_counts: dict[str, dict] = {}
    for spec in tasks:
        d = _task_domain(spec)
        domain_counts.setdefault(d, {"tasks": 0, "benchmark": d in benchmark_domains})
        domain_counts[d]["tasks"] += 1

    print(f"Loaded {len(tasks)} tasks, {args.rounds} rounds.")
    print(f"Benchmark domains: {len(benchmark_domains)}")
    print("Domain distribution:")
    for d, info in sorted(domain_counts.items()):
        mark = "B" if info["benchmark"] else "T"
        print(f"  [{mark}] {d}: {info['tasks']} tasks")

    if args.dry_run:
        print("DRY RUN OK")
        return 0

    # 初始化 budget + teacher（跨轮共享，B1 语义：限额是整个 M2 运行期间的总量）
    from jev_ultrafast.api_budget import APIBudget
    from jev_ultrafast.api_teacher import APITeacher

    budget = APIBudget(teacher_limit=args.teacher_limit,
                       recovery_limit=args.recovery_limit)
    try:
        teacher = APITeacher(budget)
    except Exception as e:
        print(f"Failed to init APITeacher: {e}", file=sys.stderr)
        return 2

    # 逐轮逐任务
    all_results: list[dict] = []
    for r in range(args.rounds):
        log_dir_round = args.log_dir / f"r{r}"
        log_dir_round.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Round {r + 1}/{args.rounds} ===")

        for i, spec in enumerate(tasks, 1):
            tid = spec["task_id"]
            start_url = _resolve_start_url(spec, args.start_url)
            print(f"[{i}/{len(tasks)}] {tid}  {start_url}")
            try:
                res = _run_one(spec, r, log_dir_round, start_url,
                               teacher, budget, args.screenshots)
            except Exception as e:
                res = {"task_id": tid, "round": r,
                       "error": f"runner_exception: {e}",
                       "traceback": traceback.format_exc()}
            got = res.get("result")
            got = got.get("result") if isinstance(got, dict) else got
            print(f"    → {res.get('error') or got}")
            all_results.append(res)
            if i < len(tasks):
                time.sleep(args.task_delay)

        if r < args.rounds - 1:
            time.sleep(args.round_delay)

    summary = _summarize(all_results)

    # 累计 decisions 从日志统计
    decisions_total = 0
    teacher_shadow_total = 0
    for r in range(args.rounds):
        for jf in (args.log_dir / f"r{r}").glob("*.jsonl"):
            with jf.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("event") == "decision":
                        decisions_total += 1
                    elif ev.get("event") == "teacher_shadow":
                        teacher_shadow_total += 1
    summary["decision_total"] = decisions_total
    summary["teacher_shadow_total"] = teacher_shadow_total
    summary["budget"] = _budget_snapshot(budget)

    # 抽取样本（缝合修正1+2：m2 包路径 + tasks 必传）
    extract_manifest = None
    if not args.skip_extract:
        try:
            from m2.sample_extractor import extract_all
            extract_manifest = extract_all(
                args.log_dir, args.samples_dir,
                tasks=tasks,
                benchmark_domains=benchmark_domains,
                training_domains=training_domains,
            )
        except Exception as e:
            extract_manifest = {"error": f"{type(e).__name__}: {e}",
                                "traceback": traceback.format_exc()}

    ok, notes = _m2_acceptance(summary, extract_manifest)

    report = {
        "summary":            summary,
        "domain_distribution": domain_counts,
        "acceptance":         {"passed": ok, "notes": notes},
        "extract_manifest":   extract_manifest,
        "results":            all_results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print()
    print(f"PASS={summary['pass']}  FAIL={summary['fail']}  "
          f"UNKNOWN={summary['unknown']}  ERROR={summary['error']}")
    print(f"decision_total={decisions_total}  teacher_shadow_total={teacher_shadow_total}")
    if extract_manifest and "counts" in extract_manifest:
        print(f"extracted: {extract_manifest['counts']}")
    print(f"M2 acceptance: {'PASS' if ok else 'FAIL'}")
    for n in notes:
        print(f"  {n}")
    print(f"report → {args.report}")

    return 0 if ok else 1


def _budget_snapshot(budget) -> dict:
    try:
        fn = getattr(budget, "log_entry", None)
        return fn() if callable(fn) else {}
    except Exception:
        return {}


if __name__ == "__main__":
    sys.exit(main())
