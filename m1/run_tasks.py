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
import os
import sys
import time
import traceback
from pathlib import Path

# 允许从仓库根运行
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_ultrafast.evaluator import evaluate          # noqa: E402
from jev_ultrafast.logger import Logger, page_digest  # noqa: E402


def _load_tasks(path: Path) -> list[dict]:
    tasks = []
    # utf-8-sig：PowerShell 5.1 的 `Set-Content -Encoding UTF8` 必写 BOM，而
    # run_one.ps1 -TaskId 就是用它落单任务文件的（BOM 让第一行 json.loads 直接崩）。
    # 无 BOM 的文件这个编码读起来完全一样。
    with path.open(encoding="utf-8-sig") as f:
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

    只许杀我们自己画像起的 Chrome。这里原来是 `taskkill /F /IM chrome.exe`——
    它按镜像名无差别收割，每个任务之间都会把用户自己的浏览器一起杀掉（脚本侧
    的 chrome-cdp-test 守卫全被这条 Python 绕过，2026-10-07 实测：起一个
    chrome-decoy-sim 画像的 Chrome，跑两个任务后它就被 taskkill 收走了）。
    子进程（renderer/gpu）的命令行里同样带 --user-data-dir，所以画像匹配能连
    孩子一起清掉，不会留孤儿子进程。
    """
    import subprocess
    import platform
    from jev_ultrafast.browser import _ensure_daemon
    system = platform.system()
    if system != "Windows":
        return
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    # 复位后重起的那个 Chrome **必须和 runner/freeze 起来的是同一个形状**：
    # `scripts/run_one.ps1:57` 与 `scripts/start_owned_chrome.ps1:9` 起的是
    # headless + `C:\chrome-cdp-test` + `--proxy-server=http://127.0.0.1:2080`。
    # 原来这里写的是 headed `chrome-jev-profile` 且**没有代理**（2026-10-11 晚发现）：
    # 于是"门控真付过一次复位"的批里，第 1 题跑 headless 走代理、后面的题跑 headed 直连——
    # 浏览器和出口 IP 一起换，站点反爬跟着变，而这一切与 agent 的决策无关。
    # L3-A 的 b27/b28/b29 恰好 0 次复位，所以那个批是自洽的；b18–b26 是混合的，读它
    # 们的分数时要记着这条（`m2/real-log.md` 已登记）。
    profile = r"C:\chrome-cdp-test"
    # 我们拥有的画像：这里起的 + PS runner 起的（谁起的都由这里收口）
    _kill_ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*chrome-jev-profile*' "
        "-or $_.CommandLine -like '*chrome-cdp-test*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", _kill_ps],
                       capture_output=True, timeout=30)
        time.sleep(2)
        proxy = os.environ.get("JEV_PROXY_URL", "http://127.0.0.1:2080")
        argv = [chrome, "--headless=new", "--remote-debugging-port=9222",
                f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check"]
        if proxy:
            argv.append(f"--proxy-server={proxy}")
        argv.append("about:blank")
        subprocess.Popen(argv,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)
        _ensure_daemon()
    except Exception as e:
        print(f"    [cdp-reset] warn: {type(e).__name__}: {e}")

#: 任务间"要不要先问一句健康"的成本读数（2026-10-11 06:4x 在自有 Chrome 上连测三次：
#: 2.77 / 2.83 / 3.05 秒；`_reset_cdp()` 一次 23.6 秒 = 0.4 杀 + 7.0 盲等 + 16.2 daemon 起，
#: 见 `m2/real-log.md` 的 #34 分解）。49 个断点上"每次都问"最多付 49×2.9≈2.4 分钟，
#: 而"每次都复位"要付 49×23.6≈19.3 分钟。

def _cdp_healthy() -> bool:
    """问一句"这个自有浏览器还能干净地开一次会话并读到**归静**的文档吗"。

    顺序不能换：**先验归属**（`_assert_owned_browser`），再去碰浏览器——探测路径也是连接
    路径，反过来就可能在问健康的路上连到用户的 Chrome（P0 硬线）。

    为什么要在 about:blank 上真的建一次会话、而不是探端口/探进程：b21 那次门控被否决，
    三行死的是 `agent_init_failed: StalePage: Document is navigating`（`m2/real-log.md` 的
    b21 表），"端口有人、归属对"全都通过，坏的是**会话起来读不到一份归静的文档**。
    这里问的就是那件真正会被下一题依赖的事。`Browser.__init__` 的 settle 段
    （floor 1200ms / quiet 250ms / cap 5000ms）本来就是"归静"的判据，复用而不是另造。

    它**不保证**下一题的起点站会顺利加载——那由 `#57`（起点观测有界退避 + 整个起点重做
    一次，`Agent._observe_start`）负责。两件事各管一段：这段管"浏览器本身还能不能用"，
    那段管"某一题的起点加载慢"。
    """
    import platform
    if platform.system() != "Windows":
        return False          # 这台机器上 _reset_cdp 在别的平台是静默跳过，无从对照
    try:
        from jev_ultrafast.browser import (Browser, MARKER_STABLE,
                                          _assert_owned_browser)
        _assert_owned_browser()
        b = Browser("about:blank")
        try:
            marker = b.evaluate(MARKER_STABLE)
            return bool(marker)
        finally:
            b.close()
    except Exception:                                    # noqa: BLE001
        return False


#: 上一行的哪些结局说明"浏览器可能被带坏了"（这些之后无条件复位，哪怕探测说健康）。
#: 名字只收见过的形状：`no-browser:`/`foreign-browser:` 是 `::_assert_owned_browser` 的两个
#: 前缀；`agent_init_failed` 是 #54 的构造失败；`agent_init_failed_after_cdp_reset` 是它
#: 复位一次之后仍失败；`_ipcresponsetimeout` 是 #58 那族（IPC 超时崩行）；
#: `document is navigating` 是 b21 三行的原文；`crash`/`unknown` 是评测侧的系统类象限。
_BROWSER_CLASS_MARKS = (
    "no-browser:", "foreign-browser:", "agent_init_failed",
    "_ipcresponsetimeout", "document is navigating",
    "no close frame received or sent",
)


def _is_browser_class(prev: dict) -> bool:
    if not isinstance(prev, dict):
        return True                                   # 连行结果都没有 = 不可知，按坏处理
    if prev.get("error"):
        text = str(prev.get("error")) + str(prev.get("exception") or "")
        if any(m in text.lower() for m in _BROWSER_CLASS_MARKS):
            return True
        return True                                   # 任何 runner 级 error 都不许带着复用往下走
    raw = prev.get("result")
    res = raw.get("result") if isinstance(raw, dict) else raw
    quad = str(raw.get("quadrant")) if isinstance(raw, dict) else ""
    return res in ("ERROR", "CRASH", None) or quad in ("system_crash", "unknown")


def _needs_reset(prev, healthy: bool) -> bool:
    """任务间决策（纯函数，便于把表钉死在测试里）：
    第一题之前没有边界 → 不复位；上一行是浏览器类结局 → 必复位；否则不健康才复位。"""
    if prev is None:
        return False
    if _is_browser_class(prev):
        return True
    return not healthy


#: 上面那个概念的**一张**表（#72）。曾经这里是两张：`_BROWSER_LOSS` 只有
#: `("no-browser:", "foreign-browser:")`，于是 b34 的 r139（`agent_init_failed: StalePage:
#: Document is navigating`，b21 的原句）被门控认成坏行、却不被自愈认成浏览器类——
#: 复位+重试一次的路径从不触发，整行白丢且没有 trace（`[browser-lost]` 在批日志里 0 次）。
#: 口径仍然**不是**"任何异常都重试"：那会把真 bug 洗成一次画像重起（`tests/test_runner_browser_recovery.py`
#: 的 ③ 用 ValueError 钉着这条边界）。
_BROWSER_LOSS = _BROWSER_CLASS_MARKS


def _is_browser_loss(exc: BaseException) -> bool:
    # 小写比对：标记里有 `document is navigating`，而原文是 `StalePage: Document is navigating`。
    text = str(exc).lower()
    return any(p in text for p in _BROWSER_LOSS)


def _run_one(spec: dict, log_dir: Path, start_url: str, screenshot: bool) -> dict:
    """运行单个 task。返回 {task_id, result, error?}。

    import 延后到函数内：fork 完成前 import Agent 会 fail，不应阻塞 --dry-run。
    """
    from jev_ultrafast.agent import Agent  # noqa: WPS433
    from jev_ultrafast.api_teacher import APITeacher  # noqa: WPS433
    from jev_ultrafast.api_budget import APIBudget  # noqa: WPS433
    from jev_ultrafast import skills as _skills  # noqa: WPS433

    task_id = spec["task_id"]
    logger = Logger(task_id=task_id, log_dir=log_dir)
    started = time.perf_counter()
    # #83 的前置仪器：`skills._STUCK` 是模块级、按页态指纹键、跨任务不清，
    # 而夜间档 r3 实测 111 个指纹里 25 个被 >1 题共用 ⇒ 上一题的"让位"笔记可以按住下一题前两拍。
    # **每题开始前**的 entries 就是这道跨题通道的直接读数（>0 = 带着上一题的笔记进场）。
    # 上一批（`reports/tier3-100-1014-105704.json`）把两件事混成一个数了：进场 61/100 行，
    # 但真正被按住只有 1 行，而且那 1 次是本题自己写的笔记 ⇒ "进场"不等于"受害"。
    # 所以这里报出任务归属，`cross_task` 那一格才是 #83 的决策量。
    _stuck_before = _skills.stuck_counters()
    _skills.set_current_task(task_id)

    # M1.5 teacher shadow（A 档）：TEACHER_SHADOW=1 时接线。触发策略——
    # stall-gated：仅 stale_retry_run>=2（reject 循环已开始烧决策）时 shadow，
    # 而非每决策都调。样本天然落在 2B 失败点（M4b P0 价值密度最高），调用省 90%+。
    api_teacher = api_budget = None
    if os.environ.get("TEACHER_SHADOW") == "1":
        try:
            api_budget = APIBudget(
                teacher_limit=int(os.environ.get("TEACHER_LIMIT", "8")),
                recovery_limit=0,
            )
            api_teacher = APITeacher(api_budget)
        except Exception as e:
            print(f"[teacher] init failed, shadow disabled: {e}")
            api_teacher = api_budget = None

    agent_kwargs = {}
    if api_teacher is not None:
        agent_kwargs["api_teacher"] = api_teacher
        agent_kwargs["api_budget"] = api_budget

    try:
        agent = Agent(url=start_url, goals=spec["goal"], task_spec=spec,
                      screenshots=screenshot, **agent_kwargs)
    except Exception as e:
        # 自有浏览器在批中途消失（b19 的 r120 那一拍）：重起我们自己的画像，重试这一行**一次**。
        # 只许一次——重起会清空画像，真·站点不可达时反复重起只会把一批烧成慢速死循环。
        # logger 不在这里关：b19 的"整行没有 trace"就是 close() 掉了一个空日志文件，
        # 事后无从判断那一拍到底看见了什么。
        if not _is_browser_loss(e):
            logger.close()
            return {
                "task_id": task_id,
                "result": "ERROR",
                "error": f"agent_init_failed: {type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            }
        print(f"    [browser-lost] {task_id}: {str(e)[:90]} -- reset owned CDP, retry once")
        _reset_cdp()
        try:
            agent = Agent(url=start_url, goals=spec["goal"], task_spec=spec,
                          screenshots=screenshot, **agent_kwargs)
        except Exception as e2:
            logger.close()
            return {
                "task_id": task_id,
                "result": "ERROR",
                "error": f"agent_init_failed_after_cdp_reset: {type(e2).__name__}: {e2}",
                "traceback": traceback.format_exc(),
            }

    try:
        for _ in agent.run():
            logger.observe(agent.state, step_budget=agent.step_budget)
    except Exception as e:
        # Agent loop 抛出未捕获异常：仍尝试评估 + finalize
        print("AGENT_EXCEPTION")
        traceback.print_exc()
        tb = traceback.format_exc()
        exc_repr = repr(e)
    else:
        tb = None
        exc_repr = None

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
    # #65 的代价要能对到 reports/*.json（仓库里的权威工件；logs/ 故意不入库）。
    # 没付就不写这个键，与 logger 的 task_result 事件同一口径。
    _paid = agent.state.get("arrival_relook_ms")
    if _paid:
        meta["arrival_relook_ms"] = int(_paid)
    # #83 前置仪器的读数：这一题**进场时**带着几条上一题的抑制笔记、这一题里又写了几条、
    # 被按住几次。只写非零，避免每行都塞空结构（与 arrival_relook_ms 同一口径）。
    # 上一批把两件事混成一个数了（进场 61/100 行，真正被按住只有 1 行，而那 1 次是本题自己写的笔记），
    # 所以 `cross_task` 才是 #83 的决策量：笔记**不是本题写的**抑制发生了几次。
    _stuck_after = _skills.stuck_counters()
    _stuck_cross = _stuck_after["cross_task"] - _stuck_before["cross_task"]
    if (_stuck_before["entries"] or _stuck_after["notes"] != _stuck_before["notes"]
            or _stuck_after["suppressed"] != _stuck_before["suppressed"] or _stuck_cross):
        meta["stuck"] = {
            "entries_at_start": _stuck_before["entries"],
            "notes": _stuck_after["notes"] - _stuck_before["notes"],
            "suppressed": _stuck_after["suppressed"] - _stuck_before["suppressed"],
            "cross_task": _stuck_cross,
        }

    # #75 的后半：断言吃的那份正文的摘要要跟着进 **reports/*.json**（`logs/` 不入库）。
    # 一份算法：`logger.page_digest`，与 task_result 事件里那个字段同源，不另抄。
    _fp = page_digest(agent.state.get("page"))
    if _fp.get("text_sha16"):
        meta["final_page"] = _fp

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
                            final_page=agent.state.get("page"),
                            state_paid_ms=agent.state.get("arrival_relook_ms"))
    finally:
        agent.close()
        logger.close()

    out = {"task_id": task_id}
    if tb is not None:
        out["error"] = "agent_loop_raised"
        out["traceback"] = tb
        out["exception"] = exc_repr
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
        if r.get("error"):
            # 循环抛异常/评估抛异常的行**照样**会被评估出一个 result（b10 的 r107：
            # error=agent_loop_raised 与 result=FAIL 并存）。只数"没有 TaskResult 的行"
            # 会让 summary.error=0 成为假话——error=0 必须意味着"这一批没有任何崩溃"。
            summary["error"] += 1
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
        # negative 任务正确拒绝（true_success + FAIL）无 failure_mode 是设计
        # 行为——"拒绝"不是 agent 失败。仅 positive FAIL 强制 failure_mode。
        if (tr.get("result") == "FAIL" and not tr.get("failure_mode")
                and tr.get("quadrant") != "true_success"):
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


def _egress_block_reason(sample_url: str):
    """批开跑前，用**批将来走的那条路**（自有 Chrome + 它自己的 `--proxy-server`）试一跳。

    b30 现场：`:2080` 代理死了而 Chrome 带 `--proxy-server=…:2080` → 100 行里 94 行
    `steps=0`、终点 `chrome-error://chromewebdata/`，最后写出一份"6/100"的报告——那是
    环境阻断，不是能力读数，却会进 reports/ 被引用。

    为什么第二版才改成走浏览器：第一版我用 `urllib` 探，**b31 现场证明它测的是另一条路**——
    `scripts/run_one.ps1` 不把代理写进环境变量，于是探针直连成功、闸门放行，而 Chrome 仍然
    走死代理（跑到第 69 行被我停掉，幸好报告是在循环结束后才写的）。判据和批不同路，闸门就是摆设。
    """
    if not (sample_url or "").startswith("http"):
        return None                                   # 没有可试的起点（本地调试）→ 不拦
    try:
        from jev_ultrafast.browser import Browser
        b = Browser(sample_url)
        try:
            url = str(b.evaluate("location.href") or "")
        finally:
            b.close()
    except Exception as e:                                # noqa: BLE001
        return f"起点页连不上（{type(e).__name__}: {str(e)[:70]}）"
    if url.startswith("chrome-error://"):
        return f"起点页落在 {url[:60]}（出口/代理不通）"
    return None


def _egress_sample_url(tasks: list[dict], start_url_override):
    """出口取样要挑一道**应当可达**的题，不能直接用第一题。

    x001 的 domain 是 `example.invalid`——它是**故意**不可达的负向题（题点是 agent 要 BLOCK）。
    2026-10-11 22:41 的冻结第 1 轮里，闸门拿第一题当样本，把 x001 读成了『出口/代理不通』，
    于是那一行不跑、不写报告，19 题只拿到 18/18。全负向的题集没有可取样，就跳过闸门照常跑批：
    闸门是防"整批被环境打掉"的，不是防"题面本身设计成打不开"的。
    """
    if start_url_override:
        return start_url_override
    for spec in tasks:
        if (spec.get("category") or "").lower() == "negative":
            continue
        return _resolve_start_url(spec, None)
    return None


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

    # 出口预检（见 `_egress_block_reason`）：不通就一行的读数都不要产。
    # 样本由 `_egress_sample_url` 挑——负向题的起点是故意不可达的，拿它取样会把能跑的批读成环境阻断。
    if not args.dry_run:
        sample = _egress_sample_url(tasks, args.start_url)
        if sample:
            why = _egress_block_reason(sample)
            if why:
                print(f"[preflight] 样本 {sample[:60]}：{why} —— 不跑批、不写报告。"
                      "这是环境阻断，写成读数会被后续引用。", file=sys.stderr)
                return 3
        else:
            print("[preflight] 题集里没有可达性可取样（全负向题），跳过出口预检")

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
        # 付一次复位要在日志里认得出来（#72⑥）：b34 复盘时分不清"没付"与"付了没打印"。
        if i > 1:
            if _needs_reset(results[-1], _cdp_healthy()):
                print(f"    [cdp-boundary] 上一行 {results[-1].get('task_id')} 的结局属浏览器类或探测不健康"
                      " —— 付一次完整复位（杀自有画像 + 重起 + daemon 预热）")
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
