"""t6: r105 最小能力刀（2026-10-17，measured 先行：m2/shape_5rows_2026-10-17.md E 段）。

病家（t4 实测，零模型）：repo 页 /pytorch/pytorch 上有 3 条 /pytorch/pytorch/releases
链接，全在 +894..984px —— 780px 视口折叠线下方，快照只索引视口内动作
（snapshot.js:124），explicit_target 结构性够不到它们；goal 的短语集只有标识
pytorch/pytorch（tests/test_phrases_ident.py ① 钉死），到达判据（goal_reached）在
releases 页本身照常 DONE（t4 T 段），断言 url_matches
github.com/pytorch/pytorch/releases 不动 —— 0-fp 硬约束：不碰任何短语到达判据。

刀：goal 明写 repository（_REPO_CTX_RE，全场 101 题 r105 唯一 witness）、当前 URL
路径就是那个仓库、目标链接（标识 + goal 目的地词都在 href/label 里）不在索引集、
explicit_target 自己弃权、且 y ≤ 334（实测几何：一步 560px 后 +894..984px 的链接
落进 780px 视口 ⇔ y+560 ≤ 894）→ 发一步 SCROLL_DOWN。一发即收。

运行：python tests/test_r105_scroll_target.py    （离线，合成页，零模型）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_ultrafast import skills as S                       # noqa: E402
from jev_ultrafast.decision_validator import validate as V  # noqa: E402

GOAL = "Open the Releases page of the pytorch/pytorch repository."
R122_GOAL = "Open RFC 9110, 'HTTP Semantics'."          # 非 repository goal（0-fp 红线）
R106_GOAL = ("Search Hugging Face for 'ggml-org/Llama-2-7B-GGUF' "
             "and open the model page.")                # 引号 id 档，不受影响


def act(i, kind, label, node, **kw):
    d = {"id": f"e{i}", "node": node, "kind": kind, "label": label}
    d.update(kw)
    return d


def page(url, title, acts, y=0, height=3000):
    p = {"url": url, "title": title, "start_url": "https://github.com/",
         "text": "", "scroll": {"y": y, "height": height}, "actions": list(acts)}
    if y + 780 < height:   # 快照在"下方还有内容"时合成 scroll_down（snapshot.js:157）
        p["actions"].append({"id": "scroll_down", "kind": "scroll",
                             "label": "Scroll down", "delta": 560})
    return p


# 病家页型（t4 E 段）：repo 页，页面上只有导航与 Code/Issues，releases 链在折叠线下
REPO_PAGE = page(
    "https://github.com/pytorch/pytorch",
    "GitHub - pytorch/pytorch: Tensors and CUDA operations",
    [act(1, "click", "Code", 1, role="link", href="/pytorch/pytorch"),
     act(2, "click", "Issues", 2, role="link", href="/pytorch/pytorch/issues")])

# y=560（滚过一步之后）：334 窗口之外，链接仍未进视口 → 不再发（等下一拍再说也不该由
# 本技能连发；实际下一拍 y=560+560=1120 早就过了链接位置吗？不——下一拍链接已可见，
# 由"目标链接在索引集"守卫弃权，explicit_target 点它）
REPO_Y560 = page(
    "https://github.com/pytorch/pytorch",
    "GitHub - pytorch/pytorch: Tensors and CUDA operations",
    [act(1, "click", "Code", 1, role="link", href="/pytorch/pytorch")],
    y=560)

# 目标链接已进索引集（滚完之后的页态）→ explicit_target 的拍，弃权
REPO_WITH_RELEASES = page(
    "https://github.com/pytorch/pytorch",
    "GitHub - pytorch/pytorch: Tensors and CUDA operations",
    [act(1, "click", "Code", 1, role="link", href="/pytorch/pytorch"),
     act(2, "click", "Releases", 2, role="link", href="/pytorch/pytorch/releases")])

# 不是 goal 点名的仓库页（别的仓库 / 站外）→ 弃权
OTHER_REPO = page(
    "https://github.com/numpy/numpy",
    "GitHub - numpy/numpy",
    [act(1, "click", "Code", 1, role="link", href="/numpy/numpy")])

# 到达页：URL 已含 goal 目的地词 → 弃权（goal_reached 的收口面）
RELEASES_PAGE = page(
    "https://github.com/pytorch/pytorch/releases",
    "Releases · pytorch/pytorch",
    [act(1, "click", "pytorch/pytorch", 1, role="link", href="/pytorch/pytorch")])

# 首页（t4 A 段）：标识不在 URL 路径里 → 弃权（原路径不动，不加回归面）
HOMEPAGE = page(
    "https://github.com/",
    "GitHub: Let's build from here",
    [act(1, "click", "Search or jump to, type / to search", 1, role="button"),
     act(2, "fill", "Enter your email", 2, role="textbox")])

# 页面滚不动（快照不给 scroll 控件）→ 弃权，不制造假决策
NO_SCROLL = {"url": "https://github.com/pytorch/pytorch",
             "title": "GitHub - pytorch/pytorch", "start_url": "https://github.com/",
             "text": "", "scroll": {"y": 0, "height": 700},
             "actions": [act(1, "click", "Code", 1, role="link", href="/pytorch/pytorch")]}


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

    # --- 1. 病家：仓库页 y=0、releases 链在折叠线下 → 一步 SCROLL_DOWN ---
    def t_repo_page_scrolls():
        d = S.repo_scroll_target(REPO_PAGE, GOAL, [])
        assert d is not None, "仓库页 y=0 上目标链接在折叠线下，该技能弃权了（修复前行为）"
        assert d["operation"] == "SCROLL_DOWN", f"op={d['operation']!r}"
        assert d["choice"] == "scroll_down", f"choice={d['choice']!r}"
        assert d["target"] is None, "validator 拒绝带 target 的 scroll"
        assert d["skill"] == "repo_scroll_target"
        assert V(d, REPO_PAGE).valid, "决策未通过 validator"

    # --- 2. y=560（窗口外）不再发 ---
    def t_y_out_of_window_abstains():
        assert S.repo_scroll_target(REPO_Y560, GOAL, []) is None

    # --- 3. 目标链接已进索引集 → 弃权（explicit_target 的拍，r116 交接） ---
    def t_target_in_index_hands_off():
        assert S.repo_scroll_target(REPO_WITH_RELEASES, GOAL, []) is None, \
            "目标链接已在索引集还滚动 = 抢 explicit_target 的拍"

    # --- 4. 不是 goal 点名的仓库页 → 弃权 ---
    def t_other_repo_abstains():
        assert S.repo_scroll_target(OTHER_REPO, GOAL, []) is None

    # --- 5. 到达页（URL 已含 releases）→ 弃权 ---
    def t_releases_page_abstains():
        assert S.repo_scroll_target(RELEASES_PAGE, GOAL, []) is None

    # --- 6. 首页（标识不在 URL 路径）→ 弃权，原路径不动 ---
    def t_homepage_abstains():
        assert S.repo_scroll_target(HOMEPAGE, GOAL, []) is None

    # --- 7. 无 scroll 控件 → 弃权，不制造假决策 ---
    def t_no_scroll_control_abstains():
        assert S.repo_scroll_target(NO_SCROLL, GOAL, []) is None

    # --- 8. 有界：历史里有本技能 → 永不再发 ---
    def t_bounded():
        hist = [{"kind": "scroll", "action": "SCROLL_DOWN",
                 "skill": "repo_scroll_target", "choice": "scroll_down"}]
        assert S.repo_scroll_target(REPO_PAGE, GOAL, hist) is None

    # --- 9. 0-fp 红线：非 repository goal（r122 形状）永不触发 ---
    def t_r122_goal_never_fires():
        assert S.repo_scroll_target(REPO_PAGE, R122_GOAL, []) is None, \
            "goal 没写 repository 时接管了（0-fp 红线）"

    # --- 10. 引号 id 档（r106 形状）不受影响：本技能对它照旧弃权 ---
    def t_r106_goal_unaffected():
        hf = page("https://huggingface.co/ggml-org/Llama-2-7B-GGUF",
                  "ggml-org/Llama-2-7B-GGUF · Hugging Face",
                  [act(1, "click", "Files", 1, role="link",
                       href="/ggml-org/Llama-2-7B-GGUF/tree/main")],
                  y=0, height=800)
        assert S.repo_scroll_target(hf, R106_GOAL, []) is None

    # --- 11. route() 穿透：整条链走得到、validator 全过 ---
    def t_route_reaches():
        d = S.route(REPO_PAGE, GOAL, [])
        assert d is not None, "route 没把这一刀交出来"
        assert d["operation"] == "SCROLL_DOWN", f"route op={d['operation']!r}"
        assert V(d, REPO_PAGE).valid

    check("① 仓库页 y=0 折叠线下的 releases → 一步 SCROLL_DOWN", t_repo_page_scrolls)
    check("② y=560（窗口外）不再发", t_y_out_of_window_abstains)
    check("③ 目标链接已进索引集 → 弃权", t_target_in_index_hands_off)
    check("④ 不是 goal 点名的仓库页 → 弃权", t_other_repo_abstains)
    check("⑤ 到达页（URL 已含 releases）→ 弃权", t_releases_page_abstains)
    check("⑥ 首页（标识不在 URL 路径）→ 弃权", t_homepage_abstains)
    check("⑦ 无 scroll 控件 → 弃权", t_no_scroll_control_abstains)
    check("⑧ 有界：一发即收", t_bounded)
    check("⑨ 0-fp：r122 形状 goal 永不触发", t_r122_goal_never_fires)
    check("⑩ 引号 id 档（r106）不受影响", t_r106_goal_unaffected)
    check("⑪ route() 全链穿透 + validator", t_route_reaches)

    print(f"\n{11 - failed}/11 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
