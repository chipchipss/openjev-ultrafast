"""Fix S2 回归：每一步都改变了页面的三连滚动，不是死循环（r116 实测，2026-10-09）。

`logs/one-r116-1009-153431/r116.jsonl` 的真形：
  步 1/2/3 = `skill=scroll_to_named_target` 的 SCROLL_DOWN（page_changed True/False/True），
  第 4 拍 = `skill=explicit_target` 的 CLICK e8 → `/cargo/`（决策已经是对的），
  **但没有 step 事件** —— `agent.py` 的 1.5「history 末 3 条 choice 相同 → blocked」
  在执行之前把它杀了，整轮以 `correct_abandon`、`final_url=/stable/` 收口。

1.5 的注释自己写的是"死点重试无用"，而同族 1.5b 早就要求"同一指纹连 5 次"才算死循环。
缺的正是"有没有进展"这一维：滚动的作用就是换掉视口，每步都改页面的滚动按定义不是死点。
例外只给 `kind == "scroll"`，且这三条里至少要有一条 `page_changed is True` ——
click/fill 不放宽：见过的病家（s001 连点"翻译此页"、n004 连填空搜索框）全是无效果重复。

不连浏览器、不调模型：Browser 整个换掉，决策要么用脚本、要么用真地板 `skills.route`。

⑥⑦ 属于下一刀 #47（Fix T）：同一个技能滚完之后必须把页面还回顶部，
否则它会把"本来能解这道题的"视口外控件一起滚走（r114 在 b15 的实测死法）。

运行：python tests/test_scroll_loop.py
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


HOME = "https://doc.rust-lang.org/stable/"
CARGO = "https://doc.rust-lang.org/cargo/"
GOAL = "From the Rust documentation home, open 'The Cargo Book'."


def page(url, fp, labels, y=0, height=3318, links_only=False, fills=()):
    """按真实快照的形状造页：click 动作 + fill 控件 + 合成滚动控件 + wait。

    `fills` 是给 #47（r114 的单向门）用的：真实快照只收录**视口内**的动作
    （`snapshot.js:124`），页头的搜索框在滚下去之后就不在 actions 里了。
    滚动控件同理：`scroll_up/scroll_top` 只在 y>0 时存在（`snapshot.js:158/163`）。
    """
    acts = [{"id": f"e{i}", "kind": "click", "node": i, "role": "link",
             "label": lab, "href": href, "value": ""}
            for i, (lab, href) in enumerate(labels, 1)]
    for j, lab in enumerate(fills, 1):
        acts.append({"id": f"e{len(labels) + j}", "kind": "fill", "node": 500 + j,
                     "role": "textbox", "label": lab, "value": ""})
    acts.append({"id": "scroll_down", "kind": "scroll", "label": "Scroll down",
                 "delta": 560, "node": 900})
    if not links_only:
        acts.append({"id": "scroll_bottom", "kind": "scroll", "label": "Scroll to bottom",
                     "delta": 9999, "node": 901})
        acts.append({"id": "wait", "kind": "wait", "label": "Wait"})
    if y > 0:
        acts.append({"id": "scroll_up", "kind": "scroll", "label": "Scroll up",
                     "delta": -560, "node": 902})
        acts.append({"id": "scroll_top", "kind": "scroll", "label": "Scroll to top",
                     "delta": -y, "node": 903})
    return {
        "url": url, "title": url.rsplit("/", 1)[-1] or url, "text": "Rust documentation",
        "actions": acts, "guards": {}, "fingerprint": fp, "marker": "m",
        "marker_stable": 1, "page_key": [1.0, url, y, 0, 1120, 780],
        "scroll": {"y": y, "height": height}, "w": 1120, "h": 780,
        "omitted_actions": 0,
    }


# r116 实测的首屏：4 个动作里没有任何 'The Cargo Book' / /cargo/ 的影子
ROOT0 = page(HOME, "fp-y0", [("The Rust Programming Language", "the-book/index.html"),
                             ("Rust API Guidelines", "api-guidelines/index.html"),
                             ("The rustc Book", "rustc/index.html"),
                             ("The Standard Library", "std/index.html")], y=0)
# 滚 1 拍（y=560）：多出导航区，仍没有目标
ROOT1 = page(HOME, "fp-y560", [(a["label"], a["href"]) for a in ROOT0["actions"]
                               if a["kind"] == "click"]
              + [("The Edition Guide", "edition-guide/index.html"),
                 ("Contributing", "contrib/index.html")], y=560)
# 滚 2 拍（y=1120）：还没有
ROOT2 = page(HOME, "fp-y1120", [(a["label"], a["href"]) for a in ROOT1["actions"]
                                if a["kind"] == "click"]
              + [("Security", "security/index.html")], y=1120)
# 滚 3 拍（y=1680）：'The Cargo Book' 进视口 —— 单任务 trace 实测的第 4 拍就是这个形状
ROOT3 = page(HOME, "fp-y1680", [(a["label"], a["href"]) for a in ROOT2["actions"]
                                if a["kind"] == "click"]
              + [("The Cargo Book", "cargo/index.html")], y=1680)
DEST = page(CARGO, "fp-cargo", [("Getting Started", "cargo/getting-started/index.html"),
                                 ("Commands", "cargo/commands/index.html")], y=1680)


class ScrollWorld:
    """世界 = 页面队列；滚动走下一页，点击跳到 dest。

    no_effect_at —— 第 i 次滚动**不**换页（真的没效果，page_changed 会记成 False）。
    """

    def __init__(self, pages, dest=None):
        self.pages = list(pages)
        self.i = 0
        self.dest = dest
        self.no_effect_at: set[int] = set()
        self.acts: list = []
        self.closed = False

    @property
    def reality(self):
        return self.pages[self.i]

    def observe(self, screenshot=True):
        return dict(self.reality)

    def act(self, action, page, text=None):
        kind = action.get("kind")
        self.acts.append((kind, action.get("id")))
        n = sum(1 for k, _ in self.acts if k == "scroll")
        if kind == "scroll":
            # 向上的滚动是**撤销**：世界回到那一级页面（#47 的回顶）。
            if action.get("id") in ("scroll_top", "scroll_up"):
                back = 0 if action.get("id") == "scroll_top" else 1
                self.i = max(0, self.i - (len(self.pages) if back == 0 else back))
                return
            if n not in self.no_effect_at and self.i + 1 < len(self.pages):
                self.i += 1
        elif kind == "click" and self.dest is not None:
            self.pages.append(self.dest)
            self.i = len(self.pages) - 1

    def fresh(self, page, action=None):
        return page["fingerprint"] == self.reality["fingerprint"]

    def close(self):
        self.closed = True


def floor_choose(page, goal, history):
    """真地板：`skills.route` 弃权就当模型也没话说（返回 BLOCKED 收口）。"""
    hit = S.route(page, goal, history)
    if hit is not None:
        return hit
    return {"choice": "BLOCKED", "operation": "BLOCKED", "target": None,
            "operation_confidence": 0.6, "target_confidence": None, "confidence": 0.6,
            "probabilities": {"BLOCKED": 1.0}, "latency_ms": 1, "usage": None,
            "skill": None, "reason": "stub"}


def scripted(decision_of):
    """按页造一条固定决策（对照用例用它来保证 choice 逐拍相同）。"""
    def choose(page, goal, history):
        return decision_of(page)
    return choose


def run(world, choose, goal=GOAL, ticks=8, start=HOME):
    S._STUCK.clear()            # 用例之间隔离"技能让位"状态（同一页指纹会被复用）
    A.Browser = lambda url: world
    A.choose = choose
    A.time.sleep = lambda s: None
    ag = A.Agent(start, goal)
    terminal = {"done", "blocked", "budget_exceeded"}
    for _ in range(ticks):
        if ag.state["status"] in terminal:
            break
        ag.command("tick")
        if ag.state["status"] not in terminal and ag.state["status"] != "ready":
            ag.state["status"] = "ready"
    return ag


def reached(ag, url):
    """任务有没有真的落到那张页（history 里的 url 是**动作之后**观测到的）。"""
    return any(h.get("url") == url for h in ag.state["history"])


@case("① r116 真形：连滚 3 拍（每拍都改页面）后，第 4 拍地板的 CLICK 必须被执行")
def t_scroll_triple_with_progress_then_click_executes():
    w = ScrollWorld([ROOT0, ROOT1, ROOT2, ROOT3], DEST)
    ag = run(w, floor_choose)
    kinds = [k for k, _ in w.acts]
    pcs = [h.get("page_changed") for h in ag.state["history"]]
    kill = (ag.state.get("pre_execute") or {}).get("loop_detection")
    assert kinds[:4] == ["scroll", "scroll", "scroll", "click"], (
        f"动作轮廓不是「滚 3 拍再点」：acts={w.acts}，status={ag.state['status']}，"
        f"page_changed={pcs}，loop_detection={kill}")
    assert reached(ag, CARGO), f"点击没落到 /cargo/：{[h.get('url') for h in ag.state['history']]}"


@case("② 对照：三连相同 choice 且**一步都没改页面** → 照旧收口，不许放宽")
def t_no_progress_triple_still_dies():
    w = ScrollWorld([ROOT0, ROOT1, ROOT2, ROOT3], DEST)
    w.no_effect_at = {1, 2, 3}                  # 三次滚动全没动世界
    ag = run(w, floor_choose, ticks=6)
    assert ag.state["status"] == "blocked", (
        f"无进展的三连滚动本该收口，却放行了：status={ag.state['status']}，"
        f"acts={w.acts}")
    assert len(w.acts) == 3, f"死循环里多执行了动作：{w.acts}"


@case("③ 对照：三连相同的 **click**（页面每拍都在变）不享有例外，仍收口")
def t_click_triple_is_not_exempted():
    def click_e1(p):
        a = p["actions"][0]
        return {"choice": a["id"], "operation": "CLICK", "target": "1",
                "operation_confidence": 1.0, "target_confidence": 1.0, "confidence": 1.0,
                "probabilities": {a["id"]: 1.0}, "latency_ms": 0, "usage": None,
                "skill": None, "reason": "stub"}

    class Repeating:
        """每拍都换页（指纹递增），但 choice 恒为 e1 —— s001 的连点形状。"""

        def __init__(self):
            self.pages = [page(HOME, f"fp-{i}",
                               [("Translate this page", "t/index.html")], y=560 * i)
                          for i in range(9)]
            self.i = 0
            self.acts = []
            self.closed = False
            self.dest = None

        @property
        def reality(self):
            return self.pages[self.i]

        def observe(self, screenshot=True):
            return dict(self.reality)

        def act(self, action, page, text=None):
            self.acts.append((action.get("kind"), action.get("id")))
            if self.i + 1 < len(self.pages):
                self.i += 1

        def fresh(self, page, action=None):
            return page["fingerprint"] == self.reality["fingerprint"]

        def close(self):
            self.closed = True

    w = Repeating()
    ag = run(w, scripted(click_e1), ticks=8)
    assert ag.state["status"] == "blocked", (
        f"点击三连被放宽成了放行：status={ag.state['status']}，acts={w.acts}")
    kill = (ag.state.get("pre_execute") or {}).get("loop_detection")
    assert kill and kill.get("reason") == "same_choice_3_times", (
        f"不是 1.5 杀的：{kill}，acts={w.acts}")


@case("④ 三连里夹一步没改页面的也算进展（不许因为一步 False 就判死）")
def t_mixed_page_changed_still_continues():
    w = ScrollWorld([ROOT0, ROOT1, ROOT2, ROOT3], DEST)
    w.no_effect_at = {2}                        # 第 2 拍滚不动（页脚/惯性区），其余都换页
    ag = run(w, floor_choose, ticks=10)
    pcs = [h.get("page_changed") for h in ag.state["history"]]
    kill = (ag.state.get("pre_execute") or {}).get("loop_detection")
    assert pcs[:4] == [True, False, True, True], f"没复现夹一步 False 的混合：{pcs}"
    assert [k for k, _ in w.acts][:5] == ["scroll"] * 4 + ["click"], \
        f"动作轮廓变了：{w.acts}，pc={pcs}"
    assert reached(ag, CARGO), f"点击没落到 /cargo/：{[h.get('url') for h in ag.state['history']]}"


@case("⑤ 有界仍在：滚满 `_PATH_SCROLL_MAX` 仍不见目标 → 地板自己弃权，不靠循环检测兜底")
def t_floor_bounds_its_own_scrolling():
    # 永远没有目标链的站点（r122 rfc-editor 的形状：滚到底也不出现 rfc9110）
    never = [page("https://www.rfc-editor.org/", f"fp-{i}",
                  [("RFC Search", "rfc-editor.org/rfc/"),
                   ("New RFCs", "rfc-editor.org/rfc/"),
                   ("About", "rfc-editor.org/about/")], y=300 * i)
             for i in range(12)]
    w = ScrollWorld(never)
    goal = "Open RFC 9110, 'HTTP Semantics'."
    ag = run(w, floor_choose, goal=goal, ticks=12)
    scrolls = sum(1 for k, _ in w.acts if k == "scroll")
    assert scrolls <= S._PATH_SCROLL_MAX + 1, (
        f"地板滚动越界（回顶那一拍之外）：{scrolls}，acts={w.acts}")


# ---------------------------------------------------------------------------
# ⑥⑦ #47（Fix T）：r114 的"单向门"。
# b15 实测（`logs/real-1009-b15-fixs2-1009-164410/r114.jsonl` + `m2/probe_scroll_cost.py`）：
# django 首屏索引集里有页头 `fill 'Search'`（b14 就是靠 search_type 2 步通关的），
# 而 `scroll_to_named_target` 在 route 序里排在它**前面**；滚过 560px 之后
# 快照不再收录视口外的动作，`fills` 变成 NONE —— campaign 不只是浪费 4 拍，
# 它是把唯一的出路滚出了视口（单向门）。目标链在 y=1120 确实被索引了
# （"Write your first Django app"），但 goal 写的是 'Writing your first Django app,
# part 1'，词重叠 3/6=0.5 → `explicit_target` 认不出，所以"少滚两拍"救不了它。
# 页面在滚下去之后仍然提供 scroll_top/scroll_up（探针实测 undo available: True），
# 所以这扇门是产品自己关的，也得由它自己打开。
# ---------------------------------------------------------------------------

DJHOME = "https://www.djangoproject.com/"
DJ_GOAL = ("From the Django homepage, open the page titled "
           "'Writing your first Django app, part 1'.")
_DJ_TOP_LABELS = [("The Python framework for the perfectionists with deadlines", ""),
                  ("Download", "download/"),
                  ("Latest news", "news/"),
                  ("Dapps", "dapps/")]
# 首屏：页头搜索框在索引集里，目标链不在
DJ0 = page(DJHOME, "fp-dj0", _DJ_TOP_LABELS, y=0, height=3401, fills=("Search",))
DJ1 = page(DJHOME, "fp-dj1", _DJ_TOP_LABELS[1:], y=560, height=3401)
DJ2 = page(DJHOME, "fp-dj2", [("Getting started", ""), ("Documentation", "")],
           y=1120, height=3401)
# 滚出来的那一行：真实标签，与 goal 的引号串只差 "Writing"/"Write" 和一个尾缀
_DJ_MID = [("Documentation", ""), ("Community", ""), ("Blog", ""),
           ("Write your first Django app", "intro/tutorial01/")]
DJ3 = page(DJHOME, "fp-dj3", _DJ_MID, y=1680, height=3401)
DJ4 = page(DJHOME, "fp-dj4", _DJ_MID, y=2240, height=3401)


def _undos(acts):
    return [a for _, a in acts if a in ("scroll_top", "scroll_up")]


@case("⑥ 滚满预算仍认不出目标 → campaign 必须把页面还回顶部，让页头搜索框重新可用")
def t_failed_campaign_gives_the_page_back():
    w = ScrollWorld([DJ0, DJ1, DJ2, DJ3, DJ4])
    ag = run(w, floor_choose, goal=DJ_GOAL, ticks=12, start=DJHOME)
    acts = w.acts
    undo = _undos(acts)
    typed = [a for k, a in acts if k == "fill"]
    assert undo, (
        f"campaign 用完了滚动预算却没有把页面滚回去：页头的搜索框从 y=560 起就不在"
        f"索引集里，`search_type` 从此再也开不了火（r114 在 b15 的死法）。"
        f"acts={acts}，status={ag.state['status']}")
    assert len(undo) == 1, f"撤销必须恰好一次，不许来回滚：{acts}"
    assert typed, f"回到顶部后 `search_type` 没接手：acts={acts}"
    assert acts.index(("scroll", undo[0])) < acts.index(("fill", typed[0])), \
        f"回顶发生在输入之后：{acts}"


@case("⑦ 对照：r116 那种第 3 拍就把目标滚出来的题，本刀一律不多花一拍回顶")
def t_successful_campaign_never_undoes():
    w = ScrollWorld([ROOT0, ROOT1, ROOT2, ROOT3], DEST)
    ag = run(w, floor_choose)
    assert _undos(w.acts) == [], f"成功的 campaign 也去回顶了：{w.acts}"
    assert [k for k, _ in w.acts][:4] == ["scroll", "scroll", "scroll", "click"], w.acts
    assert reached(ag, CARGO), f"点击没落到 /cargo/：{w.acts}"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass
    real_browser, real_choose, real_sleep = A.Browser, A.choose, A.time.sleep
    failed = 0
    try:
        for name, fn in CASES:
            try:
                fn()
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {name}\n      {e}")
            except Exception as e:                            # noqa: BLE001
                failed += 1
                print(f"ERROR {name}\n      {type(e).__name__}: {e}")
            else:
                print(f"ok    {name}")
    finally:
        A.Browser, A.choose, A.time.sleep = real_browser, real_choose, real_sleep
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
