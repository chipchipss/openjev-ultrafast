# Step Budget 规则

> **状态**：M0 产出 7/7
> **关联硬约束**：B1 / B2 / B2.1 / B4 / E1 / E2 / I5
> **冻结时间**：2026-09-23

---

## 一、双预算模型

```
StepBudget
├── steps_budget       = TaskSpec.budget.steps
└── model_calls_budget = TaskSpec.budget.model_calls  （默认 2 × steps）
```

| 预算 | 语义 | 对应 agent.py |
|---|---|---|
| steps_budget | 真实执行步数 | `len(history)` |
| model_calls_budget | 模型调用次数（含 StalePage 重试） | `len(decisions)` |

**model_calls 增速 >> steps 增速 = StalePage 风暴信号。**

---

## 二、三个阈值

每个预算独立计算 `ratio = current / budget`：

| ratio | 状态 | 动作 |
|---|---|---|
| `< 0.50` | normal | 无 |
| `[0.50, 0.80)` | warn | 日志标记 `budget_warn` |
| `[0.80, 1.00)` | degrade | 切换降级策略 |
| `>= 1.00` | abort | 终止，status = `budget_exceeded` |

**判定顺序**：先 steps，再 model_calls。

---

## 三、degrade 策略

**D1. Confidence Gate 阈值放宽**

```
normal:   P(correct) < 0.60  → API
degrade:  P(correct) < 0.75  → API
```

**D2. 禁用 WAIT。** degrade 状态下 `operation == "WAIT"` 直接拒绝 → 强制走 API。

**D3. Loop Detection 严格模式**

```
normal:  连续 3 次 page_changed is False → block
degrade: 连续 2 次相同 (operation, target) → 强制 API
```

**D4. 禁止 Recovery 的 wait 分支。** 只允许 `resnapshot` 或 `abort`。

**D5. 记录 `degrade_entry` 事件。**

---

## 四、与 Recovery Controller 的耦合

```
                tick
                  │
                  ├── pre_execute
                  │     ├── Policy / Validator / Confidence
                  │     └── StepBudget.check()  ──→ degrade? 修改 Gate 阈值
                  │
                  └── act
                        └── on exception ──→ RecoveryController
                                                  │
                                                  └── 读取 StepBudget.state
                                                       决定 resnapshot / wait / abort
```

**RecoveryController 读 StepBudget 状态，但不修改它。**
**StepBudget 修改 Confidence Gate 阈值，但不直接控制 Recovery。**

---

## 五、与双 API 预算的接口

```
APIBudget
├── TeacherBudget      ← Confidence Gate LOW 时消耗
└── RecoveryBudget     ← RecoveryController 触发 API 时消耗
```

**禁止**：StepBudget 逻辑里出现 `if api_budget > X`。
**禁止**：APIBudget 逻辑里出现 `if step_ratio > X`。
三者通过**状态查询**耦合，不通过**直接调用**耦合。

---

## 5bis. 预算冲突优先级状态机（v2 新增）

### 触发场景

某个 tick 中：

- step_ratio >= 0.80（degrade）
- Confidence Gate 判定为 LOW
- 需要调用 Teacher

### 优先级状态机

```
1. 检查 APIBudget.teacher_available

if teacher_available:
    → 调用 Teacher → 消耗 TeacherBudget
elif recovery_budget_available:
    → RecoveryController 接管
    → 消耗 RecoveryBudget
    → 尝试 resnapshot / reset
elif step_ratio < 1.00:
    → 使用 2B 决策（即使 LOW）
    → 记录 "teacher_unavailable, using local"
else:
    → abort
    → status = "budget_exceeded"
    → failure_class = "agent"
    → failure_mode = "budget_exceeded"
```

### 关键规则

**R1. StepBudget 不感知 APIBudget。**
**R2. APIBudget 不感知 StepBudget。**
**R3. 优先级由 Confidence Gate 编排。**
它是唯一读取两者状态的地方。

### degrade 状态的额外约束

degrade 且 `teacher_available == False` 时：

- **禁止 WAIT**（复用 §三 D2）
- **禁止 RecoveryController.wait 分支**（复用 §三 D4）
- 允许：resnapshot / abort

避免"预算耗尽 + Recovery 空转"的死循环。

---

## 六、Progress 接口（M5 预留）

```json
{
  "step":             18,
  "step_budget":      20,
  "budget_ratio":     0.90,
  "progress":         0.82,
  "progress_signals": ["url_changed_toward_target", "assertion_partial_match"]
}
```

M1/M2 阶段 progress = null，只记录事件。

degrade 决策的未来增强：

```
budget_ratio >= 0.80 AND progress < 0.30  → 强制 API / Recovery
budget_ratio >= 0.80 AND progress >= 0.60 → 允许继续
```

M1 不实现。字段预留。

---

## 七、状态机

```
        ┌──────────┐
        │  normal  │
        └────┬─────┘
             │ ratio >= 0.50
             ▼
        ┌──────────┐
        │   warn   │ ──── ratio 回落 → normal（保留，未来 Progress 可能触发）
        └────┬─────┘
             │ ratio >= 0.80
             ▼
        ┌──────────┐
        │ degrade  │
        └────┬─────┘
             │ ratio >= 1.00
             ▼
        ┌──────────┐
        │  abort   │
        └──────────┘
```

单向，不可逆。

---

## 八、日志格式

每条 tick 结束时写：

```json
{
  "step":              5,
  "steps_budget":      20,
  "steps_ratio":       0.25,
  "model_calls":       6,
  "model_calls_ratio": 0.15,
  "budget_state":      "normal",
  "progress":          null
}
```

状态切换时额外写：

```json
{
  "event":       "budget_transition",
  "from":        "normal",
  "to":          "warn",
  "step":        10,
  "model_calls": 12
}
```

---

## 九、TaskSpec 默认值

| category | steps_budget |
|---|---|
| search | 20 |
| form | 25 |
| navigate | 10 |
| list | 15 |
| toggle | 12 |
| negative | 20 |

model_calls_budget = 2 × steps_budget。

---

## 十、与 agent.py 的对接

替换的两处：

```python
# predict 里
if len(state["decisions"]) >= MAX_STEPS * 2:
    raise ValueError("Reached the demo's model-call budget")

# act 里
if len(state["history"]) >= MAX_STEPS:
    state["status"] = "blocked"
    raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
```

替换为：

```python
# predict 里
budget_action = self.step_budget.tick(state)
if budget_action == "abort":
    state["status"] = "budget_exceeded"
    raise BudgetExceeded("model_calls budget")

# act 里
budget_action = self.step_budget.tick(state)
if budget_action == "abort":
    state["status"] = "budget_exceeded"
    raise BudgetExceeded("steps budget")
```

run() 终止条件更新：

```python
while self.state["status"] not in {"done", "blocked", "budget_exceeded"}:
```

---

## 冻结声明

Step Budget 规则 v2 冻结于 2026-09-23。
