"""Confidence Gate.

决定决策是否直接执行，或升级到 Teacher。

关联硬约束：
  A5  Confidence Gate 不能解除 Policy，也不能绕过 Validator
  B4  预算冲突优先级由 Confidence Gate 编排（§5bis）
  D9  Confidence 分层：operation_confidence + target_confidence

M2 新增：
  MODE_SHADOW —— 采集 Teacher 对比数据，但不切换执行路径
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


SENTINELS = frozenset({"DONE", "BLOCKED"})

ESCALATION_LOCAL = "local"
ESCALATION_TEACHER = "teacher"
ESCALATION_RECOVERY = "recovery"
ESCALATION_ABORT = "abort"


# ---------------------------------------------------------------------------
# 结果类型
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    go_teacher: bool
    reason: str
    operation_confidence: float
    target_confidence: Optional[float] = None
    threshold: Optional[float] = None
    mode: str = "fixed_high"
    shadow_requested: bool = False  # M2 新增
    detail: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("detail") is None:
            d.pop("detail", None)
        return d


# ---------------------------------------------------------------------------
# ConfidenceGate
# ---------------------------------------------------------------------------

class ConfidenceGate:
    """M1: fixed_high。M2: shadow。M5: calibrated。"""

    MODE_FIXED_HIGH = "fixed_high"
    MODE_SHADOW = "shadow"
    MODE_CALIBRATED = "calibrated"

    _VALID_MODES = (MODE_FIXED_HIGH, MODE_SHADOW, MODE_CALIBRATED)

    def __init__(self, mode: str = MODE_FIXED_HIGH) -> None:
        if mode not in self._VALID_MODES:
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode

    # --- 分数与阈值 ---

    def _score(self, decision: dict) -> tuple[float, Optional[float]]:
        oc = decision.get("operation_confidence")
        tc = decision.get("target_confidence")
        if not isinstance(oc, (int, float)):
            oc = 0.0
        if tc is not None and not isinstance(tc, (int, float)):
            tc = None
        return float(oc), (float(tc) if tc is not None else None)

    def _threshold(self, step_budget) -> float:
        if step_budget is None:
            return 0.60
        return step_budget.teacher_threshold()

    # --- 主决策 ---

    def decide(self, decision: dict, step_budget=None) -> GateResult:
        operation = decision.get("operation")
        oc, tc = self._score(decision)

        # sentinel 也采集 shadow（DONE 过早是 M1 关键失败模式）
        is_sentinel = operation in SENTINELS

        if self.mode == self.MODE_FIXED_HIGH:
            return GateResult(
                go_teacher=False,
                reason="mode_fixed_high",
                operation_confidence=oc,
                target_confidence=tc,
                threshold=None,
                mode=self.mode,
                shadow_requested=False,
            )

        if self.mode == self.MODE_SHADOW:
            return GateResult(
                go_teacher=False,           # 不切换
                reason="mode_shadow",
                operation_confidence=oc,
                target_confidence=tc,
                threshold=None,
                mode=self.mode,
                shadow_requested=True,      # 采集
            )

        # MODE_CALIBRATED（M5）
        if is_sentinel:
            return GateResult(
                go_teacher=False,
                reason="sentinel_no_teacher",
                operation_confidence=oc,
                target_confidence=tc,
                threshold=None,
                mode=self.mode,
                shadow_requested=False,
            )

        threshold = self._threshold(step_budget)
        min_conf = oc
        min_name = "operation_confidence"
        if tc is not None and tc < min_conf:
            min_conf = tc
            min_name = "target_confidence"

        go = min_conf < threshold
        return GateResult(
            go_teacher=go,
            reason=(
                f"{min_name}={min_conf:.3f} < threshold={threshold:.3f}"
                if go else
                f"{min_name}={min_conf:.3f} >= threshold={threshold:.3f}"
            ),
            operation_confidence=oc,
            target_confidence=tc,
            threshold=threshold,
            mode=self.mode,
            shadow_requested=go,  # M5 下切换时也采集
            detail={"min_field": min_name, "min_value": min_conf} if go else None,
        )

    # --- §5bis 状态机 ---

    def resolve_escalation(
        self,
        gate: GateResult,
        step_budget=None,
        api_budget=None,
    ) -> str:
        if not gate.go_teacher:
            return ESCALATION_LOCAL

        if api_budget is None or self._teacher_available(api_budget):
            return ESCALATION_TEACHER

        if api_budget is not None and self._recovery_available(api_budget):
            return ESCALATION_RECOVERY

        if step_budget is not None and step_budget.steps_ratio < 1.0:
            return ESCALATION_LOCAL

        return ESCALATION_ABORT

    @staticmethod
    def _teacher_available(api_budget) -> bool:
        fn = getattr(api_budget, "teacher_available", None)
        return bool(fn()) if callable(fn) else False

    @staticmethod
    def _recovery_available(api_budget) -> bool:
        fn = getattr(api_budget, "recovery_available", None)
        return bool(fn()) if callable(fn) else False


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

def _smoke() -> None:
    passed = 0
    total = 0

    def check_eq(name, got, want):
        nonlocal passed, total
        total += 1
        if got == want:
            passed += 1
        else:
            print(f"FAIL: {name} (got {got!r}, want {want!r})")

    def check_true(name, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    # --- 构造 ---
    try:
        ConfidenceGate("unknown")
        check_true("unknown mode rejected", False)
    except ValueError:
        check_true("unknown mode rejected", True)

    g_high = ConfidenceGate(ConfidenceGate.MODE_FIXED_HIGH)
    g_cal = ConfidenceGate(ConfidenceGate.MODE_CALIBRATED)

    # --- fixed_high: 永远不走 Teacher ---
    for oc, tc in ((0.99, 0.99), (0.50, 0.50), (0.0, 0.0), (1.0, 1.0)):
        r = g_high.decide({"operation": "CLICK", "target": "1",
                           "choice": "e1",
                           "operation_confidence": oc, "target_confidence": tc})
        check_true(f"fixed_high oc={oc} tc={tc} → local", not r.go_teacher)
        check_eq("fixed_high reason", r.reason, "mode_fixed_high")
        check_eq("fixed_high mode", r.mode, "fixed_high")

    # --- sentinel（v2：fixed_high 分支先于 sentinel，reason 统一 mode_fixed_high） ---
    r = g_high.decide({"operation": "DONE", "choice": "DONE",
                       "operation_confidence": 0.5})
    check_true("DONE no teacher", not r.go_teacher)
    check_eq("DONE reason", r.reason, "mode_fixed_high")

    r = g_high.decide({"operation": "BLOCKED", "choice": "BLOCKED",
                       "operation_confidence": 0.5})
    check_true("BLOCKED no teacher", not r.go_teacher)

    # --- calibrated: 阈值判定 ---
    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.50, "target_confidence": 0.50})
    check_true("cal oc=0.50 < 0.60 → teacher", r.go_teacher)
    check_eq("cal threshold", r.threshold, 0.60)

    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.80, "target_confidence": 0.80})
    check_true("cal oc=0.80 → local", not r.go_teacher)

    # --- calibrated: 取两个 confidence 的最小值 ---
    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.90, "target_confidence": 0.40})
    check_true("cal min(op,target) < 0.60 → teacher", r.go_teacher)
    check_eq("cal min_field target", r.detail["min_field"], "target_confidence")

    # --- calibrated: target_confidence = None（control / scroll） ---
    r = g_cal.decide({"operation": "SCROLL_DOWN", "choice": "scroll_down",
                      "target": None,
                      "operation_confidence": 0.50, "target_confidence": None})
    check_true("cal tc=None → 只看 oc", r.go_teacher)
    check_eq("cal tc=None min_field oc", r.detail["min_field"], "operation_confidence")

    # --- calibrated: degrade 后阈值放宽 ---
    class FakeBudget:
        def __init__(self, degrade):
            self._d = degrade
            self.steps_ratio = 0.5

        def teacher_threshold(self):
            return 0.75 if self._d else 0.60

    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.65, "target_confidence": 0.65},
                     step_budget=FakeBudget(degrade=False))
    check_true("cal oc=0.65 normal → local", not r.go_teacher)

    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.65, "target_confidence": 0.65},
                     step_budget=FakeBudget(degrade=True))
    check_true("cal oc=0.65 degrade → teacher", r.go_teacher)
    check_eq("cal degrade threshold 0.75", r.threshold, 0.75)

    # --- 缺字段容错 ---
    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1"})
    check_true("cal missing confidence → oc=0 → teacher", r.go_teacher)
    check_eq("cal missing oc defaults 0", r.operation_confidence, 0.0)

    # --- 非数值 confidence 容错 ---
    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": "high", "target_confidence": 0.9})
    check_eq("cal string oc → 0", r.operation_confidence, 0.0)

    # --- resolve_escalation: local ---
    gate_local = g_high.decide({"operation": "CLICK", "target": "1",
                                "choice": "e1", "operation_confidence": 0.99})
    check_eq("resolve local",
             g_high.resolve_escalation(gate_local),
             ESCALATION_LOCAL)

    # --- resolve_escalation: teacher ---
    gate_teacher = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                                 "operation_confidence": 0.3, "target_confidence": 0.3})
    check_true("gate go_teacher True", gate_teacher.go_teacher)

    class FakeAPIBudgetTeacher:
        def teacher_available(self): return True
        def recovery_available(self): return False

    check_eq("resolve teacher",
             g_cal.resolve_escalation(gate_teacher, api_budget=FakeAPIBudgetTeacher()),
             ESCALATION_TEACHER)

    # --- resolve_escalation: teacher 不可用但 recovery 可用 ---
    class FakeAPIBudgetRecovery:
        def teacher_available(self): return False
        def recovery_available(self): return True

    check_eq("resolve recovery",
             g_cal.resolve_escalation(gate_teacher, api_budget=FakeAPIBudgetRecovery()),
             ESCALATION_RECOVERY)

    # --- resolve_escalation: 都不行但步数有余 → local ---
    class FakeAPIBudgetNone:
        def teacher_available(self): return False
        def recovery_available(self): return False

    class FakeBudgetRoom:
        steps_ratio = 0.5

    check_eq("resolve local fallback",
             g_cal.resolve_escalation(gate_teacher,
                                      step_budget=FakeBudgetRoom(),
                                      api_budget=FakeAPIBudgetNone()),
             ESCALATION_LOCAL)

    # --- resolve_escalation: 都不行且步数满 → abort ---
    class FakeBudgetFull:
        steps_ratio = 1.0

    check_eq("resolve abort",
             g_cal.resolve_escalation(gate_teacher,
                                      step_budget=FakeBudgetFull(),
                                      api_budget=FakeAPIBudgetNone()),
             ESCALATION_ABORT)

    # --- resolve_escalation: api_budget=None → teacher（乐观默认） ---
    check_eq("resolve no api_budget → teacher",
             g_cal.resolve_escalation(gate_teacher),
             ESCALATION_TEACHER)

    # --- to_dict ---
    d = g_high.decide({"operation": "DONE", "choice": "DONE",
                       "operation_confidence": 0.5}).to_dict()
    check_true("to_dict has go_teacher", "go_teacher" in d)
    check_true("to_dict has mode", "mode" in d)
    check_true("to_dict no detail when None", "detail" not in d)

    d = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.3, "target_confidence": 0.3}).to_dict()
    check_true("to_dict keeps detail when go", "detail" in d)

    # --- MODE_SHADOW（M2 追加） ---
    g_shadow = ConfidenceGate(ConfidenceGate.MODE_SHADOW)

    r = g_shadow.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                         "operation_confidence": 0.9, "target_confidence": 0.9})
    check_true("shadow go_teacher False", not r.go_teacher)
    check_true("shadow_requested True", r.shadow_requested)
    check_eq("shadow reason", r.reason, "mode_shadow")
    check_eq("shadow mode", r.mode, "shadow")

    r = g_shadow.decide({"operation": "DONE", "choice": "DONE",
                         "operation_confidence": 0.5})
    check_true("shadow sentinel also shadowed", r.shadow_requested)
    check_true("shadow sentinel no teacher", not r.go_teacher)

    # --- calibrated 下 shadow 也采集 ---
    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.3, "target_confidence": 0.3})
    check_true("cal go_teacher True", r.go_teacher)
    check_true("cal shadow_requested True", r.shadow_requested)

    r = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                      "operation_confidence": 0.9, "target_confidence": 0.9})
    check_true("cal high conf no shadow", not r.shadow_requested)

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    _smoke()
