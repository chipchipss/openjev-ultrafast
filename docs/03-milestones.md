# 阶段与验收

> **版本**：v1.2
> **冻结日期**：2026-09-23
> **上游依赖**：`01-hard-rules.md` v3.2 / `09-task-success.md` v2 / `10-step-budget.md` v2
> **上游文档**：`00-plan.md`
>
> **本文件描述**：各阶段目标、关键交付、验收标准。
> **本文件不描述**：具体实现细节（见代码 + 各专项文档）。

---

## 一、阶段总览

| # | 阶段 | 训练 | 状态 | 一句话目标 |
|---|---|---|---|---|
| M-1 | 可行性评估 | 否 | ✅ 完成 | 判定 fork jev-ultrafast |
| M0 | 接口与指标 | 否 | ✅ 完成 | 冻结 Schema + 硬约束 |
| M1 | 最小闭环 | 否 | ✅ 完成 | 20 任务跑通 + 失败模式清单 |
| **M2** | **数据飞轮** | **否** | **🔄 进行中** | **1000 decisions + 200 corrected** |
| M3 | Reranker | 是（小） | ⬜ | Top1/Recall 达标 |
| M4 | LoRA 2B | 是 | ⬜ | candidate acc > 80% |
| M5 | 三级路由 | 否 | ⬜ | 按需 Teacher + 校准 |
| M6 | Benchmark | 否 | ⬜ | 100～300 tasks 回归 |
| M7 | Ultrafast | 否 | ⬜ | 延迟优化 |
| M8 | 模型扩展 | 视情 | ⬜ | 换 Decider 不动其他 |

**阶段不可跳越**（F4）。前一阶段未达验收，不进入下一阶段。

---

## 二、M-1：可行性评估 ✅

**目标**：判断基座是改造 OpenJEV 还是 fork 其他项目。

**关键交付**：
- OpenJEV / jev-ultrafast 架构审查
- 8 点插入点定位
- 改造 / 抽离决策

**结论**：
- **基座 = jev-ultrafast（MIT）**
- Runtime 保留（`browser.py` / `snapshot.js`）
- Decision 层替换（`model.py:choose` / `model.py:field_text`）

**验收**：✅ `m1/recon-log.md` 完整。

---

## 三、M0：接口与指标 ✅

**目标**：把所有模块之间的协议固定下来。不追求智能。

**关键交付**（7 件）：

1. `specs/action.schema.json` v2
2. `specs/observation.runtime.schema.json`
3. `specs/decision.schema.json` v2
4. `prompts/` + `prompt-draft.md`
5. `docs/01-hard-rules.md` v3.1
6. `docs/09-task-success.md`
7. `docs/10-step-budget.md`

**验收**：✅ Schema 冻结 + 硬约束 v3.2 冻结。

---

## 四、M1：最小闭环 ✅

**目标**：跑通 1 → 20 个任务的最小闭环。产出失败模式清单。

**关键交付**：
- `evaluator.py` / `step_budget.py` / `decision_validator.py`
- `runtime_guard.py` / `policy.py` / `confidence_gate.py`
- `logger.py` / `decider/` / `m1/run_tasks.py`
- `agent.py` pre_execute 接入

**验收**（五条件）：

1. 20 任务全有 TaskResult
2. 每个 FAIL 有唯一 failure_mode
3. **fp = 0**（硬线）
4. **crash / api_unavailable = 0**（硬线）
5. 四象限有记录

**结果**（R5，判定基准轮）：
- ✅ 全过
- pass=12 / fail=8 / fp=0 / crash=0
- 失败模式清单：decision ×7 + budget_exceeded ×1

**归档**：`reports/m1-r5.json` + `logs/r5/`

---

## 五、M2：数据飞轮 🔄

**目标**：让 Agent 自己生产训练数据。

**关联硬约束**：C1～C6（数据与训练）/ B1（双预算）/ B4（冲突优先级）/ E5（失败四维）

### 5.1 Active Learning 两阶段

```
M2: 无条件全量调用 Teacher（影子模式）
    ↓
产 C 类 preference pair
    ↓
M5: 按需调用 Teacher（Confidence Gate 触发）
```

**M2 的 Teacher 是"数据采集器"**，不是"决策替代者"。

### 5.2 关键交付

| # | 文件 | 状态 |
|---|---|---|
| 1 | `api_budget.py` | ✅ |
| 2 | **`api_teacher.py`** | ⬜ |
| 3 | `confidence_gate.py` 增加 `MODE_SHADOW` | ⬜ |
| 4 | `sample_extractor.py` | ⬜ |
| 5 | `m2/run_tasks.py`（含 `--mode shadow`） | ⬜ |

### 5.3 数据来源（四类）

| 类型 | 来源 | 用途 |
|---|---|---|
| A. local correct | 2B + Validator PASS + Task PASS | SFT positive |
| B. Validator reject | 2B + Validator FAIL | 拒答训练 |
| **C. API 修正** | **2B vs Teacher 分歧** | **DPO pair** |
| D. 人工修正 | hard case | 高价值 SFT |

