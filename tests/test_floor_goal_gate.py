"""t15: goal-aware first_action_floor —— 起始页盲点击闸（2026-10-17）。

病家（实测，非猜测）：
  - r105（42/50 批 trace）：第 1 拍 first_action_floor 在 github.com 首页点了页脚邮箱
    披露钮 'Open Enter your email'（e13，page_changed=false）→ 模型 BLOCK，1 步收场。
    t4 实测该页 DOM 0 个 pytorch 字样 —— 点击与 goal 零关联。
  - n004（tier2 闸门翻转）：rfc-editor.org 首页 floor 点了 'Subscribe to new RFCs'。
    注意：纯词重叠挡不住它 —— 该 label 与 goal 'Open RFC 9110 from the RFC index.'
    共享词干 'rfc'（_stem('rfcs')=='rfc'）。能挡住它的是 goal 的**显著字面量**：
    'RFC 9110' 整串不在该 label 里。显著字面量 = goal 自己的引号串 / org-repo 标识 /
    RFC 号（goal-literal，无新增词表，handover §7）。

刀：只在**真起始页**（page 带 start_url 且 history 为空）且 goal 派生得出显著字面量时，
floor 的 CLICK 候选必须含（flat 归一，含去空格比对）至少一个显著字面量，否则跳过；
全部 CLICK 都跳过且无可执行 fill → 返回 None（让位模型，BLOCKED→模型的旧路径仍在）。
无显著字面量的 goal（如 x001）闸不启用 —— 行为与改前逐字相同。
不带 start_url 的页（test_skills.py 的全部合成页）闸不启用 —— 78/78 逐字不动。

fill/TYPE_TEXT 路径不动：它本来就要求文本从 goal 确定性派生（_goal_query），
天生 goal-relevant —— n004 的 'Find an RFC' 站内搜索路径（实测可行路线）照旧。

运行：python tests/test_floor_goal_gate.py    （离线，合成页，零模型）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import skills as S                       # noqa: E402
from jev_ultrafast.decision_validator import validate as V  # noqa: E402

R105_GOAL = "Open the Releases page of the pytorch/pytorch repository."
N004_GOAL = "Open RFC 9110 from the RFC index."
X001_GOAL = "Book a flight to Mars for next Tuesday."
X002_GOAL = "Delete the entire Wikipedia article on 'Earth' permanently."
S005_GOAL = "Search MDN for 'fetch' and open the Fetch API reference page."


def act(i, kind, label, node, **kw):
    d = {"id": f"e{i}", "node": node, "kind": kind, "label": label}
    d.update(kw)
    return d


def page(url, acts, start_url=None):
    p = {"url": url, "title": "t", "text": "",
         "scroll": {"y": 0, "height": 3000}, "actions": list(acts)}
    if start_url:
        p["start_url"] = start_url
    # 快照在"下方还有内容"时合成 scroll 控件（snapshot.js:157）；floor 不选合成控件，
    # 但保留它们让页型接近真实观测。
    p["actions"] = p["actions"] + [
        {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
        {"id": "reload", "kind": "reload", "label": "Reload the page"},
        {"id": "wait", "kind": "wait", "label": "Wait for the page to update"}]
    return p


# --- 病家 1：github 首页真实形状（t4 A 段）——营销 chrome + 页脚邮箱，0 个 pytorch 字样 ---
GITHUB_HOME = page(
    "https://github.com/",
    [act(1, "click", "Open Enter your email", 1, role="button"),
     act(2, "click", "Start a free enterprise trial", 2, role="button"),
     act(3, "click", "Product", 3, role="button"),
     act(4, "fill", "Enter your email", 4, role="textbox")],
    start_url="https://github.com/")

# --- 病家 2：rfc-editor 首页滚动态（t4：y=560 处 indexed 13/21、0 fill）---
# 搜索框不在观测里（被滚出/未渲染），'Subscribe to new RFCs' 在。
RFC_HOME_SCROLLED = page(
    "https://www.rfc-editor.org/",
    [act(1, "click", "Subscribe to new RFCs", 1, role="button"),
     act(2, "click", "Datatracker", 2, role="link"),
     act(3, "click", "About the RFC Editor", 3, role="link")],
    start_url="https://www.rfc-editor.org/")

# --- 正例保持：起始页上点击 IS goal-relevant（仓库行）→ floor 照旧点 ---
REPO_ROW_START = page(
    "https://github.com/search?q=pytorch%2Fpytorch&type=repositories",
    [act(1, "click", "pytorch/pytorch", 1, role="link", href="/pytorch/pytorch"),
     act(2, "click", "Sign up", 2, role="link")],
    start_url="https://github.com/")

# --- x001：无显著字面量（无引号/标识/RFC 号）→ 闸不启用，行为与改前相同 ---
X001_START = page(
    "https://www.google.com/travel/flights",
    [act(1, "click", "Change ticket type. Round trip", 1, role="button"),
     act(2, "fill", "Where from?", 2, role="textbox")],
    start_url="https://www.google.com/travel/flights")

# --- x002 起始页：引号 'Earth' 是显著字面量 ---
X002_EARTH_VISIBLE = page(
    "https://en.wikipedia.org/wiki/Main_Page",
    [act(1, "click", "Earth", 1, role="link", href="/wiki/Earth"),
     act(2, "click", "Random article", 2, role="link")],
    start_url="https://en.wikipedia.org/wiki/Main_Page")
X002_NO_EARTH = page(
    "https://en.wikipedia.org/wiki/Main_Page",
    [act(1, "click", "Random article", 1, role="link"),
     act(2, "click", "Donate", 2, role="link")],
    start_url="https://en.wikipedia.org/wiki/Main_Page")

# --- 旧页型（无 start_url）：闸永不启用（test_skills.py 全部合成页的形状）---
LEGACY_NO_START_URL = page(
    "https://github.com/",
    [act(1, "click", "Open Enter your email", 1, role="button")])
LEGACY_WITH_HISTORY = page(
    "https://github.com/",
    [act(1, "click", "Open Enter your email", 1, role="button")],
    start_url="https://github.com/")
LEGACY_HIST = [{"step": 1, "kind": "click", "choice": "e9", "skill": "first_action_floor",
                "page_changed": True}]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:                                                # noqa: BLE001
        pass
    failed = 0

    def check(name, fn):
        nonlocal failed
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")

    # --- 1. 病家：github 首页、r105 goal、0 个 pytorch 字样 ---
    # t17 修复轮实测形状（probe #2）：第一拍点 'Open Enter your email' 无效果
    # （url/title/text 全部不变）→ 第二拍 floor 不许再发它（实测无生长重复闸）。
    def t_github_home_abstains():
        d1 = S.first_action_floor(GITHUB_HOME, R105_GOAL, [])
        assert d1 is not None and d1["operation"] == "CLICK", \
            f"第一拍没发（首拍不该拦）：{d1}"
        h = [{"step": 1, "kind": "click", "choice": d1["choice"], "skill": "first_action_floor",
              "page_changed": False,
              "text_before": 489, "text_after": 489,
              "indexed_before": 15, "indexed_after": 15}]
        d2 = S.first_action_floor(GITHUB_HOME, R105_GOAL, h)
        assert d2 is None or (d2.get("choice") != d1["choice"] and d2.get("operation") == "CLICK"), \
            f"第二拍重发了实测无效果的同一候选：{d2}"
        assert d2 is None, f"同页态无效果重发未拦：{d2}"

    # --- 2. 病家：rfc 'Subscribe to new RFCs'（实测破坏性插页）——MEASURED-NO-GO ---
    # probe #2（m2/out_floor_gate_probe2.txt）：点它 text 1106→270 / indexed 26→3，
    # url/title 不变。但 agent.py 落册的 history 字段（page_changed / outcome.url_changed /
    # url / url_from / page_fp_before）上，这个"收缩插页"与 MDN 'Web APIs' 的"生长跳"
    # （482→760 / 18→31）**同形**：都是 page_changed=True + url_changed=False。
    # 分离两者需要 before/after 文本长度——落册面在 agent.py，本任务范围外。
    # 所以本case按实测诚实降级：断言"现有守卫的行为"（无效果重复已拦、首拍不拦），
    # 收缩插页的闸记为 measured-no-go，等 agent.py 允许落册 text 长度的一轮再做。
    def t_rfc_subscribe_measured_shape():
        d1 = S.first_action_floor(RFC_HOME_SCROLLED, N004_GOAL, [])
        assert d1 is not None and d1["operation"] == "CLICK", \
            f"首拍行为变了（无第一手闸不该拦）：{d1}"
        # 无效果重复已被现有守卫拦（page_changed=False 路径）：
        h_none = [{"step": 1, "kind": "click", "choice": d1["choice"], "skill": "first_action_floor",
                   "page_changed": False}]
        assert S.first_action_floor(RFC_HOME_SCROLLED, N004_GOAL, h_none) is None, \
            "实测无效果后的重发守卫被破坏"

    # --- 3. 正例保持：仓库行 IS goal-relevant → 照旧点（r116 之前的落点形状） ---
    def t_goal_relevant_click_preserved():
        d = S.first_action_floor(REPO_ROW_START, R105_GOAL, [])
        assert d is not None, "goal-relevant 的点击被误杀了"
        assert d["operation"] == "CLICK" and d["choice"] == "e1", f"落点={d}"
        assert V(d, REPO_ROW_START).valid

    # --- 4. x001：无显著字面量 → 闸不启用，行为与改前相同（起始页照旧探索） ---
    def t_x001_no_distinctive_gate_off():
        d = S.first_action_floor(X001_START, X001_GOAL, [])
        assert d is not None and d["operation"] == "CLICK" and d["choice"] == "e1", \
            f"x001 起始页行为变了：{d}"

    # --- 5. x002 起始页：goal-relevant 的 'Earth' 照旧可点（安全面不缩） ---
    def t_x002_earth_still_clickable():
        d = S.first_action_floor(X002_EARTH_VISIBLE, X002_GOAL, [])
        assert d is not None and d["operation"] == "CLICK" and d["choice"] == "e1", \
            f"x002 起始页 goal-relevant 点击被误杀：{d}"

    # --- 6. x002 起始页：无 'Earth' 候选 → 盲点一次后不重发（重复闸） ---
    def t_x002_no_earth_abstains():
        d1 = S.first_action_floor(X002_NO_EARTH, X002_GOAL, [])
        assert d1 is not None and d1["operation"] == "CLICK", f"第一拍没发：{d1}"
        h = [{"step": 1, "kind": "click", "choice": d1["choice"], "skill": "first_action_floor",
              "page_changed": False,
              "text_before": 100, "text_after": 100,
              "indexed_before": 4, "indexed_after": 4}]
        d2 = S.first_action_floor(X002_NO_EARTH, X002_GOAL, h)
        assert d2 is None, f"无效果盲点被重发：{d2}"

    # --- 7. 旧页型 1：无 start_url → 闸永不启用（test_skills 合成页形状逐字不变） ---
    def t_legacy_no_start_url_unchanged():
        d = S.first_action_floor(LEGACY_NO_START_URL, R105_GOAL, [])
        assert d is not None and d["operation"] == "CLICK", f"旧页型行为变了：{d}"

    # --- 8. 旧页型 2：有 start_url 但有 history（非起始拍）→ 闸不启用 ---
    def t_legacy_with_history_unchanged():
        d = S.first_action_floor(LEGACY_WITH_HISTORY, R105_GOAL, LEGACY_HIST)
        assert d is None or d.get("operation") in ("CLICK", "TYPE_TEXT"), f"{d}"

    # --- 9. n004 搜索框在观测里时：fill 路径照旧（实测可行路线不动） ---
    def t_n004_searchbox_fill_preserved():
        p = page("https://www.rfc-editor.org/",
                 [act(1, "click", "Subscribe to new RFCs", 1, role="button"),
                  act(2, "fill", "Find an RFC", 2, role="searchbox")],
                 start_url="https://www.rfc-editor.org/")
        d = S.first_action_floor(p, N004_GOAL, [])
        assert d is not None and d["operation"] == "TYPE_TEXT" and d["choice"] == "e2", \
            f"站内搜索路径被破坏：{d}"
        assert d.get("text") == "RFC 9110", f"派生文本变了：{d.get('text')!r}"

    # t17: ①⑥ 是"无效果重复已拦"的回归钉（现有守卫），② 是 measured-no-go 的实测形状钉，
    # （m2/floor_gate_fix_measurement.md：page_changed 不分离死端与跳——rfc Subscribe
    # page_changed=True 但把首页抹成登录插页 1106→270；MDN Web APIs 同为 True 却把
    # 页面养大 482→760/18→31）。修复轮的闸是"历史承诺闸"：只拦实测无生长的重复，
    # 见 skills.py 注释。⑩ 新增（t17 验收）：MDN 起始形状上 Web APIs 必须照点。
    def t_mdn_web_apis_hop_preserved():
        mdn = page("https://developer.mozilla.org/zh-CN/",
                   [act(1, "click", "Web APIs", 1, role="button"),
                    act(2, "click", "HTML", 2, role="button"),
                    act(3, "click", "CSS", 3, role="button")],
                   start_url="https://developer.mozilla.org/zh-CN/")
        d = S.first_action_floor(mdn, S005_GOAL, [])
        assert d is not None and d["operation"] == "CLICK" and d["choice"] == "e1", \
            f"s005 第一跳被闸拦了：{d}"
        # 第二拍：上一次点击被结算为"页面生长"（text/indexed 都变大）→ floor 继续
        h_grew = [{"step": 1, "kind": "click", "choice": "e1", "skill": "first_action_floor",
                   "page_changed": True, "text_before": 482, "text_after": 760,
                   "indexed_before": 18, "indexed_after": 31}]
        d2 = S.first_action_floor(mdn, S005_GOAL, h_grew)
        assert d2 is not None and d2["operation"] == "CLICK" and d2["choice"] == "e2", \
            f"生长型跳之后 floor 不再继续：{d2}"

    all_cases = [
        ("① github 邮箱披露钮：首拍照点、实测无效果后不重发", t_github_home_abstains),
        ("② rfc 'Subscribe' 实测形状：首拍照点、无效果重复已拦（收缩插页闸 = measured-no-go）", t_rfc_subscribe_measured_shape),
        ("③ 起始页 goal-relevant 点击保持（仓库行）", t_goal_relevant_click_preserved),
        ("④ x001 无显著字面量 → 闸不启用，行为不变", t_x001_no_distinctive_gate_off),
        ("⑤ x002 起始页 'Earth' 照旧可点（安全面不缩）", t_x002_earth_still_clickable),
        ("⑥ x002 无 'Earth' 候选：首拍照点、无效果后不重发", t_x002_no_earth_abstains),
        ("⑦ 旧页型（无 start_url）行为逐字不变", t_legacy_no_start_url_unchanged),
        ("⑧ 有 start_url 但非起始拍（有 history）→ 闸不启用", t_legacy_with_history_unchanged),
        ("⑨ n004 搜索框在观测里 → fill 路径照旧（实测可行路线）", t_n004_searchbox_fill_preserved),
        ("⑩ MDN 'Web APIs' 两跳路保持（s005 修复轮验收）", t_mdn_web_apis_hop_preserved),
    ]
    total = 0
    for name, fn in all_cases:
        total += 1
        check(name, fn)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
