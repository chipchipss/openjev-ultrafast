# 项目硬约束（Hard Rules）

> **版本**：v3.2
> **冻结日期**：2026-09-23
> **冻结声明**：本文件为项目宪法级文档。冻结后，任何修改必须走 A0.3 流程。
>
> **编号规则**：
> - 编号一旦分配，永不复用。
> - 废弃的约束标记 `[DEPRECATED]`，保留原文，不删除。
> - 新增约束只能追加编号，不得插入或重排。
>
> **来源标记**：
> - `[v3]`   —— v3 架构设计阶段确立
> - `[v3.1]` —— M-1 勘探后升级
> - `[v3.2]` —— Schema 层与 Hard Rules 一致性修复
> - `[M-1]`  —— 源码勘探实证

---

## A0. 元规则

**A0.1 本文件优先于一切。**
任何代码、设计、实验若与本文件冲突，必须先改本文件，再改实现。

**A0.2 违反处理。**
发现违反时：

1. 停止当前工作
2. 记录违反事实到 `CHANGELOG.md`
3. 判定：改约束 or 改实现
4. 完成后才能继续

**A0.3 修改流程。**
对本文件的任何修改必须：

1. 提出新编号
2. 说明理由（关联失败案例 or 新发现）
3. 更新 `CHANGELOG.md`
4. 检查是否与现有约束冲突

---

## A. 架构分层

**A1. 五层职责必须正交。** `[v3]`

| 层 | 回答的问题 | 允许的失败模式 |
|---|---|---|
| Candidate | 该关注什么？ | 召回率 |
| Decision | 该做什么？ | 选择准确率 |
| Permission | 允许不允许？ | 规则误杀/漏杀 |
| Uncertainty | 有多确定？ | 校准偏差 |
| Outcome | 结果是否成功？ | 判定准确率 |

**A2. Policy / Validator / Confidence / Task Success 四元组不可合并。** `[v3]`

```
Policy       = permission     （允许不允许？）
Validator    = executability  （现在能不能做？）
Confidence   = uncertainty    （值得相信吗？）
Task Success = outcome        （最终成功了吗？）
```

禁止：Validator 判断"模型对不对"；Confidence 判断"该不该允许"；Policy 判断"现在能不能执行"。

**A3. Policy 只保留三类内容。** `[v3]`

1. Safety（安全黑名单）
2. Validity（结构性约束）
3. Hard constraints（硬约束）

禁止把站点适配、元素匹配、页面逻辑塞进 Policy。

**A4. API Teacher 不豁免安全链。** `[v3]`

```
API → Policy → Validator → Execute
```

禁止 `API → Execute`。

**A5. Confidence Gate 不能解除 Policy，也不能绕过 Validator。** `[v3]`

Confidence Gate 只决定"是否找 Teacher"，不决定"是否执行"。

**A6. Runtime Guard 与 Validator 分层独立。** `[v3.1]`

```
Runtime Guard   ← 执行有效性（stale / occlusion / disabled）
Validator       ← Policy + 结构约束
```

禁止：Validator 做 freshness 检查；Runtime Guard 做 Policy 判断。

**A7. Decision Contract 采用 operation/target 分离。** `[v3.1]`

```
Decision = (Operation, Target)
```

Operation 决定 Target question 集合。禁止把动作空间作为扁平列表塞给模型。

**A8. Text Helper 独立于 Decision Model。** `[v3.1]`

Decision Model 只输出 `TYPE_TEXT target=N`。文本内容由独立 Text Helper 生成，且必须结构化（`{"text": "..."}`）。

**A9. Runtime 契约的严格校验属于 `runtime_guard.py`，不属于 JSON Schema。** `[v3.2]`

schema 表达结构可能性；runtime_guard 表达运行时刻的安全边界。

禁止：把 marker / page_key / guards 的内部结构硬编入 JSON Schema。禁止：schema 通过即视为 runtime 契约成立。

**A10. schema 与 Validator 职责分离。** `[v3.2]`

```
schema     管结构合法性（字段类型、枚举、必填）
Validator  管语义合法性（D8 三级一致性）
```

禁止：在 JSON Schema 里表达 D8；禁止：在 Validator 里重复 schema 检查。

---

## B. 预算与资源

**B1. Teacher Budget 与 Recovery Budget 必须分离。** `[v3]`

```
API Budget
├── Teacher Budget     ← 决策不确定性
└── Recovery Budget    ← Browser / State 异常
```

分别统计、分别限额、分别进入日志。禁止：Recovery 异常数据混入正常决策训练集。

**B2. Step Budget 是硬约束，不是软建议。** `[v3]` / `[v3.1]`

