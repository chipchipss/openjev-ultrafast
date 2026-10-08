"""E1 回归：初始观测撞上导航中时，Agent 构造必须有界退避，而不是把整条任务炸掉。

b7 的 r103 实况：报告行只剩 `agent_init_failed: StalePage: Document is navigating`，
traceback 落在 `Agent.__init__ -> browser.observe`，**没有 jsonl、没有 TaskResult** ——
那条任务连判据都没被跑过。observe 内部只有 10×20ms，一次真实导航是 1s 量级。

这个测试不连浏览器（Browser 整个换掉），验的是接线的三件事：
① 撞上 StalePage 会重试而不是逃出；② 退避是**递增**且有上限；
③ 全部失败时行为回到今天的样子（抛出 + 关掉会话），不静默吞掉。

运行：python tests/test_agent_init_backoff.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import agent as A  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


PAGE = {
    "url": "https://stackoverflow.com/", "title": "Stack Overflow", "text": "",
    "actions": [], "guards": {}, "fingerprint": "fp-1", "marker": "m",
    "marker_stable": 1, "page_key": [1.0, "https://stackoverflow.com/", 0, 0, 1120, 780],
    "scroll": {"y": 0, "height": 900}, "w": 1120, "h": 780, "omitted_actions": 0,
}


class FakeBrowser:
    """只记录，不连 CDP。fail_times 次 StalePage 之后才开始返回页面。"""

    instances: list["FakeBrowser"] = []

    def __init__(self, url):
        self.url = url
        self.observes = 0
        self.closed = False
        FakeBrowser.instances.append(self)

    def observe(self, screenshot=True):
        self.observes += 1
        if self.observes <= FAIL["times"]:
            raise A.StalePage("Document is navigating")
        return dict(PAGE)

    def close(self):
        self.closed = True


FAIL = {"times": 0}
SLEEPS: list[float] = []


def install():
    """换掉 Browser 与 sleep（sleep 记账，测试不真等 6 秒）。"""
    FakeBrowser.instances = []
    SLEEPS.clear()
    A.Browser = FakeBrowser
    A.time.sleep = lambda s: SLEEPS.append(s)


@case("撞上导航中的初始观测会重试，而不是把任务炸成 ERROR")
def t_retries_instead_of_escaping():
    install()
    FAIL["times"] = 3
    ag = A.Agent("https://stackoverflow.com/", "Search Stack Overflow for 'python slice step'.")
    assert ag.state["page"]["fingerprint"] == "fp-1", "退避后没把页面接上"
    assert len(SLEEPS) == 3, f"重试次数不对：{SLEEPS}"
    assert SLEEPS == sorted(SLEEPS) and SLEEPS[-1] > SLEEPS[0], f"退避没有递增：{SLEEPS}"


@case("全部失败时行为不变：抛出 StalePage 并关掉会话（不静默吞）")
def t_gives_up_cleanly_when_page_never_settles():
    install()
    FAIL["times"] = 99                      # 永远不会归静
    try:
        A.Agent("https://stackoverflow.com/", "Search for 'x'.")
    except A.StalePage:
        pass
    else:
        raise AssertionError("退避耗尽后必须仍然抛出——静默成功会把不可达说成可达")
    br = FakeBrowser.instances[0]
    assert br.closed, "放弃时没关浏览器会话（会留下挂死的 CDP target）"
    assert len(SLEEPS) == 5, f"重试必须有上限，不能无限：观察 {1+len(SLEEPS)} 次 / {SLEEPS}"


@case("非 StalePage 的错误不重试（页面坏了不是慢）")
def t_other_exceptions_do_not_burn_the_backoff():
    install()

    class Broken(FakeBrowser):
        def observe(self, screenshot=True):
            self.observes += 1
            raise RuntimeError("Target closed")

    A.Browser = Broken
    try:
        A.Agent("https://stackoverflow.com/", "Search for 'x'.")
    except RuntimeError:
        pass
    else:
        raise AssertionError("RuntimeError 不该被当成可重试")
    assert SLEEPS == [], f"非竞态错误也在退避：{SLEEPS}"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass
    real_sleep, real_browser = A.time.sleep, A.Browser
    failed = 0
    try:
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
    finally:
        A.time.sleep, A.Browser = real_sleep, real_browser
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
