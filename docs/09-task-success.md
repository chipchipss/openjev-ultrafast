# Task Success 定义

> **状态**：M0 产出 6/7
> **关联硬约束**：A2 / A5 / E3 / E4 / E5 / B2.1 / C1
> **冻结时间**：2026-09-23

---

## 一、核心原则

**Task Success 由 Task 自带断言判定，不由 Agent 自报。**

Agent 说 DONE ≠ 任务成功。
Agent 说 BLOCKED ≠ 任务失败。

判定只发生在 Agent 进入终态之后，且**只读 page + history**，不参与 Agent loop。

---

## 二、判定输入

```json
{
  "task":       TaskSpec,
  "final_page": Observation | null,
  "history":    [HistoryEntry],
  "status":     "done" | "blocked" | "budget_exceeded" | "error",
  "meta": {
    "started_at":  float,
    "ended_at":    float,
    "total_steps": int,
    "model_calls": int,
    "api_calls":   int
  }
}
```

---

## 三、TaskSpec Schema

见 specs/task.schema.json。strict core + extensions 显式扩展点。

---

## 四、判定流程

```
Agent 进入终态
      ↓ TaskSuccessEvaluator.evaluate(spec, final_page, history, status)
      ↓ if final_page is null OR final_page.url == "about:blank":
      → UNKNOWN
      else:
      → 运行 success_assertion
            ↓
         PASS / FAIL
      ↓ 分类进四象限
      ↓ 返回 TaskResult + failure_class + failure_mode
      ↓ 写入 log
```

UNKNOWN 不是"通过/失败"，而是"无法判定"。
M1 遇到 UNKNOWN 要人工看。

---

## 五、四象限

| Agent status | 断言结果 | quadrant |
|---|---|---|
| DONE | PASS | true_success |
| DONE | FAIL | false_positive |
| BLOCKED | FAIL | correct_abandon |
| BLOCKED | PASS | false_negative |

四象限全部记录。
不做合并统计。M1 的核心观察对象是 false_positive 和 false_negative。

---

## 六、失败四字段（v2 修订）

失败不是一维枚举，是四个独立维度：

```
result:        PASS | FAIL | UNKNOWN
quadrant:      true_success | false_positive | correct_abandon | false_negative | null
failure_class: agent | system | null
failure_mode:  <具体模式> | null
```

维度关系表：

| result | quadrant | failure_class | failure_mode |
|---|---|---|---|
| PASS | true_success | null | null |
| PASS | false_negative | null | null |
| FAIL | false_positive | agent | decision |
| FAIL | false_positive | agent | assertion_mismatch |
| FAIL | correct_abandon | agent | budget_exceeded |
| FAIL | correct_abandon | agent | stale_loop |
| FAIL | correct_abandon | agent | recovery_storm |
| FAIL | null | system | api_unavailable |
| FAIL | null | system | crash |
| UNKNOWN | null | system | observe_failed |

failure_class 语义：

- agent —— Agent 能力问题，用于训练数据
- system —— 基础设施问题，不进训练集（C4 落地）

failure_mode 枚举：

```python
AGENT_MODES = {
    "decision",
    "assertion_mismatch",
    "budget_exceeded",
    "stale_loop",
    "recovery_storm",
}
SYSTEM_MODES = {
    "api_unavailable",
    "crash",
    "observe_failed",
    "assertion_error",
}
```

规则：

- failure_class == "system" 的样本绝不进入训练集
- failure_class == "agent" 才是 M2 数据飞轮的采样源

---

## 七、TaskResult 格式

```json
{
  "task_id":      "g001",
  "result":       "PASS",
  "quadrant":     "true_success",
  "failure_class": null,
  "failure_mode":  null,
  "evidence": {
    "final_url":       "https://...",
    "final_title":     "...",
    "assertion_trace": [
      { "clause": {"type":"url_matches","pattern":"^https://www\\.openai\\.com/"}, "ok": true, "note": null }
    ]
  },
  "meta": {
    "steps":       int,
    "model_calls": int,
    "api_calls":   int,
    "elapsed_ms":  int
  }
}
```

assertion_trace 必须完整记录每一 clause 的判定结果。
这是 E4 的落地。

---

## 八、M1 的 20 个任务配额

| 类别 | 数量 | 说明 |
|---|---|---|
| search | 5 | 搜索 + 打开结果 |
| form | 4 | 填写 + 提交 |
| navigate | 4 | 跳转到目标页 |
| list | 3 | 滚动/筛选找到元素 |
| toggle | 2 | 切换 checkbox / dropdown |
| negative | 2 | 期望 BLOCKED |

5 个代表已给出（s001 / f001 / n001 / l001 / x001），剩余 15 个 M1 阶段补齐。

域选择遵循 C1（benchmark 域 ≠ training 域）。

---

## 九、M1 验收（不使用数字门槛）

1. 20 个任务全部有 TaskResult（无 UNKNOWN）
2. 每个 FAIL 都归类到唯一 failure_mode
3. False Positive = 0
4. api_unavailable / crash = 0
5. 四象限分布有记录

通过条件：1～4 全满足。

---

## 冻结声明

Task Success 定义 v2 冻结于 2026-09-23。
