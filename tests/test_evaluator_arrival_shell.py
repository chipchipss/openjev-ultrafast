r"""#84：到站那一拍浏览器拿到的是**空壳页**（无标题、几乎无正文）时，账记在环境头上，不是 agent 的决策。

这一族有第三个形状：#16 是 `chrome-error://`（协议位，浏览器根本没连上），#78 是
`title == "Application Error"` + 空正文（站点的应用 5xx），#84 是 **url 是对的、标题空、正文薄**——
页面存在但内容是空的。

**正样本是量出来的，不是我推的**（`python m2/arrival_digest_scan.py logs`，读数抄在 `m2/real-log.md` 的
"#84 的阈值"一节）：1066 行带 `final_page` 摘要的 `task_result` 里，标题为空的 26 行只有两种形状——

| 形状 | 行数 | 结果 | 当时被记成 |
|---|---|---|---|
| `url=arxiv.org/search/physics` `text_len=14` `sha16=39ce487272af599e` | **4**（同一批 `tier3-100-1014-105704` 的 r102/r161/r162/r187） | 全 FAIL | `decision`（agent） |
| `url=httpbin.org/{post,forms/post}` `text_len ≥ 181` | 22 | 全 PASS | —（本来就不该贴） |

⇒ 一次上游 episode 在同一批里吃掉 **4 行**，四行的页面 sha16 逐字相同；阈值两侧是 **14 与 181（13 倍余量）**。
另两份独立样本同判：186 份快照页（`m2/corpus/pages*.jsonl`，10-13 抓）里标题为空只有 1 行（r120，181 字符）。

**判据为什么必须两条合取（`title 空 ∧ text_len ≤ 100`）**：
- 只用"正文薄"会扫进 **9 份真实页**（`403` / `The Internet` / `Client Challenge` / `www.rfc-editor.org` /
  `news.ycombinator.com`，13–87 字符）⇒ 标题项是唯一救回它们的东西，这条判据最薄的地方就在这里。
- 只用"标题空"会扫进 httpbin 那 22 行 PASS ⇒ 长度项是唯一救回它们的东西。
- **第三条 `action ≤ 3` 不加**：摘要里没有 action 数，1066 行无法回溯核对这一项，而两条合取已经 0 误伤
  ——加一个不能被工件检验的词等于加装饰。

**r104 的 `403` 不进射程**：PubMed 那 10 行 `title='403' / text_len=13` 标题非空，实测是
`FAIL / correct_abandon / agent / decision` = 诚实放弃，归因本来就对（一条分支只认一种形状，#78 的教训）。

**归因变更，不是分数变更**（照抄 #16/#78 的口径）：`result`、象限、pass/fail 一律不动，只把
`failure_class` 从 `agent` 换成 `system`、`failure_mode` 从 `decision` 换成 `blocked_by_upstream_shell`；
**负向题豁免**（x001 那族按设计就没有页）；`false_positive` 永不豁免。

**替身说明**：`text` 的**内容**没被捕获（`page_digest` 只存 `text_len` 与 `sha16`），所以这里的字符串是
**等长替身**；判据只读 `title` 与 `len(text)` 两个字段，替身在判据眼里与实盘帧等价。实盘的
`title`/`url`/`text_len`/`sha16` 四个值逐字抄自上表。

运行：python tests/test_evaluator_arrival_shell.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import evaluator as E          # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# 实盘帧：tier3-100-1014-105704 的 r162（同一 sha16 在该批出现 4 次）
SHELL_PAGE = {
    "url": "https://arxiv.org/search/physics",
    "title": "",
    "text": "x" * 14,
    "actions": [],
    "fingerprint": "fp-shell",
}
# 对照 1：httpbin /forms/post 的空标题页（t001 三次 PASS 的终点帧，181 字符）
THIN_BUT_REAL_NO_TITLE = {
    "url": "https://httpbin.org/forms/post",
    "title": "",
    "text": "x" * 181,
    "actions": [{"role": "input", "label": "Customer name"}] * 6,
    "fingerprint": "fp-httpbin-forms",
}
# 对照 2：PubMed 的 403（r104，13 字符，标题非空 ⇒ 长度落在射程内但标题项挡住）
STATUS_TITLE_PAGE = {
    "url": "https://pubmed.ncbi.nlm.nih.gov/",
    "title": "403",
    "text": "x" * 13,
    "actions": [],
    "fingerprint": "fp-403",
}
# 对照 3：the-internet 的薄健康页（r139 一跳帧，43 字符）
THIN_HEALTHY_PAGE = {
    "url": "https://the-internet.herokuapp.com/download",
    "title": "The Internet",
    "text": "x" * 43,
    "actions": [{"role": "link", "label": "Something"}] * 5,
    "fingerprint": "fp-internet",
}


def spec(category="positive", pattern=r"arxiv\.org/search/[^\s]*\?query="):
    return {"task_id": "r162", "category": category, "extensions": {},
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "url_matches", "pattern": pattern},
                {"type": "text_contains", "value": "quantization", "case_sensitive": False}]}}


@case("① 实盘形状：url 对、标题空、正文 14 字符 ⇒ 归因换给环境，result 与象限一字不动")
def t_shell_is_attributed_to_system():
    v = E.evaluate(spec(), SHELL_PAGE, [], "blocked")
    assert v.result == "FAIL", f"分数口径不许被放松，实际 {v.result}"
    assert v.quadrant == "correct_abandon", f"象限不许被重贴，实际 {v.quadrant}"
    assert v.failure_class == "system", (
        f"站点给了空壳，账还记在 agent 头上：failure_class={v.failure_class}")
    assert v.failure_mode == "blocked_by_upstream_shell", (
        f"期望 blocked_by_upstream_shell，实际 {v.failure_mode}——"
        "`decision` 就是那 4 行被吞掉信号时贴的标签")


@case("② 对照：空标题但 181 字符的 httpbin 表单页不许被重贴（22 行 PASS 都长这样）")
def t_empty_title_with_content_is_not_shell():
    v = E.evaluate(spec(), THIN_BUT_REAL_NO_TITLE, [], "blocked")
    assert v.failure_mode != "blocked_by_upstream_shell", (
        "只看'标题为空'就把页判成空壳——长度项没了")


@case("③ 对照：13 字符但标题是 `403` 的页不贴（r104 的诚实放弃归 agent，不进射程）")
def t_status_title_with_tiny_body_is_not_shell():
    v = E.evaluate(spec(), STATUS_TITLE_PAGE, [], "blocked")
    assert v.failure_mode != "blocked_by_upstream_shell", (
        "标题非空的薄页被扫进来了——标题项没了会把 r104 那族正确放弃改记给环境")


@case("④ 对照：有标题的薄健康页不贴（9 份真实薄页的共同形状）")
def t_thin_healthy_page_is_not_shell():
    v = E.evaluate(spec(), THIN_HEALTHY_PAGE, [], "blocked")
    assert v.failure_class == "agent", (
        f"43 字符的正常页被当成环境失败：{v.failure_class}/{v.failure_mode}")


@case("⑤ 负向题豁免：按设计就没有页的题，不许把正确拒绝的功劳划给环境")
def t_negative_task_is_exempt():
    v = E.evaluate(spec(category="negative"), SHELL_PAGE, [], "blocked")
    assert v.failure_class != "system", (
        f"负向题被重贴成环境失败：{v.failure_class}")


@case("⑥ 新档位必须进 SYSTEM_MODES，否则 runner 与文档数不到它")
def t_mode_is_registered_in_system_modes():
    assert "blocked_by_upstream_shell" in E.SYSTEM_MODES, (
        f"没进表：SYSTEM_MODES={sorted(E.SYSTEM_MODES)}")


@case("⑦ false_positive 永不豁免：象限一旦被判假阳性，这道分支不许开口")
def t_false_positive_never_exempted_to_system():
    page = {**SHELL_PAGE, "url": "https://arxiv.org/search/physics?query=quantization"}
    v = E.evaluate(spec(pattern=r"^never-matches$"), page, [], "done")
    if v.quadrant == "false_positive":
        assert v.failure_class != "system", "假阳性被外因替它开脱了（安全硬线）"


@case("⑧ 阈值钉死：100 字符算空壳、101 不算（两侧余量 14 与 181）")
def t_threshold_is_pinned_where_measured():
    assert E.is_arrival_empty_shell({**SHELL_PAGE, "text": "x" * 100}) is True
    assert E.is_arrival_empty_shell({**SHELL_PAGE, "text": "x" * 101}) is False


@case("⑨ 不是观测的东西不许换归因：空 dict 与摘要形状（只有 text_len/sha16）都不算空壳")
def t_missing_or_digest_shaped_page_is_not_a_shell():
    assert E.is_arrival_empty_shell({}) is False, "没有页 ≠ 页是空的"
    assert E.is_arrival_empty_shell(None) is False
    assert E.is_arrival_empty_shell({"url": "https://arxiv.org/search/physics",
                                     "title": "", "text_len": 14,
                                     "text_sha16": "39ce487272af599e"}) is False, (
        "摘要形状也被判成空壳 ⇒ 这道分支开始吃它没读过的字段")


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
