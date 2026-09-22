"""Step Budget.

双预算（steps + model_calls）追踪与状态机。

关联硬约束：
  B1   Teacher Budget ≠ Recovery Budget（本模块不感知 APIBudget）
  B2   warn 0.5 / degrade 0.8 / abort 1.0
  B2.1 model_calls_budget = 2 × steps_budget
  B4   预算冲突优先级由 Confidence Gate 编排（本模块只提供状态查询）

状态机单向：
  normal → warn → degrade → abort

本模块不感知 APIBudget。
调用方通过 .state / .degrade / .wait_allowed / .teacher_threshold() 读取状态。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 异常与枚举
# ---------------------------------------------------------------------------

class BudgetExceeded(Exception):
    """预算耗尽。abort_at 触发时由调用方抛出。"""


class BudgetState(str, Enum):
    NORMAL  = "normal"
    WARN    = "warn"
    DEGRADE = "degrade"
    ABORT   = "abort"


_STATE_RANK = {
    BudgetState.NORMAL:  0,
    BudgetState.WARN:    1,
    BudgetState.DEGRADE: 2,
    BudgetState.ABORT:   3,
}


# ---------------------------------------------------------------------------
# 默认预算表（关联 docs/10-step-budget.md §九）
# ---------------------------------------------------------------------------

DEFAULT_STEPS_BUDGET = {
    "search":   20,
    "form":     25,
    "navigate": 10,
    "list":     15,
    "toggle":   12,
    "negative": 20,
}


# ---------------------------------------------------------------------------
# StepBudget
# ---------------------------------------------------------------------------

class StepBudget:
    def __init__(
        self,
        steps_budget: int,
        model_calls_budget: Optional[int] = None,
        *,
        warn_at: float = 0.50,
        degrade_at: float = 0.80,
        abort_at: float = 1.00,
    ) -> None:
        if not isinstance(steps_budget, int) or steps_budget < 1:
            raise ValueError("steps_budget must be an int >= 1")
        if model_calls_budget is None:
            model_calls_budget = 2 * steps_budget  # B2.1
        if not isinstance(model_calls_budget, int) or model_calls_budget < 1:
            raise ValueError("model_calls_budget must be an int >= 1")
        if not (0 < warn_at < degrade_at < abort_at <= 1.0):
            raise ValueError(
                "thresholds must satisfy 0 < warn_at < degrade_at < abort_at <= 1.0"
            )

        self.steps_budget = steps_budget
        self.model_calls_budget = model_calls_budget
        self.warn_at = warn_at
        self.degrade_at = degrade_at
        self.abort_at = abort_at

        self._state = BudgetState.NORMAL
        self._steps = 0
        self._model_calls = 0
        self._transitions: list[dict] = []
        self._progress: Optional[float] = None  # M5 预留

    # --- 构造 ---

    @classmethod
    def from_task_spec(cls, spec: dict) -> "StepBudget":
        """从 TaskSpec 构造。

        budget.steps 缺省时，按 category 从 DEFAULT_STEPS_BUDGET 取。
        budget.model_calls 缺省时按 B2.1 取 2× steps。
        """
        budget = spec.get("budget") or {}
        steps = budget.get("steps")
        if steps is None:
            category = spec.get("category", "")
            steps = DEFAULT_STEPS_BUDGET.get(category)
            if steps is None:
                raise ValueError(
                    f"no steps budget: spec has no budget.steps, "
                    f"and category {category!r} has no default"
                )
        return cls(steps, budget.get("model_calls"))

    # --- 计数 ---

    @property
    def steps(self) -> int:
        return self._steps

    @property
    def model_calls(self) -> int:
        return self._model_calls

    @property
    def steps_ratio(self) -> float:
        return self._steps / self.steps_budget

    @property
    def model_calls_ratio(self) -> float:
        return self._model_calls / self.model_calls_budget

    # --- 状态查询 ---

    @property
    def state(self) -> BudgetState:
        return self._state

    @property
    def degrade(self) -> bool:
        """是否处于 degrade 或更高状态。"""
        return _STATE_RANK[self._state] >= _STATE_RANK[BudgetState.DEGRADE]

    @property
    def wait_allowed(self) -> bool:
        """D2 / D4: degrade 后禁止 WAIT 和 Recovery.wait。"""
        return not self.degrade

    @property
    def transitions(self) -> list[dict]:
        return list(self._transitions)

    def teacher_threshold(self) -> float:
        """Confidence Gate 的 P(correct) 阈值。degrade 后放宽到 0.75。"""
        return 0.75 if self.degrade else 0.60

    def limiting_budget(self) -> Optional[str]:
        """当前哪个预算更接近上限。用于诊断。"""
        if self._steps == 0 and self._model_calls == 0:
            return None
        return "model_calls" if self.model_calls_ratio > self.steps_ratio else "steps"

    # --- 状态更新 ---

    def set_progress(self, progress: Optional[float]) -> None:
        """M5 预留。M1 阶段传 None。"""
        if progress is not None and not (0.0 <= progress <= 1.0):
            raise ValueError("progress must be in [0, 1] or None")
        self._progress = progress

    def tick(self, steps: int, model_calls: int) -> BudgetState:
        """更新计数。返回当前 BudgetState。

        幂等：相同输入不重复触发 transition。
        计数必须单调不减；回退抛 ValueError。

        调用方在每个 tick 里显式传递 counts：
            budget.tick(len(state["history"]), len(state["decisions"]))
        """
        if not isinstance(steps, int) or steps < 0:
            raise ValueError("steps must be a non-negative int")
        if not isinstance(model_calls, int) or model_calls < 0:
            raise ValueError("model_calls must be a non-negative int")
        if steps < self._steps:
            raise ValueError(f"steps must be monotonic: {steps} < {self._steps}")
        if model_calls < self._model_calls:
            raise ValueError(
                f"model_calls must be monotonic: {model_calls} < {self._model_calls}"
            )

        # 幂等：相同输入直接返回
        if steps == self._steps and model_calls == self._model_calls:
            return self._state

        self._steps = steps
        self._model_calls = model_calls

        worst = max(self.steps_ratio, self.model_calls_ratio)
        if worst >= self.abort_at:
            new_state = BudgetState.ABORT
        elif worst >= self.degrade_at:
            new_state = BudgetState.DEGRADE
        elif worst >= self.warn_at:
            new_state = BudgetState.WARN
        else:
            new_state = BudgetState.NORMAL

        # 单调：只有 rank 更高才切换
        if _STATE_RANK[new_state] > _STATE_RANK[self._state]:
            self._transitions.append({
                "event":       "budget_transition",
                "from":        self._state.value,
                "to":          new_state.value,
                "step":        steps,
                "model_calls": model_calls,
                "limiting":    self.limiting_budget(),
            })
            self._state = new_state

        return self._state

    # --- 日志 ---

    def log_entry(self) -> dict:
        """每个 tick 结束时写一条。见 docs/10-step-budget.md §八。"""
        return {
            "step":               self._steps,
            "steps_budget":       self.steps_budget,
            "steps_ratio":        round(self.steps_ratio, 4),
            "model_calls":        self._model_calls,
            "model_calls_budget": self.model_calls_budget,  # 便于解读 ratio
            "model_calls_ratio":  round(self.model_calls_ratio, 4),
            "budget_state":       self._state.value,
            "progress":           self._progress,
        }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    passed = 0
    total = 0

    def check(name: str, cond: bool) -> None:
        global passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def expect_raise(name: str, fn, exc_type=ValueError) -> None:
        global passed, total
        total += 1
        try:
            fn()
        except exc_type:
            passed += 1
        except Exception as e:
            print(f"FAIL: {name} (raised {type(e).__name__}: {e})")
        else:
            print(f"FAIL: {name} (no raise)")

    # --- 构造 ---
    b = StepBudget(20)
    check("B2.1 default model_calls = 2x steps", b.model_calls_budget == 40)
    check("initial state normal", b.state == BudgetState.NORMAL)
    check("initial steps 0", b.steps == 0)
    check("initial model_calls 0", b.model_calls == 0)
    check("initial teacher_threshold 0.60", b.teacher_threshold() == 0.60)
    check("initial wait_allowed", b.wait_allowed)
    check("initial not degrade", not b.degrade)
    check("initial limiting None", b.limiting_budget() is None)

    # --- 状态推进 ---
    b.tick(5, 10)
    check("ratio 0.25 -> normal", b.state == BudgetState.NORMAL)
    check("str-enum equality", b.state == "normal")

    b.tick(10, 20)
    check("ratio 0.50 -> warn", b.state == BudgetState.WARN)

    b.tick(16, 32)
    check("ratio 0.80 -> degrade", b.state == BudgetState.DEGRADE)
    check("degrade flag", b.degrade)
    check("teacher_threshold 0.75", b.teacher_threshold() == 0.75)
    check("wait_allowed false", not b.wait_allowed)

    b.tick(20, 40)
    check("ratio 1.00 -> abort", b.state == BudgetState.ABORT)

    # --- 幂等 ---
    t_before = len(b.transitions)
    b.tick(20, 40)
    check("idempotent tick: no new transition", len(b.transitions) == t_before)

    # --- 单调守卫 ---
    expect_raise("monotonic guard: steps", lambda: b.tick(19, 40))
    expect_raise("monotonic guard: model_calls", lambda: b.tick(20, 39))

    # --- transitions 日志 ---
    check("3 transitions recorded", len(b.transitions) == 3)
    check("transition[0] normal->warn", b.transitions[0]["to"] == "warn")
    check("transition[2] ->abort", b.transitions[2]["to"] == "abort")
    check("transition has limiting", "limiting" in b.transitions[0])

    # --- limiting_budget ---
    b2 = StepBudget(20, 40)
    b2.tick(15, 10)
    check("limiting: steps", b2.limiting_budget() == "steps")
    b2b = StepBudget(20, 40)
    b2b.tick(5, 30)
    check("limiting: model_calls", b2b.limiting_budget() == "model_calls")

    # --- log_entry ---
    entry = b.log_entry()
    for key in (
        "step", "steps_budget", "steps_ratio", "model_calls",
        "model_calls_ratio", "budget_state", "progress",
    ):
        check(f"log_entry has {key}", key in entry)
    check("log_entry progress is None", entry["progress"] is None)

    # --- set_progress (M5 预留) ---
    b3 = StepBudget(20)
    b3.set_progress(0.5)
    check("set_progress 0.5", b3.log_entry()["progress"] == 0.5)
    expect_raise("set_progress out of range", lambda: b3.set_progress(1.5))

    # --- from_task_spec ---
    b4 = StepBudget.from_task_spec({"category": "search", "budget": {"steps": 20}})
    check("from_task_spec steps", b4.steps_budget == 20)
    check("from_task_spec model_calls 2x", b4.model_calls_budget == 40)

    b5 = StepBudget.from_task_spec(
        {"category": "search", "budget": {"steps": 20, "model_calls": 60}}
    )
    check("from_task_spec model_calls override", b5.model_calls_budget == 60)

    b6 = StepBudget.from_task_spec({"category": "navigate", "budget": {}})
    check("from_task_spec category default", b6.steps_budget == 10)

    expect_raise(
        "from_task_spec unknown category",
        lambda: StepBudget.from_task_spec({"category": "unknown", "budget": {}}),
    )

    # --- 参数校验 ---
    expect_raise("steps_budget=0 rejected", lambda: StepBudget(0))
    expect_raise("steps_budget=-1 rejected", lambda: StepBudget(-1))
    expect_raise("model_calls_budget=0 rejected", lambda: StepBudget(20, 0))
    expect_raise(
        "bad thresholds rejected",
        lambda: StepBudget(20, warn_at=0.9, degrade_at=0.8),
    )
    expect_raise(
        "abort>1 rejected",
        lambda: StepBudget(20, abort_at=1.5),
    )

    # --- 空 tick ---
    b7 = StepBudget(20)
    check("tick(0,0) returns NORMAL", b7.tick(0, 0) == BudgetState.NORMAL)
    check("tick(0,0) no transition", len(b7.transitions) == 0)

    print(f"SMOKE OK: {passed}/{total}")
