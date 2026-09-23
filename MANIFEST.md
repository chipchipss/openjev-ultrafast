# OpenJEV Ultrafast · 仓库完整文件清单

- 状态标记：✅ 已冻结 / 📝 草案 / ⬜ 待产出
- 用途：丢失后按此清单重建。每个文件的关键内容已在对话中给出，可按摘要重建。
- 本仓库当前状态：已落盘 19 件（docs/01、09、10 + agent.py + evaluator / step_budget / decision_validator / runtime_guard / policy / confidence_gate / logger + prompts×3 + decider×5）+ 草案 m1/m1-log.md + 本清单 + 目录骨架；其余 ✅ 待落盘，⬜ 待产出。
- 统计：✅ 37 · 📝 1 · ⬜ 2，合计 40（原稿 37 件 + 新增 _http.py、action_space.py、agent.py 改造稿；落盘 19 件）。

---

## 一、根目录

```text
openjev-ultrafast/
├── README.md              ✅
├── CHANGELOG.md           ✅
├── LICENSE                ✅
├── docs/
├── specs/
└── m1/
```

**README.md ✅**

- 项目名：OpenJEV Ultrafast
- 一行目标：API Teacher + 本地 2B Decider + Validator + 数据飞轮 + Ultrafast 路由
- 指向 docs/01-hard-rules.md
- 当前阶段：M-1 完成 / M0 完成 / 待进入 M1
- 文档导航表（11 份 docs）
- 版本行：v3.2 冻结于 2026-09-23

**CHANGELOG.md ✅**

三个版本条目：

- [v3.1] 新增 A6～A8 / D6～D18 / H1～H3 / I1～I5，修改 B2 / D2
- [v3.2] 新增 A9 / A10 / E5 / B4（schema 与 runtime 分层、失败四字段、预算冲突优先级）
- [v3] 初版

**LICENSE ✅**

MIT License（继承自 jev-ultrafast）。

---

## 二、docs/

```text
docs/
├── 00-plan.md                  ✅
├── 01-hard-rules.md            ✅ v3.2
├── 02-architecture.md          ✅
├── 03-milestones.md            ✅
├── 04-data-flywheel.md         ✅
├── 05-benchmark.md             ✅
├── 06-safety.md                ✅
├── 07-recovery.md              ✅
├── 08-m1-recon.md              ✅
├── 09-task-success.md          ✅ v2
└── 10-step-budget.md           ✅ v2
```

**00-plan.md ✅**

- 目标架构 ASCII 图
- 9 个阶段（M-1 ～ M8）表格
- 当前状态：M-1 / M0 完成
- 冻结声明

**01-hard-rules.md ✅ v3.2（宪法级）**

完整内容分 A0 / A / B / C / D / E / F / G / H / I 十章。

A0 元规则：A0.1 优先级 / A0.2 违反处理 / A0.3 修改流程

A 架构分层：

- A1 五层正交
- A2 Policy/Validator/Confidence/TaskSuccess 四元组不可合并
- A3 Policy 只保留三类
- A4 API 不豁免安全链
- A5 Confidence Gate 不解除 Policy
- A6 Runtime Guard 与 Validator 分层
- A7 Decision 采用 operation/target 分离
- A8 Text Helper 独立
- A9 Runtime 契约严格校验属于 runtime_guard.py（v3.2）
- A10 schema 管结构，Validator 管语义（v3.2）

B 预算：

- B1 Teacher Budget ≠ Recovery Budget
- B2 Step Budget 三级（warn 0.5 / degrade 0.8 / abort 1.0）
- B2.1 双预算 2 倍关系
- B3 延迟是优化目标不是门槛
- B4 预算冲突优先级由 Confidence Gate 编排（v3.2）

C 数据：C1 域名隔离 / C2 Validator 过滤 / C3 双份存储 / C4 来源标记 / C5 不信任自报 confidence / C6 分层校准

D 组件演化：D1 增量价值证明 / D2 Reranker 条件性 / D3 Reranker 定位 / D4 候选递减 / D5 失败模式先于性能 / D6 复用优先 / D7 Candidate Filter = Action Space / D8 Decision 三级一致性 / D9 Confidence 分层 / D10 外部校验不可移植 / D11 action.id 位置索引 / D12 freshness 粒度不同 / D13 scroll/wait 是 control / D14 250 上限 / D15 rect 不参与 freshness / D16 领域规则是资产 / D17 Text Helper null 语义 / D18 保留号位

E 决策与失败：E1 Uncertainty ≠ State Failure / E2 Recovery 属控制平面 / E3 唯一归因 / E4 禁止模糊汇报 / E5 失败四维分层（v3.2）

F 阶段推进：F1 M-1 前不改代码 / F2 M0～M2 不训练 / F3 M0 前不实现 schema / F4 阶段不可跳 / F5 每次变更跑 M6 回归

G 安全：G1 不可逆拒绝 / G2 安全优先 / G3 误杀率 ≤5%，漏杀=0 / G4 LLM 无法突破 Policy

