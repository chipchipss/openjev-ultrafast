"""#47b 回归：`scroll` 动作之后，观测必须等偏移「落地」，不能读过渡帧。

病是量出来的，不是猜的（`m2/real-log.md` 17:3x 的读数）：产品用
`Input.dispatchMouseEvent(mouseWheel)` 发滚动（`browser.py:456`），Chrome 对这种合成 wheel
的处理时延是 **0.05~1.05s 的一次性跳变**（四个站：django 53/1027ms、rust 1046ms、
peps 1007/1040ms、rfc-editor 1012/1053ms；回顶 984~1024ms），落地前偏移一直是旧值。
而 `scroll` 不在 `SETTLE_CAPS_MS`（`browser.py:318`）里——那张表用的是 DOM 静默判据，
滚动根本不改 DOM，把它套在 scroll 上等于没等。于是 `agent.py:747` 动作后的复观察读到的是
**上一拍的视口**：r114 的 `SCROLL_TOP` 真的执行了，第 6 拍决策用的页指纹 `9892060c…`
却与回放里「y=2240（回顶之前）那一页」逐字相同 → 页头搜索框不在索引集 → 地板整体弃权 →
模型 BLOCKED（`logs/one-r114-1009-172047/r114.jsonl`）。

锁住四件事：
1. scroll 动作后多发一发 `Runtime.evaluate(awaitPromise)`，判据是「到 target 为止」——
   不能写成「偏移连续不变」，因为**未开始**与**已结束**在偏移曲线上长得一样（实测）。
2. 上限 = 实测最晚落地 1053ms + 采样误差 ≈120ms ⇒ 取 1500ms，且这个数字真的编进表达式。
3. 等待在 wheel **派发之后**，且只有 scroll 付这笔钱：click/fill 照旧走 DOM 静默那套，
   `SETTLE_CAPS_MS` 表不许被加进 scroll（仪器错了就换仪器，不扩表蒙过去）。
4. CDP 抛错（导航销毁上下文）时安静退回，不能把动作以外的错抛给主循环。

不连浏览器：`Browser.call` 整个换成记账替身（同 `tests/test_settle.py` 的 Recorder）。

运行：python tests/test_scroll_settle.py
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

    def exprs(self):
        return [p.get("expression", "") for _, p in self.calls]


def fake_browser(raise_on=None):
    b = B.Browser.__new__(B.Browser)
    b.session = "test-session"
    rec = Recorder(raise_on)
    b.call = rec.call
    return b, rec


def act(b, action):
    orig = B.browser_operation
    ops = []

    def fake_op(request):
        ops.append(request["operation"])
        return {"executed": request["action"]["id"]}

    B.browser_operation = fake_op
    b.fresh = lambda page, action=None: True
    try:
        b.act(action, {"page_key": ["1.0", "u", 0, 0, 1120, 780],
                       "guards": {}, "marker_stable": "m"})
    finally:
        B.browser_operation = orig
    return ops


SCROLL_DOWN = {"id": "scroll_down", "kind": "scroll", "label": "Scroll down",
               "delta": 560, "node": 900}
SCROLL_BOTTOM = {"id": "scroll_bottom", "kind": "scroll", "label": "Scroll to bottom",
                 "delta": 9999, "node": 901}


@case("① scroll 动作后必须多发一发「到落点为止」的等待")
def t_scroll_act_waits_for_landing():
    b, rec = fake_browser()
    act(b, SCROLL_DOWN)
    assert rec.calls, "改前实测：scroll 动作后一发 CDP 都不发，复观察读到过渡帧"
    method, params = rec.calls[-1]
    expr = params.get("expression", "")
    assert method == "Runtime.evaluate", f"落点等待必须是页内一等到底: {method}"
    assert params.get("awaitPromise") is True, "必须 awaitPromise，一次往返等到落点"
    assert "scrollY" in expr, f"没有读滚动偏移：{expr[:200]}"
    assert "Promise" in expr and "performance.now()" in expr, "不是有界等待"
    assert str(B.Browser.SCROLL_SETTLE_CAP_MS) in expr, "上限没编进表达式"


@case("② 判据是「到 target 为止」，不是「偏移连续不变」（未开始 == 已结束）")
def t_criterion_is_landing_target_not_stillness():
    b, rec = fake_browser()
    act(b, SCROLL_DOWN)
    expr = rec.exprs()[-1]
    assert "560" in expr, f"请求的 delta 没进表达式（等待不知道要滚到哪）：{expr[:200]}"
    for part in ("scrollHeight", "innerHeight"):
        assert part in expr, f"target 没有按可滚范围夹紧（缺 {part}）：{expr[:200]}"


@case("③ 滚到底（delta 9999）的 target 也必须夹紧，不许等一个到不了的位置")
def t_bottom_scroll_clamps():
    b, rec = fake_browser()
    act(b, SCROLL_BOTTOM)
    expr = rec.exprs()[-1]
    assert "9999" in expr and "scrollHeight" in expr, (
        f"滚到底没有夹紧到最大偏移：{expr[:220]}")


@case("④ 等待在 wheel 派发之后；click/fill 不付这笔钱")
def t_order_and_scope():
    b, rec = fake_browser()
    ops = act(b, SCROLL_DOWN)
    assert ops == ["act"], f"滚动动作没被执行：{ops}"
    scroll_exprs = [e for e in rec.exprs() if "scrollY" in e]
    assert len(scroll_exprs) == 1, f"一次滚动该只等一发，实发 {len(scroll_exprs)}"
    b2, rec2 = fake_browser()
    act(b2, {"kind": "click", "id": 3, "node": 3})
    assert not [e for e in rec2.exprs() if "scrollY" in e], "click 不该带落点等待"


@case("⑤ DOM 静默那张表不许被塞进 scroll（仪器错了就换仪器，不扩表）")
def t_settle_table_unchanged():
    assert set(B.Browser.SETTLE_CAPS_MS) == {"click", "select", "fill"}, (
        f"SETTLE_CAPS_MS 覆盖范围漂移：{B.Browser.SETTLE_CAPS_MS}")
    b, rec = fake_browser()
    b.await_action_settle("scroll")
    assert rec.calls == [], "scroll 的等待必须是独立仪器，不是套 DOM 静默判据"


@case("⑥ CDP 抛错时安静退回（导航销毁上下文由 observe 的 StalePage 重试接住）")
def t_swallow_errors():
    b, _ = fake_browser(raise_on="scrollY")
    act(b, SCROLL_DOWN)          # 不该抛


@case("⑦ 上限必须是量出来的数：实测最晚落地 1053ms + 采样误差 ≈120ms")
def t_cap_is_the_measured_number():
    cap = B.Browser.SCROLL_SETTLE_CAP_MS
    assert cap >= 1200, f"上限缩回亚秒会重新读到过渡帧（实测落地 1053ms）：{cap}"
    assert cap <= 2000, f"上限再长就是在「窗口不动」的页面上空烧时间：{cap}"


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)
