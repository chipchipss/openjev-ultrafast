"""Logger.

只读式抽取 agent 运行事件，落盘为 JSONL。

关联硬约束：
  A9  事件格式是 Runtime 的产物，由本模块离线抽取
  C4  训练样本必须携带来源（decider/helper 的 model 字段）
  E5  事件是四维失败（result / quadrant / failure_class / failure_mode）的输入源

设计要点：
  - 只读 agent.state / agent.step_budget，绝不修改
  - 游标式：每次 observe() 只输出新增事件
  - 5 类事件：step / decision / text_call / budget_transition / task_result
  - 一个 task 一个 JSONL
  - 不 import agent，用鸭子类型

已知边界（Step 9 观察 #2）：
  终态（DONE/BLOCKED）分支 state.pop("pre_execute") 后早返回，不写 history。
  因此终态的预算快照不会出现在 step 事件里。
  Logger 用 task_result.final_budget 补偿。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional


EVENT_STEP              = "step"
EVENT_DECISION          = "decision"
EVENT_TEXT_CALL         = "text_call"
EVENT_BUDGET_TRANSITION = "budget_transition"
EVENT_TASK_RESULT       = "task_result"


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def _to_jsonable(obj: Any) -> Any:
    """dataclass / Enum / 嵌套结构 → JSON 可序列化。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return str(obj)


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class Logger:
    def __init__(
        self,
        task_id: str,
        log_dir: str | Path,
        *,
        flush_every: int = 32,
    ) -> None:
        if not task_id:
            raise ValueError("task_id required")
        self.task_id = task_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{task_id}.jsonl"
        self.flush_every = max(1, int(flush_every))

        self._history_cursor = 0
        self._decisions_cursor = 0
        self._text_calls_cursor = 0
        self._transitions_cursor = 0
        self._buffer: list[dict] = []
        self._file = None  # lazy open

    # --- 主入口 ---

    def observe(self, state: dict, *, step_budget=None) -> list[dict]:
        """抽取 state 的新增事件。

        state:       agent.state（或等价的 dict）
        step_budget: agent.step_budget（可选，用于 budget_transition）

        返回本次新增事件列表；事件同时进入内部 buffer，达阈值自动 flush。
        """
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")

        now = time.time()
        new_events: list[dict] = []

        # 1. step
        history = state.get("history") or []
        for h in history[self._history_cursor:]:
            new_events.append({
                "event":     EVENT_STEP,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_step(h),
            })
        self._history_cursor = len(history)

        # 2. decision
        decisions = state.get("decisions") or []
        for d in decisions[self._decisions_cursor:]:
            new_events.append({
                "event":     EVENT_DECISION,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_decision(d),
            })
        self._decisions_cursor = len(decisions)

        # 3. text_call
        text_calls = state.get("text_calls") or []
        for t in text_calls[self._text_calls_cursor:]:
            new_events.append({
                "event":     EVENT_TEXT_CALL,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_text_call(t),
            })
        self._text_calls_cursor = len(text_calls)

        # 4. budget_transition
        if step_budget is not None:
            transitions = getattr(step_budget, "transitions", None) or []
            for tr in transitions[self._transitions_cursor:]:
                new_events.append({
                    "event":     EVENT_BUDGET_TRANSITION,
                    "task_id":   self.task_id,
                    "timestamp": now,
                    **_to_jsonable(tr),
                })
            self._transitions_cursor = len(transitions)

        self._buffer.extend(new_events)
        if len(self._buffer) >= self.flush_every:
            self.flush()
        return new_events

    def finalize(
        self,
        task_result: Any,
        *,
        step_budget=None,
        final_page: Optional[dict] = None,
    ) -> dict:
        """写入 task_result 事件并 flush。

        task_result: evaluator.TaskResult（dataclass）或等价 dict
        step_budget: 可选，用于终态预算快照（补偿终态 pre_execute 丢失）
        final_page:  可选，最终页面的 url / title
        """
        if is_dataclass(task_result):
            result_dict = _to_jsonable(task_result)
        elif isinstance(task_result, dict):
            result_dict = _to_jsonable(task_result)
        else:
            raise TypeError("task_result must be dataclass or dict")

        event: dict = {
            "event":     EVENT_TASK_RESULT,
            "task_id":   self.task_id,
            "timestamp": time.time(),
            "result":    result_dict,
        }
        if step_budget is not None:
            event["final_budget"] = self._budget_snapshot(step_budget)
        if final_page is not None:
            event["final_page"] = {
                "url":   final_page.get("url"),
                "title": final_page.get("title"),
            }

        self._buffer.append(event)
        self.flush()
        return event

    # --- IO ---

    def flush(self) -> None:
        if not self._buffer:
            return
        if self._file is None:
            self._file = self.log_path.open("a", encoding="utf-8")
        for ev in self._buffer:
            self._file.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._file.flush()
        self._buffer.clear()

    def close(self) -> None:
        self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # --- 清理 ---

    @staticmethod
    def _clean_step(h: dict) -> dict:
        """step 白名单。None 保留（page_changed=None 表示 observe 失败）。"""
        keys = (
            "step", "action", "kind", "choice", "operation", "target",
            "confidence", "probability", "latency_ms",
            "text", "text_helper", "text_latency_ms",
            "page_changed", "url", "elapsed_ms", "executed_ms",
        )
        out = {k: h[k] for k in keys if k in h}
        if "pre_execute" in h:
            out["pre_execute"] = _to_jsonable(h["pre_execute"])
        return out

    @staticmethod
    def _clean_decision(d: dict) -> dict:
        keys = (
            "choice", "operation", "target",
            "operation_confidence", "target_confidence", "confidence",
            "model", "latency_ms", "usage",
            "fingerprint", "elapsed_ms",
        )
        out = {k: d[k] for k in keys if k in d}
        if "probabilities" in d:
            out["probabilities"] = _to_jsonable(d["probabilities"])
        return out

    @staticmethod
    def _clean_text_call(t: dict) -> dict:
        keys = ("model", "field", "value", "latency_ms", "usage")
        return {k: t[k] for k in keys if k in t}

    @staticmethod
    def _budget_snapshot(step_budget) -> dict:
        try:
            return _to_jsonable(step_budget.log_entry())
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Smoke（纯内存，无网络、无浏览器、无 Agent 依赖）
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import tempfile
    from pathlib import Path

    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    # --- mock 数据 ---
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

    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp) / "logs"

        # --- 1. 空 state ---
        with Logger("t000", log_dir, flush_every=64) as lg:
            events = lg.observe({})
            check("empty state → no events", events == [])
            check("no file before finalize", not lg.log_path.exists())

        # --- 2. 单步 + 重复 observe ---
        with Logger("t001", log_dir, flush_every=64) as lg:
            state = {"history": [step(1)], "decisions": [], "text_calls": []}
            ev1 = lg.observe(state)
            check("single step → 1 event", len(ev1) == 1)
            check("step event type", ev1[0]["event"] == "step")
            check("step carries pre_execute", "pre_execute" in ev1[0])
            check("step page_changed True", ev1[0]["page_changed"] is True)

            ev2 = lg.observe(state)
            check("repeat observe → 0 events", ev2 == [])

        # --- 3. 增量 ---
        with Logger("t002", log_dir) as lg:
            state = {"history": [step(1)], "decisions": [decision(1)], "text_calls": []}
            lg.observe(state)
            state["history"].append(step(2))
            state["decisions"].append(decision(2))
            ev = lg.observe(state)
            types = [e["event"] for e in ev]
            check("incremental: 1 step", types.count("step") == 1)
            check("incremental: 1 decision", types.count("decision") == 1)

        # --- 4. decisions / text_calls ---
        with Logger("t003", log_dir) as lg:
            state = {
                "history": [step(1, with_pre=False)],
                "decisions": [decision(1)],
                "text_calls": [text_call("OpenAI"), text_call("hello")],
            }
            ev = lg.observe(state)
            types = [e["event"] for e in ev]
            check("1 step", types.count("step") == 1)
            check("1 decision", types.count("decision") == 1)
            check("2 text_calls", types.count("text_call") == 2)
            tc = next(e for e in ev if e["event"] == "text_call")
            check("text_call value", tc["value"] in ("OpenAI", "hello"))
            check("text_call model", tc["model"] == "mock-helper")

        # --- 5. budget_transition ---
        with Logger("t004", log_dir) as lg:
            budget = MockBudget()
            budget.transitions = [
                {"event": "budget_transition", "from": "normal", "to": "warn",
                 "step": 10, "model_calls": 12, "limiting": "steps"},
                {"event": "budget_transition", "from": "warn", "to": "degrade",
                 "step": 16, "model_calls": 20, "limiting": "steps"},
            ]
            ev = lg.observe({}, step_budget=budget)
            check("2 transitions extracted", len(ev) == 2)
            check("transition event type", ev[0]["event"] == "budget_transition")
            check("transition to warn", ev[0]["to"] == "warn")
            check("transition limiting", ev[0]["limiting"] == "steps")

            ev2 = lg.observe({}, step_budget=budget)
            check("transition cursor works", ev2 == [])

            budget.transitions.append(
                {"event": "budget_transition", "from": "degrade", "to": "abort",
                 "step": 20, "model_calls": 25, "limiting": "steps"}
            )
            ev3 = lg.observe({}, step_budget=budget)
            check("incremental transition", len(ev3) == 1)
            check("transition to abort", ev3[0]["to"] == "abort")

        # --- 6. finalize ---
        from dataclasses import dataclass as _dc

        @_dc
        class FakeTaskResult:
            task_id: str
            result: str
            quadrant: str | None
            failure_class: str | None
            failure_mode: str | None
            evidence: dict
            meta: dict

        with Logger("t005", log_dir) as lg:
            lg.observe({"history": [step(1)], "decisions": [], "text_calls": []})
            result = FakeTaskResult(
                task_id="t005", result="PASS", quadrant="true_success",
                failure_class=None, failure_mode=None,
                evidence={"final_url": "https://example.com/ok"},
                meta={"steps": 1, "model_calls": 1, "api_calls": 0, "elapsed_ms": 500},
            )
            budget = MockBudget()
            ev = lg.finalize(result, step_budget=budget,
                             final_page={"url": "https://example.com/ok", "title": "OK"})
            check("task_result event type", ev["event"] == "task_result")
            check("task_result has final_budget", "final_budget" in ev)
            check("task_result has final_page", "final_page" in ev)
            check("result.result", ev["result"]["result"] == "PASS")
            check("final_budget budget_state", ev["final_budget"]["budget_state"] == "normal")

        # --- 7. task_result 是 dict ---
        with Logger("t006", log_dir) as lg:
            ev = lg.finalize({"task_id": "t006", "result": "FAIL"})
            check("dict task_result ok", ev["result"]["result"] == "FAIL")
            check("dict no final_budget", "final_budget" not in ev)

        # --- 8. JSONL 内容 ---
        with Logger("t007", log_dir) as lg:
            lg.observe({"history": [step(1, page_changed=None)],
                        "decisions": [decision(1)], "text_calls": []})
            lg.finalize({"task_id": "t007", "result": "UNKNOWN"})

        content = (log_dir / "t007.jsonl").read_text(encoding="utf-8").strip().split("\n")
        check("JSONL 3 lines", len(content) == 3)
        import json as _json
        evs = [_json.loads(line) for line in content]
        check("line 1 is step", evs[0]["event"] == "step")
        check("step page_changed None kept", evs[0]["page_changed"] is None)
        check("line 2 is decision", evs[1]["event"] == "decision")
        check("line 3 is task_result", evs[2]["event"] == "task_result")
        check("all have task_id", all(e["task_id"] == "t007" for e in evs))
        check("all have timestamp", all("timestamp" in e for e in evs))

        # --- 9. flush_every=1 立即落盘 ---
        lg = Logger("t008", log_dir, flush_every=1)
        lg.observe({"history": [step(1)], "decisions": [], "text_calls": []})
        check("flush_every=1 → file exists", lg.log_path.exists())
        lg.close()

        # --- 10. close 幂等 ---
        lg = Logger("t009", log_dir)
        lg.close()
        lg.close()  # 不应抛
        check("close idempotent", True)

        # --- 11. 构造参数校验 ---
        try:
            Logger("", log_dir)
            check("empty task_id rejected", False)
        except ValueError:
            check("empty task_id rejected", True)

        # --- 12. 未知字段不应进事件 ---
        with Logger("t010", log_dir) as lg:
            h = step(1)
            h["unknown_secret_field"] = "should not appear"
            lg.observe({"history": [h], "decisions": [], "text_calls": []})
        line = (log_dir / "t010.jsonl").read_text().strip()
        check("unknown field excluded", "unknown_secret_field" not in line)

        # --- 13. 非法 state ---
        with Logger("t011", log_dir) as lg:
            try:
                lg.observe("not a dict")
                check("non-dict state rejected", False)
            except TypeError:
                check("non-dict state rejected", True)

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    _smoke()
