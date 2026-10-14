r"""#88：冻结轮少行必须判 BLOCKED，而不是被当成绿轮继续跑。

缺陷有工件：2026-10-14 21:19 那条阶梯（`m2/real-log.md` 的"L2 重钉的读数"一节）第一轮合并报告
只有 **17 行**（`reports/m1-baseline-1014-2122.json`，`summary.total=17`，缺 `n001`/`n002`，
是出口预检按设计拒跑的），而 `scripts/ci_local.ps1` 照旧打印 `round 1: 17/19 PASS, fp=0`
然后继续跑第二轮和批 —— 因为那段循环只对两件事 Die："没写报告"与 `fp -ne 0`。
纪律②说的"同一个 build 上 19/19 × 3 轮冻结在先"因此**没有脚本守着**。

这一刀的边界（第 6/7/8 案钉住它不许越界）：
- **少行 = BLOCKED（exit 3）**，与 #74/#85 的"没写报告"同一族：既不算过也不算失败；
- **少分 ≠ BLOCKED**：19 行齐全但有 FAIL 是分数红，这一刀不动它，所以判据必须数**行数**
  （题集里的 id 与报告里的 id 求差），不许写成 `$pass -ne 19`；
- 阈值不许被顺手改掉：`MinPass` 的 59/43 与 `MaxWallMinutes` 的 30/14 映射必须原样。

判据与实跑见证写在 `m2/real-log.md`（改前逐案数、两份真实报告直接喂 gate 的输出）。

运行：python tests/test_ci_freeze_gate.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "ci_freeze_gate.ps1"
CI = REPO / "scripts" / "ci_local.ps1"
TASK_SET = REPO / "m1" / "tasks-laya-19.jsonl"
SHORT_REPORT = REPO / "reports" / "m1-baseline-1014-2122.json"   # 17 行那份
FULL_REPORT = REPO / "reports" / "m1-baseline-1014-2135.json"    # 19 行那份

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def freeze_loop(src: str) -> str:
    """取 ci_local 的冻结档那一段（从 for ($r = 1; ... 到 回归批 那一行之前）。"""
    start = src.index('for ($r = 1; $r -le 3; $r++)')
    end = src.index('Log "regression batch')
    return src[start:end]


def task_ids() -> list[str]:
    return [json.loads(l)["task_id"] for l in read(TASK_SET).splitlines() if l.strip()]


@case("闸门必须是独立可喂的一份代码，且 .ps1 全 ASCII（PS 5.1 的 ANSI 陷阱）")
def t_gate_exists_and_ascii():
    assert GATE.exists(), f"{GATE.name} 不存在 —— 判据没有可执行的载体"
    raw = GATE.read_bytes()
    bad = [i for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, f"{GATE.name} 有 {len(bad)} 个非 ASCII 字节（首个在 {bad[0]}），PS 5.1 会把后面的行吃掉"
    src = read(GATE)
    assert re.search(r"function\s+Get-FreezeRowGap", src), "必须暴露一个纯函数，测试与阶梯用同一个判断"


@case("判据数的是行数（题集 id 与报告 id 求差），不是 pass 数")
def t_gate_counts_rows_not_score():
    src = read(GATE)
    assert "ConvertFrom-Json" in src, "闸门要读合并报告本身，不靠日志文本"
    assert re.search(r"task_id", src), "求差要按 task_id"
    assert re.search(r"-notin|-notcontains", src), "缺行必须由 id 集合求差得出"
    assert not re.search(r"\$pass\s+-ne\s+19", src), \
        "写成 `$pass -ne 19` 会把'能力掉一分'和'环境少一行'混成同一档 —— 正是 #16/#78/#84a 在拆的反面"


@case("缺的每一行要分因：preflight / crash_or_unknown / no_dump 三档都要有名字")
def t_gate_classifies_cause():
    src = read(GATE)
    assert re.search(r"\\\[preflight\\\]|\[preflight\]", src), \
        "拒跑原文里就写着 [preflight]，不分因就等于让下一个人重新猜"
    for label in ("preflight", "crash_or_unknown", "no_dump"):
        assert re.search(rf"'{label}'|\"{label}\"", src), f"分因少了 {label} 这一档"


@case("ci_local 的冻结循环必须调用闸门，并以 exit 3（BLOCKED）退出")
def t_ci_local_calls_gate_with_blocked_code():
    loop = freeze_loop(read(CI))
    assert "Get-FreezeRowGap" in loop, "冻结档没有调用闸门 —— 少行的轮仍会被当绿轮"
    m = re.search(r"Get-FreezeRowGap", loop)
    tail = loop[m.end():m.end() + 1200]
    assert re.search(r"\bDie\b", tail), "判定之后必须真的停下来"
    assert re.search(r"Die\b[^\n]*\b3\s*$", tail, re.M), \
        "Die 的码必须是 3（BLOCKED），写成 1 就把它变成了分数失败"


@case("BLOCKED 也要有工件：Die 之前先把缺行与分因写进 verdict JSON")
def t_blocked_verdict_precedes_die():
    loop = freeze_loop(read(CI))
    start = loop.index("if ($gap)")
    branch = loop[start:start + 1400]
    w = re.search(r"Write-JsonNoBom", branch)
    d = re.search(r"\bDie\b", branch)
    assert w, "少行的轮要在 verdict JSON 里看得见（stage/round/missing_ids/missing_causes）"
    assert d, "少行的轮必须真的停下来"
    assert w.start() < d.start(), "先写工件再退出，否则'为什么没跑完'没有出处"
    seg = branch[:d.start() + 400]
    for key in ("stage", "round", "missing_ids", "missing_causes", "passed"):
        assert key in seg, f"blocked verdict 少了 {key} 这一格"
    assert "freeze" in seg, "verdict 必须写明是冻结档拦下的，不是批"


@case("反向守卫：这一刀不许碰分数阈值 59/43 与 30/14")
def t_thresholds_untouched():
    src = read(CI)
    assert re.search(r"\$MinPass = \$\(if \(\$Tasks -ge 100\) \{ 59 \} else \{ 43 \}\)", src), \
        "MinPass 的 50/100 映射被改动了 —— #88 与阈值无关"
    wall_ok = bool(re.search(r"\$MaxWallMinutes\s*=\s*\$?\(if \(\$Tasks -ge 100\) \{ 30 \} else \{ 14 \}\)", src))
    assert wall_ok, "墙钟预算的 50/100 映射被改动了 —— 这一刀与阈值无关"


@case("真实工件（短）：17 行那份缺的必须正是 n001/n002")
def t_short_report_artifact_supports_the_shape():
    ids = task_ids()
    assert len(ids) == 19, f"题集应是 19 行，读到 {len(ids)}"
    rep = json.loads(read(SHORT_REPORT))
    rows = [r.get("task_id") for r in rep["results"]]
    assert len(rows) == 17, f"改前的缺陷读数应可复核：期望 17 行，实际 {len(rows)}"
    missing = sorted(set(ids) - set(rows))
    assert missing == ["n001", "n002"], f"缺的行不正是 n001/n002，而是 {missing}"
    assert rep["summary"]["total"] == 17 and rep["summary"]["false_positive"] == 0


@case("真实工件（全）：19 行那份不许被这条判据判成 BLOCKED")
def t_full_report_is_not_blocked():
    ids = set(task_ids())
    rep = json.loads(read(FULL_REPORT))
    rows = [r.get("task_id") for r in rep["results"]]
    assert len(rows) == 19, f"完整轮应是 19 行，实际 {len(rows)}"
    assert ids == set(rows), f"健康轮的行集合与题集不一致：{sorted(ids ^ set(rows))}"
    assert all((r["result"].get("result") == "PASS") for r in rep["results"]), \
        "这份见证必须是 19/19，否则'不误跳'那条就没证到"


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
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
