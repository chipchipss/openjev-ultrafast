r"""#89 的下一刀：init 抛穿那一刻，必须留下一份有界的浏览器/daemon 诊断。

缺陷有工件，而且是硬工件：`r139` 死的时候报告行里只有
`{task_id, result, error, traceback}`（`reports/ci-1014-2225-1014-224810.json` 数过，见第 5 案），
**没有 trace 目录**（`m1/run_tasks.py:294` 那句注释就是为了不关 logger 才写的，可异常发生在
`logger` 写下任何东西之前）。于是七次同签名的死亡（`m2/real-log.md` 的 #89 一节）每次只能事后猜
"当时的 `:9222` 是谁在听、daemon 面前有几个目标"——这正是 #67/#85 一路在拆的"仪器缺字段"。

四条硬线（每条一案）：
1. 诊断函数**永不抛**：它只是记录，记录失败不许改变这一行的结局
   （否则一次环境事故会被升级成 runner 事故）；
2. **两条 ERROR 出口都要有**（非浏览器类那条 `agent_init_failed` 与复位后那条
   `agent_init_failed_after_cdp_reset`）——只补一条等于没补，#72 的教训就是"一个概念两张表"；
3. 诊断里**不许进第三方内容**：目标页只留 host，路径/查询/正文一律不进
   （#79 与 `feedback-mask-third-party-values-in-docs`：记形状与来源，不记值）；
4. **健康行不许被污染**：`_run_one` 的成功路径里不许出现 `error_detail`，
   这一刀只接在异常分支上。

第 5 案钉的是"缺件是真的"（读已入库工件），第 1 案钉的是永不抛。

运行：python tests/test_init_failure_diagnostic.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _row_from_failed_init(exc_factory, monkey_reset=False):
    """真跑 `_run_one` 的异常分支：把 Agent 换成会抛的假类，返回那一条行。"""
    import m1.run_tasks as rt
    import jev_ultrafast.agent as agent_mod

    real_agent = agent_mod.Agent
    real_reset = rt._reset_cdp

    class FakeAgent:
        def __init__(self, *a, **kw):
            raise exc_factory()

    agent_mod.Agent = FakeAgent
    if monkey_reset:
        rt._reset_cdp = lambda: None
    try:
        spec = {"task_id": "zz_init", "goal": "probe only, never runs", "domain": "example.com",
                "category": "navigate", "budget": {"steps": 1},
                "success_assertion": {"type": "url_matches", "pattern": "never"}}
        with tempfile.TemporaryDirectory() as td:
            return rt._run_one(spec, Path(td), "https://example.com/", False)
    finally:
        agent_mod.Agent = real_agent
        rt._reset_cdp = real_reset


@case("①诊断函数存在且永不抛：端口没人听、daemon 死了也要交出字典")
def t_diagnostic_never_raises():
    import m1.run_tasks as rt
    assert hasattr(rt, "_init_failure_diagnostic"), "m1/run_tasks.py 里没有 _init_failure_diagnostic"
    d = rt._init_failure_diagnostic("https://127.0.0.1:1/", port=1)   # 一定连不上的端口
    assert isinstance(d, dict), f"必须返回 dict，实际 {type(d).__name__}"
    for key in ("start_url", "cdp_port", "listener_present", "listener_owned"):
        assert key in d, f"诊断少了 {key} 这一格（缺件就是这一刀要修的）"
    assert ("targets_error" in d) or ("target_count" in d), "targets 那一半要么读到了，要么记下失败原因"


@case("②非浏览器类 init 失败：行里必须带 error_detail")
def t_plain_init_failure_row_carries_detail():
    row = _row_from_failed_init(lambda: ValueError("boom: not a browser problem"))
    assert row["result"] == "ERROR", row
    assert "agent_init_failed:" in row["error"], row["error"]
    assert "error_detail" in row, "这条出口没接上诊断——同一批里另一条有，读数就会一半有一半没有"
    assert "start_url" in row["error_detail"] and "cdp_port" in row["error_detail"]


@case("③复位后仍失败的那条出口也要带（一个概念不许两张表）")
def t_reset_then_failure_row_carries_detail():
    from jev_ultrafast.browser import StalePage
    row = _row_from_failed_init(lambda: StalePage("Document is navigating"), monkey_reset=True)
    assert row["result"] == "ERROR", row
    assert "after_cdp_reset" in row["error"], f"这一支应该走复位重试后再失败：{row['error']}"
    assert "error_detail" in row, "只补第一条出口 = #72 那个坑重演（一条路径有仪器，另一条没有）"


@case("④诊断不许带第三方内容：目标页只留 host，且成功路径不被污染")
def t_diagnostic_is_masked_and_healthierows_untouched():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def _init_failure_diagnostic"):src.index("def _init_failure_diagnostic") + 2600]
    assert "netloc" in body, "targets 只许留 host（netloc）；整 URL 带查询参数就是把别人的内容抄进工件"
    assert "observe(" not in body, "诊断不许读页面正文/动作表——那会把第三方内容抄进可分享工件（#75/#79 同一族）"
    # 成功路径：_run_one 里 error_detail 只许出现在两个 ERROR 返回里
    assert src.count('"error_detail": _init_failure_diagnostic') == 2, \
        "error_detail 必须恰好接在两条 ERROR 出口上（多了会污染健康行，少了就是一半没有仪器）"


@case("⑤已入库的历史工件证明「缺件」是真的：r139 那行只有四个键")
def t_the_gap_is_real_in_a_committed_artifact():
    p = REPO / "reports" / "ci-1014-2225-1014-224810.json"
    assert p.exists(), "见证工件不见了"
    b = json.loads(p.read_text(encoding="utf-8"))
    row = next(r for r in b["results"] if r.get("task_id") == "r139")
    assert set(row.keys()) == {"task_id", "result", "error", "traceback"}, \
        f"这条 10-14 的死亡行的键集已变（{sorted(row.keys())}）——本案的钉子会失效，须改成新工件"
    assert "error_detail" not in row, "改前的缺陷就是「这里没有诊断」；若已存在，这条不再是缺陷见证"


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
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
