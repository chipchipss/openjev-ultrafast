"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import time
from pathlib import Path

from .browser import Browser, StalePage
from .model import action_space, choose, field_context, field_text
from .questions import MAX_STEPS

# --- M1: pre_execute 链 ---
from . import decision_validator
from . import policy
from .confidence_gate import (
    ConfidenceGate,
    ESCALATION_TEACHER,
    ESCALATION_RECOVERY,
    ESCALATION_ABORT,
)
from .step_budget import BudgetState, StepBudget


class Agent:
    def __init__(self, url, goals, *, record_dir=None, screenshots=False,
                 task_spec=None):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        plan = [task]
        self.pending_text = None
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)

        # --- M1: pre_execute 组件 ---
        if task_spec is not None:
            self.step_budget = StepBudget.from_task_spec(task_spec)
        else:
            # 向后兼容：没有 TaskSpec 时退化为 MAX_STEPS 硬上限
            self.step_budget = StepBudget(MAX_STEPS, MAX_STEPS * 2)
        self.confidence_gate = ConfidenceGate(ConfidenceGate.MODE_FIXED_HIGH)
        self.api_budget = None  # M5 接入

        try:
            page = self.browser.observe(screenshot=self.screenshots)
        except Exception:
            self.browser.close()
            raise
        self.state = dict(
            browser=self.browser,
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            plan=plan,
            plan_index=0,
            decisions=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
            pre_execute=None,  # M1: pre_execute 结果暂存
        )
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    # --- M1: pre_execute 链 ---

    def _pre_execute(self) -> bool:
        """链内顺序：StepBudget → DecisionValidator → Policy → ConfidenceGate。

        返回 True 表示可以继续 act；False 表示 tick 应中断。

        副作用：
          - 更新 state["status"]（可能变为 "blocked" / "budget_exceeded"）
          - 写入 state["pre_execute"]（供 act 阶段写入 history）
          - 可能抛 StalePage（走 tick 的 except 分支重新 observe + predict）

        关联硬约束：A5 / B4 / D8
        """
        state = self.state
        page = state["page"]
        decision = state["decision"]
        pre = {
            "step_budget": None,
            "validator": None,
            "policy": None,
            "confidence_gate": None,
            "escalation": None,
        }
        state["pre_execute"] = pre

        # 1. StepBudget (B2 / B2.1 / B4)
        budget_state = self.step_budget.tick(
            len(state["history"]), len(state["decisions"])
        )
        pre["step_budget"] = self.step_budget.log_entry()
        if budget_state == BudgetState.ABORT:
            state["status"] = "budget_exceeded"
            return False

        # 2. DecisionValidator (D8 三级一致性)
        val = decision_validator.validate(decision, page)
        pre["validator"] = val.to_dict()
        if not val.valid:
            # 走 StalePage 路径：重新 observe → 重新 predict
            raise StalePage(f"Decision invalid: {val.code} — {val.reason}")

        # 3. Policy (A3)
        pol = policy.check(decision, page)
        pre["policy"] = pol.to_dict()
        if not pol.allow:
            state["status"] = "blocked"
            return False

        # 4. ConfidenceGate (A5 / D9 / B4)
        gate = self.confidence_gate.decide(decision, step_budget=self.step_budget)
        pre["confidence_gate"] = gate.to_dict()
        if not gate.go_teacher:
            return True

        # 5. §5bis 状态机（M1 fixed_high 不进入此分支）
        escalation = self.confidence_gate.resolve_escalation(
            gate,
            step_budget=self.step_budget,
            api_budget=self.api_budget,
        )
        pre["escalation"] = escalation

        if escalation == ESCALATION_TEACHER:
            # M1 未接入 Teacher；保守退化为本地执行（记录以便 M5 分析）
            pre["escalation_note"] = "teacher_not_implemented_in_m1"
            return True
        if escalation == ESCALATION_RECOVERY:
            raise StalePage("Escalation → recovery")
        if escalation == ESCALATION_ABORT:
            state["status"] = "budget_exceeded"
            return False
        # ESCALATION_LOCAL
        return True

    def command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                # --- M1: pre_execute 插入点 ---
                if not self._pre_execute():
                    return self.snapshot()
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                state["decision"] = None
                state["status"] = "ready"
                state["pre_execute"] = None  # M1: 清理暂存
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["decision"] = None
            if state["status"] in {"done", "blocked", "budget_exceeded"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                raise ValueError("Reached the demo's model-call budget")
            state["decision"] = choose(state["page"], state["goal"], state["history"])
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                }
            )
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None

            # --- M1: pre_execute 结果取出（防止 tick 之间残留） ---
            pre = state.pop("pre_execute", None)

            selected = decision["choice"]
            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                state["status"] = "done" if selected == "DONE" else "blocked"
                state["plan_index"] = int(selected == "DONE")
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            action = next(a for a in page["actions"] if a["id"] == selected)
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    text, helper = field_text(context)
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            # Browser.act checks freshness immediately before input, including after text generation.
            state["browser"].act(action, page, text=text)
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                    # --- M1: pre_execute 链结果 ---
                    "pre_execute": pre,
                }
            )
            state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            state["status"] = (
                "blocked"
                if len(repeated) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in repeated)
                else "ready"
            )
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def run(self):
        # --- M1: 终止条件加 budget_exceeded ---
        while self.state["status"] not in {"done", "blocked", "budget_exceeded"}:
            yield self.command("tick")

    def close(self):
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
