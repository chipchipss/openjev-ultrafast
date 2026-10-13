r"""#65 后半场：到站那一拍必须先重看一眼，才允许地板发 DONE。

实盘形状（`logs/real-1012-b37-100-1012-181811/r154.jsonl`，全文 3 条决策 + 2 条 step）：

    STEP 1  fill  TYPE_TEXT e38 -> dom_changed   docs.python.org/3/                 skill=search_type
    STEP 2  click CLICK   e40 -> url_changed     …/3/search.html?q=enumerate         skill=search_submit
    DECISION  DONE  conf 1.0  skill=goal_reached      ← 就是这一拍读的是 +781ms 那份 654 字符快照
    RESULT  FAIL  url_matches ok=True  /  text_contains "enumerate" ok=False

`goal_reached` 的证据是 **URL 的 query 回声**（skills.py 的 submit_verb 档："提交搜索"类 goal
的 `?q=` 就是成功判据本身）——判据没写错，错在**它拿到那份页时正文波还没到**：
`searchindex.js` 是 `<script>` 加载（页内 fetch/XHR 计数器看不见它），索引到手之后才轮到取正文
的两发 fetch（`m2/probe_navigation_timing.py` 的资源时间戳 + `m2/probe_network_waves.py`）。

改法只有一条，且**故意不用断言**：地板发 DONE 之前，若 ①上一拍确实是落地（`url_changed`）
②goal 自己点名的短语不在这一份正文里 ⇒ 付**一次**有界重看（等"短语出现"，不等"变长"），
然后用新页态重判；等不到也照旧放行。"用这一行有没有 text_contains 断言来决定等不等"我试过
并否掉——那等于把评分信息喂进决策层，破的是"断言永远不进 prompt、只做执行后核验"这条 pillar。

两版失败模式都留成了案子：
① 拿"重看期间正文有没有变长"当退出条件 ⇒ r154 实跑打回（live 697 vs 手里 654，43 字符的
   搜索框噪声就让它提前退出，重新观测还是同一份 654）——`dbg` 原文：
   `arrival_relook: graded=654 live=697 fresh=654`；
② 换成"等 goal 短语出现在 live"之后，cap 必须有出处：两支零模型探针里 docs 族 `t_text`
   是 4.6–8.9 秒 ⇒ `ARRIVAL_RELOOK_CAP_MS = 6000`。

跑法与耗时：两案会真付到 cap（各约 6 秒），整套约 15 秒。

运行：python tests/test_arrival_reobserve.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import skills as S                                  # noqa: E402
from jev_ultrafast.agent import ARRIVAL_RELOOK_CAP_MS, _done_guard     # noqa: E402
from jev_ultrafast.browser import StalePage                            # noqa: E402

CASES = []

GOAL = "Search the Python documentation for 'enumerate' and reach its search results page."
URL = "https://docs.python.org/3/search.html?q=enumerate"
START = "https://docs.python.org/3/"

SHELL_TEXT = ("Python documentation\n\nSearch Docs\n\n" + "nav shell text " * 45)
RESULTS_TEXT = SHELL_TEXT + "\nResults for enumerate — showing 1-10 of 810\n" + "enumerate entry " * 90


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def short_page():
    return {"url": URL, "start_url": START, "title": "Search - Python 3.15.0 documentation",
            "text": SHELL_TEXT, "fingerprint": "f-short", "elements": []}


def grown_page():
    return {"url": URL, "start_url": START, "title": "Search - Python 3.15.0 documentation",
            "text": RESULTS_TEXT, "fingerprint": "f-grown", "elements": []}


def submit_history(outcome="url_changed"):
    return [{"step": 1, "kind": "click", "operation": "CLICK", "url": URL, "url_from": START,
             "page_changed": True,
             "outcome": {"status": outcome, "url_changed": outcome == "url_changed",
                         "page_changed": True},
             "skill": "search_submit"}]


class FakeBrowser:
    """只把"会动浏览器的那条缝"假掉。

    `missing` = 每次探测时 live DOM 里还缺几个 goal 短语（0 = 已出现）；
    `pages` = 重观测依次返回的页态。计数器告诉我它到底重看没重看——这一刀要证的是
    "程序实际做了什么"，所以不拿源码文本当证据。
    """

    def __init__(self, pages=None, missing=None, raise_observe=False, raise_evaluate=False):
        self.pages = list(pages or [])
        self.missing = list(missing or [])
        self.observes = 0
        self.evaluates = 0
        self.raise_observe = raise_observe
        self.raise_evaluate = raise_evaluate

    def evaluate(self, expression):
        self.evaluates += 1
        if self.raise_evaluate:
            raise StalePage("document changed during evaluate")
        assert "needles" in expression, f"探针表达式不是我预期的那个：{expression[:60]}"
        # 解析它到底拿哪些短语去 live DOM 里找——短语必须来自 goal，不是断言
        needles = json.loads(expression.split("})(")[1].rstrip(");"))
        assert needles == ["enumerate"], f"喂给 live 的短语不对：{needles}"
        if self.missing:
            return self.missing.pop(0)
        return 0

    def observe(self, screenshot=True):
        self.observes += 1
        if self.raise_observe:
            raise StalePage("document changed during observe")
        if self.pages:
            return self.pages.pop(0)
        return short_page()


def guard_with(browser, page=None, outcome="url_changed"):
    """跑真实的守卫路径：先让 goal_reached 发 DONE，再交给 _done_guard 判。"""
    page = page or short_page()
    hist = submit_history(outcome)
    d = S.goal_reached(page, GOAL, hist)
    assert d is not None and d["choice"] == "DONE", "夹具坏了：短页上 goal_reached 不再开火"
    state = {"goal": GOAL, "page": page, "history": hist}
    if browser is not None:
        state["browser"] = browser
    return d, state, _done_guard(d, state)


@case("前提①：实盘形状能离线复现——短页上地板发 DONE，老形状（没有 browser）当场放行")
def t_short_page_done_is_currently_accepted():
    _d, _state, reason = guard_with(None)
    assert reason is None, f"前提不成立（改前就该放行）：{reason}"


@case("前提②：短页确实不含 goal 的短语，而渲染完那份确实含——差别只在正文波")
def t_the_two_snapshots_differ_only_by_render():
    assert "enumerate" not in short_page()["text"].lower()
    assert "enumerate" in grown_page()["text"].lower()
    assert len(grown_page()["text"]) > len(short_page()["text"]) + 500


@case("#65 正身：刚落地且短语缺 ⇒ 放行之前付一次有界重看，并用新页态重判")
def t_guard_relooks_before_it_accepts():
    fake = FakeBrowser(pages=[grown_page()], missing=[1, 0])
    t0 = time.monotonic()
    _d, state, reason = guard_with(fake)
    assert fake.observes >= 1, (
        "改前的形状：地板在 +781ms 那份 654 字符快照上直接发 DONE，一次都没重看——"
        "这正是 r154/r156/r157/r158 三轮全卡的病")
    assert reason is None, f"重看之后 DONE 仍被拒（不该）：{reason}"
    assert state["page"]["fingerprint"] == "f-grown", \
        "state['page'] 没换成重看后的页态，下一拍还会读同一份残帧"
    assert time.monotonic() - t0 < ARRIVAL_RELOOK_CAP_MS / 1000.0 + 1.5, "超出了那一次等待的预算"


@case("退出条件必须是「短语出现」而不是「正文变长」：live 比手里长 43 字符不算渲染完成")
def t_growth_is_not_the_signal():
    # missing 一直为 1 ⇒ 第一版那种"live 697 > graded 654 就退出"的写法会提前收工；
    # 现在必须一路等到 cap，取回那份还是 654 的页，并且**不**因此改判失败。
    fake = FakeBrowser(pages=[short_page()], missing=[1] * 40)
    t0 = time.monotonic()
    _d, _state, reason = guard_with(fake)
    waited = time.monotonic() - t0
    assert waited * 1000 > ARRIVAL_RELOOK_CAP_MS * 0.7, (
        f"只等了 {waited:.2f} 秒就退出 ⇒ 又在拿「变长」当信号（cap 是 {ARRIVAL_RELOOK_CAP_MS}ms）")
    assert reason is None, f"等不到也须放行（只加一次看，不加否决权）：{reason}"


@case("r154 的实跑形状：手里那份快照是旧的，而 DOM 早就渲染完了")
def t_stale_graded_page_is_replaced():
    fake = FakeBrowser(pages=[grown_page()], missing=[0])
    _d, state, reason = guard_with(fake)
    assert reason is None, f"DONE 被拒（不该）：{reason}"
    assert state["page"]["fingerprint"] == "f-grown", \
        "手里还是那份 654 的残帧就被拿去评了——text_len 实测会停在半帧长度"


@case("付了多少必须落到 state —— b38 的代价要靠它数，不能靠墙钟差猜")
def t_paid_ms_is_accumulated_on_state():
    """第一版写的是 `state["history"][-1]["arrival_relook_ms"]`，而那条 step 早就 flush 了
    ⇒ b38 数出"0 行付费"的假零（同一行 r154 明明 PASS）。所以现在累加到 state，
    由 logger.finalize 写进行末的 task_result。"""
    fake = FakeBrowser(pages=[grown_page()], missing=[1, 0])
    _d, state, reason = guard_with(fake)
    assert reason is None
    paid = state.get("arrival_relook_ms")
    assert isinstance(paid, int) and paid >= 0, f"state 上没有可入账的付费记录：{paid!r}"


@case("同一行最多付一次：第二次 DONE 不许再重看（防新死循环）")
def t_relook_is_paid_at_most_once():
    fake = FakeBrowser(pages=[grown_page(), grown_page()], missing=[1, 0])
    _d, state, reason1 = guard_with(fake)
    n_after_first = fake.observes
    assert n_after_first == 1, f"第一次应当只重看一次，实际 {n_after_first}"
    _d2, _s2, reason2 = guard_with(fake, page=state["page"])
    assert reason2 is None, f"第二次 DONE 被拒：{reason2}"
    assert fake.observes == n_after_first, (
        f"latch 没生效：第二次又重看了（{n_after_first} -> {fake.observes}）")
    assert _s2.get("arrival_relook_ms") in (None, 0) or state.get("arrival_relook_ms") ==         _s2.get("arrival_relook_ms"), "第二次又付了一遍钱（latch 只挡住了观测，没挡住计时）"


@case("触发面要窄：提交过、但最后一步不是落地 ⇒ 不许付这笔钱")
def t_only_pays_on_the_landing_tick():
    """历史里第一拍是提交（url_changed，规则 5 的提交证据），最后一拍只是在同一页上
    点了个 dom 级变化 —— 那不是"刚落地"，重看它没有意义，批墙钟也付不起。"""
    fake = FakeBrowser(pages=[grown_page()], missing=[0])
    hist = [
        {"step": 1, "kind": "click", "operation": "CLICK", "url": URL, "url_from": START,
         "page_changed": True,
         "outcome": {"status": "url_changed", "url_changed": True, "page_changed": True},
         "skill": "search_submit"},
        {"step": 2, "kind": "click", "operation": "CLICK", "url": URL, "url_from": URL,
         "page_changed": True,
         "outcome": {"status": "dom_changed", "url_changed": False, "page_changed": True},
         "skill": "explicit_target"},
    ]
    d = S.goal_reached(short_page(), GOAL, hist)
    assert d is not None, "前提：这一份短页上到达判据照旧开火"
    state = {"goal": GOAL, "page": short_page(), "history": hist, "browser": fake}
    reason = _done_guard(d, state)
    assert reason is None, f"这拍本该照常放行，却被拒：{reason}"
    assert fake.observes == 0, (
        f"不是落地那一拍也去重看了（observes={fake.observes}）——批墙钟会被无谓的等待顶起来")


@case("DONE 出自 link_followed_arrival ⇒ 一分钱都不付（b39 实测 3 行各白花 6 秒）")
def t_link_arrival_done_does_not_pay():
    """r126 的真实形状：goal 点名的 'SQL Syntax' 是**起点页那条链的标签**，落地页
    `lang.html` 的正文里出现 0 次（#59 造这档判据的原因，见 m2/fixtures/r126_arrival.json）。
    等它是白等 —— 收窄之前 b39 里 r126/r172/r177 就是这么各付满 6 秒 cap 的。"""
    page = json.loads((REPO / "m2" / "fixtures" / "r126_arrival.json").read_text(encoding="utf-8"))
    goal = "From the SQLite home page, open the 'SQL Syntax' page."
    hist = [{"step": 1, "kind": "click", "action": "SQL Syntax",
             "operation": "CLICK", "url": page["url"],
             "url_from": "https://www.sqlite.org/", "page_changed": True,
             "outcome": {"status": "url_changed", "url_changed": True, "page_changed": True},
             "skill": "explicit_target"}]
    d = S.link_followed_arrival(page, goal, hist)
    assert d is not None and d["choice"] == "DONE", "前提：这一档在 r126 的落地页上照旧开火"
    fake = FakeBrowser(pages=[grown_page()], missing=[0])
    state = {"goal": goal, "page": page, "history": hist, "browser": fake,
             "start_url": "https://www.sqlite.org/"}
    reason = _done_guard(d, state)
    assert reason is None, f"DONE 本该照常放行：{reason}"
    assert fake.observes == 0, (
        f"链标签类收口去重看了（observes={fake.observes}, paid={state.get('arrival_relook_ms')}）"
        "——那个短语永远不会出现在落地页正文里，等的就是纯浪费")


@case("只降级不升级：evaluate / observe 撞 StalePage 都不许把一行崩成 error")
def t_relook_failures_degrade_quietly():
    for kwargs in ({"raise_evaluate": True}, {"raise_observe": True}):
        fake = FakeBrowser(pages=[grown_page()], missing=[1, 0], **kwargs)
        try:
            _d, _state, reason = guard_with(fake)
        except Exception as e:                                  # noqa: BLE001
            raise AssertionError(f"{list(kwargs)} 情形下守卫抛出异常（必须只降级）：{e}") from e
        assert reason is None, f"{list(kwargs)} 情形下 DONE 被拒（不该）：{reason}"


@case("cap 是硬上界：live 永远缺短语时最多付 cap，不许变成无限等")
def t_cap_bounds_the_wait():
    fake = FakeBrowser(pages=[short_page()], missing=[1] * 300)
    t0 = time.monotonic()
    _d, _state, reason = guard_with(fake)
    dt = time.monotonic() - t0
    assert reason is None
    assert dt < ARRIVAL_RELOOK_CAP_MS / 1000.0 + 1.5, f"重观测付了 {dt:.2f} 秒，超预算"


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
