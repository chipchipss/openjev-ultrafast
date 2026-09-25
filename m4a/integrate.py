"""M1 本地推理集成 runner。

把 openjev 根层模块 + 基座(laya) 三件套(browser/model/questions/snapshot.js)
拼成包命名空间 `jev`；把 model.choose/field_text 替换为 decider/*_2b
（走本地 3B LoRA server @ :8000）。复用 m1/run_tasks.py 的
_load_tasks/_summarize/_check_m1_acceptance + evaluator.evaluate + Logger。

必须用 jev env 的 python 跑（browser_harness 装在 jev env）。
"""
from __future__ import annotations

import importlib.util as iu
import json
import os
import sys
import time
import traceback
import types
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\openjev-ultrafast")
BASE = Path(r"C:\Users\Administrator\AppData\Local\Temp\laya-ultrafast\laya_ultrafast")
PKG = "jev"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# 让 browser-harness daemon 优先用系统 Chrome
os.environ.setdefault("BH_CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# --- 组包：pkg 有两个 __path__（openjev 根 + 基座）---
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT), str(BASE)]
sys.modules[PKG] = pkg


def load(name: str, src: Path):
    spec = iu.spec_from_file_location(f"{PKG}.{name}", src)
    mod = iu.module_from_spec(spec)
    sys.modules[f"{PKG}.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


load("browser", BASE / "browser.py")
load("questions", BASE / "questions.py")
model_mod = load("model", BASE / "model.py")

for n in ("decision_validator", "policy", "confidence_gate", "step_budget",
          "logger", "evaluator", "runtime_guard"):
    load(n, ROOT / f"{n}.py")

# decider 包
dec = load("decider", ROOT / "decider" / "__init__.py")
dec.__path__ = [str(ROOT / "decider")]
choose_2b = load("decider.choose_2b", ROOT / "decider" / "choose_2b.py")
ft_2b = load("decider.field_text_2b", ROOT / "decider" / "field_text_2b.py")

# H2 规定的替换点
model_mod.choose = choose_2b.choose
model_mod.field_text = ft_2b.field_text

load("agent", ROOT / "agent.py")

# 复用 m1.run_tasks 的装载/汇总（exec 顶层安全：有 __main__ 守卫）
spec = iu.spec_from_file_location("m1run", ROOT / "m1" / "run_tasks.py")
m1 = iu.module_from_spec(spec)
sys.modules["m1run"] = m1
spec.loader.exec_module(m1)


def run_one(spec_task: dict, log_dir: Path, start_url: str, screenshot: bool) -> dict:
    agent_mod = sys.modules[f"{PKG}.agent"]
    evaluator_mod = sys.modules[f"{PKG}.evaluator"]
    logger_mod = sys.modules[f"{PKG}.logger"]

    task_id = spec_task["task_id"]
    logger = logger_mod.Logger(task_id=task_id, log_dir=log_dir)
    started = time.perf_counter()

    try:
        ag = agent_mod.Agent(url=start_url, goals=spec_task["goal"],
                             task_spec=spec_task, screenshots=screenshot)
    except Exception as e:
        logger.close()
        return {"task_id": task_id, "result": "ERROR",
                "error": f"agent_init_failed: {type(e).__name__}: {e}",
                "traceback": traceback.format_exc()}

    tb = None
    try:
        for _ in ag.run():
            logger.observe(ag.state, step_budget=ag.step_budget)
    except Exception as e:
        tb = traceback.format_exc()
    else:
        tb = None
    try:
        logger.observe(ag.state, step_budget=ag.step_budget)
    except Exception:
        pass

    status = ag.state.get("status", "error")
    meta = {
        "steps": len(ag.state.get("history", [])),
        "model_calls": len(ag.state.get("decisions", [])),
        "api_calls": 0,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }

    task_result = None
    eval_error = None
    try:
        task_result = evaluator_mod.evaluate(
            spec_task,
            ag.state.get("page"),
            ag.state.get("history", []),
            status if status in {"done", "blocked", "budget_exceeded", "error"} else "error",
            meta=meta,
        )
    except Exception as e:
        eval_error = f"{type(e).__name__}: {e}"

    try:
        if task_result is not None:
            logger.finalize(task_result, step_budget=ag.step_budget,
                            final_page=ag.state.get("page"))
    finally:
        ag.close()
        logger.close()

    out = {"task_id": task_id}
    if tb:
        out["error"] = "agent_loop_raised"
        out["traceback"] = tb
    if eval_error:
        out["error"] = out.get("error") or "evaluate_raised"
        out["eval_error"] = eval_error
    if task_result is not None:
        out["result"] = task_result.to_dict()
    return out


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=ROOT / "m1" / "tasks.jsonl")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs" / "m1-local")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "m1-local.json")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个 task（0=全部）")
    parser.add_argument("--task-delay", type=float, default=3.0)
    parser.add_argument("--screenshots", action="store_true")
    args = parser.parse_args()

    tasks = m1._load_tasks(args.tasks)
    if not tasks:
        print("No tasks found.", file=sys.stderr)
        return 2
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"Loaded {len(tasks)} tasks (base={BASE.name}, decider→local 3B @ :8000)")

    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for i, spec in enumerate(tasks, 1):
        tid = spec["task_id"]
        start_url = m1._resolve_start_url(spec, None)
        print(f"[{i}/{len(tasks)}] {tid}  {start_url}")
        r = run_one(spec, args.log_dir, start_url, args.screenshots)
        res = r.get("result") if isinstance(r.get("result"), dict) else r.get("result")
        print(f"    → {r.get('error') or res}")
        results.append(r)
        if args.task_delay and i < len(tasks):
            time.sleep(args.task_delay)

    summary = m1._summarize(results)
    ok, notes = m1._check_m1_acceptance(summary, results)
    report = {"summary": summary,
              "acceptance": {"passed": ok, "notes": notes},
              "results": results}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    print(f"\nPASS={summary['pass']}  FAIL={summary['fail']}  "
          f"UNKNOWN={summary['unknown']}  ERROR={summary['error']}")
    print(f"quadrants: {summary['quadrants']}")
    print(f"failure_modes: {summary['failure_modes']}")
    print(f"system_modes: {summary['system_modes']}")
    print(f"M1 acceptance: {'PASS' if ok else 'FAIL'}")
    for n in notes:
        print(f"  {n}")
    print(f"report → {args.report}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
