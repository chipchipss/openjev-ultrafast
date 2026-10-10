"""#56 的否决记录：任务之间必须付那次完整重启，除非先修好"起点带在途导航"。

这不是"健康门控很好用"的测试——它曾经被写成那样，然后 b21 把它否决了。读数（`m2/batch_audit.py`
配对 `reports/real-1010-b21-fix56-1010-224045.json` vs `real-1010-b20-fix54-1010-213835.json`）：

| 量 | b20（每任务重启） | b21（健康就跳过重启） |
|---|---|---|
| 批墙钟 | 27.8 min | **11.0 min**（2.5 倍） |
| `error` 行 | 0 | **3**（`r139` `r140` `r141`，全是 ERROR 且**没有 trace**） |
| 新 29 行 | 29/29 | **26/29** |
| 配对 | — | `GAIN=∅ LOST=[r139,r140,r141]`（这三行在 b20 是 PASS/1 步） |

三行的死法是同一句：`agent_init_failed: StalePage: Document is navigating`
（`agent.py:149` 的第一次 `observe` 抛出，穿过 `_run_one` 的构造分支，整行作废）。
原来那次 23.6 s 的重启顺带把"上一题的在途导航"清掉了；跳过它，起点状态就露出来。
`_reset_cdp` 存在的理由（f004 的 `no close frame received or sent`）和这个新签名是**同一族**：
浏览器复用会带状态。所以顺序必须是先修"任务起点的观测要能穿过在途导航"，再谈跳过重启。

因此本文件钉两件事：① 循环里的任务间动作仍然是无条件 `_reset_cdp()`——想改门控的人必须先改掉
这条测试并拿出上面那张表的替代证据；② 那次重启依旧只许杀我们自己的两个画像（P0 杀伤侧）。

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


@case("#56 否决记录①：任务之间仍是无条件 _reset_cdp()（b21 用 3 行 ERROR 换的读数）")
def t_between_tasks_still_pays_full_reset():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    m = re.search(r"if i > 1:\n(\s+)(\S+)", src)
    assert m, "批循环里找不到任务间的动作（`if i > 1:` 被改掉了？）"
    called = m.group(2)
    assert called.startswith("_reset_cdp()"), (
        "任务间动作变成了 %r。b21 的读数：跳过重启换来 27.8→11.0 min，但也换来 "
        "r139/r140/r141 三行 `agent_init_failed: StalePage: Document is navigating`"
        "（ERROR、无 trace、新 29 行 29/29→26/29）。要重新提这个改法，先修好"
        "'任务起点的观测能穿过在途导航'，并拿出 error=0 的批读数。" % called)
    assert not hasattr(RT, "_cdp_healthy"), "健康门控又被加回来了——它没有被重新验证过"


@case("#56 否决记录②：那次重启只许杀我们自己的两个画像")
def t_reset_still_scoped_to_owned_profiles():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    reset = src[src.index("def _reset_cdp"):src.index("def _run_one")]
    assert "chrome-jev-profile" in reset and "chrome-cdp-test" in reset, \
        "_reset_cdp 的 kill filter 必须继续点名我们自己的两个画像"
    # 注释里写着当年那条 taskkill（历史说明），所以只查真正的可执行形态
    assert not re.search(r'subprocess\.(run|Popen)\(\s*\[?\s*"?taskkill', reset), \
        "裸 taskkill 回到了可执行代码里"
    assert "Get-Process chrome | Stop-Process" not in reset, "裸杀浏览器回到了可执行代码里"


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
    raise SystemExit(main())
