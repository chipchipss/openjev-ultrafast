"""Fix O 的两条回归（n004 三轮冻结里 rounds 2/3 的真因，见 m2/real-log.md）。

① 提交搜索是**整页导航**：在途计数补丁装在旧 document 上，随导航一起消失，
   于是 `_await_settle` 里 `reqBusy` 恒为假，只看 DOM 静默 120ms 就放行观测 ——
   结果行还没异步渲染就被看了（零模型探针：提交后 t=0 27 actions/0 行，+1.0s 32/1）。
   修法是把同一份补丁注册成 `Page.addScriptToEvaluateOnNewDocument`，让它活过导航。
② `search_submit` 的去重只看历史（`last_sub > last_fill`），结果页上模型把 query
   **重填**一次就把这个判据重置，而同一个按钮重新编号（e15→e10）又绕过"id 已点过"，
   于是地板再交一次 → URL 掉回 `/search/`（query 丢了）→ 任务在预算耗尽时收场。
   修法加一条**页态**判据：当前 URL 已经带着本次 query，就说明搜索已经跑过了。

两条都必须**在改前代码上失败**（纪律：单测要先证明旧代码会错）。

运行：python tests/test_fix_o.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse  # noqa: F401  (对照用)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import browser as B  # noqa: E402
from jev_ultrafast import skills as S  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


class Recorder:
    """替掉 Browser.call：只记账，不连浏览器。"""

    def __init__(self):
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, params))
        return {"result": {"value": 1}}


def fake_browser():
    b = B.Browser.__new__(B.Browser)
    b.session = "test-session"
    b.rec = Recorder()
    b.call = b.rec.call
    return b


@case("在途计数补丁注册成 new-document 脚本（活过整页导航）")
def test_patch_survives_navigation():
    b = fake_browser()
    b._settle_patch()
    b._settle_patch()          # 幂等：第二次不该重复注册
    methods = [m for m, _ in b.rec.calls]
    assert "Page.addScriptToEvaluateOnNewDocument" in methods, (
        f"补丁只装在当前 document（{methods}）——整页导航后 window.__jevSettle 消失，"
        "reqBusy 恒假，观测会跑在异步结果渲染前面")
    reg = [p for m, p in b.rec.calls if m == "Page.addScriptToEvaluateOnNewDocument"]
    assert len(reg) == 1, f"new-document 脚本注册了 {len(reg)} 次，应幂等"
    assert "__jevSettle" in reg[0].get("source", ""), "注册的脚本不是那份在途计数补丁"


@case("URL 已含本次 query 时不再重交搜索（n004 round 1331 的第 5 拍）")
def test_search_submit_skips_when_query_already_in_url():
    # 逐字照抄失败轮的形态：首页填 query → 交 → 模型在结果页把同一句**重填**，
    # 于是历史判据（last_sub>last_fill）失效，而按钮换成了 e10。
    goal = "Search the RFC Editor for 'RFC 9110' and open the document page."
    history = [
        {"kind": "fill", "choice": "e13", "action": "Find an RFC (number, title, author)", "text": "RFC 9110"},
        {"kind": "click", "choice": "e15", "action": "Submit search"},
        {"kind": "click", "choice": "e5", "action": "Search"},
        {"kind": "fill", "choice": "e8", "action": "Search RFCs", "text": "RFC 9110"},
    ]
    results_page = {
        "url": "https://www.rfc-editor.org/search/?q=RFC+9110",
        "actions": [
            {"id": "e8", "kind": "fill", "label": "Search RFCs", "value": "RFC 9110"},
            {"id": "e10", "kind": "click", "label": "Submit search", "role": "button"},
        ],
    }
    d = S.search_submit(results_page, goal, history)
    assert d is None, (
        f"地板在第 5 拍又交了一次（{d}）—— 实测这一交把 URL 打回 /search/、"
        "query 丢失，成功的结果页被毁掉")


@case("没交过的搜索照旧要交（守卫不许把第一次提交也关掉）")
def test_search_submit_still_fires_first_time():
    goal = "Search the RFC Editor for 'RFC 9110' and open the document page."
    history = [{"kind": "fill", "choice": "e13",
                "action": "Find an RFC (number, title, author)", "text": "RFC 9110"}]
    home_page = {
        "url": "https://www.rfc-editor.org/",
        "actions": [
            {"id": "e13", "kind": "fill", "label": "Find an RFC (number, title, author)", "value": "RFC 9110"},
            {"id": "e15", "kind": "click", "label": "Submit search", "role": "button"},
        ],
    }
    d = S.search_submit(home_page, goal, history)
    assert d is not None and d.get("choice") == "e15", f"第一次提交被守卫误杀：{d}"


@case("结果页上换了新 query 仍允许再交（守卫只拦同一句已被提交过）")
def test_search_submit_allows_revised_query():
    goal = "Search the RFC Editor for 'RFC 9110' and open the document page."
    history = [
        {"kind": "fill", "choice": "e13", "action": "Find an RFC", "text": "RFC 9110"},
        {"kind": "click", "choice": "e15", "action": "Submit search"},
        {"kind": "fill", "choice": "e8", "action": "Search RFCs", "text": "RFC 9110bis"},
    ]
    page = {
        "url": "https://www.rfc-editor.org/search/?q=RFC+9110",
        "actions": [
            {"id": "e8", "kind": "fill", "label": "Search RFCs", "value": "RFC 9110bis"},
            {"id": "e10", "kind": "click", "label": "Submit search", "role": "button"},
        ],
    }
    d = S.search_submit(page, goal, history)
    assert d is not None and d.get("choice") == "e10", f"改了查询词之后不该被拦：{d}"


@case("提交后的那一次观测，在**要读的那个 document 上**再等一次归静（导航销毁 act 时的 settle）")
def test_observe_settles_after_action():
    b = fake_browser()
    settles = []
    b._await_settle = lambda cap_ms, floor_ms=0, quiet_ms=None: settles.append(cap_ms)
    orig = B.browser_operation
    try:
        B.browser_operation = lambda req: {"marker": "m", "marker_stable": "s",
                                           "url": "https://x/", "text": "", "actions": [],
                                           "scroll": {}, "page_key": [1, "u", 0, 0, 1, 1],
                                           "guards": {}, "screenshot": None}
        b.after_input = {"kind": "click", "node": 1}
        b.observe(screenshot=False)
    finally:
        B.browser_operation = orig
    assert settles, ("act() 之后的 settle 在整页导航时会被 `except Exception: pass` 吞掉"
                     "（上下文销毁），而 observe 只会重试「读」、不等「渲染」 —— "
                     "n004 实测：第 3 拍观测没有结果行，地板弃权，模型重交一次")
    assert settles[0] == B.Browser.SETTLE_CAPS_MS["click"]
    # 对照组：wait 之后本来就没有要等的渲染 —— 第二次观测不该再等
    b2 = fake_browser()
    got2 = []
    b2._await_settle = lambda cap_ms, floor_ms=0, quiet_ms=None: got2.append(cap_ms)
    try:
        B.browser_operation = lambda req: {"marker": "m", "marker_stable": "s",
                                           "url": "https://x/", "text": "", "actions": [],
                                           "scroll": {}, "page_key": [1, "u", 0, 0, 1, 1],
                                           "guards": {}, "screenshot": None}
        b2.after_input = {"kind": "wait", "node": 1}
        b2.observe(screenshot=False)
    finally:
        B.browser_operation = orig
    assert not got2, f"wait 之后不该再 settle（等的是动作渲染，不是无动作）：{got2}"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}\n       {e}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