```
warn_at    = 0.50
degrade_at = 0.80
abort_at   = 1.00
```

参考 jev-ultrafast 的 `MAX_STEPS = 60` 作为上限。达到 `degrade_at` 必须切换策略；达到 `abort_at` 必须终止并记录。

**B2.1 双预算保留 2 倍关系。** `[M-1]`

```
model_call_budget = 2 × action_budget
```

语义：允许每步一次重试。

**B3. 延迟不是验收门槛，是优化目标。** `[v3]`

```
Quality floor > Safety floor > API rate ceiling > Latency target
```

禁止为了延迟牺牲决策质量。

**B4. 预算冲突优先级由 Confidence Gate 编排。** `[v3.2]`

```
StepBudget 不感知 APIBudget。
APIBudget  不感知 StepBudget。
Confidence Gate 是唯一读取两者状态的组件。
```

Teacher 不可用时按 `10-step-budget.md §5bis` 状态机降级。

禁止：StepBudget 逻辑里出现 `if api_budget > X`；禁止：APIBudget 逻辑里出现 `if step_ratio > X`。

---

## C. 数据与训练

**C1. Benchmark 域名 ≠ Training 域名。** `[v3]`

任何训练 / 校准 / 调参数据不得包含 benchmark 域名。按域名划分 train / val / test，不随机切分。

**C2. API 结果必须经 Validator 才能进入训练集。** `[v3]`

**C3. 训练样本必须双份存储。** `[v3]`

- `structured`：原始 JSON
- `rendered`：prompt 用文本

只存 rendered = 数据信息丢失。

**C4. 每条训练样本必须携带来源。** `[v3]`

`source ∈ {local, api, human}` + `api_model` + `api_confidence`。

**C5. 不信任模型自报 confidence。** `[v3]`

必须经 Calibration Model 校准。Temperature scaling 是**实验**，不是架构前提。

**C6. 校准集必须独立，按 action type 分层。** `[v3]`

---

## D. 组件演化

**D1. 所有新组件必须证明增量价值。** `[v3]`

```
Baseline → A/B → 同一 Benchmark → 同一指标 → 证明收益
```

**D2. Reranker 是条件性组件。** `[v3]` / `[v3.1]`

不再默认存在。引入前必须证明：`Filter + Action Space + 2B` 的组合不足。

**D3. Reranker 只负责减少搜索空间，不替 Decider 做决策。** `[v3]`

**D4. Candidate 数量随 pipeline 递减，不可回增。** `[v3]`

```
DOM → Filter(30~50) → Reranker(10~15) → Decider
```

**D5. 新组件必须先有失败模式分类，再有性能数字。** `[v3]`

**D6. 新增组件前，先证明现有 Runtime 无法满足。** `[v3.1]`

**D7. Candidate Filter = Dynamic Action Space 的抽象名。** `[v3.1]`

不再作为独立组件存在。其实现即 Runtime 的 indexed controls 构造。

**D8. Decision 三级一致性。** `[M-1]`

```
if operation in targets:       choice == targets[operation][target]["id"]
elif operation in controls:    choice == controls[operation]["id"]
elif operation in sentinel:    choice == operation and target is None
```

Validator 必须校验，不通过则拒绝。

**D9. Confidence 分层。** `[M-1]`

Confidence 必须区分 `operation_confidence` 和 `target_confidence`。Confidence Gate 决策时两个都要考虑。

**D10. 外部校验不可移植。** `[M-1]`

TypeSafe 的 `validate_choice` 5 条约束是特定 provider 语义。2B 的 validation 必须重新定义，不能照搬。

**D11. action.id 是本次 snapshot 内的位置索引。** `[M-1]`

`e1` / `e2` / ... 跨 snapshot 无稳定语义。跨 snapshot 引用旧 id 必须走 `freshness` 检查。

**D12. fill 与 click/select 的 freshness 粒度不同。** `[M-1]`

- click / select → guard 节点级
- fill / scroll / wait → marker 页级

fill 更容易触发 StalePage。Confidence Gate 决策时需要考虑。

**D13. scroll / wait 是 control action，不是 DOM action。** `[M-1]`

它们没有 `node` / `role` / `rect`。在 `action_space()` 里进入 `controls`，choice 就是大写 id。

**D14. 250 上限是硬上限。** `[M-1]`

snapshot.js 主动截断 actions 到 250。`omitted_actions > 0` 表示页面元素过多，应触发警告。这是后续 Reranker 唯一可能的合理引入点。

**D15. rect 不参与 freshness。** `[M-1]`

marker 计算时剔除 `rect`。执行前的几何检查由 Runtime Guard 实时做。

