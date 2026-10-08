"""b10 实况回归：`page_not_ready` 的 WAIT 必须有上限，撞顶不许抛异常。

b10 的 r107（logs/real-1008-b10-fixp-1008-172503/r107.jsonl，60 步 / 22.6s）：
  步#1 `first_action_floor CLICK e117` 在 HN 首页抓了一条新闻外链，落到
  `https://dat-ecosystem.org/`；那张页观测回来**既无正文也无可交互元素**
  （代理下没渲染出来），于是 步#2–#60 全是 `page_not_ready` 的 WAIT
  ——conf 1.0、latency 0、page_changed=False，各拍照记，一路记到 59 次"没效果"。
收口不是判据收的，是 `agent.py:650-651` 的硬上限：
  `ValueError: Stopped at the 60-action demo budget` 从 `run()` 生成器逃逸，
runner 把它同时写成 `error=agent_loop_raised` **和** `result=FAIL /
failure_mode=decision`，于是那一轮的 summary 报 error=0。

为什么守卫没拦住：WAIT 被**所有**停滞守卫排除（`agent.py:220/240/260`
——"wait 不是动作"），而 `agent.py:258` 的注释假设"wait 的上限由技能侧的
`_can_wait` 兜底"。这个假设对 `page_not_ready` 不成立：`skills.py:181` 直接
`return _wait("page_not_ready")`，从没调用 `_can_wait`（同文件的
`entity_confirm` 在 1314/1323 行是调了的）。

同一形状的账在前一档就有过：`page_not_ready` 的注释里写着 f002 曾因
httpbin 回显页"连等 57 拍撞上 60 步上限"，当时的修法是"有正文就不算没渲染"；
**没渲染的空白页那一半仍然无界**。

不连浏览器、不调模型。

运行：python tests/test_wait_bound.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import agent as A  # noqa: E402
from jev_ultrafast import skills as S  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def wait_row() -> dict:
    return {"action": "wait", "kind": "wait", "operation": "WAIT",
            "target": None, "page_changed": False, "outcome": {"status": "wait_no_change"}}


def blank_page(url: str = "https://example.org/") -> dict:
    """观测里只有合成控件（scroll/reload/wait）、正文为空 —— page_not_ready 的触发面。"""
    return {
        "url": url, "title": "", "text": "",
        "actions": [{"id": "scroll_down", "kind": "scroll", "label": "Scroll down"},
                    {"id": "wait", "kind": "wait", "label": "Wait"}],
        "guards": {}, "fingerprint": "blankfp", "marker": "m", "marker_stable": 1,
        "page_key": [1.0, url, 0, 0, 1120, 780],
        "scroll": {"y": 0, "height": 900}, "w": 1120, "h": 780, "omitted_actions": 0,
    }


def text_page() -> dict:
    p = blank_page()
    p["text"] = "hello world"
    return p


# --- 技能层：判据本身 -------------------------------------------------------

@case("起始页不触发（空白页交给 predict 的重试逻辑）")
def _():
    return S.page_not_ready(blank_page(), "Open the newest stories page.", []) is None


@case("第一拍仍该等（正向对照，别把技能缴械）")
def _():
    d = S.page_not_ready(blank_page(), "Open the newest stories page.",
                         [{"action": "click", "kind": "click", "page_changed": True}])
    return isinstance(d, dict) and d.get("skill") == "page_not_ready"


@case("连续 wait 到上限后必须让位（r107 的形状：59 拍无界）")
def _():
    hist = [{"action": "click", "kind": "click", "page_changed": True}]
    hist = hist + [wait_row() for _ in range(S.PAGE_NOT_READY_MAX_WAITS + 2)]
    return S.page_not_ready(blank_page(), "Open the newest stories page.", hist) is None


@case("上限之前不许提前弃权（bounded，但不是 1 拍就放手）")
def _():
    hist = [{"action": "click", "kind": "click", "page_changed": True}]
    hist = hist + [wait_row() for _ in range(max(1, S.PAGE_NOT_READY_MAX_WAITS - 2))]
    d = S.page_not_ready(blank_page(), "Open the newest stories page.", hist)
    return isinstance(d, dict) and d.get("skill") == "page_not_ready"


@case("有正文、零可交互元素 = 内容页，不等待（f002 的既有语义不许动）")
def _():
    return S.page_not_ready(text_page(), "Post hello world and read the echo.",
                            [wait_row(), wait_row()]) is None


@case("滚到可见类目标让位给模型（l004 的既有语义不许动）")
def _():
    return S.page_not_ready(blank_page(),
                            "Scroll down the list until Product 40 is visible.",
                            [{"action": "scroll", "kind": "scroll", "page_changed": True}]) is None


# --- 循环层：撞顶不许把异常抛给 runner -------------------------------------

class BlankAfterClickBrowser:
    """r107 的世界：起始页有一条可点链接，点完就落到一张永远空白的页。"""

    def __init__(self):
        home = blank_page("https://news.ycombinator.com/")
        home["text"] = "front page"
        home["actions"] = [{"id": "e1", "kind": "click", "node": 8, "role": "link",
                            "label": "Some story", "value": ""}] + home["actions"]
        home["fingerprint"] = "fp-home"
        self.reality = home
        self.blank = blank_page("https://dat-ecosystem.org/")
        self.acted = []
        self.closed = False

    def observe(self, screenshot=True):
        return dict(self.reality)

    def act(self, action, page, text=None):
        self.acted.append(action)
        if action.get("kind") == "click":
            self.reality = self.blank

    def fresh(self, page, action=None):
        return page["fingerprint"] == self.reality["fingerprint"]

    def close(self):
        self.closed = True


def _run_blank_loop():
    """跑一轮"点进去就永远空白"的世界，返回 (status, len(history), 逃逸的异常或 None)。"""
    escaped = None
    real_browser, real_choose, real_sleep = A.Browser, A.choose, A.time.sleep
    A.Browser = lambda *a, **k: BlankAfterClickBrowser()
    A.time.sleep = lambda *a, **k: None

    def choose(page, goal, history):
        # 真实管线里 skills.route 永远先跑（model.py:458），所以桩必须保留技能层，
        # 只把"模型那一半"换成弃权 —— r107 的 59 拍 WAIT 全是技能发的，不是模型。
        hit = S.route(page, goal, history)
        if hit is not None:
            return hit
        links = [a for a in page["actions"] if a.get("kind") == "click"]
        if links:                                  # 模拟地板的第一跳（r107 步#1）
            a = links[0]
            return {"choice": a["id"], "operation": "CLICK", "target": "1",
                    "operation_confidence": 1.0, "target_confidence": 1.0,
                    "confidence": 1.0, "probabilities": {a["id"]: 1.0},
                    "latency_ms": 0, "usage": None, "skill": None, "reason": "stub"}
        return {"choice": "BLOCKED", "operation": "BLOCKED", "target": None,
                "operation_confidence": 0.6, "target_confidence": None, "confidence": 0.6,
                "probabilities": {"BLOCKED": 1.0}, "latency_ms": 1, "usage": None,
                "skill": None, "reason": "stub"}

    A.choose = choose
    try:
        ag = A.Agent(url="https://news.ycombinator.com/", goals="Open the newest stories page.")
        for _ in ag.run():
            pass
        status, hist = ag.state.get("status"), ag.state.get("history", [])
    except Exception as e:                                  # noqa: BLE001
        status, hist, escaped = type(e).__name__, [], e
    finally:
        A.Browser, A.choose, A.time.sleep = real_browser, real_choose, real_sleep
    return status, len(hist), escaped


@case("空白世界的收口：不抛异常、干净 blocked（r107 是 ValueError 逃逸）")
def _():
    status, n, escaped = _run_blank_loop()
    return escaped is None and status in {"blocked", "done"}


@case("同一世界的 WAIT 拍数必须有界（旧行为连等 59 拍撞 60 硬顶）")
def _():
    _, n, escaped = _run_blank_loop()
    return escaped is None and n <= 10


# --- runner 层：崩了的行必须算进 error，不许藏进 FAIL -----------------------

def _fail_row_with_error():
    from m1.run_tasks import _summarize
    return _summarize([{
        "task_id": "r107",
        "error": "agent_loop_raised",
        "result": {"task_id": "r107", "result": "FAIL", "quadrant": "true_failure",
                   "failure_class": "agent", "failure_mode": "decision", "meta": {}},
    }])


@case("崩溃行与 FAIL 并存时 summary.error 必须数到它（旧行为报 error=0）")
def _():
    s = _fail_row_with_error()
    return s["error"] == 1 and s["fail"] == 1


@case("对照：没有任何 error 字段的一批，error 仍是 0")
def _():
    from m1.run_tasks import _summarize
    s = _summarize([{"task_id": "x001",
                     "result": {"task_id": "x001", "result": "PASS",
                                "quadrant": "true_success"}}])
    return s["error"] == 0 and s["pass"] == 1


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            ok = fn()
        except Exception as e:                              # noqa: BLE001
            if isinstance(e, AssertionError):
                ok = False
            elif "PAGE_NOT_READY_MAX_WAITS" in str(e):
                print(f"FAIL  {name}\n      skills.PAGE_NOT_READY_MAX_WAITS 还不存在（无界 WAIT 未修）")
                failed += 1
                continue
            else:
                print(f"ERROR {name}\n      {type(e).__name__}: {e}")
                failed += 1
                continue
        if ok:
            print(f"ok    {name}")
        else:
            print(f"FAIL  {name}")
            failed += 1
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
