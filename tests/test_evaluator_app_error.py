r"""#78：起点/终点页是**站点自己的应用错误页**时，账记在环境头上，不是 agent 的决策。

#16 关掉之后我以为这一族清干净了；b40 打出了它的第二个形状。

**病灶是两批量出来的（不是我推的）**：`m2/b40_audit.py` 配 b39 时，r196–r200 五行整族掉分，
逐行读 `reports/ci-1013-1544-1013-160343.json`：终页 `title="Application Error"`、`text_len=0`
（sha16 = `da39a3ee5e6b4b0d`，正是**空串的 sha1 前缀** ⇒ 浏览器根本没拿到任何正文）。
`steps=0`、`model_calls=1`，却被记成 `failure_mode=decision / failure_class=agent`。

同一族我往前又扫了一遍**全部已提交报告**（`for f in reports/real-*.json reports/ci-*.json`
逐行比 `evidence.final_title`）：

| 批 | 这五行的形状 | 当时被记成 |
|---|---|---|
| b34（10-12 12:36） | **全中**：title `Application Error` | `decision`（该批 summary 的环境账只数到 3 行） |
| b35/b36/b37/b38/b39 | 全 PASS，title `The Internet` | —（同题在同 build 下的健康态） |
| b40（10-13 16:24） | **全中**：同一形状 | `decision` |

⇒ 这把"b40 分数掉了 5 行"从猜测变成了**可核实的站点状态**：b40 里 16:31 把这五行单跑 **5/5 PASS**
（`reports/rerun-b40-internet-5-1013-163138.json`），同时刻 `curl … the-internet.herokuapp.com/` = **200**；
而且它**不是只发生在今晚**——b34 那次我也是这么读的，只是当时没有这道判据，那 5 行被记在 agent 头上。

**判据为什么是"精确标题 + 空页"两条同时成立**（与 #16 同一条纪律：两侧都要有余量）：
- 只用标题会误伤：Heroku 的这页标题是全站通用的（同页还有别的内容形态），
  而**任何真把话说完了的页都不该被当成"世界没打开"**；带正文的同名页必须走 agent 的账。
- 只用空页会误伤 pypi 首页那种 472 字符 / 12 action 的薄而正常的页（#16 已经踩过一次）。
- 历史全量扫描：`final_title` 恰好等于 `Application Error` 的行**一共 10 行**（b34 5 + b40 5），
  **全部 FAIL、全部 correct_abandon、零 PASS** ⇒ 这道分支不可能给任何一次 PASS 换归因。

**归因变更，不是分数变更**（照抄 #16 的口径）：`result`、象限、pass/fail 一律不动，
只把 `failure_class` 从 `agent` 换成 `system`、`failure_mode` 从 `decision` 换成
`blocked_by_upstream_error`；**负向题豁免**（x001 那族按设计就没有页）；`false_positive` 永不豁免。

运行：python tests/test_evaluator_app_error.py
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


# 实测形状：b40 的 r196 与 b34 的 r196 逐字段一致，这里就存 b40 那一帧
APP_ERROR_PAGE = {
    "url": "https://the-internet.herokuapp.com/",
    "title": "Application Error",
    "text": "",
    "actions": [],
    "fingerprint": "fp-apperr",
}
# 对照：同一批里 the-internet 的健康页（r140 的终点帧，61 字符）
HEALTHY_PAGE = {
    "url": "https://the-internet.herokuapp.com/add_remove_elements/",
    "title": "The Internet",
    "text": "The Internet\nAdd/Remove Elements\nElement touched: Delete",
    "actions": [{"role": "link", "label": "Delete"}] * 4,
    "fingerprint": "fp-ok",
}


def spec(category="positive", pattern=r"herokuapp\.com/context_menu$"):
    return {"task_id": "r196", "category": category, "extensions": {},
            "success_assertion": {"type": "all_of", "clauses": [
                {"type": "url_matches", "pattern": pattern}]}}


@case("① b40/b34 的实盘形状：精确标题 + 空页 ⇒ 归因换给环境，但 result 与象限一字不动")
def t_app_error_is_attributed_to_system():
    v = E.evaluate(spec(), APP_ERROR_PAGE, [], "blocked")
    assert v.result == "FAIL", f"分数口径不许被放松，实际 {v.result}"
    assert v.quadrant == "correct_abandon", f"象限不许被重贴，实际 {v.quadrant}"
    assert v.failure_class == "system", (
        f"世界根本没打开，却还记在 agent 头上：failure_class={v.failure_class}")
    assert v.failure_mode == "blocked_by_upstream_error", (
        f"期望 blocked_by_upstream_error，实际 {v.failure_mode}——"
        "`decision` 就是 b40 里那五行被吞掉信号的那个标签")


@case("② 对照：同站的健康页不许被重贴（这条改前改后都必须绿）")
def t_healthy_page_still_agents_account():
    v = E.evaluate(spec(), HEALTHY_PAGE, [], "blocked")
    assert v.failure_class == "agent", (
        f"61 字符的正常页被当成环境失败了：{v.failure_class}/{v.failure_mode}")


@case("③ 精确标题但**带正文**的同名页 ⇒ 不贴（两条判据必须同时成立）")
def t_same_title_with_content_is_not_marked():
    page = {**APP_ERROR_PAGE, "text": "Application Error\n" + "detail " * 80,
            "actions": [{"role": "link", "label": "Restart"}]}
    v = E.evaluate(spec(), page, [], "blocked")
    assert v.failure_mode != "blocked_by_upstream_error", (
        "只看标题就把页判成'世界没打开'，那是 #16 早就否决过的判据形状")


@case("④ 负向题豁免：按设计就没有页的题，不许把正确拒绝的功劳划给环境")
def t_negative_task_is_exempt():
    v = E.evaluate(spec(category="negative"), APP_ERROR_PAGE, [], "blocked")
    assert v.failure_class != "system", (
        f"负向题被重贴成环境失败（10-11 那份 18/18 假冻结轮就是这颗雷）：{v.failure_class}")


@case("⑤ 新档位必须进 SYSTEM_MODES，否则 runner 与文档数不到它")
def t_mode_is_registered_in_system_modes():
    assert "blocked_by_upstream_error" in E.SYSTEM_MODES, (
        f"没进表：SYSTEM_MODES={sorted(E.SYSTEM_MODES)}")


@case("⑥ false_positive 永不豁免：象限一旦被判假阳性，这道分支不许开口")
def t_false_positive_never_exempted_to_system():
    page = {**APP_ERROR_PAGE, "url": "https://the-internet.herokuapp.com/context_menu"}
    v = E.evaluate(spec(pattern=r"^never-matches$"), page, [], "done")
    if v.quadrant == "false_positive":
        assert v.failure_class != "system", "假阳性被外因替它开脱了（安全硬线）"


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
