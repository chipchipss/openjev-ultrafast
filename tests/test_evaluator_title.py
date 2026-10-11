"""计划书 2.3 的断言拆分：`--expect-url / --expect-title / --expect-text` 三类独立断言。

为什么现在只有"一个 --expect"不够：`scripts/run_task.py` 把它同时塞进 `url_matches` 和
`text_contains` 再套一层 `any_of`（:95-97）——也就是说**任何一个**证据命中就算 PASS。
2026-10-07 第一个真实任务就是这么翻车的（HN 那次：agent 点进外链，`--expect` 给了
`item` 链接 → MISSING；换成 mistral.ai 才 PASS）。当时结论已经写下
（"给终点证据，不是路径证据"），但接口没改，于是同类误判只能靠人肉记住。

拆完之后每类证据各管各的：
  --expect-url RE      → `url_matches`
  --expect-title STR   → `title_contains`（本文件第 1-3 案；评测器新增）
  --expect-text  STR   → `text_contains`
多条同类之间是 `all_of`（都要成立），不同类型之间也是 `all_of`。
并且**断言永不进模型 prompt**（这条是硬线，APUS 的做法与我们自己的支柱三一致）。

运行：python tests/test_evaluator_title.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast import evaluator as E        # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


PAGE = {"url": "https://example.com/a/b", "title": "Otter – Simple English Wikipedia",
        "text": "The sea otter is a marine mammal.", "actions": [], "fingerprint": "fp",
        "scroll": {}}


def verdict(assertion):
    spec = {"task_id": "t", "category": "positive", "success_assertion": assertion}
    r = E.evaluate(spec, PAGE, [], "done")
    return str(r.result)


@case("title_contains：命中")
def t_title_hit():
    got = verdict({"type": "title_contains", "value": "Wikipedia"})
    assert got == "PASS", f"评测器不认 title_contains（返回 {got!r}）"


@case("title_contains：不命中就 FAIL（不能靠正文救回来）")
def t_title_miss():
    got = verdict({"type": "title_contains", "value": "Zebra"})
    assert got == "FAIL", f"标题不含该词却判 {got!r}——判据没读到 title"


@case("三类断言同时给：必须全成立（all_of），不再是 any_of")
def t_three_kinds_all_required():
    ok = {"type": "all_of", "clauses": [
        {"type": "url_matches", "pattern": r"example\.com/a"},
        {"type": "title_contains", "value": "Otter"},
        {"type": "text_contains", "value": "marine mammal"}]}
    assert verdict(ok) == "PASS"
    weak = {"type": "all_of", "clauses": [
        {"type": "url_matches", "pattern": r"example\.com/a"},
        {"type": "title_contains", "value": "Zebra"},
        {"type": "text_contains", "value": "marine mammal"}]}
    assert verdict(weak) == "FAIL", "标题不命中还能过 = 又回到 any_of 的误判"


@case("断言不进 prompt：喂模型的那几个模块里不许出现 success_assertion")
def t_assertion_never_reaches_prompt():
    # 提示/请求构造在 `model.py`（wire 请求体）与 `questions.py`（题型模板）里；
    # `agent.py` 允许持有 spec —— 它只把 final_page/history 交给 evaluator。
    for rel in ("jev_ultrafast/model.py", "jev_ultrafast/questions.py",
                "jev_ultrafast/decision_validator.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "success_assertion" not in src, f"{rel} 里出现了 success_assertion（断言漏进喂模型的一层）"


@case("CLI 三参数存在且写进 spec（run_task.py）")
def t_cli_has_split_flags():
    src = (REPO / "scripts" / "run_task.py").read_text(encoding="utf-8")
    for flag in ("--expect-url", "--expect-title", "--expect-text"):
        assert flag in src, f"{flag} 还没有"
    assert '"title_contains"' in src, "断言没接上 title_contains"


def main() -> int:
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
