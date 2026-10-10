"""#54 回归：批里自有浏览器掉了，runner 要会重起并重试这一行。

发现的形状（b19 实测，`reports/real-1010-b19-fix52-1010-160144.json`）：
r120 整行没有 trace（批目录只有 49 个 jsonl），报告原文是

    agent_init_failed: RuntimeError: no-browser: nothing listens on :9222 --
    the owned CDP Chrome was started by the runner ...

`browser.py::_assert_owned_browser` 的 fail-closed 是**对的**（宁可废一行，也绝不回退去
开用户自己的浏览器）。缺的是它后面没有自愈：`m1/run_tasks.py::_reset_cdp()` 本来就会
"只杀我们自己的两个画像 + 在 :9222 重起 + `_ensure_daemon()`"，但 `_run_one` 在 Agent
构造失败时直接把这一行判死，从不叫它。代价 = 一行分母 + 一次 28 分钟的重跑，而 L3 的
100–300 题长批只会更容易撞上。

四条用例：① 掉一次要重起并重试；② 连掉两次必须有界（不许无限重跑）；
③ 非浏览器异常不许被误当成掉线（不许拿自愈当遮羞布）；④ 自愈路径仍然只许动自有画像
（静态盯 `_reset_cdp` 的 kill filter 与 browser.py 的归属前缀，防止有人为了"能重跑"放宽 P0）。

不连浏览器、不调模型：全部用假 Agent 与打桩的 `_reset_cdp`。
运行：python tests/test_runner_browser_recovery.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import m1.run_tasks as RT                                     # noqa: E402
import jev_ultrafast.agent as AG                              # noqa: E402

CASES = []
NO_BROWSER = "no-browser: nothing listens on :9222 -- refusing to fall back"
FOREIGN = "foreign-browser: :9222 is served by a Chrome we did not start"


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


class FakeAgent:
    """只提供 `_run_one` 真正会碰到的四个面。"""

    step_budget = 20
    closed = 0

    def __init__(self, *a, **kw):
        self.state = {"status": "done", "history": [], "decisions": [],
                      "page": {"url": "https://example.org/done", "title": "Done",
                               "text": "done", "actions": []}}

    def run(self):
        return iter(())

    def close(self):
        FakeAgent.closed += 1


class BoomAgent:
    """每次都抛浏览器丢失。"""

    step_budget = 20
    calls = 0

    def __init__(self, *a, **kw):
        BoomAgent.calls += 1
        raise RuntimeError(NO_BROWSER)

    def close(self):
        pass


class ValueBoom:
    def __init__(self, *a, **kw):
        raise ValueError("task_spec 少字段")

    def close(self):
        pass


def install(monkey, agent_cls):
    """打桩：真 Agent / 真 logger / 真 evaluate 一概不碰。"""
    calls = {"reset": 0}

    def fake_reset():
        calls["reset"] += 1

    class FakeLogger:
        def __init__(self, *a, **kw):
            pass

        def observe(self, *a, **kw):
            pass

        def finalize(self, *a, **kw):
            pass

        def close(self):
            pass

    def fake_evaluate(spec, page, history, status, meta=None):
        payload = {"task_id": spec["task_id"], "result": "PASS",
                   "quadrant": "true_success", "failure_class": "none",
                   "failure_mode": None,
                   "evidence": {"final_url": (page or {}).get("url"),
                                "final_title": "Done", "assertion_trace": []},
                   "meta": dict(meta or {}, elapsed_ms=1)}

        class FakeResult:      # `run_tasks.py:206` 真会调 task_result.to_dict()
            def to_dict(self):
                return payload
        return FakeResult()

    saved = (AG.Agent, RT._reset_cdp, RT.Logger, RT.evaluate)
    AG.Agent = agent_cls
    RT._reset_cdp = fake_reset
    RT.Logger = FakeLogger
    RT.evaluate = fake_evaluate
    monkey.append(saved)
    return calls


def undo(monkey):
    AG.Agent, RT._reset_cdp, RT.Logger, RT.evaluate = monkey.pop()


SPEC = {"task_id": "r120", "goal": "Open the done page.",
        "budget": {"steps": 20},
        "success_assertion": {"type": "url_matches", "pattern": r"example\.org/done$"}}


def run_one(agent_cls, monkey):
    calls = install(monkey, agent_cls)
    with tempfile.TemporaryDirectory() as td:
        row = RT._run_one(SPEC, Path(td), "https://example.org/", False)
    undo(monkey)
    return row, calls


@case("#54① 浏览器掉一次：重起自有画像并重试这一行，不许直接判死")
def t_recovers_once():
    monkey = []
    row, calls = run_one(FakeAgent, monkey)      # FakeAgent 构造永不失败
    assert row["result"] != "ERROR", row
    # 正常路径不该平白重起浏览器（重起是有代价的：整页画像清空）
    assert calls["reset"] == 0, f"正常行不该 reset：{calls}"

    class Flaky:
        """第一次构造遇到 no-browser，第二次成功——就是 r120 那一拍。"""
        n = 0
        step_budget = 20

        def __new__(cls, *a, **kw):
            cls.n += 1
            if cls.n == 1:
                raise RuntimeError(NO_BROWSER)
            return FakeAgent(*a, **kw)

        def close(self):
            pass

    Flaky.n = 0
    monkey2 = []
    row2, calls2 = run_one(Flaky, monkey2)
    assert calls2["reset"] == 1, f"掉浏览器后没有重起画像：{row2}"
    assert row2["result"] != "ERROR", f"重试没把这一行救回来：{row2}"


@case("#54② 连掉两次：重试有界（reset 恰好 1 次），然后按实报 ERROR")
def t_retry_is_bounded():
    BoomAgent.calls = 0
    monkey = []
    row, calls = run_one(BoomAgent, monkey)
    assert calls["reset"] == 1, f"重跑必须有界，实到 {calls['reset']} 次"
    assert BoomAgent.calls == 2, f"应当只重试一次构造，实到 {BoomAgent.calls}"
    assert row["result"] == "ERROR" and "agent_init_failed" in row.get("error", ""), row


@case("#54③ 非浏览器异常不许被当成掉线（自愈不是遮羞布）")
def t_other_errors_not_swallowed():
    monkey = []
    row, calls = run_one(ValueBoom, monkey)
    assert calls["reset"] == 0, f"普通 bug 不该触发画像重起：{calls}"
    assert row["result"] == "ERROR" and "ValueError" in row.get("error", ""), row


@case("#54④ 自愈路径仍然只许动自有画像，且只认 browser.py 的两个 fail-closed 前缀")
def t_ownership_line_intact():
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    reset = src[src.index("def _reset_cdp"):src.index("def _run_one")]
    # `_reset_cdp` 的**注释**里写着当年那条 `taskkill /F /IM chrome.exe`（历史说明），
    # 拿字符串直接比会把说明文当成现行代码——先把 docstring 摘掉再断言。
    import inspect
    doc = RT._reset_cdp.__doc__ or ""
    code = reset.replace(doc, "")
    assert "chrome-jev-profile" in code and "chrome-cdp-test" in code, \
        "_reset_cdp 的 kill filter 必须继续点名我们自己的两个画像"
    for bare in ("taskkill /F /IM chrome.exe", "Get-Process chrome | Stop-Process"):
        assert bare not in code, f"裸杀浏览器又回到了可执行代码里：{bare}"
    bsrc = (REPO / "jev_ultrafast" / "browser.py").read_text(encoding="utf-8")
    assert "no-browser:" in bsrc and "foreign-browser:" in bsrc, \
        "归属守卫的前缀变了，分类器要同步——不许为了重试放宽 P0"
    assert "_BROWSER_LOSS" in src and "_is_browser_loss" in src, \
        "自愈必须走窄口径分类器（只认那两个前缀），不是 except Exception 兜底"


def main():
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                              # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