**M2 的核心产出是 C 类。**

### 5.4 数据量目标

```
1000+ decisions
200+ corrected
```

**路径**：
- M1 存量：≈ 100 decisions
- M2 新增：50 任务 × 3 轮 ≈ 750
- 人工修正补：≈ 150
- **合计 ≈ 1000**

### 5.5 污染控制（C1～C6）

- benchmark 域 ≠ 训练域
- API 结果经 Validator 才能进训练集
- 训练样本双份存储（structured + rendered）
- 来源标记（source / api_model / api_confidence）
- 不信任自报 confidence
- 校准集独立，按 action type 分层

### 5.6 验收

1. `logs/` 累计 ≥ 1000 decisions
2. 抽出的 C 类样本 ≥ 200
3. 污染控制检查通过（C1 脚本验证）
4. `system / crash` 样本占比 = 0（同 M1）

**通过后才进 M3。**

---

## 六、M3：Candidate Reranker ⬜

**目标**：让正确候选进入 Top-K。

**触发条件**（D2）：`Filter + Action Space + 2B` 出现"候选太多 → 2B 选择困难"。

**M1/M2 未观察到该信号 → M3 可能跳过。**

**关键交付**：Reranker 模型 + 训练数据 + 推理集成。

**验收**（D2 / D3）：
- Recall@10 ≥ 90%
- Recall@10 不得比 Filter-only baseline 下降
- 2B decision accuracy 不下降
- API rate 有统计意义上下降

**Top1 仅作诊断。**

---

## 七、M4：LoRA 2B ⬜

**目标**：让本地模型从数据飞轮中学习。

**关键交付**：QLoRA 微调后的 Decider 2B。

**数据量**：3000～10000 samples。

**验收**：
- candidate accuracy > 80%
- action accuracy > 85%
- API < 30%

---

## 八、M5：三级路由 ⬜

**目标**：Rule → Local → API 按需调度。

**关键交付**：
- `MODE_CALIBRATED` ConfidenceGate
- 校准模型（特征融合）
- L0 Rules
- 按需 Teacher 触发

**两阶段差异**：
- M2 的 Teacher：无条件全量
- M5 的 Teacher：按需触发

**验收**：
- Task success > 85%
- API < 20%
- 校准曲线报告

---

## 九、M6：Benchmark ⬜

**目标**：可靠评测 + 回归体系。

**关键交付**：
- 100～300 tasks
- 按域名划分 train / val / test
- 自动回归

**验收**：
- 每次变更自动跑
- p50 / p95 / p99 延迟报告
- 失败可定位到 failure_mode

**本阶段建立后，F5 生效**（每次代码变更必须跑回归）。

---

## 十、M7：Ultrafast ⬜

**目标**：延迟优化。

**关联硬约束**：B3（延迟不是门槛）

**优化方向**：
- 增量 snapshot
- Candidate cache
- 模型量化 / ONNX / TensorRT
- 预测 / prefetch
- API 异步化

**验收**：
- Decision p50 / p95 / p99 报告
- E2E p50 / p95 / p99 报告
- **不设门槛，只报告**

**优先级**：Quality > Safety > API rate > Latency。

---

## 十一、M8：模型扩展 ⬜

**目标**：换 Decider 不动其他。

**路径**：2B → 4B → 7B → 多模态。

**验收**：换 Decider 后，Browser / Filter / Validator / Policy / Logger / Benchmark **零修改**。

---

## 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-09-23 | 初版（9 阶段） |
| v1.1 | 2026-09-23 | M1 收口记录，R5 归档 |
| **v1.2** | **2026-09-23** | **A0.3 修订：api_teacher 归属从 M5 前移到 M2** |

---

## A0.3 修订记录（v1.2）

**触发**：M2 规划时发现"API 修正"是 M2 数据飞轮的四类数据之一，Teacher 必须 M2 接入。

**修订**：
- `api_teacher.py` 从 M5 关键交付 → **M2 关键交付**
- M5 的 Teacher 定位改为：**从"无条件全量"转为"按需触发"**
- 引入 "Active Learning 两阶段" 显式表述

**冲突检查**（对照 `01-hard-rules.md` v3.2）：
- ✅ 与 F2（M0～M2 不训练）不冲突：M2 只收集数据，不训练模型
- ✅ 与 B1（Teacher / Recovery Budget 分离）一致：`api_budget.py` 已实现双池
- ✅ 与 B4（预算冲突由 Confidence Gate 编排）一致：M2 用 `MODE_SHADOW`，M5 用 `MODE_CALIBRATED`
- ✅ 与 C2（API 结果经 Validator）一致：Teacher 输出走同一 Validator
- ✅ 与 E1（Uncertainty ≠ State Failure）一致：Teacher 只处理 uncertainty 类
- ✅ 与 H2（Decision 层可替换）一致：Teacher 是 Decision 层的扩展，不影响 Runtime

**无冲突。**

---

## 冻结声明

**本文件 v1.2 冻结于 2026-09-23。**

后续修改必须走 A0.3 流程。
