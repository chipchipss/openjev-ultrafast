# M1 实施日志

> **状态**：📝 草案（持续追加）
> **关联硬约束**：F1 / F5 / A9 / A10 / D8 / B2
> **用途**：M1 阶段实现过程记录——进度、踩坑、跨文件同步点。

---

## 一、进度

| Step | 文件/事项 | 状态 |
|---|---|---|
| 1 | fork + demo.py 跑通 | ⬜ |
| 2 | evaluator.py | ✅ |
| 3 | step_budget.py | ✅ |
| 4 | decision_validator.py | ✅ |
| 5 | runtime_guard.py | ✅ |
| 6 | choose_2b() | ⬜ |
| 7 | pre_execute 接入 agent.py | ⬜ |
| 8 | Logger 统一 | ⬜ |
| 9 | 20 tasks | ⬜ |

---

## 二、记录

### 2026-09-22 · step_budget 冒烟 off-by-one

- 现象：断言 `len(transitions) == 4` 且取 `transitions[3]` → `IndexError`；实际只有 3 次切换。
- 定位：`StepBudget` 初始即 NORMAL，首次 `tick(5,10)`（ratio 0.25）不触发切换、不记 transition。
- **教训："枚举 N 个值" ≠ "N 次 transition"——首态不计。**
  后续任何 enum 推进的断言，先想清楚"首态是否触发"，再写计数和索引。
- 处置：改测试不改代码。初始 NORMAL 不是 transition，符合 docs/10-step-budget.md §八
  （`budget_transition` 仅在状态切换时写）。
- 修正后：`SMOKE OK: 47/47`。

### 2026-09-22 · decision_validator 同步点（D8 落地）

decision_validator.py 不 import model.py（H2：Decision 层可完全替换），
以下约定在两边独立定义，**任何一处改动必须两边同步**：

| 项 | decision_validator.py | 来源 |
|---|---|---|
| SENTINELS | `{"DONE", "BLOCKED"}` | model.py + questions.py |
| kind_to_op | `{"click":"CLICK", "fill":"TYPE_TEXT", "select":"SELECT"}` | model.py:action_space() |
| select target 形态 | `f"{index}:{count}"` | model.py:action_space() |

- 职责边界（A10 / A6）：只查 operation / target / choice 映射链；
  类型合法性归 schema，freshness / occlusion / disabled 归 Runtime Guard，黑名单归 Policy。
- 冒烟：`SMOKE OK: 35/35`。

### 2026-09-22 · runtime_guard 同步点（A9 落地）

runtime_guard.py 不 import snapshot.js / browser.py，以下结构常量在两边独立定义，
**任何 snapshot.js 改动导致这三个数组结构变化，本文件必须同步**：

| runtime_guard 常量 | snapshot.js 来源 |
|---|---|
| `PAGE_KEY_LEN = 7` | `cache.pageKey()` 返回数组长度 |
| `MARKER_LEN = 10` | `return {..., marker}` 处 marker 构造 |
| `GUARD_LEN = 14` | `cache.guard=e=>{...}` 返回数组长度 |
| `INPUT_STATE_LEN = 6` | `pageKey[6]` 内每个 input state |
| `MARKER_FIELDS` | marker 各位置顺序 |
| `GUARD_FIELDS` | guard 各位置顺序 |

- 职责边界（A6 / A9）：只做结构校验（长度、类型、位置）；不做语义判断、
  不实现 freshness 比对（browser.py 职责）、不做 I/O。
- 失败路径（E5）：`RuntimeContractViolation` → `failure_class="system"` /
  `failure_mode="observe_failed"`，不进训练集。
- 陷阱：`bool ≠ int`——所有 `_is_int` 显式排除 bool，冒烟含专门用例
  （`page_key[4] = True`）。
- 冒烟：`SMOKE OK: 40/40`。
