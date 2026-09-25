"""M1 Benchmark Runner.

读取 m1/tasks.jsonl → 逐 task 运行 → 写 task_result → 汇总。

用法：
  python3 -m m1.run_tasks --tasks m1/tasks.jsonl --log-dir logs/ --report reports/m1.json

环境依赖：
  DECIDER_2B_BASE_URL / DECIDER_2B_MODEL / DECIDER_2B_API_KEY
  TEXT_HELPER_BASE_URL / TEXT_HELPER_MODEL / TEXT_HELPER_API_KEY

基座依赖：
  agent.py / browser.py / model.py /questions.py（fork jev-ultrafast 后置于本包内）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

# 允许从仓库根运行
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_ultrafast.evaluator import evaluate          # noqa: E402
from jev_ultrafast.logger import Logger               # noqa: E402


def _load_tasks(path: Path) -> list[dict]:
    tasks = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from None
    return tasks


def _resolve_start_url(spec: dict, override: str | None) -> str:
    if override:
        return override
    domain = spec["domain"]
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def _reset_cdp() -> None:
    """每个 task 间重置 CDP：杀 Chrome + 重启干净实例 + 预热 daemon。

    治 f004 类 `no close frame received or sent`（浏览器会话累积后 WS 断帧）。
    跨平台安全：非 Windows / 找不到 Chrome 时静默跳过（daemon 自修兜底）。
    """
    import subprocess
    import platform
    from browser_harness.admin import ensure_daemon
    system = platform.system()
    if system != "Windows":
        return
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    profile = r"C:\Users\Administrator\chrome-jev-profile"
    try:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                       capture_output=True, timeout=15)
        time.sleep(2)
        subprocess.Popen([chrome, f"--remote-debugging-port=9222",
                          f"--user-data-dir={profile}",
                          "--no-first-run", "--no-default-browser-check",
                          "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)
        ensure_daemon()
    except Exception as e:
        print(f"    [cdp-reset] warn: {type(e).__name__}: {e}")

def _run_one(spec: dict, log_dir: Path, start_url: str, screenshot: bool) -> dict:
    """运行单个 task。返回 {task_id, result, error?}。

    import 延后到函数内：fork 完成前 import Agent 会 fail，不应阻塞 --dry-run。
    """
    from jev_ultrafast.agent import Agent  # noqa: WPS433

    task_id = spec["task_id"]
    logger = Logger(task_id=task_id, log_dir=log_dir)
    started = time.perf_counter()

    try:
        agent = Agent(url=start_url, goals=spec["goal"], task_spec=spec,
                      screenshots=screenshot)
    except Exception as e:
        logger.close()
        return {
            "task_id": task_id,
            "result": "ERROR",
            "error": f"agent_init_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    try:
        for _ in agent.run():
            logger.observe(agent.state, step_budget=agent.step_budget)
    except Exception as e:
        # Agent loop 抛出未捕获异常：仍尝试评估 + finalize
        tb = traceback.format_exc()
    else:
        tb = None

    # 循环结束后抽取剩余事件 + 评估
    try:
        logger.observe(agent.state, step_budget=agent.step_budget)
    except Exception:
        pass

    status = agent.state.get("status", "error")
    meta = {
        "steps":       len(agent.state.get("history", [])),
        "model_calls": len(agent.state.get("decisions", [])),
        "api_calls":   0,  # M1 fixed_high 恒 0
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

    out = {"task_id": task_id}
    if tb is not None:
        out["error"] = "agent_loop_raised"
        out["traceback"] = tb
    if eval_error is not None:
        out["error"] = out.get("error") or "evaluate_raised"
        out["eval_error"] = eval_error
    if task_result is not None:
        out["result"] = task_result.to_dict()
    return out


def _summarize(results: list[dict]) -> dict:
    summary = {
        "total":     len(results),
        "pass":      0,
        "fail":      0,
        "unknown":   0,
        "error":     0,
        "quadrants": {},
        "failure_modes": {},
        "agent_modes": {},
        "system_modes": {},
    }
    for r in results:
        raw = r.get("result")
        if not isinstance(raw, dict):
            # init 失败（result="ERROR" 字符串）或 runner 异常（无 result）都计入 error
            summary["error"] += 1
            continue
        tr = raw
        res = tr.get("result")
        if res == "PASS":     summary["pass"] += 1
        elif res == "FAIL":   summary["fail"] += 1
        elif res == "UNKNOWN":summary["unknown"] += 1
        q = tr.get("quadrant")
        if q:
            summary["quadrants"][q] = summary["quadrants"].get(q, 0) + 1
        fc = tr.get("failure_class")
        fm = tr.get("failure_mode")
        if fm:
            bucket = summary["agent_modes"] if fc == "agent" else summary["system_modes"]
            bucket[fm] = bucket.get(fm, 0) + 1
            summary["failure_modes"][fm] = summary["failure_modes"].get(fm, 0) + 1
    return summary


def _check_m1_acceptance(summary: dict, results: list[dict]) -> tuple[bool, list[str]]:
    """M1 五条验收。见 docs/09-task-success.md §九。"""
    notes = []
    ok = True

    # 1. 20 task 全有 TaskResult
    missing = [r["task_id"] for r in results if not isinstance(r.get("result"), dict)]
    if missing:
        ok = False
        notes.append(f"FAIL: {len(missing)} tasks missing TaskResult: {missing}")

    # 2. 每个 FAIL 有唯一 failure_mode
    for r in results:
        tr = r.get("result")
        if not isinstance(tr, dict):
            continue
        if tr.get("result") == "FAIL" and not tr.get("failure_mode"):
            ok = False
            notes.append(f"FAIL: {r['task_id']} FAIL without failure_mode")
            break

    # 3. False Positive = 0
    fp = summary["quadrants"].get("false_positive", 0)
    if fp != 0:
        ok = False
        notes.append(f"FAIL: false_positive = {fp} (must be 0)")

    # 4. api_unavailable / crash = 0
    sys_modes = summary["system_modes"]
    bad_sys = {k: v for k, v in sys_modes.items()
               if k in ("api_unavailable", "crash")}
    if bad_sys:
        ok = False
        notes.append(f"FAIL: system failure_modes present: {bad_sys}")

    # 5. 四象限有记录（不要求非零，只要求字段存在）
    #     实际判定：所有非 UNKNOWN/ERROR 的结果必须有 quadrant
    for r in results:
        tr = r.get("result")
        if not isinstance(tr, dict):
            continue
        res = tr.get("result")
        if res in ("PASS", "FAIL") and not tr.get("quadrant"):
            ok = False
            notes.append(f"FAIL: {r['task_id']} {res} without quadrant")
            break

    return ok, notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("m1/tasks.jsonl"))
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument("--report", type=Path, default=Path("reports/m1.json"))
    parser.add_argument("--start-url", default=None,
                        help="override start URL for all tasks (debug)")
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="只加载 + 校验 tasks，不启动 browser")
    parser.add_argument("--task-delay", type=float, default=3.0,
                        help="seconds to wait between tasks (rate-limit friendly)")
    args = parser.parse_args()

    tasks = _load_tasks(args.tasks)
    if not tasks:
        print("No tasks found.", file=sys.stderr)
        return 2

    print(f"Loaded {len(tasks)} tasks from {args.tasks}")

    if args.dry_run:
        # 只做 schema 级 sanity check
        from jev_ultrafast.evaluator import TERMINAL_STATUSES  # noqa: F401
        for spec in tasks:
            for key in ("task_id", "domain", "category", "goal", "budget", "success_assertion"):
                if key not in spec:
                    print(f"FAIL: {spec.get('task_id','?')} missing {key}", file=sys.stderr)
                    return 2
        print("DRY RUN OK")
        return 0

    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for i, spec in enumerate(tasks, 1):
        tid = spec["task_id"]
        start_url = _resolve_start_url(spec, args.start_url)
        print(f"[{i}/{len(tasks)}] {tid}  {start_url}")
        if i > 1:
            _reset_cdp()
        try:
            r = _run_one(spec, args.log_dir, start_url, args.screenshots)
        except Exception as e:
            r = {"task_id": tid, "error": f"runner_exception: {e}",
                 "traceback": traceback.format_exc()}
        raw = r.get("result")
        res = raw.get("result") if isinstance(raw, dict) else raw
        print(f"    → {r.get('error') or res}")
        results.append(r)
        if i < len(tasks):
            time.sleep(args.task_delay)

    summary = _summarize(results)
    ok, notes = _check_m1_acceptance(summary, results)

    report = {
        "summary":    summary,
        "acceptance": {"passed": ok, "notes": notes},
        "results":    results,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print()
    print(f"PASS={summary['pass']}  FAIL={summary['fail']}  "
          f"UNKNOWN={summary['unknown']}  ERROR={summary['error']}")
    print(f"quadrants: {summary['quadrants']}")
    print(f"failure_modes: {summary['failure_modes']}")
    print(f"M1 acceptance: {'PASS' if ok else 'FAIL'}")
    for n in notes:
        print(f"  {n}")
    print(f"report → {args.report}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
