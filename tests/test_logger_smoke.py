r"""#68：把 `logger.py` 里那坨 `_smoke()` 夹具搬进 tests/——生产文件只留 Logger 本体。

外部体检报告点验为真的一条规模：`_smoke()` 占 `jev_ultrafast/logger.py` 约三分之二
（591 行里第 323-591 行），而且**没有任何调用方**：`scripts/smoke.ps1` 的 tier 1 只跑
`tests/test_*.py`，所以这 50 项检查一直挂在一个没人执行的 `__main__` 分支上。

搬过来要付的代价说清楚，别偷偷缩水：
- 搬家前 `python -m jev_ultrafast.logger` 报 `SMOKE OK: 50/50`，最后一项检查就是"检查数不少于 50"。
- 每一段编号夹具成为一个 case，失败时能直接说出是哪一段（旧 check() 只 print 一行然后继续跑）。

运行：python tests/test_logger_smoke.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_ultrafast.logger import Logger      # noqa: E402

CASES = []
CHECKS = 0


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def verify(name: str, cond: bool) -> None:
    global CHECKS
    CHECKS += 1
    assert cond, f"检查失败：{name}"


# --- mock 数据（与搬家前逐字一致，动它们等于动被测面） ---
class MockBudget:
    def __init__(self):
        self.transitions = []

    def log_entry(self):
        return {"step": 3, "steps_budget": 20, "steps_ratio": 0.15,
                "model_calls": 4, "model_calls_budget": 40,
                "model_calls_ratio": 0.10, "budget_state": "normal",
                "progress": None}


def step(n, page_changed=True, with_pre=True):
    h = {
        "step": n, "action": f"act{n}", "kind": "click",
        "choice": f"e{n}", "operation": "CLICK", "target": str(n),
        "confidence": 0.9, "probability": 0.9, "latency_ms": 100,
        "text": None, "text_helper": None, "text_latency_ms": 0,
        "page_changed": page_changed, "url": "https://example.com",
        "elapsed_ms": n * 500, "executed_ms": n * 400,
    }
    if with_pre:
        h["pre_execute"] = {
            "step_budget": {"budget_state": "normal"},
            "validator":   {"valid": True, "code": "ok"},
            "policy":      {"allow": True, "code": "ok"},
            "confidence_gate": {"go_teacher": False, "reason": "mode_fixed_high"},
            "escalation":  None,
        }
    return h


def decision(n):
    return {
        "choice": f"e{n}", "operation": "CLICK", "target": str(n),
        "operation_confidence": 0.9, "target_confidence": 0.9,
        "confidence": 0.9, "probabilities": {f"e{n}": 0.9},
        "model": "mock-decider", "latency_ms": 80, "usage": {"total_tokens": 100},
        "fingerprint": f"fp{n}", "elapsed_ms": n * 500,
    }


def text_call(v):
    return {"model": "mock-helper", "field": "Search", "value": v,
            "latency_ms": 40, "usage": {"total_tokens": 20}}


def teacher_entry(n):
    return {
        "step": n,
        "local":   {"choice": "e1", "operation": "CLICK", "target": "1",
                    "operation_confidence": 0.9, "target_confidence": 0.9},
        "teacher": {"choice": "e2", "operation": "CLICK", "target": "2",
                    "operation_confidence": 0.95, "target_confidence": 0.95,
                    "source": "api", "api_model": "mock", "api_confidence": 0.95},
        "agree": False, "operation_match": True, "target_match": False,
        "latency_ms": 500, "usage": {"total_tokens": 100},
        "actions_snapshot": [
            {"id": "e1", "kind": "click", "node": 12, "role": "button", "label": "A"},
            {"id": "e2", "kind": "click", "node": 42, "role": "button", "label": "B"},
        ],
    }


@dataclass
class FakeTaskResult:
    task_id: str
    result: str
    quadrant: str | None
    failure_class: str | None
    failure_mode: str | None
    evidence: dict
    meta: dict


@case("1. 空 state：不产事件，也不提前建文件")
def t_empty_state():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t000", Path(tmp) / "logs", flush_every=64) as lg:
            verify("empty state -> no events", lg.observe({}) == [])
            verify("no file before finalize", not lg.log_path.exists())


@case("2. 单步 observe 与重复 observe（游标）")
def t_single_step_and_cursor():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t001", Path(tmp) / "logs", flush_every=64) as lg:
            state = {"history": [step(1)], "decisions": [], "text_calls": []}
            ev1 = lg.observe(state)
            verify("single step -> 1 event", len(ev1) == 1)
            verify("step event type", ev1[0]["event"] == "step")
            verify("step carries pre_execute", "pre_execute" in ev1[0])
            verify("step page_changed True", ev1[0]["page_changed"] is True)
            verify("repeat observe -> 0 events", lg.observe(state) == [])


@case("3. 增量：新追加的 history/decisions 各自只抽一次")
def t_incremental():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t002", Path(tmp) / "logs") as lg:
            state = {"history": [step(1)], "decisions": [decision(1)], "text_calls": []}
            lg.observe(state)
            state["history"].append(step(2))
            state["decisions"].append(decision(2))
            types = [e["event"] for e in lg.observe(state)]
            verify("incremental: 1 step", types.count("step") == 1)
            verify("incremental: 1 decision", types.count("decision") == 1)


@case("4. decisions / text_calls 各自成事件并带字段")
def t_decisions_and_text_calls():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t003", Path(tmp) / "logs") as lg:
            state = {
                "history": [step(1, with_pre=False)],
                "decisions": [decision(1)],
                "text_calls": [text_call("OpenAI"), text_call("hello")],
            }
            ev = lg.observe(state)
            types = [e["event"] for e in ev]
            verify("1 step", types.count("step") == 1)
            verify("1 decision", types.count("decision") == 1)
            verify("2 text_calls", types.count("text_call") == 2)
            tc = next(e for e in ev if e["event"] == "text_call")
            verify("text_call value", tc["value"] in ("OpenAI", "hello"))
            verify("text_call model", tc["model"] == "mock-helper")


@case("5. budget_transition：抽取、游标、再增量")
def t_budget_transition():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t004", Path(tmp) / "logs") as lg:
            budget = MockBudget()
            budget.transitions = [
                {"event": "budget_transition", "from": "normal", "to": "warn",
                 "step": 10, "model_calls": 12, "limiting": "steps"},
                {"event": "budget_transition", "from": "warn", "to": "degrade",
                 "step": 16, "model_calls": 20, "limiting": "steps"},
            ]
            ev = lg.observe({}, step_budget=budget)
            verify("2 transitions extracted", len(ev) == 2)
            verify("transition event type", ev[0]["event"] == "budget_transition")
            verify("transition to warn", ev[0]["to"] == "warn")
            verify("transition limiting", ev[0]["limiting"] == "steps")
            verify("transition cursor works", lg.observe({}, step_budget=budget) == [])

            budget.transitions.append(
                {"event": "budget_transition", "from": "degrade", "to": "abort",
                 "step": 20, "model_calls": 25, "limiting": "steps"}
            )
            ev3 = lg.observe({}, step_budget=budget)
            verify("incremental transition", len(ev3) == 1)
            verify("transition to abort", ev3[0]["to"] == "abort")


@case("6. finalize：task_result 带 final_budget / final_page")
def t_finalize():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t005", Path(tmp) / "logs") as lg:
            lg.observe({"history": [step(1)], "decisions": [], "text_calls": []})
            result = FakeTaskResult(
                task_id="t005", result="PASS", quadrant="true_success",
                failure_class=None, failure_mode=None,
                evidence={"final_url": "https://example.com/ok"},
                meta={"steps": 1, "model_calls": 1, "api_calls": 0, "elapsed_ms": 500},
            )
            ev = lg.finalize(result, step_budget=MockBudget(),
                             final_page={"url": "https://example.com/ok", "title": "OK"})
            verify("task_result event type", ev["event"] == "task_result")
            verify("task_result has final_budget", "final_budget" in ev)
            verify("task_result has final_page", "final_page" in ev)
            verify("result.result", ev["result"]["result"] == "PASS")
            verify("final_budget budget_state", ev["final_budget"]["budget_state"] == "normal")


@case("7. finalize 收 dict：没有预算对象就不许伪造 final_budget")
def t_finalize_dict():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t006", Path(tmp) / "logs") as lg:
            ev = lg.finalize({"task_id": "t006", "result": "FAIL"})
            verify("dict task_result ok", ev["result"]["result"] == "FAIL")
            verify("dict no final_budget", "final_budget" not in ev)


@case("8. JSONL 落盘：行序、page_changed=None 要留住、每行带 task_id/timestamp")
def t_jsonl_content():
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        with Logger("t007", log_dir) as lg:
            lg.observe({"history": [step(1, page_changed=None)],
                        "decisions": [decision(1)], "text_calls": []})
            lg.finalize({"task_id": "t007", "result": "UNKNOWN"})
        content = (log_dir / "t007.jsonl").read_text(encoding="utf-8").strip().split("\n")
        verify("JSONL 3 lines", len(content) == 3)
        evs = [json.loads(line) for line in content]
        verify("line 1 is step", evs[0]["event"] == "step")
        verify("step page_changed None kept", evs[0]["page_changed"] is None)
        verify("line 2 is decision", evs[1]["event"] == "decision")
        verify("line 3 is task_result", evs[2]["event"] == "task_result")
        verify("all have task_id", all(e["task_id"] == "t007" for e in evs))
        verify("all have timestamp", all("timestamp" in e for e in evs))


@case("9-11. flush_every=1 立即落盘 / close 幂等 / 空 task_id 拒绝")
def t_flush_close_and_validation():
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        lg = Logger("t008", log_dir, flush_every=1)
        lg.observe({"history": [step(1)], "decisions": [], "text_calls": []})
        verify("flush_every=1 -> file exists", lg.log_path.exists())
        lg.close()

        lg = Logger("t009", log_dir)
        lg.close()
        lg.close()
        verify("close idempotent", True)

        try:
            Logger("", log_dir)
            verify("empty task_id rejected", False)
        except ValueError:
            verify("empty task_id rejected", True)


@case("12. 白名单：不在名单里的字段不许进日志")
def t_unknown_field_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        with Logger("t010", log_dir) as lg:
            h = step(1)
            h["unknown_secret_field"] = "should not appear"
            lg.observe({"history": [h], "decisions": [], "text_calls": []})
        line = (log_dir / "t010.jsonl").read_text(encoding="utf-8").strip()
        verify("unknown field excluded", "unknown_secret_field" not in line)


@case("13. 非法 state 要抛 TypeError，不能静默吞")
def t_bad_state():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t011", Path(tmp) / "logs") as lg:
            try:
                lg.observe("not a dict")
                verify("non-dict state rejected", False)
            except TypeError:
                verify("non-dict state rejected", True)


@case("14. teacher_shadow：抽取、快照、游标、增量")
def t_teacher_shadow():
    with tempfile.TemporaryDirectory() as tmp:
        with Logger("t012", Path(tmp) / "logs") as lg:
            state = {"history": [], "decisions": [], "text_calls": [],
                     "teacher_decisions": [teacher_entry(0)]}
            ev = lg.observe(state)
            verify("teacher_shadow event", ev[0]["event"] == "teacher_shadow")
            verify("teacher_shadow has actions_snapshot", "actions_snapshot" in ev[0])
            verify("teacher_shadow agree False", ev[0]["agree"] is False)
            verify("teacher_shadow teacher.api_model", ev[0]["teacher"]["api_model"] == "mock")
            verify("teacher_shadow cursor", lg.observe(state) == [])

            state["teacher_decisions"].append(teacher_entry(1))
            ev3 = lg.observe(state)
            verify("teacher_shadow incremental", len(ev3) == 1)
            verify("teacher_shadow step 1", ev3[0]["step"] == 1)


@case("15. teacher_shadow 落盘 JSONL")
def t_teacher_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"
        with Logger("t013", log_dir) as lg:
            lg.observe({"history": [], "decisions": [], "text_calls": [],
                        "teacher_decisions": [teacher_entry(0)]})
        ev = json.loads((log_dir / "t013.jsonl").read_text(encoding="utf-8").strip().split("\n")[0])
        verify("jsonl teacher_shadow", ev["event"] == "teacher_shadow")
        verify("jsonl actions_snapshot persisted", "actions_snapshot" in ev)
        verify("jsonl actions_snapshot length 2", len(ev["actions_snapshot"]) == 2)


@case("搬家不许缩水：检查项不少于仓内 _smoke 报过的 50 项")
def t_no_coverage_loss():
    assert CHECKS >= 50, f"只跑到 {CHECKS} 项检查，旧 _smoke() 是 50 项——搬家弄丢了东西"


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
    print(f"checks run: {CHECKS}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
