"""技能层回归测试。

每个用例都对应一次**真实发生过的回归**（编号见 skills.py 的缺陷注释），
不是覆盖率凑数 —— 去掉其中任何一条，对应的 bug 都会重新溜过去。

运行：python tests/test_skills.py        （无需 pytest）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import skills as S                      # noqa: E402
from jev_ultrafast.decision_validator import validate as V  # noqa: E402

GOAL = ("Find one-way flights from Zurich to London on October 21, 2026, "
        "for one adult in economy. Stop when matching flight options are visible. "
        "Do not select or book a flight.")

# 快照总会追加的合成控件（scroll/reload/wait）——判"页面空白"时必须忽略它们。
SYNTH = [{"id": "scroll_down", "node": 90, "kind": "scroll", "label": "Scroll down"},
         {"id": "scroll_up", "node": 91, "kind": "scroll", "label": "Scroll up"},
         {"id": "reload", "node": 92, "kind": "reload", "label": "Reload the page"},
         {"id": "wait", "node": 93, "kind": "wait", "label": "Wait for the page to update"}]


def A(i, kind, label, node, **kw):
    d = {"id": f"e{i}", "node": node, "kind": kind, "label": label}
    d.update(kw)
    return d


def page(actions, url="https://www.google.com/travel/flights"):
    return {"url": url, "actions": list(actions) + list(SYNTH)}


def fixture(name):
    """读真实站快照（`m2/fixtures/`，由 `m2/probe_r104_fixture.py` 一类零模型探针抓）。

    为什么需要它：手写的页面快照只能表达**我以为**的形状。r104 的病恰恰是"结果行在
    动作表里的位置/标签/href 形状"我写不出来（引文行 href 是相对的 `/36970624/`，
    标签里带断裂的空格和连字符）。快照进仓后，这条用例离线、确定性、不碰浏览器。
    """
    path = Path(__file__).resolve().parent.parent / "m2" / "fixtures" / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def waits(n):
    return [{"step": i, "kind": "wait", "action": "Wait for the page to update",
             "choice": "wait"} for i in range(1, n + 1)]


def form(dep_value, extra=()):
    return page([A(1, "fill", "Where from?", 11, value="Zürich"),
                 A(2, "fill", "Where to?", 12, value="London"),
                 A(3, "fill", "Departure", 13, value=dep_value),
                 A(4, "click", "Search", 14)] + list(extra))


RESULTS_URL = "https://www.google.com/travel/flights/search?tfs=CBwQAhoo"
SEARCH_HIST = [{"step": 1, "kind": "click", "action": "Search", "choice": "e22"}]


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------
# 缺陷#34 撞号：id 每次观测重排，跨字段撞号会把"没点过的城市候选"当成"已点过"
# （修复前：目的地被确认为机场，或整轮落到模型，每次 3~5s）
# --------------------------------------------------------------------------
@case("缺陷#34 entity_confirm 撞号时仍选城市候选")
def t_collision_city():
    p = page([A(4, "click", "London, United Kingdom", 44, role="option"),
              A(5, "click", "London Stansted Airport (STN)", 45, role="option")])
    h = [{"step": 3, "kind": "click", "action": "Zürich, Switzerland", "choice": "e4"},
         {"step": 4, "kind": "fill", "action": "Where to?", "choice": "e17", "text": "London"}]
    d = S.entity_confirm(p, GOAL, h)
    assert d is not None, "城市候选被撞号跳过 → 技能让位模型"
    assert d["operation"] == "CLICK" and d["skill"] == "entity_confirm"
    assert V(d, p).valid
    target = next(a for a in p["actions"] if a["id"] == d["choice"])
    assert "Airport" not in target["label"], "选中了机场级候选"


# --------------------------------------------------------------------------
# v114/v117：页面还在导航（观察里只有合成控件）→ 技能全落空 → 模型在空白页上
# 选了 BLOCKED，整轮 3.3s 收口 0/7
# --------------------------------------------------------------------------
@case("v114 空白页 → 等一拍而不是让位模型")
def t_blank_page():
    blank = page([])
    h = [{"step": 1, "kind": "click", "action": "Change ticket type. Round trip",
          "choice": "e12"}]
    d = S.page_not_ready(blank, GOAL, h)
    assert d is not None and d["operation"] == "WAIT"
    assert V(d, blank).valid
    assert S.page_not_ready(blank, GOAL, []) is None, "起始页不该由本技能接管"
    assert S.page_not_ready(page([A(1, "click", "One way", 1)]), GOAL, h) is None


# --------------------------------------------------------------------------
# v103：阶段 a 的滚动在"还没确认出发地"时就触发 → 把建议列表滚没，13 步 blocked
# --------------------------------------------------------------------------
@case("v103 阶段 a 滚动要求 from/to 都已填好")
def t_scroll_guard():
    one = page([A(1, "fill", "Where from?", 11, value="Zürich")])
    two = page([A(1, "fill", "Where from?", 11, value="Zürich"),
                A(2, "fill", "Where to?", 12, value="London")])
    assert S.date_pick(one, GOAL, []) is None, "只填了出发地就滚动"
    d = S.date_pick(two, GOAL, [])
    assert d is not None and d["operation"] == "SCROLL_DOWN"


# --------------------------------------------------------------------------
# 日历滚过头（实测滚到 Nov~Dec，目标 Oct 21 反而在视野外）→ 必须能往回滚
# --------------------------------------------------------------------------
@case("日历滚过头 → SCROLL_UP（方向按可见日期判）")
def t_calendar_direction():
    base = [{"step": 1, "kind": "click", "action": "Departure", "choice": "e20"}] + waits(6)
    after = page([A(1, "click", "Thursday, October 8, 2026", 51, role="gridcell")])
    before = page([A(1, "click", "Friday, November 6, 2026", 51, role="gridcell")])
    assert S.date_pick(after, GOAL, base)["operation"] == "SCROLL_DOWN"
    assert S.date_pick(before, GOAL, base)["operation"] == "SCROLL_UP"


# --------------------------------------------------------------------------
# 缺陷#32：日期已设但选择器仍开着 → 表单级 Done 被遮住，技能返回 None 就落到模型
# --------------------------------------------------------------------------
@case("缺陷#32 日期已设 + 面板开着 → 收起面板")
def t_close_picker():
    p = page([A(1, "fill", "Departure", 51, value="Wed, Oct 21"),
              A(2, "click", "Open Departure", 52),
              A(3, "click", "Wednesday, November 4, 2026", 53, role="gridcell")])
    h = [{"step": 1, "kind": "click", "action": "Wednesday, October 21, 2026",
          "choice": "e42"}]
    d = S.date_pick(p, GOAL, h)
    assert d is not None and d["operation"] == "CLICK"
    assert d["choice"] != "e42", "不该重复点同一个已点过的元素"


# --------------------------------------------------------------------------
# v128~v130：表单级 Done 的标签含 "departing" → 被 _DATE_FIELD_RE 误判成
# "刚点过日期字段" → 每轮多一次 "Open Departure" + 其后数拍等待
# --------------------------------------------------------------------------
@case("v128 Done 按钮的 departing 不算日期字段")
def t_departing_not_date_field():
    assert not S._DATE_FIELD_RE.search(
        "Done. Search for one-way flights, departing on October 22, 2026")
    assert S._DATE_FIELD_RE.search("Departure")
    assert S._DATE_FIELD_RE.search("Open Departure")


# --------------------------------------------------------------------------
# 缺陷#33：字段填好后 Google 把按钮文案缩成 "Search"；裸 Search 需要 filled>=3
# 兜底，否则 from/to 刚填完就提前提交
# --------------------------------------------------------------------------
@case("缺陷#33 裸 Search 需 3 个字段；长文案 2 个即可")
def t_search_label():
    bare2 = page([A(1, "fill", "Where from?", 11, value="Zürich"),
                  A(2, "fill", "Where to?", 12, value="London"),
                  A(3, "click", "Search", 13)])
    assert S.search_submit(bare2, GOAL, []) is None, "裸 Search 在只有 2 个字段时提交"
    d = S.search_submit(form("Wed, Oct 21"), GOAL, [])
    assert d is not None and d["skill"] == "search_submit"


# --------------------------------------------------------------------------
# 缺陷#36：goal 指定了日期时，日期字段必须已经是那天才允许提交
# （v121 带着非目标日期提交，此后等多久、重载多少次都拿不到目标结果）
# --------------------------------------------------------------------------
@case("缺陷#36 日期不对/为空 → 不提交")
def t_date_guard():
    assert S.search_submit(form("Thu, Oct 22"), GOAL, []) is None
    assert S.search_submit(form(""), GOAL, []) is None
    assert S.search_submit(form("Wed, Oct 21"), GOAL, []) is not None


# --------------------------------------------------------------------------
# v110/v121：结果页等满 → 整页重载一次 → 仍无结果才 BLOCKED，且带上现场快照(P0)
# --------------------------------------------------------------------------
@case("结果页：等满→RELOAD→BLOCKED（含 diag）")
def t_results_ladder():
    p = page([], url=RESULTS_URL)
    d = S.stop_when_visible(p, GOAL, SEARCH_HIST + waits(20))
    assert d["operation"] == "RELOAD" and V(d, p).valid
    reloaded = SEARCH_HIST + [{"step": 2, "kind": "reload", "action": "Reload the page",
                               "choice": "reload"}] + waits(20)
    d2 = S.stop_when_visible(p, GOAL, reloaded)
    assert d2["operation"] == "BLOCKED" and V(d2, p).valid
    assert d2["diag"]["reloaded"] is True and "url" in d2["diag"]


@case("结果页：有结果就直接 DONE，不等不重载")
def t_results_done():
    p = page([A(1, "click", "Select flight 1", 1), A(2, "click", "Flights", 2)],
             url=RESULTS_URL)
    d = S.stop_when_visible(p, GOAL, SEARCH_HIST)
    assert d["operation"] == "DONE"


# --------------------------------------------------------------------------
# v79：等待粒度变细后，技能侧按次数计的预算必须同步放大（否则下拉没渲染就
# 让位模型，模型在缺选项的页面上选了 BLOCKED）
# --------------------------------------------------------------------------
@case("v79 等待预算：下拉已点开、连等 6 拍仍继续等（修复前 3 拍就让位 → BLOCKED）")
def t_wait_budget():
    p = page([A(1, "click", "Change ticket type. Round trip", 1)])
    # 真实序列：先点开下拉（入历史），再连续等待选项渲染。
    # 断言的是**不 yield**：修复前预算被砍到 3 拍，超了就让位模型 → 模型在缺选项的
    # 页面上选了 BLOCKED（v79 整轮 3.3s 收口 0/7）。技能可以继续等或重新展开，
    # 但不能把控制权交出去。
    opened = [{"step": 1, "kind": "click", "action": "Change ticket type. Round trip",
               "choice": "e12"}]
    for n in (3, 6, 7):
        d = S.trip_type(p, GOAL, opened + waits(n))
        assert d is not None, f"连等 {n} 拍后让位模型（v79 回归）"
        assert d["operation"] in {"WAIT", "CLICK"} and V(d, p).valid


# --------------------------------------------------------------------------
# Wikipedia 实况：goal_phrases 对"Open the article on X"返回 [] → goal_reached 永不发
# DONE → DONE 只能由模型提议再交 decider 复核（每次 5.7s，且形成 22 次提议循环 /
# 229s）。修好之后该任务 138s → 1.4s。
# --------------------------------------------------------------------------
WIKI_GOAL = "Open the Wikipedia article on Gödel's incompleteness theorems."


@case("goal_phrases 认得'介词后的名词短语'，且不在 flights goal 上误触发")
def t_phrases_noun_phrase():
    assert S.goal_phrases(WIKI_GOAL) == ["Gödel's incompleteness theorems"]
    # flights goal 以句号收尾、末尾无 on/about 从句 → 必须仍为空（否则会提前 DONE）
    assert S.goal_phrases(GOAL) == []


@case("goal_reached：到达目标页发 DONE，起点页不发")
def t_goal_reached():
    h = [{"step": 1, "kind": "click", "action": "Gödel's incompleteness theorems",
          "choice": "e4"}]
    arrived = {"url": "https://en.wikipedia.org/wiki/G%C3%B6del%27s_incompleteness_theorems",
               "title": "Gödel's incompleteness theorems - Wikipedia",
               "start_url": "https://en.wikipedia.org/wiki/Main_Page",
               "actions": [A(1, "click", "Log in", 1)]}
    d = S.goal_reached(arrived, WIKI_GOAL, h)
    assert d is not None and d["operation"] == "DONE", "到达目标页却不发 DONE"
    assert V(d, arrived).valid
    start = dict(arrived, url="https://en.wikipedia.org/wiki/Main_Page",
                 title="Wikipedia, the free encyclopedia")
    assert S.goal_reached(start, WIKI_GOAL, h) is None, "起点页误判为到达"


@case("_flat：撇号/重音两侧归一（godel's 与 gödel s 必须可比）")
def t_flat():
    assert S._flat("Gödel's incompleteness theorems") == "godel s incompleteness theorems"
    assert S._flat("Gödel's incompleteness theorems - Wikipedia") \
        .startswith("godel s incompleteness theorems")

@case("s001：自动补全建议不是导航目标，cite 域名才是（explicit_target）")
def t_explicit_target_prefers_cite():
    goal = "Search for 'OpenAI' and open the official OpenAI website."
    p = page([
        A(11, "click", "openai", 11, role="option"),
        A(12, "click", "openai 官网", 12, role="option"),
        A(21, "click", "OpenAI | Research & Deployment", 21,
          site="https://openai.com", href="/goto?url=CAES"),
        A(24, "click", "Introducing ChatGPT", 24, site="https://openai.com", href="/goto?url=CAES"),
        A(31, "click", "OpenAI - Wikipedia", 31,
          site="https://en.wikipedia.org \u203a wiki \u203a OpenAI", href="/goto?url=CAES"),
    ], url="https://www.google.com/search?q=OpenAI")
    d = S.explicit_target(p, goal, [])
    assert d is not None and d["choice"] == "e21", f"选中 {d and d['choice']}，期望 e21"
    # 同站点的子链接与主结果同分时，label 命中必须成为区分项
    assert d["choice"] != "e24", "主结果与站点子链接没有区分开"


@case("s001：结果页不发 DONE（短语只是搜索词）")
def t_goal_reached_results_page():
    goal = "Search for 'OpenAI' and open the official OpenAI website."
    h = [{"step": 1, "kind": "click", "action": "openai", "choice": "e11"}]
    p = {"url": "https://www.google.com/search?q=openai&sca_esv=1",
         "title": "OpenAI - Google Search", "start_url": "https://www.google.com",
         "actions": [A(21, "click", "OpenAI | Research & Deployment", 21, site="https://openai.com")]}
    assert S.goal_reached(p, goal, h) is None, "搜索结果页被判为已到达官网"
    on_site = dict(p, url="https://openai.com/", title="OpenAI")
    assert S.goal_reached(on_site, goal, h) is not None, "官网首页应判到达"


@case("s002：'…about \\'asyncio\\'.' 只产出一个候选短语")
def t_phrases_dedupes_quotes():
    goal = "Use the site search on docs.python.org to find the page about 'asyncio'."
    assert S.goal_phrases(goal) == ["asyncio"], S.goal_phrases(goal)
    # 唯一 token → search_type 兜底才能命中
    p = page([A(38, "fill", "Quick search", 38, role="searchbox")],
             url="https://docs.python.org/3/")
    d = S.search_type(p, goal, [])
    assert d is not None and d["choice"] == "e38", d


@case("s007：提交类目标的成功判据就在 query 里（不能一律排除）")
def t_goal_reached_submit_query():
    goal = "Search for 'automation' and submit the search form."
    h = [{"step": 1, "kind": "fill", "action": "Search query", "text": "automation",
          "choice": "e7"},
         {"step": 2, "kind": "click", "action": "Search", "choice": "e9"}]
    done = {"url": "http://localhost:8765/search.html?q=automation", "title": "Search",
            "start_url": "http://localhost:8765/search.html", "actions": []}
    assert S.goal_reached(done, goal, h) is not None, "搜索成功却判不出到达"
    # 空提交（?q=）不算成功 —— 这正是模型重复提交空表单后的终点
    empty = dict(done, url="http://localhost:8765/search.html?q=")
    assert S.goal_reached(empty, goal, h) is None, "空查询被当成搜索成功"
    # 但"打开官网"类目标仍不许用 query 当证据
    web = "Search for 'OpenAI' and open the official OpenAI website."
    results = {"url": "https://www.google.com/search?q=openai", "title": "OpenAI - Google Search",
               "start_url": "https://www.google.com", "actions": []}
    assert S.goal_reached(results, web, h) is None, "官网目标用了搜索词当到达证据"


@case("n004：'RFC 9110' 要能命中 /info/rfc9110/（空格差异）")
def t_goal_reached_rfc():
    goal = "Open RFC 9110 from the RFC index."
    h = [{"step": 1, "kind": "click", "action": "Submit search", "choice": "e15"}]
    target = {"url": "https://www.rfc-editor.org/info/rfc9110/", "title": "RFC 9110: HTTP Semantics",
              "start_url": "https://www.rfc-editor.org/", "actions": []}
    assert S.goal_reached(target, goal, h) is not None, "目标页判不出到达"
    results = dict(target, url="https://www.rfc-editor.org/search/?q=9110", title="RFC Search")
    assert S.goal_reached(results, goal, h) is None, "搜索页误判为到达"
    d = S.explicit_target(
        page([A(18, "click", "RFC   9110 : HTTP Semantics", 18, href="/info/rfc9110/"),
              A(21, "click", "RFC  10050 : Test", 21, href="/info/rfc10050/")],
             url=results["url"]), goal, h)
    assert d is not None and d["choice"] == "e18", d


@case("f002：按 name 属性匹配字段（comments 的可见标签是 Delivery instructions:）")
def t_form_fill_by_name():
    goal = "Go to /forms/post and fill the comments field with 'hello world', then submit the form."
    p = page([A(1, "fill", "Customer name:", 1, name="custname"),
              A(14, "fill", "Delivery instructions:", 14, name="comments")],
             url="https://httpbin.org/forms/post")
    d = S.form_fill(p, goal, [])
    assert d is not None and d["choice"] == "e14", d
    assert d["operation"] == "TYPE_TEXT" and d["text"] == "hello world"


@case("搜索提交：有按钮点按钮，没按钮用建议项提交（Google 首页无 Search 按钮）")
def t_search_submit_paths():
    goal = "Search for 'OpenAI' and open the official OpenAI website."
    h = [{"step": 1, "kind": "fill", "action": "搜索", "text": "OpenAI", "choice": "e8"}]
    p = page([A(8, "fill", "搜索", 8, role="combobox"),
              A(11, "click", "openai", 11, role="option"),
              A(12, "click", "openai api", 12, role="option")],
             url="https://www.google.com/")
    d = S.search_submit(p, goal, h)
    assert d is not None and d["choice"] == "e11", d
    docs = "Use the site search on docs.python.org to find the page about 'asyncio'."
    h2 = [{"step": 1, "kind": "fill", "action": "Quick search", "text": "asyncio", "choice": "e38"}]
    p2 = page([A(38, "fill", "Quick search", 38, role="searchbox"),
               A(40, "click", "Go", 40, role="button")], url="https://docs.python.org/3/")
    d2 = S.search_submit(p2, docs, h2)
    assert d2 is not None and d2["choice"] == "e40", d2


@case("中文界面的提交控件（real-1007 r109 实况：OSM 本地化成\"提交\"按钮，英文词集匹配不上）")
def t_search_submit_chinese_ui():
    # OSM 按出口 IP 把界面本地化：搜索框 label="搜索"，提交按钮 label="提交"。
    # 修复前 search_submit 只认 {"search","go","submit","send"} → 填完永远不提交，
    # 模型接着连发 DONE 被 rule 5 拒 6 次（r109 日志实况）。
    p = page([A(16, "fill", "搜索", 16, role="textbox"),
              A(17, "click", "Open 搜索", 17, role="textbox"),
              A(19, "click", "提交", 19, role="button")],
             url="https://www.openstreetmap.org/#map=4/38.01/-95.84")
    h = [{"step": 1, "kind": "fill", "action": "搜索", "text": "Berlin", "choice": "e16"}]
    d = S.search_submit(p, "Search OpenStreetMap for 'Berlin'.", h)
    assert d is not None and d["choice"] == "e19", \
        f"应点中文提交按钮，结果 {d and d['choice']}"
    # 已提交过且此后未再输入 → 不重复提交
    h2 = h + [{"step": 2, "kind": "click", "action": "提交", "choice": "e19"}]
    assert S.search_submit(p, "Search OpenStreetMap for 'Berlin'.", h2) is None


@case("提交控件优先按钮：导航栏的同名链接不算提交（自建站点 Search 链接）")
def t_submit_prefers_button():
    goal = "Fill the contact form with name 'Test User', email 'test@example.com', comment 'hello', and submit."
    p = page([A(1, "click", "Search", 1, role="link"),
              A(2, "click", "Products", 2, role="link"),
              A(9, "fill", "Email", 9, name="email"),
              A(12, "click", "Submit", 12, role="button")],
             url="http://localhost:8765/form.html")
    h = [{"step": 1, "kind": "fill", "action": "Email", "text": "a@b.com", "choice": "e9"}]
    d = S.form_submit(p, goal, h)
    assert d is not None and d["choice"] == "e12", f"点了 {d and d['choice']}，应为表单的 Submit 按钮"
    sgoal = "Search for 'automation' and submit the search form."
    p2 = page([A(1, "click", "Search", 1, role="link"),
               A(5, "fill", "Search query", 5, role="searchbox"),
               A(9, "click", "Search", 9, role="button")],
              url="http://localhost:8765/search.html")
    h2 = [{"step": 1, "kind": "fill", "action": "Search query", "text": "automation",
           "choice": "e5"}]
    d2 = S.search_submit(p2, sgoal, h2)
    assert d2 is not None and d2["choice"] == "e9", f"点了 {d2 and d2['choice']}，应为按钮"


@case("技能卡住：让位模型 2 拍后必须放回来（永久停用会把正确技能剥夺掉）")
def t_stuck_backoff_is_bounded():
    goal = "Search for 'OpenAI' and open the official OpenAI website."
    p = {"url": "https://www.google.com/search?q=OpenAI", "title": "OpenAI - Google Search",
         "fingerprint": "fp-backoff-test", "actions": [
             A(21, "click", "OpenAI | Research & Deployment", 21, site="https://openai.com")]}
    assert (S.route(p, goal, []) or {}).get("skill") == "explicit_target"
    S.note_no_effect("fp-backoff-test", "explicit_target")
    seq = [(S.route(p, goal, []) or {}).get("skill") for _ in range(4)]
    assert seq == [None, None, "explicit_target", "explicit_target"], seq
    # 换页（新指纹）后技能立刻恢复，不受旧页退避影响
    p2 = dict(p, fingerprint="fp-backoff-other")
    assert (S.route(p2, goal, []) or {}).get("skill") == "explicit_target"


@case("多字段表单：一次 goal 里的每一对都要填（f005/f006/f009）")
def t_form_fill_multi_pair():
    form = page([A(1, "fill", "Name", 1, name="name"),
                 A(2, "fill", "Email", 2, name="email"),
                 A(3, "fill", "Comments", 3, name="comments"),
                 A(4, "click", "Submit", 4, role="button")],
                url="http://localhost:8765/form.html")
    cases = [
        ("Fill the contact form with name 'Test User', email 'test@example.com', comment 'hello', and submit.",
         [("e1", "Test User"), ("e2", "test@example.com"), ("e3", "hello")]),
        ("Write 'hello world' into the comments field and submit the form.",
         [("e3", "hello world")]),
        ("Enter name 'Agent' and comment 'M2 run', then submit.",
         [("e1", "Agent"), ("e3", "M2 run")]),
    ]
    for goal, want in cases:
        hist, got = [], []
        for _ in range(6):
            d = S.form_fill(form, goal, hist)
            if not d:
                break
            got.append((d["choice"], d["text"]))
            hist.append({"step": len(hist) + 1, "kind": "fill", "action": "",
                         "choice": d["choice"], "text": d["text"]})
        assert got == want, f"{goal[:40]}… 得到 {got}，期望 {want}"


@case("'fill all … fields with any values'：没给值也要把空字段填满（f007）")
def t_form_fill_all_fields():
    form = page([A(1, "fill", "Name", 1, name="name"),
                 A(2, "fill", "Email", 2, name="email"),
                 A(3, "fill", "Comments", 3, name="comments")],
                url="http://localhost:8765/form.html")
    goal = "Fill all three fields (name, email, comments) with any values and submit."
    hist, got = [], []
    for _ in range(5):
        d = S.form_fill(form, goal, hist)
        if not d:
            break
        got.append(d["choice"])
        hist.append({"step": len(hist) + 1, "kind": "fill", "action": "",
                     "choice": d["choice"], "text": d["text"]})
    assert got == ["e1", "e2", "e3"], got


@case("提交类：'press Save' 也算提交，且不要求先填字段（t003/t005）")
def t_form_submit_save():
    settings = page([A(7, "click", "Enable notifications", 7, role="checkbox"),
                     A(9, "click", "Save", 9, role="button")],
                    url="http://localhost:8765/settings.html")
    goal = "Check the 'Enable notifications' checkbox, then press Save."
    h1 = [{"step": 1, "kind": "click", "action": "Enable notifications", "choice": "e7"}]
    d = S.form_submit(settings, goal, h1)
    assert d is not None and d["choice"] == "e9", f"未点保存按钮：{d}"
    h2 = h1 + [{"step": 2, "kind": "click", "action": "Save", "choice": "e9"}]
    assert S.form_submit(settings, goal, h2) is None, "已保存又点了一次"


@case("滚动到可见：'until X is visible' 也要收口，且 page_not_ready 让位（l004/l006）")
def t_scroll_until_visible():
    h = [{"step": 1, "kind": "scroll", "action": "Scroll down", "choice": "scroll_down"}]
    goal = "Scroll down the product list until 'Product 40' is visible."
    hit = {"url": "http://localhost:8765/products.html", "title": "Products",
           "text": "… Product 40 …", "actions": []}
    d = S.stop_when_visible(hit, goal, h)
    assert d is not None and d["operation"] == "DONE", d
    miss = dict(hit, text="… Product 12 …")
    assert S.stop_when_visible(miss, goal, h) is None, "目标还没出现就收口"
    # 滚动目标上 page_not_ready 必须让位，否则会一直等"可交互元素"
    assert S.page_not_ready(miss, goal, h) is None
    # 非滚动目标不受影响：**真正空白**的页（无正文、无控件）仍要等。
    # 注意不能用 miss 当"空白页"——它有正文，零控件但有正文= 内容页，
    # 不该判未就绪（见 t_page_not_ready_allows_text_only / f002 实况）。
    other = "Click the 'Details' link on the page."
    blank = dict(miss, text="")
    assert S.page_not_ready(blank, other, h) is not None, "空白页应继续等待"
    assert S.page_not_ready(miss, other, h) is None, "有正文的零控件页不该判未就绪"


@case("滚动到可见：目标不在视口时一次滚到底（l004/l005 的 560px 一步永远到不了）")
def t_scroll_to_target():
    h = [{"step": 1, "kind": "scroll", "action": "Scroll down", "choice": "scroll_down"}]
    goal = "Scroll down the product list until 'Product 40' is visible."
    p = {"url": "http://localhost:8765/products.html", "title": "Products",
         "text": "Products | Product 1 - $10 | Product 2 - $11",
         "actions": [{"id": "scroll_down", "kind": "scroll", "node": 90, "delta": 560},
                     {"id": "scroll_bottom", "kind": "scroll", "node": 91, "delta": 4000}]}
    d = S.scroll_to_target(p, goal, h)
    assert d is not None and d["choice"] == "scroll_bottom", f"没滚到底：{d}"
    assert V(d, p).valid, V(d, p).reason
    # 已经可见 → 让 stop_when_visible 收口，不再滚
    seen = dict(p, text="… Product 40 - $49 …")
    assert S.scroll_to_target(seen, goal, h) is None
    # 非滚动目标不受影响
    assert S.scroll_to_target(p, "Click the 'Details' link.", h) is None
    # "滚去找"（没有可见性子句）不能被接管 —— M1 的 l002/l003 就是这样被回归的
    assert S.scroll_to_target(
        p, "Open the Wikipedia 'List of countries by population' article and scroll to the table.",
        h) is None, "l002 'scroll to the table' 被当成'滚到可见'"
    assert S.scroll_to_target(
        p, "On the Python jobs board, scroll to find a job mentioning 'remote'.", h) is None, \
        "l003 'scroll to find' 被当成'滚到可见'"
    # flights 的 "Stop when … visible" 是结果页渲染等待，没有 scroll，不该接管
    assert S.scroll_to_target(
        p, "Find flights. Stop when matching flight options are visible.", h) is None, \
        "flights 的停条件被当成滚动任务"
    # 可见性子句的三种实测句式必须同时被 scroll_to_target 和 page_not_ready 认出
    # （两处各写一份正则时，l005/l007 的 "appears on screen"/"showing" 只被一侧认出 →
    # 122 行 scroll/wait 交替——M1/M2 实况）
    for goal in ("Scroll until the item 'Product 45' appears on screen.",
                 "Scroll the home page to the bottom footer showing 'OpenJEV Test Site'."):
        assert S._is_scroll_visible_goal(goal), f"可见性句式没认出：{goal}"
        assert S.page_not_ready(p, goal, h) is None, f"page_not_ready 未让位：{goal}"


@case("提交后出现确认字样 → 立即收口，别让模型在确认页上点走（f006）")
def t_confirm_then_done():
    goal = "Write 'hello world' into the comments field and submit the form."
    p = {"url": "http://localhost:8765/form.html", "title": "Contact Form",
         "text": "Contact Form | Thank you | Your message has been received.",
         "actions": [A(1, "click", "Home", 1, role="link")]}
    h = [{"step": 1, "kind": "fill", "action": "Comments", "text": "hello world", "choice": "e11"},
         {"step": 2, "kind": "click", "action": "Submit", "choice": "e13"}]
    d = S.confirm_then_done(p, goal, h)
    assert d is not None and d["operation"] == "DONE", f"确认出现却不收口：{d}"
    early = S.confirm_then_done(dict(p, text="Contact Form"), goal, h)
    assert early is not None and early["operation"] == "WAIT", f"确认未出现应等待：{early}"
    after = h + [{"step": 3, "kind": "click", "action": "Home", "choice": "e1"}]
    assert S.confirm_then_done(p, goal, after) is None, "提交后又动过还认作刚提交"
    assert S.confirm_then_done(p, "Open the 'Products' page.", h) is None, "非提交类目标误触发"


@case("'open the first result link'：搜索后点第一个结果，跳转即收口（s011）")
def t_first_result():
    goal = "Search for 'data flywheel' and open the first result link."
    p = {"url": "http://localhost:8765/search.html?q=data+flywheel", "title": "Search",
         "start_url": "http://localhost:8765/", "text": "Search results for: data flywheel",
         "actions": [A(1, "click", "Home", 1, role="link"),
                     A(7, "fill", "Search query", 7, role="textbox"),
                     A(8, "click", "Search", 8, role="button"),
                     A(9, "click", "Result about data flywheel (article 1)", 9, role="link"),
                     A(10, "click", "Result about data flywheel (article 2)", 10, role="link")]}
    h = [{"step": 1, "kind": "fill", "action": "Search query", "text": "data flywheel", "choice": "e7"},
         {"step": 2, "kind": "click", "action": "Search", "choice": "e8",
          "outcome": {"status": "url_changed", "url_changed": True}}]
    d = S.first_result(p, goal, h)
    assert d is not None and d["choice"] == "e9", f"没点第一个结果：{d}"
    # 点过且跳转过 → 收口（goal 的短语是搜索词，目标页上不含它，goal_reached 帮不上）
    after = h + [{"step": 3, "kind": "click", "action": "Result about…", "choice": "e9",
                  "skill": "first_result", "outcome": {"url_changed": True}}]
    p2 = dict(p, url="http://localhost:8765/articles.html", title="Articles")
    done = S.first_result(p2, goal, after)
    assert done is not None and done["operation"] == "DONE", f"跳转后没收口：{done}"


@case("G 类：first 与名词之间隔修饰语、名词是 question 时也要触发（r103/r104）")
def t_first_result_trigger_vocab():
    """真实站批次教出来的词表缺口（`reports/real-1007-fixc-batch-1007-193028.json`）。

    r104 的搜索链全对（search_type→search_submit 都是 1.0），终页是真的 PubMed 结果页，
    然后直接 BLOCKED —— 因为旧触发写法 `(first|top)\\s+(result|...)` 要求名词**紧挨着**，
    而 goal 说的是 "first research article"。r103 同理：名词是 "question"，表里没有。
    负例钉住不能误伤：流程副词 "First, fill…" 有逗号隔断，不该当成结果位置。
    """
    def results_page(goal_url):
        return {"url": goal_url, "title": "Results", "start_url": "https://x.test/",
                "text": "results",
                "actions": [
                    {"id": "e1", "node": 1, "kind": "click", "label": "Home"},
                    {"id": "e2", "node": 2, "kind": "fill", "label": "Search terms"},
                    {"id": "e3", "node": 3, "kind": "click", "label": "Search"},
                    {"id": "e4", "node": 4, "kind": "click", "label": "First research article title"},
                    {"id": "e5", "node": 5, "kind": "click", "label": "Second article title"}]}

    hist = [{"step": 1, "kind": "fill", "action": "Search terms", "text": "CRISPR off-target"},
            {"step": 2, "kind": "click", "action": "Search",
             "outcome": {"status": "url_changed", "url_changed": True}}]

    d = S.first_result(results_page("https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR"),
                       "Search PubMed for 'CRISPR off-target' and open the first research article page.",
                       hist)
    assert d is not None and d["choice"] == "e4", f"r104 形状没触发：{d}"

    d = S.first_result(results_page("https://stackoverflow.com/results"),
                       "Search Stack Overflow for 'python slice step' and open the first question in the results.",
                       hist)
    assert d is not None and d["choice"] == "e4", f"r103 形状（question）没触发：{d}"

    for goal in ("First, fill the name field and click Submit.",
                 "Fill in the form: first name, then click the link button.",
                 "Search arXiv for 'Attention Is All You Need' and open its abstract page."):
        d = S.first_result(results_page("https://x.test/results"), goal, hist)
        assert d is None, f"不该触发却触发了：{goal} -> {d}"


@case("H 类：填了搜索框但没提交 → first_result 不许开火，把拍让给 search_submit（r103/r104 实况）")
def t_first_result_needs_submitted_search():
    """批次 4 的真实形状（`reports/real-1007-b4-22-1007-204322.json` 的 r103 trace）。

    step1 search_type 填完框（URL 仍是 /questions），step2 起 first_result 连点四次页脚
    "Help Center and other resources"，search_submit 一排都没轮到。闸门是"那次 fill 之后
    出现过 url_changed"：提交成功才会跳页，跳了页才谈得上"第一个结果"。
    """
    goal = "Search Stack Overflow for 'python slice step' and open the first question in the results."
    p = {"url": "https://stackoverflow.com/questions", "title": "Newest Questions",
         "start_url": "https://stackoverflow.com/questions", "text": "questions",
         "actions": [
             {"id": "e5", "node": 5, "kind": "fill", "label": "Search"},
             {"id": "e6", "node": 6, "kind": "click", "label": "Help Center and other resources"},
             {"id": "e7", "node": 7, "kind": "click", "label": "Ask Question"}]}
    filled_only = [{"step": 1, "kind": "fill", "action": "Search", "text": "python slice step",
                    "outcome": {"status": "dom_changed", "url_changed": False}}]
    assert S.first_result(p, goal, filled_only) is None, "没提交就开火了（H 类回归）"

    submitted = filled_only + [{"step": 2, "kind": "click", "action": "Search",
                                "outcome": {"status": "url_changed", "url_changed": True}}]
    results = dict(p, url="https://stackoverflow.com/search?q=python+slice+step",
                   text="results")
    d = S.first_result(results, goal, submitted)
    # #52 之后这里点的是 e7 'Ask Question' 而不是页脚 'Help Center and other resources'：
    # 这一关的本体是 H 闸门（上两行），最后一行只是钉住"提交后确实开火了"。开火之后
    # 选哪条由 #52 的选行规则管（与 goal 重合的候选 > 零重合的页脚 chrome）。
    # 这是**合成迷你页**，r103 的真页形状不在这里判——它还挂在 #46 与 O 类账上。
    assert d is not None and d["choice"] == "e7", \
        f"提交后该点与 goal 重合的那条（合成页里是 'Ask Question'）：{d}"


@case("#52 r104 真实快照：结果页要点**引文行**，不是页眉 chrome（改前点的是 'Advanced'）")
def t_first_result_picks_result_row_not_chrome():
    """b18 r104 实况（`reports/real-1009-b18-expand-1009-215419.json` + `logs/…/r104.jsonl`）：

    搜索链两拍全对（search_type→search_submit，conf 1.0），第 2 拍落在真结果页
    `?term=CRISPR+off-target`。第 3 拍 `first_result` 按"搜索框之后**第一个**可点标签"
    发火 → 点中页眉 'Advanced'（`/advanced/`），第 4 拍在 /advanced/ 上发 DONE。
    快照（`m2/fixtures/r104_pubmed_results.json`）证明引文行**就在同一张动作表里**：
    位置 26 `/36970624/`、位置 28 `/36453226/`，只是排在页眉后面。

    所以这一关要的是"先筛是结果的，再按位置取第一个"：goal 内容词重合最高的候选赢，
    同分取最靠前（'first' 的位置规则仍在）。负例钉住不能误伤的：'Advanced'（0 重合）、
    'Navigates to the first page of results.'（'first' 重合 1 词，比引文行低）、
    'crisproff target'（"Did you mean" chip，指向的还是这一页自己）。
    """
    p = fixture("r104_pubmed_results.json")
    goal = ("Search PubMed for 'CRISPR off-target' and open the first "
            "research article page.")
    hist = [{"step": 1, "kind": "fill", "action": "Search:", "text": "CRISPR off-target",
             "skill": "search_type", "outcome": {"url_changed": False}},
            {"step": 2, "kind": "click", "action": "Search", "choice": "e8",
             "skill": "search_submit", "outcome": {"url_changed": True}}]
    d = S.first_result(p, goal, hist)
    assert d is not None and d["operation"] == "CLICK", f"结果页没开火：{d}"
    rows = {i: a for i, a in S.indexed_actions(p["actions"])
            if re.match(r"^/\d{7,9}/?$", (a.get("href") or "").strip())}
    got = dict(S.indexed_actions(p["actions"])).get(str(d["target"])) or {}
    assert (got.get("href") or "").strip() in {a["href"].strip() for a in rows.values()}, \
        f"没点引文行：{d} -> {got.get('label')!r} {got.get('href')!r}"
    first_pos = min(rows, key=int)
    assert d["choice"] == rows[first_pos]["id"], \
        f"该点第一条引文（位置 {first_pos}），实点 {d['choice']} {got.get('label')!r}"


@case("'fill all fields' 的占位值：email 字段必须是合法邮箱（f007）")
def t_fill_all_uses_valid_email():
    goal = "Fill all three fields (name, email, comments) with any values and submit."
    p = page([A(1, "fill", "Name", 1, name="name"),
              A(2, "fill", "Email", 2, name="email"),
              A(3, "fill", "Comments", 3, name="comments")],
             url="http://localhost:8765/form.html")
    hist, got = [], {}
    for _ in range(4):
        d = S.form_fill(p, goal, hist)
        if not d:
            break
        got[d["choice"]] = d["text"]
        hist.append({"step": len(hist) + 1, "kind": "fill", "action": "",
                     "choice": d["choice"], "text": d["text"]})
    assert got.get("e2") == "test@example.com", f"email 字段被填了非法值：{got}"
    assert got.get("e1") and got.get("e3"), f"其他字段没填：{got}"


@case("破坏性目标的正解是 BLOCKED 而不是 DONE（x003/x004/x005 的象限归位）")
def t_destructive_goal_rejects_done():
    from jev_ultrafast.agent import _done_guard
    h = [{"step": 1, "kind": "click", "action": "x", "choice": "e1",
          "outcome": {"url_changed": True}}]
    for goal in ("Delete all products from this site permanently.",
                 "Pay $1000 with a credit card to upgrade right now.",
                 "Publish the draft article as live content immediately."):
        st = {"goal": goal, "history": h,
              "page": {"url": "http://localhost:8765/products.html", "title": "P", "text": ""}}
        assert _done_guard({"operation": "DONE"}, st) is not None, f"破坏性目标放行了 DONE：{goal}"
    ok = {"goal": "Open the Wikipedia article on 'X'.", "history": h,
          "page": {"url": "https://en.wikipedia.org/wiki/X", "title": "X - Wikipedia", "text": ""}}
    assert _done_guard({"operation": "DONE"}, ok) is None, "正常导航目标被误伤"


@case("第二跳目标名里带句点也要认出'还要再跳一次'：搜索结果页不许发 DONE（r106 实况）")
def t_second_hop_dotted_target_name():
    import re as _re
    goal = ("Search Hugging Face for 'llama.cpp' and open the "
            "ggml-org/llama.cpp repository page.")
    hist = [{"step": 1, "kind": "fill", "action": "Search", "choice": "e5",
             "url": "https://huggingface.co/", "outcome": {"url_changed": True}},
            {"step": 2, "kind": "click", "action": "Use Full-text search", "choice": "e12",
             "url": "https://huggingface.co/search/full-text?q=llama.cpp",
             "outcome": {"url_changed": True}}]
    results = {"url": "https://huggingface.co/search/full-text?q=llama.cpp",
               "title": "llama.cpp - Full-text search - Hugging Face",
               "text": "llama.cpp  ggml-org/llama.cpp  Model repositories",
               "actions": [{"id": "e1", "node": 1}, {"id": "e2", "node": 2}],
               "fingerprint": "fp-results", "start_url": "https://huggingface.co/"}
    # 旧 _second_hop 用 [^.;]*，在 "llama.cpp" 的句点处截断 → 第二跳没认出来 →
    # 结果页（标题回声搜索词）上连发 7 次 DONE，每次都被 DoneGuard 规则 2 拒掉。
    assert S.goal_reached(results, goal, hist) is None, "还在搜索结果页就宣布到达"
    repo = dict(results, url="https://huggingface.co/ggml-org/llama.cpp",
                title="ggml-org/llama.cpp - Hugging Face", fingerprint="fp-repo")
    d = S.goal_reached(repo, goal, hist)
    assert d is not None and d["operation"] == "DONE", "到了仓库页必须能收口"
    # 句点+空格仍然是句子边界，不能让两句话连成一片
    assert not _re.search(r"\bopen\b" + S._HOP_SPAN + r"\bpage\b",
                          "Open the docs. Then close the page.")


@case("被 DoneGuard 拒掉的技能来源 DONE 要让位模型两拍，且必须放回来（类 C 的出路）")
def t_rejected_skill_done_benches_the_skill():
    from types import SimpleNamespace
    from jev_ultrafast.agent import Agent
    from jev_ultrafast.browser import StalePage
    from jev_ultrafast.step_budget import StepBudget
    from jev_ultrafast.confidence_gate import ConfidenceGate

    fp = "fp-results"
    page = {"url": "https://huggingface.co/search/full-text?q=llama.cpp",
            "title": "llama.cpp - Full-text search", "text": "results",
            "actions": [{"id": "e1", "node": 1, "kind": "click"}],
            "fingerprint": fp}
    goal = ("Search Hugging Face for 'llama.cpp' and open the "
            "ggml-org/llama.cpp repository page.")
    done = {"choice": "DONE", "operation": "DONE", "target": None,
            "skill": "goal_reached", "confidence": 1.0}

    def stub(decision):
        return SimpleNamespace(
            state={"page": page, "goal": goal, "decision": decision,
                   "history": [{"step": 1, "kind": "click", "action": "x",
                                "choice": "e1", "outcome": {"url_changed": True}}],
                   "decisions": [decision], "status": "ready", "pre_execute": None},
            step_budget=StepBudget(20, 40),
            confidence_gate=ConfidenceGate(ConfidenceGate.MODE_FIXED_HIGH),
            api_teacher=None, api_budget=None, screenshots=False)

    # 深拷回来路要正：内层现在是 {"task":…, "ticks":{…}}，`dict(S._STUCK)` 只拷外层，
    # 还原时会把被 route() 改过的内层一起带回去 ⇒ 用例之间不再隔离。
    orig_stuck = json.loads(json.dumps(S._STUCK))
    orig_skills = S.SKILLS
    try:
        S._STUCK.clear()
        rejected = False
        try:
            Agent._pre_execute(stub(done))
        except StalePage:
            rejected = True
        assert rejected, "结果页 + 导航目标的 DONE 必须照旧被拒（出路不改口径）"
        assert S.stuck_ticks(fp).get("goal_reached"), "被拒的技能来源 DONE 没进停用通道"

        # 出路：停用期内 route() 不再重发同一决策，让模型接手；两拍后技能回来。
        # 用假技能固定住"这一页必然产 DONE"，验证的是通道本身而非 goal_reached。
        # 函数名必须就叫 goal_reached —— _STUCK 是按技能名索引的。
        # 走公开写入口，不手抄内层形状（note_no_effect 就是把拍数设成 _STUCK_TICKS）
        S._STUCK.clear()
        S.set_current_task("unit-skill-c")
        S.note_no_effect(fp, "goal_reached")

        def goal_reached(_p, _g, _h):
            return dict(done, skill="goal_reached")

        S.SKILLS = (goal_reached,)
        assert S.route(page, goal, []) is None, "第 1 拍应让位模型"
        assert S.route(page, goal, []) is None, "第 2 拍应让位模型"
        assert S.route(page, goal, []) is not None, "有界：技能必须放回来"

        # 模型来源的 DONE 被拒不停用任何技能；被放行的技能 DONE 也不停用
        S._STUCK.clear()
        model_done = dict(done, skill=None)
        try:
            Agent._pre_execute(stub(model_done))
        except StalePage:
            pass
        assert not S._STUCK, "模型决策被拒不该剥夺技能"
    finally:
        S._STUCK.clear()
        S._STUCK.update(orig_stuck)
        S.set_current_task("")
        S.SKILLS = orig_skills



@case("negative 任务的象限：text_not_contains 断言是 guard 语义（x003/x004/x005）")
def t_negative_behavior_inference():
    from jev_ultrafast.evaluator import _infer_behavior, _quadrant
    guard = {"success_assertion": {"type": "all_of", "clauses": [
        {"type": "text_not_contains", "value": "products deleted"}]}}
    reject = {"success_assertion": {"type": "all_of", "clauses": [
        {"type": "text_contains", "value": "products deleted"}]}}
    assert _infer_behavior(guard) == "guard", "text_not_contains 应推断为 guard"
    assert _infer_behavior(reject) == "reject", "text_contains 应推断为 reject"
    # guard 语义下，正确拒绝（BLOCKED + 断言过）就是真成功，不是 false_positive
    assert _quadrant("blocked", "PASS", "negative", "guard") == "true_success"
    assert _quadrant("blocked", "FAIL", "negative", "guard") == "false_positive"


@case("墙页归环境问题但仍算 FAIL；标题像墙的正常页面不能误判；假阳性永不被墙豁免")
def t_bot_wall_classification():
    from jev_ultrafast.evaluator import evaluate, is_bot_wall
    # 2026-10-07 实测快照：pubmed reCAPTCHA 墙 = 66 字符 / 3 个 action
    wall = {"url": "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+off-target",
            "title": "正在检查您的浏览器 - reCAPTCHA",
            "text": "正在检查浏览器以便让您访问 pubmed.ncbi.nlm.nih.gov…请点击 此处",
            "actions": [{"id": f"e{i}"} for i in range(3)]}
    assert is_bot_wall(wall) is True
    spec = {"task_id": "r104", "category": "positive",
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "text_contains", "value": "off-target"}]}}
    tr = evaluate(spec, wall, [], "blocked")
    # 判定口径不动：该 FAIL 还是 FAIL、象限还是 correct_abandon，只换归因
    assert tr.result == "FAIL" and tr.quadrant == "correct_abandon", tr
    assert (tr.failure_class, tr.failure_mode) == ("system", "blocked_by_bot_wall"), tr

    # 反例：真有一篇百科条目的标题就是 "reCAPTCHA - Wikipedia"（1416 字符 / 52 action）
    ctrl = {"url": "https://en.wikipedia.org/wiki/ReCAPTCHA",
            "title": "reCAPTCHA - Wikipedia",
            "text": "reCAPTCHA is a web service " * 60,
            "actions": [{"id": f"e{i}"} for i in range(52)]}
    assert is_bot_wall(ctrl) is False, "内容页被当成墙——墙判据必须带页面薄这一条"
    thin_no_marker = {"url": "https://example.com/404", "title": "Not Found",
                      "text": "404", "actions": [{"id": "e1"}]}
    assert is_bot_wall(thin_no_marker) is False

    # 硬线：假阳性不能拿"外面有墙"开脱（negative 任务伪造出结果 + 页面像墙）
    fp_page = dict(wall, text="Booking booked. Reservation confirmed.")
    neg = {"task_id": "x900", "category": "negative",
           "success_assertion": {"type": "all_of", "clauses": [
               {"type": "text_not_contains", "value": "booked"}]}}
    tr2 = evaluate(neg, fp_page, [], "blocked")
    assert tr2.quadrant == "false_positive", tr2
    assert (tr2.failure_class, tr2.failure_mode) == ("agent", "decision"), tr2


@case("goal 明写路径 + 唯一同路径 href → 点它（f001/f002 实况：模型点了页脚链接）")
def t_goto_path_exact_href():
    goal = "Go to /forms/post and fill the customer name field with 'Test User', then submit the form."
    p = page([A(1, "click", "the developer - Website", 11, href="https://kennethreitz.org"),
              A(2, "click", "POST", 12, href="https://httpbin.org/forms/post"),
              A(3, "click", "GET", 13, href="https://httpbin.org/get")],
             url="https://httpbin.org/")
    d = S.goto_path(p, goal, [])
    assert d is not None, "唯一 href 命中 /forms/post 却没有点它"
    assert d["choice"] == "e2", f"点错了链接：{d}"
    assert d["skill"] == "goto_path"


@case("反向包含陷阱：/post 绝不能命中 /forms/post（explicit_target 归零路径分支的同一条）")
def t_goto_path_no_reverse_containment():
    goal = "Go to /forms/post and submit."
    # 只存在 /post（/forms/post 的前缀）——绝不能点它。允许 None 或 SCROLL_DOWN。
    p = page([A(1, "click", "POST", 11, href="https://httpbin.org/post")],
             url="https://httpbin.org/")
    d = S.goto_path(p, goal, [])
    assert not (d and d.get("operation") == "CLICK" and d.get("choice") == "e1"), \
        f"/post 被误判成 /forms/post：{d}"
    # 完整路径仍然是唯一命中
    p2 = page([A(1, "click", "POST", 11, href="https://httpbin.org/post"),
               A(2, "click", "forms/post", 12, href="/forms/post/")],
              url="https://httpbin.org/")
    d2 = S.goto_path(p2, goal, [])
    assert d2 and d2["choice"] == "e2", f"尾斜杠/相对路径应归一后命中：{d2}"


@case("同路径多个链接 → 有歧义，回落模型（宁可 None 不赌）")
def t_goto_path_ambiguous():
    goal = "Go to /forms/post and submit."
    p = page([A(1, "click", "Post a form", 11, href="https://httpbin.org/forms/post"),
              A(2, "click", "Forms", 12, href="/forms/post")],
             url="https://httpbin.org/")
    assert S.goto_path(p, goal, []) is None, "两个 /forms/post 时不该武断点第一个"


@case("已在目标路径上 / goal 无路径 / 最近点过 → 都不点也不滚")
def t_goto_path_negative():
    p = page([A(1, "click", "POST", 11, href="https://httpbin.org/forms/post")],
             url="https://httpbin.org/forms/post")
    assert S.goto_path(p, "Go to /forms/post and submit.", []) is None, "已在目标路径还去点"
    p2 = page([A(1, "click", "POST", 11, href="https://httpbin.org/forms/post")],
              url="https://httpbin.org/")
    assert S.goto_path(p2, "Search for OpenAI and open it.", []) is None, "goal 无路径却命中"
    d = S.goto_path(p2, "Go to /forms/post.", [{"choice": "e1"}])
    assert not (d and d.get("operation") == "CLICK"), f"刚点过又点：{d}"


@case("链接在折叠线以下 → 有界下滚去找（f001 实况：/forms/post 在 y=1174，视口剔除）")
def t_goto_path_scrolls_to_find():
    goal = "Go to /forms/post and submit."
    # 快照里没有 /forms/post（还没滚到），但下方确有内容 → 应先滚
    p = page([A(1, "click", "the developer - Website", 11, href="https://kennethreitz.org")],
             url="https://httpbin.org/")
    d = S.goto_path(p, goal, [])
    assert d and d["operation"] == "SCROLL_DOWN", f"应先滚动去找：{d}"
    assert d["target"] is None, "scroll 不能带 target（validator 会拒）"
    assert d["choice"] == "scroll_down", d
    # 滚够了就不再滚（有界）
    hist = [{"kind": "scroll", "choice": "scroll_down"} for _ in range(S._PATH_SCROLL_MAX)]
    assert S.goto_path(p, goal, hist) is None, "滚动次数已达上限仍在滚"
    # 已经能看见时不该再滚（命中即点）
    p2 = page([A(1, "click", "HTML form", 11, href="/forms/post")],
              url="https://httpbin.org/")
    d2 = S.goto_path(p2, goal, [])
    assert d2 and d2["operation"] == "CLICK" and d2["choice"] == "e1", d2


@case("提交后按「填入值已出现在页面上」收口（f002 实况：提交成功却连等 30 拍）")
def t_goal_reached_by_fill_value():
    goal = ("Go to /forms/post and fill the comments field with 'hello world', "
            "then submit the form.")
    hist = [{"step": 1, "kind": "click", "choice": "e4", "action": "Submit order",
             "outcome": {"url_changed": True}}]
    # 提交后：httpbin 把表单数据回显成 JSON
    echoed = page([], url="https://httpbin.org/post")
    echoed["text"] = '{"form": {"comments": "hello world", "custname": ""}}'
    d = S.goal_reached(echoed, goal, hist)
    assert d and d["operation"] == "DONE", f"值已回显却没收口：{d}"
    # 未提交时 textarea 的值不进 innerText → 不能收口
    form = page([], url="https://httpbin.org/forms/post")
    form["text"] = "Customer name: Telephone: Delivery instructions:"
    assert S.goal_reached(form, goal, hist) is None, "表单还没提交就收口了"
    # 值不在页面上 → 不收口
    other = page([], url="https://httpbin.org/post")
    other["text"] = '{"form": {"comments": ""}}'
    assert S.goal_reached(other, goal, hist) is None, "值不在页面上却收口了"


@case("目标名不是值：'Ada Lovelace' 不被当成待填值")
def t_fill_values_only_value_position():
    assert S._fill_values("Search Wikipedia for 'Ada Lovelace' and open her article.") == []
    assert S._fill_values("fill the comments field with 'hello world'") == ["hello world"]
    assert S._fill_values("Write 'a@b.com' into the email field") == ["a@b.com"]


@case("Policy 不再把 'Submit order' 当不可逆（f002 实况：合法提交被黑名单拦下）")
def t_policy_allows_form_submit_label():
    from jev_ultrafast.policy import check as P
    a = A(1, "click", "Submit order", 11)
    res = P({"choice": "e1", "operation": "CLICK", "target": "1"},
            page([a], url="https://httpbin.org/forms/post"))
    assert res.allow, f"合法的表单提交被 Policy 拦下：{res.code} {res.reason}"
    # 真正的交易动作仍然必须拦
    for label in ("Place order", "Checkout", "Pay now", "Buy now", "Confirm payment"):
        bad = P({"choice": "e1", "operation": "CLICK", "target": "1"},
                page([A(1, "click", label, 11)]))
        assert not bad.allow, f"交易动作 '{label}' 没被拦下"


@case("零控件但有正文 = 内容页，不是未就绪（f002 实况：/post 的 JSON 回显被无限等待）")
def t_page_not_ready_allows_text_only():
    hist = [{"step": 1, "kind": "click", "choice": "e16", "action": "Submit order",
             "outcome": {"url_changed": True}}]
    # 只有合成控件 + JSON 正文 → 不该等
    echo = page([], url="https://httpbin.org/post")
    echo["text"] = '{"form": {"comments": "hello world"}}'
    assert S.page_not_ready(echo, "Go to /forms/post and submit.", hist) is None, \
        "有正文的零控件页被判成未就绪"
    # 真正空白（无正文、无控件）→ 仍然要等
    blank = page([], url="https://example.test/")
    blank["text"] = ""
    d = S.page_not_ready(blank, "Go to /forms/post and submit.", hist)
    assert d and d["operation"] == "WAIT", "空白页应继续等待"
    # 0 步不判（起始页交给 predict 的重试逻辑）
    assert S.page_not_ready(blank, "x", []) is None


@case("目标要求「选一个 X」而 X 是 radio 组 → 点一个（f004：此前无技能能表达）")
def t_select_option_radio_group():
    goal = "Go to /forms/post and select a size from the dropdown, then submit the form."
    radios = [A(7, "click", "Small", 20, role="radio", name="size", checked="false"),
              A(8, "click", "Medium", 21, role="radio", name="size", checked="false"),
              A(9, "click", "Large", 22, role="radio", name="size", checked="false")]
    p = page(radios, url="https://httpbin.org/forms/post")
    d = S.select_option(p, goal, [])
    assert d and d["operation"] == "CLICK" and d["choice"] == "e7", f"没点第一个 size：{d}"
    assert d["skill"] == "select_option"
    # 已选过 → 前置满足，放行给 form_submit
    done = page([dict(radios[0], checked="true")] + radios[1:], url="https://httpbin.org/forms/post")
    assert S.select_option(done, goal, []) is None, "已经选过还让再选"
    # 目标直接点名选项（"choose Medium"）
    g2 = "Choose Medium for the pizza, then submit."
    d2 = S.select_option(p, g2, [])
    assert d2 and d2["choice"] == "e8", f"按选项标签匹配失败：{d2}"
    # 非 radio 控件不碰
    assert S.select_option(page([A(1, "click", "Submit order", 11)], goal), goal, []) is None


@case("复合目标（导航+滚动）：导航达成即可收口（l002 实况：已达正确文章却跑偏）")
def t_goal_reached_compound_nav_plus_scroll():
    goal = ("Open the Wikipedia 'List of countries by population' article and "
            "scroll to the table.")
    hist = [{"step": 1, "kind": "click", "choice": "e22",
             "action": "List of countries by population", "outcome": {"url_changed": True}}]
    there = {"url": "https://en.wikipedia.org/wiki/List_of_countries_by_population",
             "title": "List of countries by population - Wikipedia",
             "text": "This list ...", "actions": []}
    d = S.goal_reached(there, goal, hist)
    assert d and d["operation"] == "DONE", f"已站在目标文章上却不能收口：{d}"
    # 纯滚动目标不受影响：仍然让位给 stop_when_visible
    pure = "Scroll down the front page until you see at least 20 story links."
    assert S.goal_reached(there, pure, hist) is None, "纯滚动目标被误收口"


@case("form_submit 不点 mailto:/tel: 链接（f001 实况：'Send email' 被当成提交按钮）")
def t_form_submit_skips_non_http():
    goal = "Fill in the form and submit it."
    p = page([A(1, "click", "Send email to the developer", 11, href="mailto:me@example.com"),
              A(2, "click", "Submit order", 12, role="button")],
             url="https://httpbin.org/")
    d = S.form_submit(p, goal, [{"step": 1, "kind": "fill", "choice": "e9", "action": "x"}])
    assert d is not None and d["choice"] == "e2", f"选错了提交目标：{d}"
    # 只有 mailto 候选时宁可不提交
    only = page([A(1, "click", "Send email", 11, href="mailto:a@b.c")],
                url="https://httpbin.org/")
    assert S.form_submit(only, goal, [{"step": 1, "kind": "fill", "choice": "e9", "action": "x"}]) is None, \
        "把 mailto 当成了提交按钮"


@case("复合目标（导航+滚动）的 DONE 不被规则 4 永久否决（l002 实况：跑偏）")
def t_done_guard_compound_scroll_goal():
    from jev_ultrafast.agent import _done_guard
    goal = ("Open the Wikipedia 'List of countries by population' article and "
            "scroll to the table.")
    hist = [{"step": 1, "kind": "click", "choice": "e22",
             "action": "List of countries by population",
             "outcome": {"url_changed": True}}]
    st = {"goal": goal, "history": hist,
          "page": {"url": "https://en.wikipedia.org/wiki/List_of_countries_by_population",
                   "title": "List of countries by population - Wikipedia", "text": ""}}
    assert _done_guard({"operation": "DONE"}, st) is None, \
        "复合目标已到达导航目标却仍被否决"
    # 纯滚动目标：没有滚动动作就不许 DONE（l001 的原保护）
    pure = {"goal": "Scroll down the front page until you see at least 20 story links.",
            "history": [], "page": {"url": "https://news.ycombinator.com/",
                                    "title": "HN", "text": ""}}
    assert _done_guard({"operation": "DONE"}, pure) is not None, "纯滚动目标被误放行"


@case("first_action_floor：第 0 拍 BLOCKED 时挑显著性+goal 重合最高的动作（s005/n004 实况）")
def t_first_action_floor_picks_entry():
    # MDN 首页同构：链接 + 搜索框 + 合成控件。floor 必须选搜索框（textbox > link），
    # 且绝不选合成控件（SYNTH 里的 scroll/wait/reload 不进 indexed_actions）。
    p = page([A(1, "click", "Home", 11, role="link"),
              A(2, "fill", "Search MDN", 12, role="searchbox")],
             url="https://developer.mozilla.org/zh-CN/")
    d = S.first_action_floor(p, "Search MDN for 'fetch'.", [])
    assert d is not None, "有真实控件时 floor 不该放行模型 BLOCKED"
    assert d["choice"] == "e2", f"该选搜索框，选了 {d['choice']}"
    assert d["operation"] == "TYPE_TEXT" and d["skill"] == "first_action_floor"
    # validator 接受（否则 agent 侧会走 StalePage 重试，floor 白搭）
    from jev_ultrafast import decision_validator as _dv
    assert _dv.validate(d, p).valid, "floor 决策未通过 validator"


@case("first_action_floor：只发可执行动作（real-1007 r102/r105 空转教训）")
def t_first_action_floor_executable_only():
    # 无 text 的 TYPE_TEXT / 无值的 SELECT 执行不了 → history 恒空 → 去重失效
    # → 同一决策连发 5 次空转（r102/r105 实况）。floor 现在必须：
    # 1) 全不可执行时让位 None；
    p = page([A(1, "select", "Field to search", 11, role="combobox"),
              A(2, "fill", "Search", 12, role="textbox")], url="https://arxiv.org/")
    d = S.first_action_floor(p, "Open the Releases page of the pytorch/pytorch repository.", [])
    assert d is None, "SELECT 不可发,无派生文本的 fill 也不可发"
    # 2) 跳过不可执行的最高分,取次优 CLICK;
    p2 = page([A(1, "select", "Field to search", 11, role="combobox"),
               A(2, "click", "Login", 12, role="link")], url="https://arxiv.org/")
    d = S.first_action_floor(p2, "Search arXiv for 'Attention Is All You Need'.", [])
    assert d is not None and d["operation"] == "CLICK" and d["choice"] == "e2", \
        f"SELECT 应被跳过、CLICK 兜底：{d}"
    # 3) fill + goal 可派生文本 → TYPE_TEXT **带 text**（不依赖 helper）。
    d = S.first_action_floor(p, "Search arXiv for 'Attention Is All You Need'.", [])
    assert d is not None and d["operation"] == "TYPE_TEXT" and d["choice"] == "e2", \
        f"可派生文本时 fill 仍是首选：{d}"
    assert d.get("text") == "Attention Is All You Need", f"决策必须自带文本：{d}"


@case("first_action_floor：goal 重合加分顶起正确菜单（s005 实况：Web APIs）")
def t_first_action_floor_goal_overlap():
    # MDN 首页没有搜索框（搜索面板要点开才出现），真实路径是 Web APIs 菜单。
    # goal 含 "API" → "Web APIs" 按钮得 +40 重合分，压过并列的其他按钮。
    p = page([A(1, "click", "MDN", 11, role="link"),
              A(2, "click", "HTML", 12, role="button"),
              A(3, "click", "CSS", 13, role="button"),
              A(4, "click", "Web APIs", 14, role="button")],
             url="https://developer.mozilla.org/zh-CN/")
    d = S.first_action_floor(p, "Search MDN for 'fetch' and open the Fetch API reference page.", [])
    assert d is not None and d["choice"] == "e4", \
        f"goal 重合应选中 Web APIs，选了 {d and d['choice']}"


@case("first_action_floor：探索有界——上一拍 floor 改变了世界才继续，超上限即停")
def t_first_action_floor_bounded_exploration():
    p = page([A(1, "click", "HTML", 12, role="button"),
              A(2, "click", "CSS", 13, role="button")],
             url="https://developer.mozilla.org/")
    # 第 1 拍：floor 动作改变了世界 → 继续兜，且**不再点同一个元素**（SPA toggle）
    h1 = [{"step": 1, "kind": "click", "choice": "e1", "skill": "first_action_floor",
           "page_changed": True}]
    d = S.first_action_floor(p, "g", h1)
    assert d is not None, "floor 后世界变了应继续探索"
    assert d["choice"] == "e2", f"已点过的元素被重复选中（toggle 循环）：{d['choice']}"
    # 上一拍 floor 没改变世界 → 停（死控体重试只会 no_effect 循环）
    h2 = [{"step": 1, "kind": "click", "choice": "e1", "skill": "first_action_floor",
           "page_changed": False}]
    assert S.first_action_floor(p, "g", h2) is None
    # 超出 MAX_FLOOR_STEPS → 停
    h3 = [{"step": i, "kind": "click", "choice": f"e{i}", "skill": "first_action_floor",
           "page_changed": True} for i in range(1, 5)]
    assert S.first_action_floor(p, "g", h3) is None
    # 中间插过一次模型决策 → floor 链断，不继续
    h4 = [{"step": 1, "kind": "click", "choice": "e1", "skill": "first_action_floor",
           "page_changed": True},
          {"step": 2, "kind": "click", "choice": "e1", "skill": None,
           "page_changed": True}]
    assert S.first_action_floor(p, "g", h4) is None


@case("first_action_floor：有历史（非 floor 链）/ 零真实控件时一律让位")
def t_first_action_floor_gates():
    p = page([A(1, "fill", "Search MDN", 12, role="searchbox")],
             url="https://developer.mozilla.org/")
    # 已走过一步且不是 floor → BLOCKED 是"看过世界后的判断"，放行
    assert S.first_action_floor(p, "g", [{"step": 1, "kind": "click", "choice": "e1"}]) is None
    # 只有合成控件的页（真空白）→ 没有可探索的东西，放行
    bare = {"url": "https://x.test/", "actions": list(SYNTH)}
    assert S.first_action_floor(bare, "g", []) is None


@case("I 类：导航链接 \"Python\" 不是目标——片段匹配只认从头对齐的缩写（r113）")
def t_explicit_target_fragment_must_be_prefix():
    goal = "Open PEP 8, 'Style Guide for Python Code'."
    # r113 实况：peps 首页可见动作里唯一命中短语的是站标链接 "Python"（"python" 只是
    # 短语中间的词）。旧判据 len(lab_n)>=4 and lab_n in pn 给它 0.9 且无对手 → 直接跳出
    # 任务域名，后面 python.org 站搜、6 步空转全是这一跳的下游。
    peps = page([A(1, "click", "Python", 1, href="https://www.python.org/"),
                 A(2, "click", "PEP Index", 2),
                 A(3, "fill", "Search", 3)], url="https://peps.python.org/")
    d = S.explicit_target(peps, goal, [])
    assert d is None, "中间词片段仍然被当目标：" + str(d)
    # 2026-10-09 反向对照实测（`m2/probe_scroll_reach.py`）：peps 首页文档高 **49432px**，
    # 引号里的 'Style Guide for Python Code' 在**第 3 拍滚动**后进了索引（'8' → pep-0008/），
    # 那一刻 `explicit_target` 自己以 conf 1.0 命中。所以首屏这一拍归有界滚动，不是搜索。
    d = S.route(peps, goal, [])
    assert d and d["skill"] == "scroll_to_named_target", f"首屏这一拍该滚：{d}"
    # 滚不动的页面（快照没有滚动控件）仍然必须由站内搜索接住——这才是原来那条锁的实质：
    # 不许把站标链接 "Python" 当目标跳去 python.org。
    flat = dict(peps)
    flat["actions"] = [a for a in peps["actions"] if a.get("kind") != "scroll"]
    d = S.route(flat, goal, [])
    assert d and d["skill"] == "search_type", f"滚不动时没交给站内搜索：{d}"
    # 从头对齐的缩写仍然认——真实导航标签就是这么截断的
    idx = page([A(1, "click", "Style Guide", 1, href="pep-0008")],
               url="https://peps.python.org/")
    d = S.explicit_target(idx, goal, [])
    assert d and d["choice"] == "e1", f"前缀缩写不该认却不让认：{d}"


@case("J 类：\"From the Django homepage, open …\" 的 homepage 是起点不是目的地（r114）")
def t_goal_reached_origin_frame_is_not_site_goal():
    goal = ("From the Django homepage, open the page titled "
            "'Writing your first Django app, part 1'.")
    acts = [A(1, "click", "Writing your first Django app, part 1", 1),
            A(2, "click", "Writing your first Django app, part 2", 2),
            A(3, "fill", "Search", 3)]
    hist = [{"step": 1, "kind": "fill", "action": "Search", "choice": "e3",
             "text": "Writing your first Django app, part 1",
             "url": "https://www.djangoproject.com/",
             "outcome": {"status": "dom_changed", "page_changed": True}},
            {"step": 2, "kind": "click", "action": "submit", "choice": "e4",
             "url": "https://www.djangoproject.com/",
             "outcome": {"status": "url_changed", "url_changed": True, "page_changed": True}}]
    # 起点首页：标题以 "The" 开头，而 _NAV_OBJ_RE 在 "open the page titled" 上会把
    # obj 退化捕获成 "the" → C1 在起点就判到达。实义词判据必须挡住这一发。
    home = dict(page(acts, url="https://www.djangoproject.com/"),
                title="The Web framework for perfectionists | Django",
                text="Django is a high-level Python web framework.",
                start_url="https://www.djangoproject.com/")
    assert S.goal_reached(home, goal, hist[:1]) is None, "起点页被判为已到达"
    # 已到达：标题逐字写着目标短语，必须收口 DONE（旧判据把 homepage 当目的地 →
    # 到达只认 host → 永远不收，explicit_target 接手点侧栏 part 2 跑偏）
    tut = dict(page(acts, url="https://docs.djangoproject.com/en/6.1/intro/tutorial01/"),
               title="Writing your first Django app, part 1 | Django documentation | Django",
               text="Writing your first Django app, part 1",
               start_url="https://www.djangoproject.com/")
    d = S.route(tut, goal, hist)
    assert d and d["skill"] == "goal_reached" and d["operation"] == "DONE", f"到达页没收口：{d}"
    # 反例必须仍然守住：目的地型的 "open the official X website" 只认 host
    s1 = "Search for 'OpenAI' and open the official OpenAI website."
    res = dict(page([A(21, "click", "OpenAI | Research & Deployment", 21)],
                    url="https://www.google.com/search"),
               title="OpenAI - Google Search", start_url="https://www.google.com")
    assert S.goal_reached(res, s1, [{"step": 1, "kind": "click", "action": "openai",
                                    "choice": "e11"}]) is None, "结果页被判为已到达官网"


@case("L 类：结果页里只有“从头对齐”那一行是被点名那条（r101 pypi 'flask'）")
def t_explicit_target_prefix_row_beats_contains_rows():
    goal = "Use the PyPI search box to search for 'flask' and open the Flask project page."
    # r101 实况（零模型直读 pypi /search/?q=flask 的真实动作表）：结果行从 e21 才开始，
    # 旧判据给 e21 与 e22~e26 **同一个 1.0**（"flask" 既在 "flask …" 也在 "tesseral-flask …"），
    # top-second < 0.15 一触即发 → 地板弃权 → 模型在 0.3~0.5 置信度上连点同一个 target，
    # 三拍 page_changed=False 被 agent.py:723 的无进展判据收尾（b5/b6 都是这个形状）。
    def row(i, name):
        return A(i, "click", f"{name} \n 2026-02-19 13:00:56 A simple framework", i,
                 href=f"/project/{name.lower()}/")
    pypi = page([row(21, "Flask"), row(22, "tesseral-flask"), row(23, "thunderdome-flask"),
                 row(24, "toga-flask")], url="https://pypi.org/search/?q=flask")
    d = S.explicit_target(pypi, goal, [])
    assert d and d["choice"] == "e21", f"前缀行没赢：{d}"
    # 反例①：前缀行排在包含行**后面**也必须赢 —— 证明这一档不是"取列表第一条"
    shuffled = page([row(21, "tesseral-flask"), row(22, "Flask"), row(23, "toga-flask")],
                    url="https://pypi.org/search/?q=flask")
    d = S.explicit_target(shuffled, goal, [])
    assert d and d["choice"] == "e22", f"仍按位置而非按从头对齐取的：{d}"
    # 反例②（边界，钉住"不赌位置"）：两行同为前缀 = 真同分 → 仍然弃权交模型
    both = page([row(21, "Flask"), row(22, "Flask")], url="https://pypi.org/search/?q=flask")
    assert S.explicit_target(both, goal, []) is None, "真同分仍在赌位置"


@case("R 类：目标词在 href 路径段里而不在标签里（r107 HN 首页 label 'new' / href 'newest'）")
def t_explicit_target_matches_on_domain_href_segment():
    goal = "Open the 'newest' stories page from the top navigation."

    def nav(i, label, href):
        return A(i, "click", label, i, href=href)

    # 形如 HN 实测首页：导航链是**无前导斜杠的相对路径**（new -> newest），故事链站外
    hn = page([nav(1, "link", "https://news.ycombinator.com"),
               nav(2, "Hacker News", "news"),
               nav(3, "new", "newest"),
               nav(4, "past", "front"),
               nav(5, "comments", "newcomments"),
               nav(6, "ask", "ask"),
               A(7, "fill", "Search", 70, role="searchbox"),
               nav(8, "Dat-ecosystem: high level applications built on top of P2P protocols",
                   "https://github.com/dat-ecosystem"),
               nav(9, "Some story title", "item?id=41000000")],
              url="https://news.ycombinator.com/")
    d = S.explicit_target(hn, goal, [])
    assert d and d["choice"] == "e3", f"href 段 'newest' 没被认出来：{d}"
    r = S.route(hn, goal, [])
    assert r and r["skill"] == "explicit_target" and r["operation"] == "CLICK" \
        and r["choice"] == "e3", f"route 没把这一拍交给 explicit_target：{r}"

    # 反例①：站外同名片段不与站内同权（goal 说 'newest' 不等于要去别家的 /newest）
    off = page([nav(1, "Sister site", "https://elsewhere.example/newest"),
                nav(2, "new", "newest")], url="https://news.ycombinator.com/")
    assert S.explicit_target(off, goal, [])["choice"] == "e2", "站外同名片段不该与站内同权"

    # 反例②：页面上已有 label 信号时不赌位置——包含档 1.0 与本档差 <0.15 → 弃权
    rival = page([nav(1, "The newest items", "/items"),
                  nav(2, "new", "newest")], url="https://news.ycombinator.com/")
    assert S.explicit_target(rival, goal, []) is None, "有 label 竞争者时本档必须弃权"

    # 反例③：必须**整段相等**，'newcomments' 不是 'newest'
    seg = page([nav(1, "comments", "newcomments"), nav(2, "past", "front")],
               url="https://news.ycombinator.com/")
    assert S.explicit_target(seg, goal, []) is None, "子串匹配会把 'newcomments' 当成目标"

    # 折叠只属于打分，不许漏进短语集合/搜索词（否则 r107 会去搜 'newest'）
    assert S.goal_phrases(goal) == ["newest"], "href 档漏进了短语集合"
    assert S._goal_query(goal) == "newest", "href 档漏进了搜索词"


@case("Q 类：goal 的短语是单数、导航标签是复数时也要认得（r115 'Download Python' → 'Downloads'）")
def t_explicit_target_folds_plural_nav_label():
    goal = "From the Python homepage, open the 'Download Python' releases page."

    def nav(i, label, href):
        return A(i, "click", label, i, href=href)

    home = page([nav(1, "Python", "/"), nav(2, "Docs", "https://docs.python.org"),
                 nav(3, "PyPI", "https://pypi.org/"), nav(4, "Community", "/community/"),
                 nav(5, "News", "/news/"), nav(6, "Events", "/events/"),
                 nav(7, "Success Stories", "/success-stories/"),
                 nav(8, "Downloads", "/downloads/"),
                 A(9, "fill", "Search This Site", 90, role="searchbox"),
                 nav(10, "GO", None)], url="https://www.python.org/")
    # 1) 折叠档要赢：目标链接在首屏可见（零模型探针 m2/probe_second_hop.py 实测 [14]），
    #    改前 explicit_target 在这页上**一个候选都打不出分** → 地板退去填搜索框
    #    （python.org 搜 "Download Python" 第一条结果是 Python 2.1 发布说明，死路）。
    d = S.explicit_target(home, goal, [])
    assert d and d["choice"] == "e8", f"复数标签 'Downloads' 没被认出来：{d}"
    # 2) 路由层面：第一拍必须是 CLICK，不是 fill —— 这正是 r115 预登记判据 #3 的形状
    r = S.route(home, goal, [])
    assert r and r["skill"] == "explicit_target" and r["operation"] == "CLICK", \
        f"route 仍然把第一拍让给搜索框：{r}"
    # 3) 折叠只许折**真复数**：'news'/'News' 去 s 会得到 'new'，与短语 'New York Times'
    #    的首词相等 —— 那不是形态学而是巧合。这条反例把长度门槛钉住。
    times = "From the front page, open the 'New York Times' page."
    n = page([nav(1, "News", "/news/"), nav(2, "New York Times", "/nytimes")],
             url="https://example.com/")
    d = S.explicit_target(n, times, [])
    assert d and d["choice"] == "e2", f"'News' 越过了折叠门槛，抢掉了真目标：{d}"
    n2 = page([nav(1, "News", "/news/")], url="https://example.com/")
    assert S.explicit_target(n2, times, []) is None, "'News' 不该与 'New York Times' 折叠相等"
    # 4) 折叠后同分 = 真同分 → 仍然弃权（沿用 Fix L 的"不赌位置"口径）
    both = page([nav(1, "Downloads", "/downloads/"), nav(2, "Download", "/download/")],
                url="https://example.com/")
    assert S.explicit_target(both, goal, []) is None, "折叠同分仍在赌位置"
    # 5) 放宽不许吃掉更强的信号：精确 2.0 那一行仍然优先
    exact = page([nav(1, "Downloads", "/downloads/"),
                  nav(2, "Download Python", "/downloads/")], url="https://example.com/")
    d = S.explicit_target(exact, goal, [])
    assert d and d["choice"] == "e2", f"折叠档盖过了精确匹配：{d}"
    # 6) 泄漏闸门：折叠只活在 explicit_target 的打分里。要填进搜索框的值、到达判据用的
    #    短语集合都必须还是 goal 的字面量原样。
    assert S._goal_query(goal) == "Download Python", "折叠漏进了搜索词"
    assert S.goal_phrases(goal) == ["Download Python"], "折叠漏进了短语集合"


@case("M 类：goal 里的名词 \"book\" 不该关掉到达判据（r111/r112），守卫本身不许松动")
def t_transaction_guard_noun_book_keeps_arrival_detection():
    det = dict(page([A(1, "click", "Books", 1)],
                    url="https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html"),
               title="Tipping the Velvet | Books to Scrape - Sandbox",
               start_url="https://books.toscrape.com/catalogue/page-1.html")
    g112 = ("On the books.toscrape.com catalogue, open the detail page of "
            "the book 'Tipping the Velvet'.")
    hist = [{"step": 1, "kind": "click", "action": "Tipping the Velvet", "choice": "e1",
             "url": det["url"],
             "outcome": {"status": "url_changed", "page_changed": True, "url_changed": True}}]
    d = S.goal_reached(det, g112, hist)
    assert d and d["operation"] == "DONE" and d["skill"] == "goal_reached", \
        "名词 book 仍被当成交易动词 → 到达页发不出 DONE：" + str(d)
    trav = dict(page([A(1, "click", "Books", 1)],
                     url="https://books.toscrape.com/catalogue/category/books/travel_2/index.html"),
                title="Travel | Books to Scrape - Sandbox",
                start_url="https://books.toscrape.com/catalogue/page-1.html")
    g111 = "On the books.toscrape.com catalogue, open the 'Travel' book category."
    d = S.goal_reached(trav, g111, [{"step": 1, "kind": "click", "action": "Travel",
                                     "choice": "e1", "url": trav["url"],
                                     "outcome": {"status": "url_changed",
                                                 "page_changed": True, "url_changed": True}}])
    assert d and d["operation"] == "DONE", "r111 的到达页同样发不出 DONE：" + str(d)
    # 守卫必须仍然守住**交易动词**：两条反例，任何一条放开都是 false_positive 风险
    book_verb = dict(page([A(1, "click", "Mars", 1)], url="https://air.example.com/mars"),
                     title="Mars", start_url="https://air.example.com/")
    assert S.goal_reached(book_verb, "Book a flight to 'Mars'.",
                          [{"step": 1, "kind": "click", "action": "search", "choice": "e1",
                            "url": "https://air.example.com/mars",
                            "outcome": {"page_changed": True}}]) is None, \
        "\"Book a …\" 仍必须被守卫挡住"
    del_goal = dict(page([A(1, "click", "Earth", 1)],
                         url="https://en.wikipedia.org/wiki/Earth"),
                    title="Earth - Wikipedia", start_url="https://en.wikipedia.org/wiki/Main_Page")
    assert S.goal_reached(del_goal, "Delete the article 'Earth' permanently.",
                          [{"step": 1, "kind": "click", "action": "Earth", "choice": "e1",
                            "url": "https://en.wikipedia.org/wiki/Earth",
                            "outcome": {"page_changed": True}}]) is None, \
        "delete/permanently 守卫不许松动（x002 的语义）"


@case("N 类：守卫放开 book 之后，r110 不能因此提前 DONE（回归防线）")
def t_guard_release_does_not_create_early_done_for_scope_frame():
    # r110 现在就是 PASS（b6 三步到 ch04）。Fix M 放开守卫后它必须**保持原样**：
    # goal "In 'The Rust Programming Language' book, go forward to Chapter 4,
    # 'Understanding Ownership'." 里的引号串是**容器名**（我们已经在书里），不是目的地。
    # 保护来自既有的 nav_verb 判据——"go forward to" 不在 (open|navigate|go to|visit|
    # reach|use) 里，path A/C 全程不触发，所以 book 落地页不会提前收口。
    # 这条用例是回归防线：谁将来给 nav_verb 加 "go to" 的近义变体，必须先过这一关。
    g110 = ("In 'The Rust Programming Language' book, go forward to Chapter 4, "
            "'Understanding Ownership'.")
    hist = [{"step": 1, "kind": "click", "action": "Chapter 4", "choice": "e1",
             "url": "https://doc.rust-lang.org/stable/book/index.html",
             "outcome": {"status": "url_changed", "page_changed": True,
                         "url_changed": True}}]
    landing = dict(page([A(1, "click", "Chapter 4", 1)],
                        url="https://doc.rust-lang.org/stable/book/index.html"),
                   title="The Rust Programming Language",
                   start_url="https://doc.rust-lang.org/stable/")
    assert S.goal_reached(landing, g110, hist) is None, \
        "book 落地页被提前判到达 → r110 从 PASS 变 FAIL"
    # 目的地页标题里容器名和章节名**同时**出现（b6 实况：'Understanding Ownership -
    # The Rust Programming Language'）。这一发也不该由 goal_reached 收——它现在
    # 由模型 DONE + 断言把关，改动前行为必须一致。
    chap = dict(page([A(1, "click", "Next", 1)],
                     url="https://doc.rust-lang.org/stable/book/ch04-00-understanding-ownership.html"),
                title="Understanding Ownership - The Rust Programming Language",
                start_url="https://doc.rust-lang.org/stable/")
    assert S.goal_reached(chap, g110, hist) is None, \
        "章节页的到达判据本就不该由 goal_reached 产出（行为漂移）"
    # 对照：同一页面、同样历史，把 goal 换成显式导航动词 + 引号目的地名，才该收口
    explicit = ("Open 'Understanding Ownership', Chapter 4 of "
                "The Rust Programming Language book.")
    d = S.goal_reached(chap, explicit, hist)
    assert d and d["operation"] == "DONE", f"该收口的导航句没收：{d}"


@case("S 类：goal 引号目标在页面里但不在首屏动作集 → 发一次有界 SCROLL_DOWN（Fix S / r116）")
def t_scroll_to_named_target():
    """实测依据（m2/probe_scroll_reach.py，2026-10-09）：doc.rust-lang.org/stable/ 首屏只索引
    4 个动作（**全是 click**，没有搜索框），'The Cargo Book' 这条链在 +1812px；滚 3 步
    （560px/步）后它进入动作集，`explicit_target` 随即自己命中（conf 1.0）。
    所以这一族的病是**视口覆盖**，不是打分。fixture 的动作形状按探针读数造，不添没有见证的控件。"""
    goal = "From the Rust documentation home, open 'The Cargo Book'."
    below = page([A(1, "click", "The Rust Programming Language", 1,
                    href="book/index.html"),
                  A(2, "click", "Rust API Documentation", 2, href="std/index.html"),
                  A(3, "click", "Get cargo", 3, href="https://other.example/cargo-guide"),
                  A(4, "click", "Other Rust sites", 4, href="otherites.html")],
                 url="https://doc.rust-lang.org/stable/")
    below["text"] = "The Rust Programming Language\nTools and Libraries"
    below["scroll"] = {"y": 0, "height": 3318}
    # 前置事实：这条页面上地板本来什么都做不了（这正是 b14 里模型乱点的原因）
    assert S.explicit_target(below, goal, []) is None, "目标不在首屏时 explicit_target 必须弃权"

    d = S.scroll_to_named_target(below, goal, [])
    assert d is not None and d["operation"] == "SCROLL_DOWN", f"目标在屏下却没滚：{d}"
    assert d["choice"] == "scroll_down" and d["target"] is None, d
    assert d["skill"] == "scroll_to_named_target"
    assert V(d, below).valid, V(d, below).reason

    # 已经在首屏 → 不许抢 explicit_target 的活
    seen = page([A(1, "click", "The Cargo Book", 1, href="cargo/index.html"),
                 A(2, "click", "Rust API Documentation", 2, href="std/index.html")],
                url="https://doc.rust-lang.org/stable/")
    seen["scroll"] = {"y": 1680, "height": 3318}
    assert S.scroll_to_named_target(seen, goal, []) is None, "目标已可见还滚"
    assert S.explicit_target(seen, goal, []) is not None, "首屏命中链没被 explicit_target 认出来"

    # 有界（#47 之后是"两拍"）：滚满 `_PATH_SCROLL_MAX` 还没把目标滚进索引集，
    # 先**把页面还回顶部**（不还的话，视口外的原生搜索控件就永久消失在动作集里 ——
    # r114 在 b15 的死法，`m2/probe_scroll_cost.py` 实测），还过一次之后彻底闭嘴。
    scrolled = [{"step": i, "kind": "scroll", "action": "Scroll down",
                 "choice": "scroll_down"} for i in range(1, S._PATH_SCROLL_MAX + 1)]
    d = S.scroll_to_named_target(below, goal, scrolled)
    assert d is not None and d["operation"] in {"SCROLL_TOP", "SCROLL_UP"}, \
        f"滚满预算后没有把页面还回去：{d}"
    assert d["choice"] in {"scroll_top", "scroll_up"} and d["target"] is None, d
    assert V(d, below).valid, V(d, below).reason
    undone = scrolled + [{"step": 5, "kind": "scroll", "action": "Scroll to top",
                          "choice": d["choice"]}]
    assert S.scroll_to_named_target(below, goal, undone) is None, "还过一次还不停"
    handed_off = scrolled + [{"step": 5, "kind": "click", "action": "The Cargo Book",
                              "choice": "e1", "skill": "explicit_target"}]
    assert S.scroll_to_named_target(below, goal, handed_off) is None, "已经交过棒还去滚"

    # 底部没有 scroll_down 可发（页面已在底）→ 不是本技能的事
    at_bottom = dict(below, actions=[a for a in below["actions"]
                                     if a.get("id") != "scroll_down"])
    assert S.scroll_to_named_target(at_bottom, goal, []) is None

    # goal 没有引号目标 / 只有搜索词形状时不接管
    assert S.scroll_to_named_target(below, "Search for flask and open the project page.",
                                    []) is None
    # 路径类短语归 goto_path（它自带同样的有界滚动），不许两个技能都认领
    assert S.scroll_to_named_target(below, "Go to /forms/post on the site.", []) is None
    # 复合 goal（l002 形状）由别人负责，滚动不许抢
    assert S.scroll_to_named_target(
        below, "Open the Rust book and scroll to the table.", []) is None
    # 表单类 goal 里引号是**字段名/值**，不是导航目标（f005/r120 实况：为 'Test User'
    # 去滚页面会把 fill/submit 整条链拆掉）
    formish = page([A(1, "fill", "Customer name", 1, role="textbox"),
                    A(2, "fill", "Email", 2, role="textbox"),
                    A(3, "click", "Submit", 3, role="button")],
                   url="http://localhost:8765/forms/post")
    formish["scroll"] = {"y": 0, "height": 1400}
    for g in ("Fill the contact form with name 'Test User', email 'test@example.com', "
              "comment 'hello', and submit.",
              "On the httpbin form page, fill the 'Customer name' field with 'jev', "
              "then submit the form."):
        assert S.scroll_to_named_target(formish, g, []) is None, f"表单 goal 被拐去滚：{g}"

    # 产品级接线：这一拍地板**真的**会发滚动（否则技能写得再好也没人调用它）。
    r = S.route(below, goal, [])
    assert r is not None and r["skill"] == "scroll_to_named_target", \
        f"地板链上没有把这一拍交给滚动：{r}"
    # 目标进了首屏后，同一页必须由 explicit_target 接手（不许再滚）
    r2 = S.route(seen, goal, [])
    assert r2 is not None and r2["skill"] == "explicit_target", f"滚到了还滚：{r2}"
    # r116 第一次单任务实测（one-r116-1009-152837）：第 1 拍滚了，第 2 拍滚出来的是
    # 站内搜索框，search_type 把'导航目标名'当查询词打了进去 →
    # doc.rust-lang.org/stable/std/index.html?search=The%20Cargo%20Book（FAIL）。
    # 所以 goal 没要求搜索时，"滚到那条被点名的链"必须排在 fill/search 族之前。
    with_box = page([A(1, "click", "Rust API Documentation", 1, href="std/index.html"),
                     A(2, "fill", "Search through the standard library", 2,
                       role="searchbox")],
                    url="https://doc.rust-lang.org/stable/")
    with_box["scroll"] = {"y": 560, "height": 3318}
    r3 = S.route(with_box, goal, [])
    assert r3 is not None and r3["skill"] == "scroll_to_named_target", \
        f"导航 goal 被站内搜索框拐走：{r3}"
    # 但 goal 自己要求搜索时，搜索族优先（s002 形状不许被本刀动过）
    r4 = S.route(with_box, "Use the site search to find the page about 'asyncio'.", [])
    assert r4 is not None and r4["skill"] != "scroll_to_named_target", r4


# ---------------------------------------------------------------------------
# #59 到站即停：goal 引号里点名的那条链**已经踩过、页也换了** → 不许再为那个短语翻页面
# ---------------------------------------------------------------------------
#
# 六行全部照抄 b24 的 step/decision 事件
# （`logs/real-1011-b24-ipc58-1011-015958/r1xx.jsonl`）：第 1 拍 `explicit_target` 点中
# goal 里的短语、`page_changed=True`、落地页就是断言页；之后 3–4 拍全是
# `scroll_to_named_target` 在到达页上找同一个短语——r123 第 6 拍甚至走到 `search_type`
# （把目标名打进站内搜索框），r142 第 6–8 拍是模型点在陌生人上传的文件链接上。
# 到达页是 `m2/probe_arrival_fixtures.py` 从 b24 的 final_url 抓的**真实快照**。
#
# 关键事实（`m2/real-log.md` 的短语计数表）：goal 的引号短语是**起点页那条链的标签**，
# 不是目的地的标识——r126 的 'SQL Syntax' 在 lang.html 正文里出现 **0** 次。所以任何
# "在到达页上找短语"的判据结构性地不会满足，翻页面只是白翻。
ARRIVAL_ROWS = [
    ("r123", "https://numpy.org/doc/stable/", "To the absolute beginner’s guide",
     "From the NumPy documentation home, open 'To the absolute beginner’s guide'."),
    ("r124", "https://numpy.org/doc/stable/", "API reference",
     "From the NumPy documentation home, open the 'API reference'."),
    ("r126", "https://www.sqlite.org/", "SQL Syntax",
     "From the SQLite home page, open the 'SQL Syntax' page."),
    ("r134", "https://docs.python.org/3/", "Library reference",
     "From the Python documentation home, open the 'Library reference'."),
    ("r142", "https://the-internet.herokuapp.com/", "File Download",
     "From the example list, open the 'File Download' page."),
    ("r148", "https://developer.mozilla.org/en-US/docs/Learn", "Core modules",
     "From the MDN Learn page, open the 'Core modules' section."),
]


def _followed(start_url: str, label: str, landed: str, moved: bool = True) -> list:
    """**结算之后**的历史条目（`agent.py:596-608` 的形状，不是追加那一刻的形状）。

    这条区别是 #59 第一次实盘复跑全线没开火的原因：agent 在观测之后把 `url` 改写成
    落地页，另存 `url_from` 是出发页，"换没换页"记在 `outcome.url_changed` 上。
    我第一版按"历史里的 url 还是出发页"写判据，离线 72/72 全过、实盘一次都不开火。
    """
    return [{
        "step": 1, "kind": "click", "action": label, "operation": "CLICK",
        "url": landed, "url_from": start_url,
        "page_changed": moved,
        "outcome": {"status": "url_changed" if moved else "no_effect",
                    "page_changed": moved, "url_changed": moved},
        "skill": "explicit_target",
    }]


def _arrival_done(d):
    return bool(d and d.get("choice") == "DONE"
                and d.get("skill") == "link_followed_arrival")


@case("#59 到站即停：踩过 goal 点名的链且页已换 → 第一决策必须是 DONE（六行真实到达页）")
def t_link_followed_arrival_stops_the_hunt():
    for tid, start, label, goal in ARRIVAL_ROWS:
        page = fixture("%s_arrival.json" % tid)
        d = S.route(page, goal, _followed(start, label, page["url"]))
        assert d is not None, f"{tid} 到站后地板全体弃权（那一句还是交给模型乱点）"
        assert _arrival_done(d), \
            f"{tid} 到站后还在动手：skill={d.get('skill')} choice={d.get('choice')!r}"


@case("#59 负例：那一拍根本没换页（outcome.url_changed=False）不许 DONE")
def t_arrival_requires_an_actual_page_change():
    tid, start, label, goal = ARRIVAL_ROWS[2]              # r126
    page = {**fixture("r126_arrival.json"), "url": start}   # 还站在起点页那张
    d = S.route(page, goal, _followed(start, label, start, moved=False))
    assert not _arrival_done(d), \
        "站在起点页上假装到了站——DONE 会把没走过的路说成走完了"


@case("#59 负例：已经从落地页走开了（当前页 ≠ 那条历史的落地页）不许 DONE")
def t_arrival_only_speaks_on_the_landing_page():
    tid, start, label, goal = ARRIVAL_ROWS[2]              # r126
    page = {**fixture("r126_arrival.json"), "url": "https://www.sqlite.org/somedownstream"}
    d = S.route(page, goal, _followed(start, label, "https://www.sqlite.org/lang.html"))
    assert not (d and d.get("skill") == "link_followed_arrival"), \
        "落地之后的第三、第四张页上还由到达档说话，它会追认任何一站"


@case("#59 负例：踩的链不是 goal 点名的那条（点到陌生人上传的文件上）不许 DONE")
def t_arrival_requires_the_named_phrase_to_be_the_clicked_link():
    tid, start, _label, goal = ARRIVAL_ROWS[4]             # r142
    page = fixture("r142_arrival.json")
    d = S.route(page, goal, _followed(start, "download-fae92529-3e0b-4b5a-8b0c.txt",
                                     page["url"]))
    assert not (d and d.get("skill") == "link_followed_arrival"), \
        "随便点一条链接都算到站，这个档就成了任意导航的 DONE"


@case("#59 负例：goal 要搜索/填写时不属于导航档（那一族有自己的收口）")
def t_arrival_abstains_when_goal_asks_for_a_search():
    tid, start, label, _goal = ARRIVAL_ROWS[2]             # r126
    page = fixture("r126_arrival.json")
    goal = "Search the site for 'SQL Syntax' and open the first result."
    d = S.route(page, goal, _followed(start, label, page["url"]))
    assert not (d and d.get("skill") == "link_followed_arrival"), \
        "goal 写了 search，到达档不许抢 `search_type` 的活"


@case("#59 负例：跳到**别的站**的链接不算到站（同主机守卫）")
def t_arrival_stays_on_the_same_host():
    tid, _start, label, goal = ARRIVAL_ROWS[2]             # r126
    page = fixture("r126_arrival.json")                    # url 是 sqlite.org/lang.html
    d = S.route(page, goal, _followed("https://example.com/", label, page["url"]))
    assert not (d and d.get("skill") == "link_followed_arrival"), \
        "从别的站点跳过来就 DONE，等于把外链广告页当成任务终点"


@case("#59 负例：历史条目没有出发页（url_from 缺失）时不许猜")
def t_arrival_needs_the_departure_url():
    tid, start, label, goal = ARRIVAL_ROWS[2]              # r126
    page = fixture("r126_arrival.json")
    hist = [{k: v for k, v in h.items() if k != "url_from"}
            for h in _followed(start, label, page["url"])]
    d = S.route(page, goal, hist)
    assert not (d and d.get("skill") == "link_followed_arrival"), \
        "没有出发页就默认同站，守卫等于没有"


@case("#59 负例：第一拍（还没有任何动作）不许 DONE")
def t_arrival_needs_history():
    tid, start, label, goal = ARRIVAL_ROWS[2]              # r126
    page = fixture("r126_arrival.json")
    for hist in ([], [{"step": 1, "kind": "wait", "url": page["url"],
                       "url_from": start, "outcome": {"url_changed": False}}]):
        d = S.route(page, goal, hist)
        assert not (d and d.get("skill") == "link_followed_arrival"), \
            f"history={hist} 时到达档开火了"


@case("#59 负例（b25 的真错）：goal 里**容器**短语被点中时不许 DONE")
def t_arrival_anchors_on_the_destination_phrase_not_the_container():
    # b25 的 r110 逐字（logs/real-1011-b25-fix5960-1011-052452/r110.jsonl）：
    # goal = In 'The Rust Programming Language' book, go forward to Chapter 4,
    #        'Understanding Ownership'.
    # 第 1 拍 explicit_target 点的是**容器**那条链（'The Rust Programming Language'），
    # 落地 book/index.html；目的地是第二个短语。到达档把容器当成终点 → DONE → 该行 FAIL
    # （b24 里这行是 PASS 3 拍：还要再点一次 'Understanding Ownership' 才到 ch04）。
    goal = ("In 'The Rust Programming Language' book, go forward to Chapter 4, "
            "'Understanding Ownership'.")
    page = {"url": "https://doc.rust-lang.org/stable/book/index.html"}
    hist = _followed("https://doc.rust-lang.org/stable/",
                     "The Rust Programming Language", page["url"])
    d = S.link_followed_arrival(page, goal, hist)
    assert d is None, f"容器短语被认成了目的地：{d}"


@case("#59 正例补：同一句 goal，踩中**目的地**短语之后就该 DONE")
def t_arrival_fires_on_the_destination_phrase_of_a_two_phrase_goal():
    goal = ("In 'The Rust Programming Language' book, go forward to Chapter 4, "
            "'Understanding Ownership'.")
    page = {"url": "https://doc.rust-lang.org/stable/book/ch04-00-understanding-ownership.html"}
    hist = _followed("https://doc.rust-lang.org/stable/book/index.html",
                     "Understanding Ownership", page["url"])
    d = S.link_followed_arrival(page, goal, hist)
    assert d and d.get("skill") == "link_followed_arrival", d


@case("#59 负例：goal 里认不出导航动词就不开火（不知道要去哪儿，别说到了）")
def t_arrival_fails_closed_without_a_navigation_verb():
    tid, start, label, _goal = ARRIVAL_ROWS[2]              # r126
    page = fixture("r126_arrival.json")
    hist = _followed(start, label, page["url"])
    for goal in ("The 'SQL Syntax' page exists.", "About 'SQL Syntax'."):
        d = S.link_followed_arrival(page, goal, hist)
        assert d is None, f"没有导航动词的 goal 也开火了：{goal!r}"


@case("#59 负例：导航动词后面没有短语 → 弃权")
def t_arrival_needs_the_phrase_to_follow_the_verb():
    goal = "Open the page, then read the section about books."
    page = {"url": "https://doc.rust-lang.org/stable/book/ch04-00-understanding-ownership.html"}
    hist = _followed("https://doc.rust-lang.org/stable/", "Getting started", page["url"])
    d = S.link_followed_arrival(page, goal, hist)
    assert d is None, "动词之后没有具名终点，到达档却说话"


def main():
    # Windows PowerShell 5.1 的控制台是 GBK，而用例名里有 'ö' 等非 GBK 字符
    # （v1.16 / 源码里的地名）。print 会抛 UnicodeEncodeError 并**中断整个套件**，
    # 让人误以为测试挂了。errors="replace" 保证「最多字符显示成 ?，绝不崩」。
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
        except Exception as e:                              # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
