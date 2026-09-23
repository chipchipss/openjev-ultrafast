# Changelog

> 本文件记录项目的**阶段级**与**约束级**变更。
> 单文件代码变更由 git log 记录。
> 硬约束变更由 `docs/01-hard-rules.md` 的 A0.3 流程触发本文件追加条目。

---

## [M2-start] - 2026-09-23

### Added
- `api_budget.py`（B1 / B4 落地，双池隔离）
- `m2/tasks_extra.jsonl`（30 任务模板，占位域待 C1 填）

### Changed (A0.3)
- **`docs/03-milestones.md` v1.2**：`api_teacher` 归属从 M5 前移到 M2
- **M5 的 Teacher 定位调整**：从"无条件全量"改为"按需触发"
- **引入 Active Learning 两阶段显式表述**：M2 采集 / M5 按需

### Rationale
M2 数据飞轮的四类数据包含 "API 修正"，Teacher 必须 M2 接入。
M2 的 Teacher 是"数据采集器"（影子模式），M5 才是"决策替代者"。

### Conflict Check
无冲突。详见 `docs/03-milestones.md` §A0.3 修订记录。

---

## [M1-close] - 2026-09-23

### Status
- M1 五条件全过（fp=0 / crash=0 / 无 UNKNOWN / 无 FAIL 无 failure_mode / 四象限完整）
- R5 归档为判定基准轮：`reports/m1-r5.json` + `logs/r5/`

### Added (M1 组件)
- `evaluator.py` / `step_budget.py` / `decision_validator.py`
- `runtime_guard.py` / `policy.py` / `confidence_gate.py`
- `logger.py` / `decider/` / `prompts/` / `m1/`

### Changed (基座)
- `agent.py`：tick 内插入 pre_execute 链（唯一改基座处）
- `model.py`：`choose` / `field_text` 桥接到 `decider/`
- `m1/run_tasks.py`：`--task-delay` / `--dry-run` / `--screenshot`

### 失败模式清单（M2 首批原料）
- decision ×7（s001 环境基线 / s005 / f001 / f002 / f004 / t001 / x001）
- budget_exceeded ×1（n004）
- 附记：x002 = false_negative（PASS+blocked 语义正确）
- 附记：s001 环境类不进训练集
- 附记：DoneGuard 两个已知误伤窗口留给 M6

---

## [v3.2] - 2026-09-23

### Added
- **A9** Runtime 契约严格校验属于 `runtime_guard.py`，不属于 JSON Schema
- **A10** schema 管结构，Validator 管语义
- **E5** 失败是四维的（result / quadrant / failure_class / failure_mode）
- **B4** 预算冲突优先级由 Confidence Gate 编排

### Changed
- `decision.schema.json`：扁平双置信度（`operation_confidence` / `target_confidence`）
- `task.schema.json`：strict core + `extensions` 显式扩展点

### Frozen
- Schema 层与 Hard Rules 一致性修复完成

---

## [v3.1] - 2026-09-23

### Added
- **A6** Runtime Guard 与 Validator 分层独立
- **A7** Decision Contract 采用 operation/target 分离
- **A8** Text Helper 独立于 Decision Model
- **D6** 新增组件前先证明现有 Runtime 不足
- **D7** Candidate Filter = Dynamic Action Space 抽象
- **D8** Decision 三级一致性
- **D9** Confidence 分层
- **D10** 外部校验不可移植
- **D11** action.id 是位置索引
- **D12** fill 与 click/select 的 freshness 粒度不同
- **D13** scroll / wait 是 control action
- **D14** 250 上限是硬上限
- **D15** rect 不参与 freshness
- **D16** 领域规则集是资产
- **D17** Text Helper null 语义
- **H1** Agent Runtime 优先复用成熟实现
- **H2** Decision 层必须与 Runtime 解耦
- **H3** 基座决策：Fork jev-ultrafast
- **I1～I5** 代码不变量

### Changed
- **B2** Step Budget 三级细化
- **D2** Reranker 从"M3 必做"改为"条件性组件"

---

## [v3] - 2026-09-23

### Added
- 初版硬约束：A1～A5 / B1～B3 / C1～C6 / D1～D5 / E1～E4 / F1～F5 / G1～G4
- M-1 ～ M8 阶段划分

### Frozen
- 架构设计 v3 冻结

---

## [v2] - 2026-09-23

### Added
- M-1 可行性评估
- Task Success 定义
- 数据污染控制
- 延迟目标现实化
- Observation 预留多模态

---

## [v1] - 2026-09-23

### Added
- 初版规划
