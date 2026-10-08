"""Fix P 回归：动作后的复观察抛 StalePage 时，**不许**把这一步记成"没效果"。

b9 实况（logs/real-1008-b9-fixo-1008-150222，逐条对照决策指纹量出来的）：
  - r116 步#1：地板点 "Rust API documentation"，页面从 /stable/ **真的导航到了**
    /stable/std/index.html（下一拍决策的指纹已换），但历史里写的是
    page_changed=False。后果不是"难看"：skills.py:228 的地板守卫
    `if not floor_hist[-1].get("page_changed"): return None` 就此缴械，
    模型下一拍 BLOCKED(0.693) → 整条任务 1 步收口。
  - r102 步#1：同形（地板点 arxiv 的 "Search"，页也换了，也记成 False）。
  - 对照：b9 全批 52 步里 pc=False 的有 15 步，其中**只有 2 步**是这种误记，
    其余 13 步是真的没效果（"Open …" 折叠开关点下去页面纹丝不动）。
    所以这不是普遍现象，是一个会被当成普遍现象的谎。

根因在记账，不在浏览器：agent.py 的 act 末尾复观察
    try: state["page"] = observe()
    except StalePage: pass          # <- 页面留在**动作前**那个对象
    page_changed = state["page"]["fingerprint"] != page["fingerprint"]
导航中的观测失败 → 两个 fingerprint 必然相同 → False。

修法（两半都是承重的）：
  ① 观测失败时写 None（未知），不是 False —— logger.py:229 早就定义了
     三态语义（"page_changed=None 表示 observe 失败"），是 act 这条路没遵守。
  ② 下一拍 predict 拿到归静的观测后，用该步自己的 page_fp_before **结算**这个 None。
     只有 ① 没有 ② 会把未知一直挂着（evaluator 连数 3 个 None 判 stale_loop）；
     只有 ② 没有 ① 会把"页面后来自己变了"错记到上一个动作头上——
     所以 case ④ 专门钉这条假阳性。

不连浏览器、不调模型：Browser 整个换掉，choose 换成脚本化决策。

运行：python tests/test_page_changed_unknown.py
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


HOME = "https://doc.rust-lang.org/stable/"
NEW = "https://doc.rust-lang.org/stable/std/index.html"


def page(url: str, fp: str, n: int = 1) -> dict:
    acts = [{"id": f"e{i}", "kind": "click", "node": 7 + i, "role": "link",
             "label": f"Link {i}", "value": ""} for i in range(1, n + 1)]
    acts.append({"id": "wait", "kind": "wait", "label": "Wait"})
    return {
        "url": url, "title": url.rsplit("/", 1)[-1], "text": "body",
        "actions": acts, "guards": {}, "fingerprint": fp, "marker": "m",
        "marker_stable": 1, "page_key": [1.0, url, 0, 0, 1120, 780],
        "scroll": {"y": 0, "height": 900}, "w": 1120, "h": 780,
        "omitted_actions": 0,
    }


class FakeBrowser:
    """世界状态 = self.reality；观测 = 从 reality 读，可按调用序号注入失败。

    fail_at      —— 第 i 次 observe 抛 StalePage（导航在途）
    returns_old  —— 第 i 次 observe **成功但返回动作前的旧页**（观测太早）
    navigates    —— act 之后世界是否真的换了一张页
    """

    def __init__(self, start_page):
        self.reality = start_page
        self.next_page = start_page      # act 之后 reality 变成的页
        self.navigates = True
        self.fail_at: set[int] = set()
        self.returns_old: set[int] = set()
        self.old_page = start_page
        self.observes = 0
        self.acted: list = []
        self.closed = False

    def observe(self, screenshot=True):
        i = self.observes
        self.observes += 1
        if i in self.fail_at:
            raise A.StalePage("Document is navigating")
        if i in self.returns_old:
            return dict(self.old_page)
        return dict(self.reality)

    def act(self, action, page, text=None):
        self.acted.append(action)
        if self.navigates:
            self.reality = self.next_page

    def fresh(self, page, action=None):
        return page["fingerprint"] == self.reality["fingerprint"]

    def close(self):
        self.closed = True


def make_choose():
    """每拍点页面上第一个链接；没有可点的就 BLOCKED 收口。"""
    def choose(page_, goal, history):
        links = [a for a in page_["actions"] if a["kind"] == "click"]
        if not links:
            return {"choice": "BLOCKED", "operation": "BLOCKED", "target": None,
                    "operation_confidence": 0.6, "target_confidence": None,
                    "confidence": 0.6, "probabilities": {"BLOCKED": 1.0},
                    "latency_ms": 1, "usage": None, "skill": None, "reason": "stub"}
        a = links[0]
        # action_space 的 target 是"第几个可交互元素"，不是 node 号
        idx = str(links.index(a) + 1)
        return {"choice": a["id"], "operation": "CLICK", "target": idx,
                "operation_confidence": 1.0, "target_confidence": 1.0,
                "confidence": 1.0, "probabilities": {a["id"]: 1.0, "BLOCKED": 0.0},
                "latency_ms": 0, "usage": None, "skill": None, "reason": "stub"}
    return choose


def start(fail_at=(), returns_old=(), navigates=True, hop=1):
    """建一个跑在 FakeBrowser 上的 Agent；不碰 CDP，不碰 :8090。

    hop：每次 act 让世界跳到 NEW 的第几代页（不同指纹）。
    """
    home = page(HOME, "fp-home")
    dest = page(NEW, f"fp-new-{hop}")
    br = FakeBrowser(home)
    br.next_page = dest
    br.navigates = navigates
    br.fail_at = set(fail_at)
    br.returns_old = set(returns_old)
    A.Browser = lambda url: br
    A.choose = make_choose()
    A.time.sleep = lambda s: None
    ag = A.Agent(HOME, "Open the Cargo Book on doc.rust-lang.org.")
    return ag, br


@case("① 复观察撞上导航：这一步不能记成 False（未知就是未知）")
def t_failed_reobserve_is_not_recorded_as_no_effect():
    # observe#0=init（成功），#1=act 后的复观察（抛 StalePage）
    ag, br = start(fail_at={1})
    ag.command("tick")
    h = ag.state["history"][-1]
    assert h["page_changed"] is None, (
        f"观测失败却记了 page_changed={h['page_changed']!r} —— "
        "把未知写成'没效果'就是缴地板的械")


@case("② 下一拍拿到归静观测后必须结算成 True（r116 的形状）")
def t_next_settled_observation_resolves_it_to_true():
    ag, br = start(fail_at={1})
    ag.command("tick")
    ag.command("tick")                       # 重新观察 → 新页 → 结算
    h = ag.state["history"][0]
    assert h["page_changed"] is True, f"导航被结算成了 {h['page_changed']!r}"
    assert h["url"] == NEW, f"结算后历史里还是旧 URL：{h['url']}"
    out = h.get("outcome") or {}
    assert out.get("status") in {"url_changed", "dom_changed"}, f"outcome={out!r}"


@case("③ 负例：复观察成功且页面确实没变 → 照旧 False，不许变成 None/True")
def t_genuine_no_effect_stays_false():
    ag, br = start(navigates=False)          # 折叠开关：点了，世界没动
    ag.command("tick")
    h = ag.state["history"][-1]
    assert h["page_changed"] is False, f"真没效果被改成了 {h['page_changed']!r}"
    assert h["outcome"]["status"] == "no_effect", h["outcome"]


@case("④ 假阳性守卫：观测**成功但太早**返回旧页，后来的变化不算在上一个动作")
def t_later_change_is_not_credited_to_the_action():
    ag, br = start(returns_old={1})          # 世界已导航，但这一拍读到旧页
    ag.command("tick")
    h = ag.state["history"][-1]
    assert h["page_changed"] is False, "可信的观测结果不该被改写成未知"
    ag.command("tick")                       # 下一拍才看到新页
    assert h is ag.state["history"][0]
    assert ag.state["history"][0]["page_changed"] is False, (
        f"后来的页面变化被错记给上一个动作："
        f"{ag.state['history'][0]['page_changed']!r}")


@case("⑤ 未知不许悬挂：结算成 False 也要落地，不给 evaluator 留 None")
def t_unresolved_none_is_always_settled():
    ag, br = start(fail_at={1}, navigates=False)   # 观测失败，但世界其实没变
    ag.command("tick")
    assert ag.state["history"][-1]["page_changed"] is None
    ag.command("tick")
    assert ag.state["history"][0]["page_changed"] is False, (
        f"未知挂成了 {ag.state['history'][0]['page_changed']!r} —— "
        "连数 3 个 None 会被判 stale_loop")


@case("⑥ 导航中的连点不该攒成'连续三次无效果'→blocked")
def t_unknown_does_not_feed_the_no_effect_streak():
    ag, br = start(fail_at={1, 3, 5})        # 每拍 act 后的复观察都撞导航
    for _ in range(3):
        ag.command("tick")
        if ag.state["status"] in {"blocked", "done", "budget_exceeded"}:
            break
        ag.state["status"] = "ready"
        hop = len(ag.state["history"]) + 1
        br.reality = page(NEW, f"fp-hop-{hop}", 2)
        br.next_page = br.reality
    assert ag.state["status"] != "blocked", (
        "三次导航全被记成没效果 → 任务被判死；真实站点里这就是 r116 的死法")
    pcs = [h.get("page_changed") for h in ag.state["history"]]
    assert False not in pcs, f"仍有导航被结算成了没效果：{pcs}"


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