H 基座：H1 Runtime 复用优先 / H2 Decision 与 Runtime 解耦 / H3 基座 = jev-ultrafast

I 不变量：

- I1 tick 原子性
- I2 decision 一次性消费
- I3 执行先于观察
- I4 fingerprint 严格匹配
- I5 page_changed 三态

**02-architecture.md ✅**

- 五层抽象表（Candidate / Decision / Permission / Uncertainty / Outcome）
- 控制平面（Recovery Controller / Step Budget / Loop Detection / Page State）
- 职责表（12 个组件）
- API 安全链图

**03-milestones.md ✅**

- M-1 ～ M8 表格 + 每阶段验收标准

**04-data-flywheel.md ✅**

- 四类数据来源（local correct / validator reject / api correction / human）
- Active Learning 触发条件
- 污染控制
- 存储（SQLite + JSONL）
- 数据规模

**05-benchmark.md ✅**

- 任务集 100～300
- 按域名划分
- 9 个指标（含 p50/p95/p99）
- 回归机制

**06-safety.md ✅**

- 硬规则黑名单
- 轻量分类器
- 不可逆操作白名单
- 误杀率/漏杀率目标

**07-recovery.md ✅**

- Recovery 触发条件
- StalePage / 3×no-change
- RecoveryController 接口

**08-m1-recon.md ✅**

- 元问题 4 条
- 8 点勘探卡片
- 最终产出定义

**09-task-success.md ✅ v2**

- 判定输入
- TaskSpec schema
- 9 种 assertion DSL
- 四象限（true / false_positive / correct_abandon / false_negative）
- 失败四字段：result / quadrant / failure_class / failure_mode（v2）
- AGENT_MODES / SYSTEM_MODES
- 5 个任务模板（s001 / f001 / n001 / l001 / x001）
- M1 五条验收（无数字门槛）

**10-step-budget.md ✅ v2**

- 双预算模型
- 三级阈值
- degrade 策略（D1～D5）
- 与 Recovery 耦合
- §5bis 预算冲突优先级状态机（v2）
- R1～R3：StepBudget 不感知 APIBudget
- Progress 接口（M5 预留）
- 状态机单向
- 日志格式
- 默认预算表

---

## 三、specs/

```text
specs/
├── action.schema.json              ✅ v2
├── action.schema.test-cases.md     ✅
├── observation.runtime.schema.json ✅
├── decision.schema.json            ✅ v2
└── task.schema.json                ✅ v2
```

**action.schema.json ✅ v2**

- 顶层：id / kind / label required
- id 禁 DONE / BLOCKED
- unevaluatedProperties: false
- oneOf 三分支：
  - DOM-backed：click / fill / select（含 node / role / rect / value / current_value / checked / selected / expanded）
  - Control-scroll：delta
  - Control-wait：无额外字段

**action.schema.test-cases.md ✅**

12 个用例：

- 5 应通过（click / fill / select / scroll / wait）
- 7 应拒绝（delta 混入 click / node 混入 scroll / 缺 node / sentinel id / hover / wait+node）

**observation.runtime.schema.json ✅**

- 顶层：url / title / w / h / text / scroll / actions / marker / page_key / guards / omitted_actions
- marker / page_key / guards 宽松（adapter 策略，A9）
- actions maxItems 253

**decision.schema.json ✅ v2**

- choice / operation / operation_confidence required
- additionalProperties: false
- 扁平双置信度：
  - operation_confidence：0～1
  - target_confidence：0～1 或 null
- target：string 或 null
- probabilities / latency_ms / model / usage / request 可选

**task.schema.json ✅ v2**

- strict core + extensions 显式扩展点
- 所有分支 additionalProperties: false
- 9 种 assertion DSL

---

## 四、m1/

```text
m1/
├── m1-log.md             📝 草案
├── recon-checklist.md    ✅
├── recon-log.md          ✅
└── tasks.jsonl           ⬜ 待产出
```

**m1-log.md 📝**

- M1 实施日志：进度表 + 踩坑记录 + 跨文件同步点清单，持续追加

**recon-checklist.md ✅**

- 8 点勘探卡片 + 记录模板

**recon-log.md ✅ 完整版**

- 元问题回答（驱动 browser-harness / 入口 agent.py run / 循环 while tick / Decision provider 替换为 2B / 基座 fork）
- 8 点结论表
- 替换点精确位置（model.py:choose() / model.py:field_text()）
- 插入点（tick 内 pre_execute）
- 不变量 I1～I5
- 已知失败模式（Windows 菜单 / shadow root / 双预算硬停）
- 基座决策：Fork jev-ultrafast

**tasks.jsonl ⬜**

20 个 M1 任务，配额：

- search 5 / form 4 / navigate 4 / list 3 / toggle 2 / negative 2
- 5 个代表已给出（s001 / f001 / n001 / l001 / x001）
- 待补 15 个

---

## 五、M1 阶段待产出代码文件

顶层 7 个 py + prompts×3 + decider×5 已落盘，其余尚未开始（api_teacher.py / tasks.jsonl）。列出便于规划目录。

