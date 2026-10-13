r"""#82：提示词承诺的操作词表，不许比校验器允许的宽。

**病灶是 #80 的云端臂量出来的**（`m2/real-log.md` 的 #80 读数一节）：
`DECIDER_MODE=openai` 打 Groq 免费档跑 19 行冻结集，`gpt-oss-20b` 被拒收 15 次、
`gpt-oss-120b` 被拒收 5 次，**两臂逐字同一句** `unknown operation 'SCROLL_DOWN'`，
共同掉的那一行 l001 就是这个形状（A 烧到 9 步 FAIL，B 5 次调用 0 步 FAIL）。

机制在源码里一读就通，而且**责任不在模型**：

| 位置 | 说什么 |
|---|---|
| `jev_ultrafast/prompts/next_action.txt` 的 Rules | `operation is one of: CLICK, TYPE_TEXT, SELECT, SCROLL_DOWN, SCROLL_UP, WAIT, DONE, BLOCKED` —— **无条件**列出的固定表 |
| `decider/choose_2b.py:_render_operations` | "Available operations:" 由**当前页**的 targets + controls 生成 —— 页面滚到底时 `scroll_down` 不存在，这一行就不列它 |
| `decider/choose_2b.py:_map_choice` | 只认 targets/controls 里真存在的键，否则抛 `unknown operation` |

⇒ 模型照着 system prompt 的规则办事，挑了一个**这一页此刻不给**的操作，被自己的校验器拒收；
每一次拒收按缺陷#5 的口径还**计入一次真实模型调用**（`model_calls`），所以它既烧预算又烧步数。
本地 2B 不暴露这格，是因为 typesafe 那条线走"给候选打分"，模型从不自己拼操作名。

修法只有一句：**静态 Rules 不再列页依赖的操作名，改为指向页面那份 Available operations**。
这一族以前也踩过（#80 之前是"提示词与产品不同步"的另一种形状），所以这里把三份东西一起钉住：
静态表不许超出动态表、动态表本身按页正确、拒收信息要能事后诊断。

运行：python tests/test_prompt_operation_vocabulary.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast.decider import choose_2b as C2      # noqa: E402

CASES = []
PROMPT = (REPO / "jev_ultrafast" / "prompts" / "next_action.txt").read_text(encoding="utf-8")


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco

# 页依赖的操作：由 snapshot.js 按当前页状态加进 actions（滚到底就没有 scroll_down，
# 页顶就没有 scroll_up），所以它们**不能**出现在静态词表里。
PAGE_DEPENDENT = ("SCROLL_DOWN", "SCROLL_UP", "SCROLL_BOTTOM", "SCROLL_TOP")


def rules_operation_line(text: str) -> str:
    m = re.search(r"operation is one of[^\n]*", text, re.I)
    assert m, "提示词里找不到 'operation is one of' 这一行——测试的锚点变了，去看那份文件"
    return m.group(0)


@case("① 静态 Rules 不许无条件列出页依赖的操作（#80 两臂共同掉 l001 的那句源头）")
def t_prompt_does_not_promise_page_dependent_operations():
    line = rules_operation_line(PROMPT)
    promised = [op for op in PAGE_DEPENDENT if re.search(r"\b%s\b" % op, line)]
    assert not promised, (
        f"提示词无条件承诺了 {promised}，而 `_render_operations` 只在当前页真有这个控件时才列它 —— "
        f"模型照规则挑一个本页不给的操作，就会被自己的校验器拒收。原文：{line!r}")
    assert re.search(r"available operations", line, re.I), (
        f"这一行必须把操作名的唯一来源指向页面那份 Available operations：{line!r}")


@case("② 动态那份才是唯一来源：有滚动控件的页面会列，滚到底的页面不会")
def t_available_operations_is_page_dependent():
    targets = {"CLICK": {"1": {"id": "e1"}}}
    with_scroll = C2._render_operations(targets, {"SCROLL_DOWN": {"id": "s1"}})
    without = C2._render_operations(targets, {})
    assert "SCROLL_DOWN" in with_scroll, "页面给了滚动控件，Available operations 却没列它"
    assert "SCROLL_DOWN" not in without, "已经滚到底的页面还被告知可以 SCROLL_DOWN"


@case("③ 拒收信息要能事后诊断：报 unknown operation 时把当页可选列表一起带出来")
def t_rejection_names_the_available_alternatives():
    targets = {"CLICK": {"1": {"id": "e1"}}}
    try:
        C2._map_choice("SCROLL_DOWN", None, targets, {})
    except ValueError as e:
        msg = str(e)
        assert "unknown operation" in msg, f"错误口径变了：{msg!r}"
        assert "CLICK" in msg, (
            "只说 unknown operation 'SCROLL_DOWN' 不够 —— trace 里那条字符串是事后唯一能看出"
            "'模型当时有哪些选择'的地方（b41/A/B 三批的拒收都只能数次数，看不出模型为什么挑它）")
    else:
        raise AssertionError("非法操作居然没被拒收")


@case("④ 对照：本页真给了控件时，同一个操作名必须照常放行（修表不许把能力修没）")
def t_offered_control_still_maps():
    targets = {"CLICK": {"1": {"id": "e1"}}}
    choice, target = C2._map_choice("SCROLL_DOWN", None, targets, {"SCROLL_DOWN": {"id": "s1"}})
    assert choice == "s1" and target is None, (
        f"页面给了 scroll_down 时应当映射到它的 id，实际 {choice!r}/{target!r}")


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("ok    " + name)
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print("FAIL  " + name)
            print("      " + f"{type(e).__name__}: {str(e)[:320]}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    raise SystemExit(1 if failed else 0)
