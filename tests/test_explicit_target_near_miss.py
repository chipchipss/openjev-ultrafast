r"""#46：`explicit_target` 的词重叠档不许单独开火（r113 的近似行劫持）。

**病灶两页都是当场抓的真实快照**（`m2/probe_r113_scroll_ladder.py`，零模型，逐格往下滚并当场重放地板）：

| tick | scroll.y | 页面上有点得动的 'Style Guide' 行 | `explicit_target` 选的 | 选中的 href |
|---|---|---|---|---|
| 1 | 560 | 只有 `Style Guide for C Code` | 那一行 | `pep-0007/`（**错**）|
| 2 | 1120 | C 与 Python 两行都在 | `Style Guide for Python Code` | `pep-0008/`（对）|

goal 的引号串是 `Style Guide for Python Code`。`'Style Guide for C Code'` 与它
**不是**精确 / 前缀 / 包含 / 从头对齐片段 / 单复数折叠任何一种关系 —— 唯一能给它分数的是最后的
**词重叠档**：4 个实义词命中 3 个（`python` 缺）= 0.75 ⇒ 分数 `0.75 + 0.75/10 = 0.825`，
而地板底部的门槛是 `top[0] ≥ 0.75` 且 `top − second ≥ 0.15`：**页面上只有一行候选时 `second = 0`**，
0.825 一个人就过了 ⇒ 地板把"被点名那一页"的近似行点了。批里的实况就是 3 步：
`scroll → 点 pep-0007 → 点 pep-0008 → DONE`（`logs/ci-1014-1332-1014-135106/r113.jsonl` 与
`logs/ci2-1014-1320-1014-131826/r113.jsonl` 两轮**一字不差**）。

**删这一档而不是加一道守卫的理由，是两条离线读数**：
1. `m2/probe_near_miss_tier_attribution.py`：186 份真实页上 `explicit_target` 非弃权 **71 次**，
   档位分布 = 精确 50 / 前缀 6 / 包含 8 / 从头对齐片段 3 / 单复数折叠 1 / 其它(href·域名) 3，
   **词重叠档 0 次** —— 语料里没有任何一次正确的命中靠它。
2. `m2/golden_tier3.py --compare reports/tier3-golden-1013-233451.json`：把门槛抬到刚好压过它（0.86）之后
   **193 页 / 772 例的摘要一字不动**（`f7e05f70…`）⇒ 这一档在语料上是**死档**。
   （同一份读数的另一面必须写出来：语料 0 例意味着 **golden 抓不到它的回归**，所以这条判据只能靠下面这个测试钉。）

**为什么这样反而更快**：tick 1 弃权后，地板落到 `scroll_to_named_target`（**同一次离线重放里读到的**：
`route(tick1) = SCROLL_DOWN`），再滚一格就是 tick 2 那种"两行都在、精确档 2.0 压住"的页面 ⇒
预测 r113 从 3 步变 2 步。这条预测由单任务实跑裁决，不在这里当结论。

**负向检查（防"为了分数把地板弄哑"）**：第 ⑤ 条要求"从头对齐片段"档（0.9）照样开火 ——
弃权必须是**只对这一档**，不是 `explicit_target` 整体失效。

运行：python tests/test_explicit_target_near_miss.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import skills as S          # noqa: E402

FIX = json.loads((REPO / "m2" / "fixtures" / "r113_near_miss_rows.json")
                 .read_text(encoding="utf-8"))
GOAL = FIX["goal"]
PAGES = {p["tick"]: p for p in FIX["pages"]}
HIST_SCIROLL = [{"choice": "scroll_down", "kind": "scroll", "operation": "SCROLL_DOWN",
                 "url": "https://peps.python.org/", "skill": "scroll_to_named_target"}]

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def label_of_target(page: dict, target: str) -> str:
    for index, act in S.indexed_actions(page.get("actions") or []):
        if index == str(target):
            return str(act.get("label") or "")
    return "<找不到序号>"


def href_of_target(page: dict, target: str) -> str:
    for index, act in S.indexed_actions(page.get("actions") or []):
        if index == str(target):
            return str(act.get("href") or "")
    return ""


@case("① 只看得见近似行的那一页：地板必须弃权（改前它点 pep-0007，这就是红的那一条）")
def t_only_near_miss_row_must_abstain():
    page = PAGES[1]
    pick = S.explicit_target(page, GOAL, HIST_SCIROLL)
    assert pick is None, (
        "近似行被单独开火的词重叠档点了：target=%s label=%r href=%r"
        % (pick.get("target"), label_of_target(page, pick["target"]),
           href_of_target(page, pick["target"])))


@case("② 地板整条不许在这一页上落到 pep-0007（弃权之后交给滚动，不是交给一次点击）")
def t_floor_does_not_click_the_near_miss():
    page = PAGES[1]
    d = S.route(page, GOAL, HIST_SCIROLL)
    if d and d.get("operation") == "CLICK":
        href = href_of_target(page, d.get("target"))
        assert "pep-0007" not in href, (
            "地板在被点名 'Style Guide for Python Code' 之后点向 pep-0007："
            "label=%r" % label_of_target(page, d["target"]))


@case("③ 两行都在的那一页照旧点 Python 那行（改前改后都必须绿 —— 这是对照）")
def t_exact_row_still_wins_when_visible():
    page = PAGES[2]
    pick = S.explicit_target(page, GOAL, HIST_SCIROLL)
    assert pick is not None, "两行都在时精确档必须开火，现在连它也不开了"
    assert href_of_target(page, pick["target"]) == "pep-0008/", (
        "点错行：label=%r" % label_of_target(page, pick["target"]))


@case("④ 点中的必须是**逐字精确**那一档（2.0），不是靠包含或片段侥幸")
def t_winner_is_the_exact_tier():
    page = PAGES[2]
    pick = S.explicit_target(page, GOAL, HIST_SCIROLL)
    assert pick is not None
    assert label_of_target(page, pick["target"]).lower() == "style guide for python code", (
        "被点中的 label 与 goal 引号串逐字不等：%r" % label_of_target(page, pick["target"]))


@case("⑤ 反空转：从头对齐片段档（0.9）不许被一起弄哑")
def t_fragment_tier_still_fires():
    # 同一条 goal，页面只给 'Style Guide'（短语从头对齐的前缀）——那是 0.9 档，不是词重叠档。
    page = dict(PAGES[1])
    page["actions"] = [
        {"id": "x1", "node": 1, "kind": "click", "role": "link",
         "label": "Style Guide", "href": "pep-0008/"},
        {"id": "scroll_down", "node": 2, "kind": "scroll", "label": "Scroll down", "delta": 560},
    ]
    pick = S.explicit_target(page, GOAL, [])
    assert pick is not None, (
        "explicit_target 整条哑了 —— 弃权必须只对词重叠档，不是把地板关掉")
    assert str(pick.get("target")) == "1"


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("ok    " + name)
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print("FAIL  " + name)
            print("      " + f"{type(e).__name__}: {str(e)[:300]}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    raise SystemExit(1 if failed else 0)
