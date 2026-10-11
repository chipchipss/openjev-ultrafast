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
4. 复位**重起的那次 Chrome 必须和 runner/freeze 起的是同一个形状**（headless + `chrome-cdp-test`
   + `--proxy-server`）。少这一条，一批里就会出现"第 1 题走代理、其余直连"，站点反爬跟着出口 IP
   变，而且 headed/headless 的渲染与动作时序也不同——那是网络和浏览器的差异，不是 agent 的差异。

判据不在这个文件里：门控省下多少墙钟、有没有新死法，由 50 行的批读数判（`m2/batch_audit.py`
配对 b26），不在单元测试里判——单元测试只管"政策长这样、而且改回去会红"。

运行：python tests/test_runner_reset_policy.py
"""
from __future__ import annotations

import os
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


@case("复位重起的 Chrome 必须和 runner/freeze 起的是**同一个形状**（headless + chrome-cdp-test + 代理）")
def t_relaunch_matches_the_runner_browser():
    """**行为检查，不查源码文本**——注释里写着 `--proxy-server` 也能骗过文本检查。

    现役代码走假仪器（`subprocess.run`/`Popen`/`time.sleep`/`_ensure_daemon` 全换成假的，
    只取真正递给 Chrome 的 argv）。HEAD 那一侧只做括号配平的文本提取，**不执行旧函数**：
    执行它会真的把画像里的 Chrome 杀一遍。

    2026-10-11 晚发现：`_reset_cdp` 重起的 Chrome 既没带代理，也不是 runner 起的那个
    headless `chrome-cdp-test`，而是 headed `chrome-jev-profile`。于是"门控真付过一次复位"
    的批里，第 1 题走代理 + headless，后面的题直连 + headed——出口 IP 和浏览器一起换，
    站点反爬跟着变，而这一切与 agent 的决策无关。b27/b28/b29 恰好 0 次复位所以自洽，
    b18–b26 是混合的。
    """
    argv = _capture_reset_launch(RT)
    joined = " ".join(argv)
    assert "--proxy-server=" in joined, \
        "复位起的 Chrome 没有代理参数：批内会出现'第一题走代理、其余直连'的两条出口"
    assert "--headless=new" in joined, \
        "复位起的 Chrome 不是 headless：runner 起的是 headless，复位却换成 headed 画像"
    assert "chrome-cdp-test" in joined, \
        "复位重起的画像必须就是 runner/freeze 用的那个（chrome-cdp-test）"
    assert "--remote-debugging-port=9222" in joined, "端口没钉在 :9222，守护进程会找不到它"

    # 对照：改前的 `_reset_cdp` 传给 Chrome 的那串参数里，这三样都必须没有
    old = _head_reset_cdp_flags()
    if old is None:
        print("      skip: HEAD 已带新形状（提交已落）——对照对象消失")
    else:
        miss = [flag for flag in ("--proxy-server=", "--headless=new", "chrome-cdp-test")
                if flag not in old]
        assert len(miss) == 3, "改前的复位竟然已经是新形状：这台仪器分辨不出改动 (%s)" % miss

    runner = (REPO / "scripts" / "run_one.ps1").read_text(encoding="utf-8")
    assert "--proxy-server=" in runner and "--headless=new" in runner, \
        "runner 那边的形状也变了——这条测试钉的是**两边一致**，不是两边各自硬编码"


def _capture_reset_launch(module, proxy_env="http://127.0.0.1:2080"):
    """真的走一遍 `_reset_cdp()`，但把 run/Popen/sleep/daemon 全部换成假的，只取 argv。"""
    import subprocess as sp
    import time as _time
    import types
    import jev_ultrafast.browser as BR
    captured = {}
    saved = (sp.run, sp.Popen, _time.sleep, BR._ensure_daemon)
    saved_proxy = os.environ.get("JEV_PROXY_URL")

    def fake_run(*a, **k):
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def fake_popen(argv, *a, **k):
        captured["argv"] = list(argv)
        return types.SimpleNamespace(poll=lambda: None)

    sp.run, sp.Popen, _time.sleep = fake_run, fake_popen, lambda s: None
    BR._ensure_daemon = lambda *a, **k: None
    os.environ["JEV_PROXY_URL"] = proxy_env
    try:
        module._reset_cdp()
    finally:
        sp.run, sp.Popen, _time.sleep, BR._ensure_daemon = saved
        if saved_proxy is None:
            os.environ.pop("JEV_PROXY_URL", None)
        else:
            os.environ["JEV_PROXY_URL"] = saved_proxy
    return captured.get("argv") or []


def _head_reset_cdp_flags():
    """从 HEAD 的源码里取出旧 `_reset_cdp` 真正传给 Chrome 的那串 argv（**不执行它**）。

    旧代码若执行会真的去杀一遍画像，所以这里只做括号配平的文本提取。对照的意义：
    改前那串里没有代理、没有 headless、画像是 `chrome-jev-profile`。
    """
    import subprocess as sp
    out = sp.run(["git", "show", "HEAD:m1/run_tasks.py"], cwd=str(REPO), capture_output=True)
    if out.returncode != 0:
        raise AssertionError("git show 失败，无从对照")
    src = out.stdout.decode("utf-8", "replace")
    if "def _reset_cdp" not in src:
        return None
    body = src[src.index("def _reset_cdp"):]
    body = body[:body.index("\ndef ")]
    marker = "subprocess.Popen("
    if marker not in body:
        return None
    i = body.index(marker) + len(marker)
    depth, j = 1, i
    while j < len(body) and depth:
        if body[j] == "(":
            depth += 1
        elif body[j] == ")":
            depth -= 1
        j += 1
    chunk = body[i:j] + body[body.index("profile ="):body.index("profile =") + 80]
    if "--proxy-server=" in chunk and "--headless=new" in chunk:
        return None                                    # 对照对象已消失（提交已落）
    return chunk


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
