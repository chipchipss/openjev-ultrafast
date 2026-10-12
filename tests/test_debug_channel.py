r"""#68：静默降级要么留痕、要么明确不许留痕——用一个 `JEV_DEBUG` 才出声的通道。

外部体检报告点验为真的两条规模：**宽 `except Exception` 实测 29 处**
（`skills.py` 9 / `agent.py` 7 / `browser.py` 12 / `logger.py` 1），`browser.py` 里 **7 处裸 `print`**。
其中最贵的一处是 `skills.route()`：技能内部抛异常被吞成 `d = None`，行为上"回落模型"是对的，
但**哪个技能、抛了什么**在日志里一点痕迹都没有——#59 那一整轮误诊（把"技能已经能判达"读成
"模型能力问题"）就是这个形状。

这一支的边界要说清楚，别做过头：

- **不改控制流**。异常照旧吞、降级照旧降级（`Page.enable` 装不上不能让新页面起不来）。
- **默认零输出**。`JEV_DEBUG` 不设时一个字都不写，批日志与报告格式完全不变。
- 只给**会改变解释**的那几处装留痕：route 的技能异常、浏览器四类安装/自愈降级点，
  以及原本用裸 `print` 输出的 `FRESH_MISMATCH` 诊断块。

运行：python tests/test_debug_channel.py
"""
from __future__ import annotations

import io
import re
import sys
import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES = []


def except_block(src: str, except_match) -> str:
    """取 except 行的块体：按缩进划界，不受中间注释/空行影响。

    上一版仪器用『锚点后 N 个字符』当窗口，量到的是常量定义体而不是安装点，
    于是把已经装好的留痕读成无声——那条红是仪器造的，不是代码造的。
    """
    line_start = src.rfind("\n", 0, except_match.start()) + 1
    indent = len(src[line_start:except_match.start()]) - len(
        src[line_start:except_match.start()].lstrip())
    lines = src[src.index("\n", except_match.end()) + 1:].split("\n")
    out = []
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            continue
        if len(ln) - len(ln.lstrip()) <= indent:
            break
        out.append(ln)
    return "\n".join(out[:12])


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("logger 里有 dbg()：默认一声不出，JEV_DEBUG=1 时往 stderr 写一行带 tag 的留痕")
def t_dbg_exists_and_is_gated():
    import os
    from jev_ultrafast.logger import dbg

    err = io.StringIO()
    os.environ.pop("JEV_DEBUG", None)
    with contextlib.redirect_stderr(err):
        dbg("skill_raised", "goal_reached ValueError")
    assert err.getvalue() == "", f"没设 JEV_DEBUG 也出声了：{err.getvalue()!r}"

    os.environ["JEV_DEBUG"] = "1"
    try:
        err2 = io.StringIO()
        with contextlib.redirect_stderr(err2):
            dbg("skill_raised", "goal_reached ValueError")
        line = err2.getvalue()
        assert "skill_raised" in line and "goal_reached" in line, f"开了开关却没留痕：{line!r}"
        assert line.count("\n") == 1, "每次降级只许一行，否则批日志会被刷屏"
    finally:
        os.environ.pop("JEV_DEBUG", None)


@case("route() 的技能异常必须留痕（改前必须红：现在只是 d = None）")
def t_route_logs_skill_exceptions():
    src = (REPO / "jev_ultrafast" / "skills.py").read_text(encoding="utf-8")
    i = src.index("def route(")
    body = src[i:]
    m = re.search(r"for fn in SKILLS:.*?except Exception", body, re.S)
    assert m, "route() 里找不到技能调用那个 except 分支——本条要跟着重写"
    block = except_block(body, m)
    assert 'dbg("skill_raised"' in block, \
        "技能异常仍然无声：d = None 之后没人知道是哪个技能抛的（#59 那轮误诊的形状）"
    assert "d = None" in block, "留痕不该改掉原有的回落行为：块体里仍要有 d = None"


@case("browser 的四处降级点与 FRESH_MISMATCH 诊断必须走 dbg，不再裸 print")
def t_browser_degradations_are_traceable():
    src = (REPO / "jev_ultrafast" / "browser.py").read_text(encoding="utf-8")
    assert "from jev_ultrafast.logger import dbg" in src or "import dbg" in src, \
        "browser 没接入留痕通道"
    # 每处降级点认它自己的 tag，不认常量名出现的位置：常量定义在前、安装点在后，
    # 拿定义位置当锚点会量到定义体（上一版仪器的红就是这个原因，不是代码没装）。
    sites = {
        "daemon 起不来": ("daemon_ensure_failed", "daemon_restart_failed"),
        "MODAL_GUARD 装不上": ("modal_guard_not_installed",),
        "SETTLE_INIT 装不上": ("settle_init_eval_failed", "settle_init_not_registered"),
        "滚动结算失败": ("scroll_settle_failed",),
        "FRESH_MISMATCH 诊断": ("fresh_mismatch",),
    }
    for label, tags in sites.items():
        missing = [t for t in tags if f'dbg("{t}"' not in src]
        assert not missing, f"降级点 {label} 仍然无声（tag {missing}）：装不上=等价改前行为，但要留一行痕迹"
    assert 'print("FRESH_MISMATCH' not in src, \
        "FRESH_MISMATCH 还是裸 print：它混在批 stdout 里既不是日志也不是报告"


@case("留痕不许改变控制流：装了 dbg 的 except 分支里仍然没有 raise")
def t_dbg_does_not_change_flow():
    checked = 0
    for rel in ("jev_ultrafast/browser.py", "jev_ultrafast/skills.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"except Exception[^\n]*", src):
            block = except_block(src, m)
            if "dbg(" in block:
                checked += 1
                assert not re.search(r"(?m)^\s*raise\b", block), \
                    "装了留痕顺手把降级改成抛出：#68 明令不动控制流\n" + block[:160]
    # 8 个留痕点里 7 个在 except 分支（browser 6 + route 1）；fresh_mismatch 是
    # 正常分支里的诊断行，不属于本条要守的"降级不许变抛出"。
    assert checked >= 7, f"只查到 {checked} 处留痕分支，少于已装的 7 处 except 降级点：仪器没跑全"


def main() -> int:
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
