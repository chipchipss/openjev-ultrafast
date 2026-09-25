"""API Budget. B1 / B4 落地：Teacher 与 Recovery 双预算分离。

关联硬约束：
  B1  Teacher Budget ≠ Recovery Budget——分别统计、分别限额、分别进入日志。
      禁止 Recovery 异常数据混入正常决策训练集（消费侧靠 source 标记，本模块分池）。
  B4  预算冲突优先级由 Confidence Gate 编排——本模块只提供状态查询，
      不感知 StepBudget（与 step_budget 互不 import）。

M2 定位（M1 日志记档的 A0.3 归属澄清）：
  M2 Teacher = 无条件全量调用（shadow，产 C 类 preference pair 数据）
  M5 Teacher = 按需调用（校准后 P(correct) 低才触发）——Active Learning 两阶段。

接口契约（与 confidence_gate.resolve_escalation 的鸭子类型探测对齐）：
  teacher_available() / recovery_available() ——方法名即契约，勿改。
"""
from __future__ import annotations


class APIBudgetExhausted(RuntimeError):
    """预算耗尽后仍被 consume——调用方应先查 available()。"""


class APIBudget:
    def __init__(self, teacher_limit: int, recovery_limit: int) -> None:
        if not isinstance(teacher_limit, int) or isinstance(teacher_limit, bool) or teacher_limit < 0:
            raise ValueError("teacher_limit must be an int >= 0")
        if not isinstance(recovery_limit, int) or isinstance(recovery_limit, bool) or recovery_limit < 0:
            raise ValueError("recovery_limit must be an int >= 0")

        self.teacher_limit = teacher_limit
        self.recovery_limit = recovery_limit

        self._teacher_used = 0
        self._recovery_used = 0
        self._teacher_cost_usd = 0.0
        self._recovery_cost_usd = 0.0

    # --- 状态查询（B4：只读接口） ---

    @property
    def teacher_used(self) -> int:
        return self._teacher_used

    @property
    def recovery_used(self) -> int:
        return self._recovery_used

    @property
    def teacher_cost_usd(self) -> float:
        return self._teacher_cost_usd

    @property
    def recovery_cost_usd(self) -> float:
        return self._recovery_cost_usd

    def teacher_available(self) -> bool:
        return self._teacher_used < self.teacher_limit

    def recovery_available(self) -> bool:
        return self._recovery_used < self.recovery_limit

    # --- 消费 ---

    def consume_teacher(self, cost_usd: float = 0) -> None:
        if not self.teacher_available():
            raise APIBudgetExhausted(
                f"teacher budget exhausted ({self._teacher_used}/{self.teacher_limit})"
            )
        if not isinstance(cost_usd, (int, float)) or isinstance(cost_usd, bool) or cost_usd < 0:
            raise ValueError("cost_usd must be a number >= 0")
        self._teacher_used += 1
        self._teacher_cost_usd += float(cost_usd)

    def consume_recovery(self, cost_usd: float = 0) -> None:
        if not self.recovery_available():
            raise APIBudgetExhausted(
                f"recovery budget exhausted ({self._recovery_used}/{self.recovery_limit})"
            )
        if not isinstance(cost_usd, (int, float)) or isinstance(cost_usd, bool) or cost_usd < 0:
            raise ValueError("cost_usd must be a number >= 0")
        self._recovery_used += 1
        self._recovery_cost_usd += float(cost_usd)

    # --- 日志（B1：分别进入日志；结构与 step_budget.log_entry 同风格，可直入 logger） ---

    def log_entry(self) -> dict:
        return {
            "teacher_used":       self._teacher_used,
            "teacher_limit":      self.teacher_limit,
            "teacher_available":  self.teacher_available(),
            "teacher_cost_usd":   round(self._teacher_cost_usd, 4),
            "recovery_used":      self._recovery_used,
            "recovery_limit":     self.recovery_limit,
            "recovery_available": self.recovery_available(),
            "recovery_cost_usd":  round(self._recovery_cost_usd, 4),
        }


