r"""#81：题集里同一个 `task_id` 不许有两份**语义不同**的定义。

触发这件事的是 18:1x 的一次实跑：`scripts/run_one.ps1 -TaskId r139` 拒绝出题，因为 `r139`
在 `m2/tasks_real.jsonl` 与 `m2/tasks_real_100.jsonl` 里都有定义。入口 fail-closed 是对的
（#73 那次 smoke 取题器就是死在"按文件顺序撞上的那份"），但**清点没人做过**，
所以"到底有几对重复、其中有没有真不同"当时没人答得出来。

今天的实测答案（`m2/census_task_ids.py`）：**10 个题集文件、152 个唯一 id、99 个 id 出现在 >1 个文件里，
其中"同 id 不同定义"= 0**。这个测试钉的是**这件事会不会悄悄变坏**：

- 往第二份题集复制一题而改了 goal / url / 断言 ⇒ ②类闸门必须红；
- 但"只是外面套了一层 `all_of[单一子句]`" **不算**两种定义 —— 这条不是我猜的：
  第一版清点就是按字段逐字数，报了 t001 一例"冲突"，逐字段对比后发现两边子句完全相同
  （`history_has_kind: click`），只差那层包装，而 `evaluator._assert_all_of` 对单元素 clauses
  就是返回该子句的结果。③钉住这个等价，谁要改判据得先说服这条测试。

运行：python tests/test_task_id_uniqueness.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SPEC = importlib.util.spec_from_file_location(
    "census_task_ids", REPO / "m2" / "census_task_ids.py")
CT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CT)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _row(tid, goal, url, assertion):
    return {"task_id": tid, "goal": goal, "url": url, "success_assertion": assertion}


def _write(rows, name):
    p = Path(tempfile.mkdtemp()) / name
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")
    return str(p)


@case("① 现役题集的真实读数：99 个重复 id 全是同一定义（0 个语义冲突）")
def t_real_corpus_has_no_conflicting_ids():
    files = CT.task_files()
    seen, same, differ = CT.scan(files)
    assert len(files) >= 10, f"题集文件数变了，这条的锚要重写：{len(files)}"
    assert differ == {}, (
        "出现了同 id 不同定义：" + json.dumps(
            {k: [os.path.basename(o[0]) for o in v] for k, v in differ.items()},
            ensure_ascii=False))
    assert len(same) > 0, "重复本来存在（旧集与新集共用题号），这条不该假装世界干净"


@case("② 闸门会响：同 id 换了断言，就必须被算成冲突")
def t_conflict_is_detected():
    a = _write([_row("tX", "open the page", "https://e.test/",
                     {"type": "all_of", "clauses": [{"type": "text_contains", "value": "A"}]})],
               "tasks-a.jsonl")
    b = _write([_row("tX", "open the page", "https://e.test/",
                     {"type": "all_of", "clauses": [{"type": "text_contains", "value": "B"}]})],
               "tasks-b.jsonl")
    _seen, same, differ = CT.scan([a, b])
    assert list(differ) == ["tX"], f"换了断言却没报冲突（same={list(same)}）——闸门是个摆设"
    assert not same


@case("③ 等价包装不算两种定义（第一版清点在这里误报过 t001）")
def t_single_clause_wrapper_is_not_a_conflict():
    bare = _write([_row("tY", "scroll then submit", "https://e.test/forms",
                        {"type": "history_has_kind", "kind": "click"})], "tasks-bare.jsonl")
    wrapped = _write([_row("tY", "scroll then submit", "https://e.test/forms",
                           {"type": "all_of",
                            "clauses": [{"type": "history_has_kind", "kind": "click"}]})],
                     "tasks-wrapped.jsonl")
    _seen, same, differ = CT.scan([bare, wrapped])
    assert differ == {}, (
        "把等价写法当成了两种定义 ⇒ 清点的红会变成假警报，第一次就是这么错的")
    assert list(same) == ["tY"]
    # 多子句的 all_of 不能一起放过：那才是真的换了判据
    multi = _write([_row("tY", "scroll then submit", "https://e.test/forms",
                         {"type": "all_of", "clauses": [
                             {"type": "history_has_kind", "kind": "click"},
                             {"type": "text_contains", "value": "x"}]})], "tasks-multi.jsonl")
    _s2, _same2, differ2 = CT.scan([bare, multi])
    assert list(differ2) == ["tY"], "两条子句 vs 一条子句被当成了同一定义，判据松了"


@case("④ 单题入口仍然拒绝歧义 id（清点不等于允许猜）")
def t_entry_still_refuses_ambiguous_ids():
    src = (REPO / "scripts" / "run_one.ps1").read_text(encoding="utf-8")
    assert "refusing to guess" in src, "单题入口的 fail-closed 被拆了"
    assert "$hitFiles.Count -gt 1" in src, "入口不再检查『同 id 出现在多个文件』"


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
