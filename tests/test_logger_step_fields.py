r"""step 事件的字段完整性（外部体检报告核实为真的第一条，转成任务 #67）。

**病灶不是审美，是仪表**：`Logger._clean_step` 用一份 15 键白名单过滤 agent 写进 history 的条目，
而 `agent.py:553` 那次 append 实际写了 21 个键。被丢掉的四个人里有三个是**到达判据在读的东西**：

- `outcome`（`status` / `url_changed`，agent 在观测归静后结算出来，`agent.py:605-623`）
- `url_from`（出发页；#59 `link_followed_arrival` 的同主机守卫只能拿它比）
- `page_fp_before`（动作前指纹，Fix P 的未知结算依据）
- 还有 `skill`（这一拍是哪个地板技能发的）

代价在 2026-10-11 晚实盘发生：要判断 python-docs 搜索结果文本"何时出现"，
`logs/real-1011-b33-100-*/r154.jsonl` 里读不到页面观测的任何痕迹，只能重开一个自有浏览器做零模型复探。
项目的硬规矩是"反常指标第一动作是翻 jsonl 日志"——日志缺字段，规矩就落空。

这个文件钉两件事：① 那四个键必须出现在落盘的 step 事件里（行为检查，真的写一遍 jsonl）；
② **白名单与写入点之间要有一份显式的丢弃清单**——以后谁往 history 里加字段而没登记，
这条测试必须红，而不是静默地把字段留在内存里、丢在磁盘外。

运行：python tests/test_logger_step_fields.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast.logger import Logger      # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _history_entry() -> dict:
    """照 `agent.py:553` 那次 append 的形状造一条**已结算**的 history 条目。

    结算后的形状有出处，不是发明：`page_changed` 从 None 变成布尔、`url` 被改写成落地页、
    `outcome` 挂上三元组（`agent.py:605-623`）。这正是"字段什么时候被丢"要看的时刻。
    """
    return {
        "step": 1, "action": "click 'Docs'", "kind": "click", "choice": "e7",
        "probability": 0.9, "confidence": 0.9, "latency_ms": 12,
        "text": None, "text_helper": None, "text_latency_ms": 0,
        "operation": "CLICK", "target": "7", "skill": "link_followed_arrival",
        "page_changed": True, "url": "https://docs.python.org/3/search.html?q=list",
        "url_from": "https://docs.python.org/3/",
        "page_fp_before": "fp-before", "usage": {"total_tokens": 100},
        "executed_ms": 340, "elapsed_ms": 1200,
        "outcome": {"status": "url_changed", "page_changed": True, "url_changed": True},
        "pre_execute": {"validator": {"valid": True}},
    }


def _read_step_event(tmp: Path) -> dict:
    files = list(Path(tmp).glob("*.jsonl"))
    assert files, "Logger 没写出 jsonl 文件"
    for line in files[0].read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        if ev.get("event") == "step":
            return ev
    raise AssertionError("日志里没有 step 事件")


@case("step 事件必须带上到达判据在读的四个字段（outcome/url_from/page_fp_before/skill）")
def t_arrival_fields_are_logged():
    tmp = tempfile.mkdtemp()
    with Logger("t-fields", Path(tmp)) as lg:
        lg.observe({"history": [_history_entry()], "decisions": [], "text_calls": []})
    ev = _read_step_event(Path(tmp))
    missing = [k for k in ("outcome", "url_from", "page_fp_before", "skill") if k not in ev]
    assert not missing, (
        "step 事件里没有 %s —— 这些是 agent 写在 history 上的字段（`agent.py:553` 起），"
        "到达判据与 #59 靠它们推理。日志里没有，诊断就只能重开浏览器复探（2026-10-11 晚实盘发生）。" % missing)
    assert ev["outcome"]["status"] == "url_changed", "outcome 被截断了，判据拿不到 status"
    assert ev["url_from"] == "https://docs.python.org/3/", "出发页丢了：同主机守卫没法比"


@case("白名单与 agent 写入点之间有一份显式的丢弃清单（新增字段没登记就红）")
def t_drop_list_is_declared_and_complete():
    assert hasattr(Logger, "STEP_DROP_KEYS"), \
        "Logger 没有 STEP_DROP_KEYS：字段是被静默丢掉还是有意丢掉，读代码分不出来"
    ag = (REPO / "jev_ultrafast" / "agent.py").read_text(encoding="utf-8")
    i = ag.find('"page_changed": None,')
    assert i > 0, "agent.py 里 history 那次 append 的形状变了（锚点找不到），本条测试要跟着重写"
    start = ag.rfind('state["history"].append', 0, i)
    block = ag[start:ag.find("pre_execute", i)]
    written = set(re.findall(r'^\s*"(\w+)":', block, re.M))
    # 结算阶段另外挂上去的两个键也在同一份 history 条目上（agent.py:605-623）
    written |= {"outcome", "url"}
    kept = set(Logger._clean_step(_history_entry()).keys())
    dropped = written - kept - {"pre_execute"}
    declared = set(Logger.STEP_DROP_KEYS)
    assert dropped == declared, (
        "实际丢掉 %s，登记的只有 %s —— 差集里的字段是**静默**消失的。"
        "要么补进白名单，要么在 STEP_DROP_KEYS 里写下为什么不留。" % (sorted(dropped), sorted(declared)))


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
