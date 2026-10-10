"""#57 回归：起点观测越过退避边界时，重做一次完整起点，而不是把 6 秒改大。

发现的形状（b21，`reports/real-1010-b21-fix56-1010-224045.json`）：三行 r139/r140/r141
以 `agent_init_failed: StalePage: Document is navigating` 生吞——异常穿出 `Agent.__init__`，
runner 记 ERROR，**整行连 trace 都没有，判据一次也没跑过**。

边界在哪（读代码，不是猜）：`agent.py` 的 init 退避是 `0.4·(k+1)` × 6 次 = **6.0 s**，
`browser.py:240-249` 的 observe 内部只重试 10×20 ms = **200 ms**。

为什么不许把 6 秒改大：今晚 `m2/probe_init_latency.py` 想复现那个窗口，**没复现**——
同族 8 个页面全好，最慢起点 3.05 s，空快照最长 0.03 s。所以现在只有一条 >6 s 的读数和
一条 ≤3.05 s 的读数，拿它调边界就是猜。站得住的形状只有一条：**重做一次完整起点**
（新建 `Browser(url)` → 再走一遍 readyState + settle + observe），有界一次。
这与 tick 循环里缺陷#15b 的处理同族——那里的注释就写着"'Document is navigating' 逃逸本
handler 变 crash"，区别只在 tick 那侧有第二次机会、起点这侧没有。

运行：python tests/test_agent_init_stale_retry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import jev_ultrafast.agent as AG                      # noqa: E402
from jev_ultrafast.browser import StalePage           # noqa: E402

CASES = []
GOAL = "Open the 'Dropdown' page."
SPEC = {"task_id": "r139", "domain": "https://the-internet.herokuapp.com/",
        "category": "navigate", "goal": GOAL, "budget": {"steps": 20},
        "success_assertion": {"type": "url_matches",
                               "pattern": r"the-internet\.herokuapp\.com/dropdown$"}}


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def page(url="https://the-internet.herokuapp.com/"):
    return {"url": url, "title": "The Internet", "text": "Welcome",
            "actions": [{"id": "e1", "node": 1, "kind": "click", "label": "Dropdown",
                         "href": "/dropdown"}],
            "scroll": {"y": 0, "max": 100}}


class FakeBrowser:
    """假起点：`fail_first=True` 时第一个实例的 observe 永远 StalePage，第二个实例正常。

    `navigates` 记录被构造过几次 = 起点被做过几次（`Browser(url)` 里面才有关联画像的
    归属校验与 `_ensure_daemon`，所以"重做起点"必须体现在构造次数上）。
    """

    made = 0
    closes = 0
    fail_first = False

    def __init__(self, url):
        FakeBrowser.made += 1
        self.index = FakeBrowser.made
        self.url = url

    def observe(self, screenshot=True):
        if FakeBrowser.fail_first and self.index == 1:
            raise StalePage("Document is navigating")
        return page()

    def evaluate(self, expression):
        return "complete"

    def close(self):
        FakeBrowser.closes += 1


class AlwaysStale(FakeBrowser):
    def observe(self, screenshot=True):
        raise StalePage("Document is navigating")


class BoomBrowser(FakeBrowser):
    def observe(self, screenshot=True):
        raise RuntimeError("connection refused by :9222")


def install(cls):
    """打桩 Browser 与 sleep：用例只判控制流，不真等 6 秒，也不碰端口。"""
    FakeBrowser.made = 0
    FakeBrowser.closes = 0

    class NoSleep:
        @staticmethod
        def sleep(_s):
            return None

        @staticmethod
        def monotonic():
            import time as _t
            return _t.monotonic()

        @staticmethod
        def perf_counter():
            import time as _t
            return _t.perf_counter()

    saved = (AG.Browser, AG.time)
    AG.Browser = cls
    AG.time = NoSleep                       # agent 模块内的 time 名字，不外溢
    return saved


def undo(saved):
    AG.Browser, AG.time = saved


def build():
    return AG.Agent(url="https://the-internet.herokuapp.com/", goals=GOAL,
                    task_spec=SPEC, screenshots=False)


@case("#57① 起点退避耗尽 → 重做一次完整起点，这一行必须活下来")
def t_retries_the_start_once():
    FakeBrowser.fail_first = True
    saved = install(FakeBrowser)
    try:
        a = build()
    finally:
        undo(saved)
    try:
        assert FakeBrowser.made == 2, f"没有重做起点（只构造了 {FakeBrowser.made} 个浏览器）"
        assert a.state.get("page"), f"重做了却没拿到起点页面：{a.state.get('page')}"
        assert FakeBrowser.closes >= 1, "重做之前必须关掉旧 target（否则一批下来全是泄漏的页签）"
    finally:
        FakeBrowser.fail_first = False


@case("#57② 两次都不行 → 有界：只做一次重做，然后照旧抛出")
def t_retry_is_bounded():
    saved = install(AlwaysStale)
    try:
        raised = False
        try:
            build()
        except StalePage:
            raised = True
        assert raised, "起点彻底不可读时不许假装成功"
        assert FakeBrowser.made == 2, \
            f"重做必须有界（一次），实到 {FakeBrowser.made} 次起点"
    finally:
        undo(saved)


@case("#57③ 非 StalePage 的起点异常不许触发重做（不许把重试当遮羞布）")
def t_other_init_error_not_retried():
    saved = install(BoomBrowser)
    try:
        try:
            build()
            assert False, "原异常被吞了"
        except RuntimeError:
            pass
        assert FakeBrowser.made == 1, \
            f"普通错误不该重做起点，实到 {FakeBrowser.made} 次"
    finally:
        undo(saved)


@case("#57④ 起点正常时不许多付一次重做（否则每行白送一个浏览器）")
def t_healthy_start_not_retried():
    FakeBrowser.fail_first = False
    saved = install(FakeBrowser)
    try:
        build()
    finally:
        undo(saved)
    assert FakeBrowser.made == 1, f"健康起点被多跑了一遍（{FakeBrowser.made} 次）"


@case("#57⑤ 重做必须走 Browser(url) 本身，归属校验不许被绕过")
def t_redo_keeps_ownership_line():
    src = (REPO / "jev_ultrafast" / "agent.py").read_text(encoding="utf-8")
    seg = src[src.index("self.browser = Browser(url)"):]
    seg = seg[:seg.index("self.record_dir")] if "self.record_dir" in seg else seg[:2000]
    assert "Browser(" in seg, "起点必须经 Browser(url) 构造（那里面才有 _ensure_daemon 与归属校验）"
    for banned in ("socket.", "urllib.request.urlopen", "requests.get"):
        assert banned not in seg, f"绕开归属校验自己连端口：{banned}"


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