```text
openjev-ultrafast/
├── evaluator.py            ✅ TaskSuccessEvaluator（已落盘）
├── step_budget.py          ✅ StepBudget（已落盘）
├── decision_validator.py   ✅ DecisionValidator（D8 三级一致性，已落盘）
├── runtime_guard.py        ✅ Runtime 契约严格校验（A9，已落盘）
├── logger.py               ✅ 统一日志出口（已落盘）
├── policy.py               ✅ Policy（先空实现 + 黑名单，已落盘）
├── confidence_gate.py      ✅ Confidence Gate（先固定 HIGH，已落盘）
├── api_teacher.py          ⬜ API Teacher（M1 后期）
├── decider/
│   ├── __init__.py                          ✅（已落盘）
│   ├── _http.py                             ✅ OpenAI 兼容 HTTP 客户端（新增，已落盘）
│   ├── action_space.py                      ✅ 移植 model.py:action_space()（新增，已落盘）
│   ├── choose_2b.py                         ✅ 替换 model.py:choose（已落盘）
│   └── field_text_2b.py                     ✅ 替换 model.py:field_text（已落盘）
└── prompts/
    ├── next_action.txt                      ✅ 移植 questions.py:NEXT_ACTION（对话原文，覆盖旧稿）
    ├── target.txt                           ✅ 移植 questions.py:TARGET（对话原文，M1 暂不加载，D16 保留）
    └── text_value.txt                       ✅ 移植 questions.py:TEXT_VALUE（对话原文，覆盖旧稿）
```

来源说明（2026-09-23 更新）：prompts×3 与 decider×5 实现原文由用户在对话中给出并落盘，覆盖此前按契约新写稿；questions.py / model.py 原文仍不在 LA、DE 任何机器（基座 Step 1 未 fork），Step 9 接入 agent.py 时以基座为准复核（见 m1/m1-log.md 同步点）。运行依赖新增 httpx（decider/_http.py）。

替换点（唯一改 jev-ultrafast 的两处）：

- model.py:choose() → 调用 decider/choose_2b.py
- model.py:field_text() → 调用 decider/field_text_2b.py

插入点（唯一改 agent.py 的一处）：

- tick 内 predict 后、act 前：插入 pre_execute 链

---

## 六、目录树全貌

```text
openjev-ultrafast/
├── README.md                                ✅
├── CHANGELOG.md                             ✅
├── LICENSE                                  ✅
├── docs/
│   ├── 00-plan.md                           ✅
│   ├── 01-hard-rules.md                     ✅
│   ├── 02-architecture.md                   ✅
│   ├── 03-milestones.md                     ✅
│   ├── 04-data-flywheel.md                  ✅
│   ├── 05-benchmark.md                      ✅
│   ├── 06-safety.md                         ✅
│   ├── 07-recovery.md                       ✅
│   ├── 08-m1-recon.md                       ✅
│   ├── 09-task-success.md                   ✅
│   └── 10-step-budget.md                    ✅
├── specs/
│   ├── action.schema.json                   ✅
│   ├── action.schema.test-cases.md          ✅
│   ├── observation.runtime.schema.json      ✅
│   ├── decision.schema.json                 ✅
│   └── task.schema.json                     ✅
├── m1/
│   ├── m1-log.md                            📝
│   ├── recon-checklist.md                   ✅
│   ├── recon-log.md                         ✅
│   └── tasks.jsonl                          ⬜
├── agent.py                                 ✅
├── evaluator.py                             ✅
├── step_budget.py                           ✅
├── decision_validator.py                    ✅
├── runtime_guard.py                         ✅
├── logger.py                                ✅
├── policy.py                                ✅
├── confidence_gate.py                       ✅
├── api_teacher.py                           ⬜
├── decider/
│   ├── __init__.py                          ✅
│   ├── _http.py                             ✅
│   ├── action_space.py                      ✅
│   ├── choose_2b.py                         ✅
│   └── field_text_2b.py                     ✅
└── prompts/
    ├── next_action.txt                      ✅
    ├── target.txt                           ✅
    └── text_value.txt                       ✅
```

- ✅ 已冻结文件：37 个（21 项基础文档 + agent.py + 7 顶层 py + prompts 3 + decider 5；其中已落盘 19 件 = docs 3 + agent.py + 顶层 py 7 + prompts 3 + decider 5）
- 📝 草案：1 个（m1/m1-log.md）
- ⬜ 待产出：2 个（tasks.jsonl + api_teacher.py）

---

## 七、重建顺序建议

**立即重建（不依赖外部）**

1. README.md
2. CHANGELOG.md
3. LICENSE
4. docs/01-hard-rules.md（最优先——宪法）
5. docs/09-task-success.md
6. docs/10-step-budget.md
7. specs/ 5 份
8. docs/ 其余 8 份
9. m1/recon-*.md

**稍后重建（依赖 clone）**

10. m1/tasks.jsonl（补齐 20 个）
11. evaluator.py（第一个可写代码，已落盘）
12. 其余代码
