r"""#73：smoke tier 2 的取题必须**有出处**，同一个 id 不许有两份断言靠目录顺序决定。

改前实测（不是推测）：把 `m1/tasks-laya-19.jsonl`（x001 = `all_of[text_not_contains "booked"]`）
和 `m1/tasks-reachable.jsonl`（x001 = `any_of[text_contains "not available", …]`）的形状放进
同一个临时目录，逐字照跑 `scripts/smoke.ps1` 第 76-84 行那段选取逻辑，打印选中的断言：

    picked x001 assertion.type=all_of

也就是说：**两份定义都在仓里、都合法，闸门跑的是按文件顺序撞上的那一份**，而且没有任何一行
说明它出自哪个文件。`all_of[text_not_contains …]` 在 `example.invalid` 那种按设计不存在的页面上
恒真 ⇒ "死页也判 PASS"（今天 15:44 那轮的 x001 就是 `chrome-error://chromewebdata/`、
steps=0、model_calls=1、象限 true_success，见 `reports/smoke-1013-154436-*.json`）。

运行：python tests/test_smoke_task_provenance.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
import sys                                                   # noqa: E402

sys.path.insert(0, str(REPO))
SPEC = importlib.util.spec_from_file_location("smoke_tasks", REPO / "m2" / "smoke_tasks.py")
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _row(tid, atype, value="booked"):
    return {"task_id": tid, "domain": "example.invalid", "category": "negative",
            "goal": "Book a flight to Mars for next Tuesday.",
            "success_assertion": ({"type": atype, "clauses": [
                {"type": "text_not_contains" if atype == "all_of" else "text_contains",
                 "value": value}]} if atype != "url_matches" else
                {"type": "all_of", "clauses": [{"type": "url_matches", "pattern": "mdn"}]})}


def _write(dirpath, name, rows):
    p = Path(dirpath) / name
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")
    return str(p)


@case("① 钉住的题集是权威：别的文件里同 id 的不同断言只算被遮蔽，并且**打出来**")
def t_pin_is_authority_and_says_so():
    d = tempfile.mkdtemp()
    pin = _write(d, "tasks-laya-19.jsonl", [_row("x001", "all_of")])
    other = _write(d, "tasks-reachable.jsonl", [_row("x001", "any_of", "not available")])
    out = os.path.join(d, "picked.jsonl")
    rc = ST.main(["--out", out, "--ids", "x001", "--pin", pin, "--scan", d])
    assert rc == 0, f"有权威文件在，就不该拒绝出题，实际 rc={rc}"
    rows = [json.loads(l) for l in open(out, encoding="utf-8") if l.strip()]
    assert rows[0]["success_assertion"]["type"] == "all_of", "选中的必须是钉住那份"
    src = ST.collect([pin, other], ["x001"], pin)
    _, conflicts, shadowed = src
    assert conflicts == [] and len(shadowed) == 1, (
        f"两份定义不同却只报了 {len(conflicts)} 冲突 / {len(shadowed)} 遮蔽——"
        "遮蔽不打印出来，下一次还是会当成'目录顺序决定'")


@case("② 没被钉住的 id 在两处断言不同 ⇒ 拒绝出题，且不写出题文件")
def t_unpinned_conflict_refuses():
    d = tempfile.mkdtemp()
    pin = _write(d, "tasks-pin.jsonl", [_row("s005", "url_matches")])
    a = _write(d, "tasks-a.jsonl", [_row("x001", "all_of")])
    b = _write(d, "tasks-b.jsonl", [_row("x001", "any_of", "not available")])
    out = os.path.join(d, "picked.jsonl")
    rc = ST.main(["--out", out, "--ids", "s005,x001", "--pin", pin, "--scan", d])
    assert rc == 2, f"两份互相矛盾又没有权威，必须拒绝，实际 rc={rc}"
    assert not os.path.exists(out), "拒绝出题却写了文件——写出来的那份是按顺序猜的"
    del a, b


@case("③ 请求的 id 谁都没有 ⇒ 也是拒绝，不许静默少出一行")
def t_missing_id_refuses():
    d = tempfile.mkdtemp()
    pin = _write(d, "tasks-laya-19.jsonl", [_row("x001", "all_of")])
    out = os.path.join(d, "picked.jsonl")
    rc = ST.main(["--out", out, "--ids", "x001,r142", "--pin", pin, "--scan", d])
    assert rc == 2, f"缺行应当拒绝（少一行 = 闸门少一格），实际 rc={rc}"


@case("④ 真实仓：5 行都出得来，x001 出自 m1/tasks-laya-19.jsonl，且遮蔽警告恰有一条")
def t_real_repo_shape():
    out = os.path.join(tempfile.mkdtemp(), "picked.jsonl")
    rc = ST.main(["--out", out, "--ids", "s005,n004,x001,x002,r142",
                  "--pin", str(REPO / "m1" / "tasks-laya-19.jsonl"),
                  "--scan", str(REPO / "m1") + "," + str(REPO / "m2")])
    assert rc == 0, f"真实仓里出不了题：rc={rc}"
    rows = [json.loads(l) for l in open(out, encoding="utf-8") if l.strip()]
    by = {r["task_id"]: r for r in rows}
    assert set(by) == {"s005", "n004", "x001", "x002", "r142"}, sorted(by)
    assert by["x001"]["success_assertion"]["type"] == "all_of", (
        "tier 2 的 x001 必须出自那把 19 行尺子，不是 reachable 那份 any_of")
    chosen, conflicts, shadowed = ST.collect(
        [str(REPO / "m1" / "tasks-laya-19.jsonl"), str(REPO / "m1" / "tasks-reachable.jsonl"),
         str(REPO / "m1" / "tasks-skills.jsonl")], ["x001"],
        str(REPO / "m1" / "tasks-laya-19.jsonl"))
    assert len(shadowed) >= 1, (
        "仓里现在确实存在两份 x001（laya-19 的 all_of 与 reachable 的 any_of）——"
        "这条把**现状**钉住：一旦哪天有人删了其中一份，遮蔽数变了，这里会红，"
        "那时应当把 real-log 与 #73 一起改，而不是让尺子悄悄变形")
    del conflicts


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
