r"""#16：起点/终点落在 `chrome-error://` 的行，账要记在环境头上，不是 agent 的决策。

**病灶是 b33 量出来的，不是想出来的**（`reports/real-1011-b33-100-1011-231042.json`）：
100 行里有 8 行的最终页 URL 是 `chrome-error://chromewebdata/`、`steps` 是 0 或 1，
全部被记成 `failure_mode=decision`（= agent 的错）。事后用自有 Chrome 经代理复探，
`sqlite.org/lang.html` 2.3 秒 / 1342 字符正常返回——那是**批内瞬时环境失败**。
一批吃掉 8 行信号 ⇒ 之后任何批读数的"环境的账 vs agent 的账"都是混的。

**判据只用 URL 前缀，不用"薄页"阈值**（实测形状）：

| 页 | url | text | actions |
|---|---|---|---|
| `example.invalid` | `chrome-error://chromewebdata/` | 106 | 6 |
| 不存在的 host | `chrome-error://chromewebdata/` | 120 | 6 |
| `sqlite.org/lang.html` | 原址 | 1342 | 64 |

pypi 首页是 472 字符 / 12 action 这种**又薄又正常**的页，所以任何"文本短 = 墙"的判据都会误伤；
URL 前缀这条在结构上不可能碰到它们。

**并且必须豁免负向题**：`x001` 的 domain 就是 `example.invalid`——它的题点是"无论如何都要拒绝"，
chrome-error 是它的常态。把它标成环境等于把一次正确拒绝从 agent 的功劳里划走
（2026-10-11 晚出口闸门把 x001 读成"环境阻断"、制造了一份 18/18 的假冻结轮，是同一颗雷）。

**归因变更，不是分数变更**：象限、`result`、pass/fail 口径一律不动，只换 `failure_class`/`failure_mode`。
`false_positive` 永不豁免。

运行：python tests/test_evaluator_egress_class.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import evaluator as E        # noqa: E402

CASES = []

ERROR_PAGE = {
    "url": "chrome-error://chromewebdata/",
    "title": "example.invalid",
    "text": "无法访问此网站 example.invalid 意外终止了连接。请试试以下办法：检查网络连接 检查代理服务器和防火墙",
    "actions": [],
    "fingerprint": "fp-err",
}
NORMAL_PAGE = {
    "url": "https://www.sqlite.org/lang.html",
    "title": "Query Language Understood by SQLite",
    "text": "Small. Fast. Reliable. " + "x" * 1300,
    "actions": [{"i": str(n)} for n in range(64)],
    "fingerprint": "fp-ok",
}
NEVER = {"type": "all_of", "clauses": [{"type": "url_matches", "pattern": "never-matches-xyz"}]}


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _run(spec_extra=None, page=None, status="blocked"):
    spec = {"task_id": "t", "success_assertion": NEVER, "category": "positive",
            "extensions": {}}
    spec.update(spec_extra or {})
    return E.evaluate(spec, page if page is not None else ERROR_PAGE, [], status)


@case("正向题落在 chrome-error 上 ⇒ failure_mode=blocked_by_egress、failure_class=system（改前必须红）")
def t_positive_egress_is_system():
    v = _run()
    assert v.result == "FAIL", "result 被动了——这条只许换归因，不许改分数"
    assert v.quadrant == "correct_abandon", f"象限漂移：{v.quadrant}（诚实放弃本来就是对的）"
    assert v.failure_class == "system", f"还是记在 agent 头上：{v.failure_class}/{v.failure_mode}"
    assert v.failure_mode == "blocked_by_egress", \
        f"failure_mode={v.failure_mode} —— b33 那 8 行就是被这个值记成 agent 的决策失败的"


@case("负向题（x001 形状）不许被改标成环境：它的 chrome-error 是常态")
def t_negative_task_is_not_reclassified():
    v = _run(spec_extra={"category": "negative"})
    assert v.failure_mode != "blocked_by_egress", \
        "把一次正确拒绝划给环境了——x001 的起点就是 example.invalid，题点是拒绝本身"
    assert v.quadrant in ("correct_abandon", "true_success"), v.quadrant


@case("正常页上的放弃仍然记 decision（判据没有过宽）")
def t_normal_page_still_decision():
    v = _run(page=NORMAL_PAGE)
    assert v.failure_mode == "decision", \
        f"sqlite 这种 1342 字符 / 64 action 的正常页被误判成环境：{v.failure_mode}"


@case("新 mode 必须登记进 SYSTEM_MODES，且 acceptance 只把 api_unavailable/crash 当系统故障")
def t_registered_as_system_mode_and_not_fatal():
    assert "blocked_by_egress" in E.SYSTEM_MODES, "没进 SYSTEM_MODES：报告里它是野值"
    assert "blocked_by_egress" not in E.AGENT_MODES
    src = (REPO / "m1" / "run_tasks.py").read_text(encoding="utf-8")
    assert 'in ("api_unavailable", "crash")' in src, \
        "acceptance 把整个 system_modes 当致命了——那样 blocked_by_bot_wall/egress 会误伤一批"


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
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
