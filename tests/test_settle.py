"""settle detection 的 Python 侧回归（不依赖浏览器）。

验的是接线与收口，不是页面行为：
- 按动作类型路由：click/select/fill 走 settle，wait/scroll/reload 不触发；
- act() 顺序：先装在途计数补丁，再执行动作，再等归静；
- CDP 调用抛异常（导航销毁上下文）时必须安静退回，不能把 StalePage 之外的错抛给主循环。

运行：python tests/test_settle.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import browser as B  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


class Recorder:
    """替掉 Browser.call：只记账，不连浏览器。"""

    def __init__(self, raise_on=None):
        self.calls = []
        self.raise_on = raise_on

    def call(self, method, **params):
        self.calls.append((method, params))
        if self.raise_on and self.raise_on in str(params.get("expression", "")):
            raise RuntimeError("context destroyed")
        return {"result": {"value": 1}}


def fake_browser(raise_on=None):
    b = B.Browser.__new__(B.Browser)
    b.session = "test-session"
    rec = Recorder(raise_on)
    b.call = rec.call
    return b, rec


def js_expressions(rec):
    return [p.get("expression", "") for _, p in rec.calls]


@case("settle 上限表只覆盖会触发渲染/请求的动作")
def _caps_table():
    caps = B.Browser.SETTLE_CAPS_MS
    assert set(caps) == {"click", "select", "fill"}, f"覆盖范围漂移: {caps}"
    assert caps["click"] >= 1000, "n004 的 SPA 结果要数秒才渲染，click 上限不能缩回亚秒"


@case("非 settle 动作不产生任何 CDP 调用")
def _other_kinds_are_noop():
    b, rec = fake_browser()
    for kind in ("wait", "scroll", "reload", "submit"):
        b.await_action_settle(kind)
    assert rec.calls == [], "不该有调用"


@case("settle JS 同时盯三件事：DOM 归静、在途请求、未完成的 transition")
def _settle_js_covers_all_signals():
    b, rec = fake_browser()
    b.await_action_settle("click")
    assert len(rec.calls) == 1
    method, params = rec.calls[0]
    assert method == "Runtime.evaluate"
    assert params.get("awaitPromise") is True
    expr = params["expression"]
    for signal in ("MutationObserver", "__jevSettle", "CSSTransition", "setTimeout(check"):
        assert signal in expr, f"缺信号: {signal}"
    # 上限真的编进了表达式（按动作类型设上限是这个方案的核心）
    assert str(B.Browser.SETTLE_CAPS_MS["click"]) in expr


@case("补丁幂等：已装过就不重复包 fetch/XHR")
def _patch_is_idempotent():
    b, rec = fake_browser()
    b._settle_patch()
    expr = rec.calls[0][1]["expression"]
    assert "if (window.__jevSettle) return 1" in expr


@case("CDP 抛错时安静退回（导航销毁上下文交给 observe 的 StalePage 重试）")
def _swallow_errors():
    b, _ = fake_browser(raise_on="__jevSettle")
    b.await_action_settle("click")  # 不该抛
    b2, _ = fake_browser(raise_on="__jevSettle")
    b2._settle_patch()  # 不该抛


@case("act() 顺序：补丁 → 执行 → settle")
def _act_order():
    b, rec = fake_browser()
    b.fresh = lambda page, action=None: True
    ops = []
    orig = B.browser_operation

    def fake_op(request):
        ops.append(request["operation"])
        return {"executed": request["action"]["id"]}

    B.browser_operation = fake_op
    try:
        b.act({"kind": "click", "id": 3, "node": 3}, {"page_key": "p", "guards": {}, "marker_stable": "m"})
    finally:
        B.browser_operation = orig
    exprs = js_expressions(rec)
    patch = [e for e in exprs if "window.__jevSettle = st" in e]
    settle = [e for e in exprs if "playState" in e]
    assert patch and settle, f"缺补丁或 settle 调用: {exprs}"
    i_patch = exprs.index(patch[0])
    i_settle = exprs.index(settle[0])
    assert i_patch < i_settle, "补丁必须在动作执行前装，否则数不到动作发起的请求"
    assert ops == ["act"]
    assert b.after_input is None or b.after_input["kind"] == "click"


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)