**D16. 领域规则集是资产。** `[M-1]`

`questions.py` 的 NEXT_ACTION 规则是项目核心资产。任何替换 Decider 的方案必须显式保留这些规则。

**D17. Text Helper null 语义。** `[M-1]`

Text Helper 找不到值时**必须返回 null**，不得编造。`field_text()` 的 `ValueError` 路径是**设计特性**，不是 bug。

**D18. [保留号位]** `[M-1]` —— 见 B2.1。

---

## E. 决策与失败

**E1. Uncertainty escalation ≠ State failure escalation.** `[v3]`

```
Uncertainty   → Teacher
State Failure → Recovery
```

页面 loading 不该走 Teacher。

**E2. 恢复机制属于 Agent Runner 的控制平面，不属于 Validator。** `[v3]`

**E3. 每一步必须可归因到唯一失败模式。** `[v3]`

失败模式维度：Filter recall ↓ / Reranker ↓ / Decision ↓ / Policy reject ↑ / Validator reject ↑ / Confidence calibration ↓ / Recovery ↓ / Browser execution ↓ / Task assertion ↓

**E4. 禁止模糊汇报。** `[v3]`

不报"成功率从 83% 降到 76%"，报分层归因。

**E5. 失败是四维的，不是一维枚举。** `[v3.2]`

```
result / quadrant / failure_class / failure_mode
```

- failure_class == "system" 的样本绝不进入训练集
- failure_mode 只允许出现在 failure_class != null 时
- failure_class == "agent" 才是 M2 数据飞轮的采样源

---

## F. 阶段推进

**F1. M-1 之前禁止改 OpenJEV / jev-ultrafast 代码。** `[v3]` / `[v3.1]`

**F2. M0～M2 不训练。** `[v3]`

**F3. M0 之前不实现 Schema（可先冻结文档版本）。** `[v3]`

**F4. 阶段不可跳越。** `[v3]`
前一阶段未达验收，不进入下一阶段。

**F5. 每次代码变更必须跑 M6 回归（M6 建立后）。** `[v3]`

---

## G. 安全

**G1. 不可逆操作默认拒绝。** `[v3]`

支付 / 删除 / 发送 / 提交 / 授权 / 登录凭证 / 验证码 / 账号安全 → 需显式确认。

**G2. 安全优先于任务成功。** `[v3]`

**G3. 安全误杀率 ≤ 5%，漏杀率 = 0。** `[v3]`

**G4. LLM 永远无法突破 Policy。** `[v3]`

---

## H. 基座策略

**H1. Agent Runtime 优先复用成熟实现。** `[v3.1]`

不重新发明 Browser / Snapshot / Execution。jev-ultrafast 的 `browser.py` + `snapshot.js` 是 Runtime 基座。

**H2. Decision 层必须与 Runtime 解耦。** `[v3.1]`

支持替换：`Jev API → 2B → 2B + Teacher Router`。替换点明确为 `model.py:choose()` 和 `model.py:field_text()`。

**H3. 基座决策：Fork jev-ultrafast（MIT）。** `[M-1]`

Runtime 保留，Decision 层替换。

---

## I. 代码不变量

**I1. tick 原子性。** `[M-1]`
`tick = predict + pre_execute + act`，任一环节失败则整体失败。pre_execute 不得暴露成独立命令。

**I2. decision 一次性消费。** `[M-1]`
`decision = None` 必须在 `browser.act()` 之前。pre_execute 引发的决策替换必须走新的 decision 对象。

**I3. 执行先于观察。** `[M-1]`
`history.append()` 必须在 `browser.observe()` 之前。observe 失败时 `page_changed` 保持 `None`。

**I4. fingerprint 严格匹配。** `[M-1]`
`body.fingerprint == page.fingerprint` 是 act 的前置条件。pre_execute 不得修改 fingerprint。

**I5. page_changed 三态。** `[M-1]`
`True / False / None` 三态语义。`None` 表示 "observe 失败，状态未知"。Loop Detection 必须用 `is False` 而非 `not`。

---

## 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v3   | 2026-09-23 | 初版：A1～A5, B1～B3, C1～C6, D1～D5, E1～E4, F1～F5, G1～G4 |
| v3.1 | 2026-09-23 | 新增 A6～A8, D6～D18, H1～H3, I1～I5；修改 B2, D2 |
| v3.2 | 2026-09-23 | 新增 A9, A10, E5, B4（schema / runtime 分层、失败四维、预算冲突优先级） |

## 冻结声明

**本文件 v3.2 已冻结。**
架构设计阶段结束。进入 M1 实现阶段。