# ---------------------------------------------------------------------------
# Smoke（含 ConfidenceGate §5bis 四分支真实集成）
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import json
    from importlib import import_module

    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def check_raises(name, fn, exc):
        nonlocal passed, total
        total += 1
        try:
            fn()
        except exc:
            passed += 1
        except Exception as e:
            print(f"FAIL: {name} (raised {type(e).__name__}: {e})")
        else:
            print(f"FAIL: {name} (no raise)")

    # --- 构造与校验 ---
    b = APIBudget(3, 2)
    check("teacher limit", b.teacher_limit == 3)
    check("recovery limit", b.recovery_limit == 2)
    check("teacher initially available", b.teacher_available())
    check("recovery initially available", b.recovery_available())
    check("used zero", b.teacher_used == 0 and b.recovery_used == 0)
    check_raises("negative teacher limit", lambda: APIBudget(-1, 2), ValueError)
    check_raises("bool limit rejected", lambda: APIBudget(True, 2), ValueError)
    check_raises("float limit rejected", lambda: APIBudget(3.5, 2), ValueError)

    # --- B1 分池消费：互不干扰 ---
    b.consume_teacher(1.5)
    b.consume_teacher(1.0)
    check("teacher used 2", b.teacher_used == 2)
    check("recovery untouched by teacher (B1)", b.recovery_used == 0)
    check("teacher cost summed", b.teacher_cost_usd == 2.5)
    check("recovery cost zero (B1)", b.recovery_cost_usd == 0.0)
    check("teacher still available", b.teacher_available())

    b.consume_teacher(0.5)
    check("teacher exhausted", not b.teacher_available())
    check("recovery still available (B1 分离)", b.recovery_available())
    check_raises("teacher over-consume raises",
                 lambda: b.consume_teacher(0.1), APIBudgetExhausted)

    b.consume_recovery(2.0)
    b.consume_recovery()
    check("recovery exhausted", not b.recovery_available())
    check_raises("recovery over-consume raises",
                 lambda: b.consume_recovery(), APIBudgetExhausted)
    check_raises("negative cost rejected", lambda: APIBudget(1, 1).consume_teacher(-0.1),
                 ValueError)

    # --- 零限额 = 立即不可用（合法配置） ---
    z = APIBudget(0, 0)
    check("zero limit unavailable", not z.teacher_available() and not z.recovery_available())

    # --- log_entry ---
    entry = b.log_entry()
    for key in ("teacher_used", "teacher_limit", "teacher_available", "teacher_cost_usd",
                "recovery_used", "recovery_limit", "recovery_available", "recovery_cost_usd"):
        check(f"log_entry has {key}", key in entry)
    check("log_entry teacher exhausted flag", entry["teacher_available"] is False)
    check("log_entry recovery exhausted flag", entry["recovery_available"] is False)
    check("log_entry teacher cost", entry["teacher_cost_usd"] == 3.0)
    json.dumps(entry)  # must be JSON-safe for logger

    # --- 与 ConfidenceGate.resolve_escalation 的鸭子类型集成（§5bis 四分支） ---
    # 平铺（主仓 python3 api_budget.py）与包内（fork python -m jev_ultrafast.api_budget）双布局
    pkg = __package__ or ""
    cg = import_module(f"{pkg}.confidence_gate" if pkg else "confidence_gate")
    gate_mod = cg

    g_cal = gate_mod.ConfidenceGate(gate_mod.ConfidenceGate.MODE_CALIBRATED)
    go_gate = g_cal.decide({"operation": "CLICK", "target": "1", "choice": "e1",
                            "operation_confidence": 0.3, "target_confidence": 0.3})
    check("low confidence → go_teacher", go_gate.go_teacher)

    class Room:
        steps_ratio = 0.5

    class Full:
        steps_ratio = 1.0

    # 分支 1：teacher 可用 → TEACHER
    fresh = APIBudget(1, 1)
    check("§5bis → teacher",
          g_cal.resolve_escalation(go_gate, step_budget=Room(), api_budget=fresh)
          == gate_mod.ESCALATION_TEACHER)
    fresh.consume_teacher()
    # 分支 2：teacher 耗尽、recovery 可用 → RECOVERY
    check("§5bis → recovery",
          g_cal.resolve_escalation(go_gate, step_budget=Room(), api_budget=fresh)
          == gate_mod.ESCALATION_RECOVERY)
    fresh.consume_recovery()
    # 分支 3：双耗尽、步数有余 → LOCAL
    check("§5bis → local",
          g_cal.resolve_escalation(go_gate, step_budget=Room(), api_budget=fresh)
          == gate_mod.ESCALATION_LOCAL)
    # 分支 4：双耗尽、步数满 → ABORT
    check("§5bis → abort",
          g_cal.resolve_escalation(go_gate, step_budget=Full(), api_budget=fresh)
          == gate_mod.ESCALATION_ABORT)

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    _smoke()
