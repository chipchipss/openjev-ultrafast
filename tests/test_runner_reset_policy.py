"""#56 的复位政策：任务之间**先问健康、再付复位**，但浏览器类结局必须强制复位。

这个文件以前是一条**否决记录**（当时写的是"任务之间必须无条件 `_reset_cdp()`"）。它否决的理由
留在原文里，一个字没删：

| 量 | b20（每任务重启） | b21（健康就跳过重启） |
|---|---|---|
| 批墙钟 | 27.8 min | **11.0 min**（2.5 倍） |
| `error` 行 | 0 | **3**（`r139` `r140` `r141`，全是 ERROR 且**没有 trace**） |
| 新 29 行 | 29/29 | **26/29** |
| 配对 | — | `GAIN=∅ LOST=[r139,r140,r141]`（这三行在 b20 是 PASS/1 步） |

三行死法同一句：`agent_init_failed: StalePage: Document is navigating`——**复用浏览器会把上一题的
在途导航带进下一题的起点观测**。那次否决写下的前置条件是：
"顺序必须是先修'任务起点的观测能穿过在途导航'，再谈跳过重启"。

前置已经落地并被独立验过两轮：`#57`（起点观测的有界退避 + 整个起点重做一次，
`Agent._observe_start` / `__init__`）过了冻结 19/19×3 与 b22/b23/b24 三批。所以这条现在
**按门控重写**，并且把当年那次没做的另一半也补上：

1. **健康问句不许只看端口**。它必须真的建一次会话、读到**归静**的文档（`MARKER_STABLE`
   非空）才算健康——"归属对 + 进程在"通过不了 r139 那种死法。
2. **上一行是浏览器类结局（error / 崩溃 / 没有 trace / `no-browser:` / `foreign-browser:` /
   IPC 超时 / 起点 StalePage）时，下一道边界无条件复位**，哪怕探测说健康。复用会带状态，
   所以带过状态的那一行之后不赌。
3. 复位本身没变，也只许杀我们自己的两个画像（P0 杀伤侧，`_reset_cdp` 的 kill filter）。

判据不在这个文件里：门控省下多少墙钟、有没有新死法，由 50 行的批读数判（`m2/batch_audit.py`
配对 b26），不在单元测试里判——单元测试只管"政策长这样、而且改回去会红"。

运行：python tests/test_runner_reset_policy.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import m1.run_tasks as RT          # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("门控存在，且批循环走的是它（当前代码是无条件复位——这条应当在改前失败）")
def t_boundary_is_health_gated():
    assert hasattr(RT, "_cdp_healthy"), "没有健康问句：任务间还是无条件付 23.6 秒"
    assert hasattr(RT, "_needs_reset"), "没有纯决策函数：门控没法单测，也没法证明'坏行必复位'"
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    m = re.search(r"if i > 1:\n\s+if _needs_reset\(", src)
    assert m, "批循环的任务间动作不是 `if _needs_reset(...)`（改回无条件复位本条会红）"


@case("健康问句先验归属，再去碰会话（不许在探测里连到别人的浏览器）")
def t_health_probe_checks_ownership_first():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def _cdp_healthy"):]
    body = body[:body.index("\ndef ")]
    i_guard = body.find("_assert_owned_browser")
    assert i_guard >= 0, "探测里没有归属守卫"
    i_use = min(x for x in (body.find("Browser("), body.find("MARKER_STABLE"), body.find("cdp(")) if x >= 0)
    assert i_guard < i_use, "归属守卫排在真正去碰浏览器之后"


@case("健康问句要读到**归静**的文档，不是读'端口有人'")
def t_health_probe_needs_a_settled_document():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def _cdp_healthy"):]
    body = body[:body.index("\ndef ")]
    assert "MARKER_STABLE" in body, "没读归静 marker——那正是 r139/r140/r141 漏过去的东西"
    assert "about:blank" in body, "没在新开的空白会话上问（在旧页上问等于问'上一页归静没'）"


@case("决策表：坏行之后必复位；健康就别复位；不健康就复位；第一题之前没有边界")
def t_needs_reset_decision_table():
    N = RT._needs_reset
    bad = {"task_id": "r139", "error": "agent_init_failed: StalePage: Document is navigating"}
    crashed = {"task_id": "r142", "result": {"result": "CRASH"}}
    no_trace = {"task_id": "r120", "result": {"result": "ERROR", "error": "no-browser: :9222"}}
    ipc = {"task_id": "r122", "error": "_IPCResponseTimeout: Runtime.evaluate timed out"}
    good = {"task_id": "r126", "result": {"result": "PASS", "quadrant": "true_success"}}
    abandon = {"task_id": "r101", "result": {"result": "FAIL",
                                             "quadrant": "correct_abandon",
                                             "failure_mode": "blocked_by_bot_wall"}}
    assert N(bad, healthy=True) is True, "b21 那种 error 行之后还允许复用 = 三行没 trace 的死法"
    assert N(crashed, healthy=True) is True, "崩溃行之后不许复用"
    assert N(no_trace, healthy=True) is True, "浏览器没了/不是我们的，之后必复位"
    assert N(ipc, healthy=True) is True, "IPC 超时（#58 那族）之后必复位"
    assert N(good, healthy=True) is False, "健康且上一行干净时还是要付 23.6 秒——门控就白做了"
    assert N(good, healthy=False) is True, "探测说不健康却没复位"
    assert N(abandon, healthy=True) is False, "correct_abandon 是**任务的正当结局**，不是浏览器坏了"
    assert N(None, healthy=False) is False, "第一题之前没有边界动作"


@case("复位那次仍只许杀我们自己的两个画像")
def t_reset_still_scoped_to_owned_profiles():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    reset = src[src.index("def _reset_cdp"):src.index("def _cdp_healthy")]
    assert "chrome-jev-profile" in reset and "chrome-cdp-test" in reset, \
        "_reset_cdp 的 kill filter 必须继续点名我们自己的两个画像"
    assert not re.search(r'subprocess\.(run|Popen)\(\s*\[?\s*"?taskkill', reset), \
        "裸 taskkill 回到了可执行代码里"
    assert "Get-Process chrome | Stop-Process" not in reset, "裸杀浏览器回到了可执行代码里"


@case("负例：改前的 m1/run_tasks.py 根本没有门控（本文件第 1 案因此在改前失败）")
def t_pre_fix_code_fails():
    """改动落进 HEAD 之后对照对象消失，按 Skip 处理（同 test_cdp_ownership 的规矩）。"""
    import subprocess
    out = subprocess.run(["git", "show", "HEAD:m1/run_tasks.py"],
                         cwd=str(REPO), capture_output=True)
    if out.returncode != 0:
        raise AssertionError("git show 失败，无从对照")
    old = out.stdout.decode("utf-8", "replace")
    if "_cdp_healthy" in old:
        print("      skip: HEAD 已带门控（提交已落）——对照对象消失")
        return
    assert "if i > 1:\n            _reset_cdp()" in old, \
        "改前的批循环不是无条件 `_reset_cdp()`，那第 1 案失败就不是归因到点上"


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
