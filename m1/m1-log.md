# M1 实施日志

> **状态**：📝 草案（持续追加）
> **关联硬约束**：F1 / F5 / A9 / A10 / D8 / B2
> **用途**：M1 阶段实现过程记录——进度、踩坑、跨文件同步点。

---

## 一、进度

| Step | 文件/事项 | 状态 |
|---|---|---|
| 1 | fork + demo.py 跑通 | ⬜（全局卡点） |
| 2 | evaluator.py | ✅ |
| 3 | step_budget.py | ✅ |
| 4 | decision_validator.py | ✅ |
| 5 | runtime_guard.py | ✅ |
| 6 | policy.py | ✅ |
| 7 | confidence_gate.py | ✅ |
| 8 | decider/ + prompts/ | ✅ |
| 9 | agent.py 改造 | ✅ |
| 10 | logger.py | ✅ |
| 11 | tasks.jsonl | ✅ |
| 11 | run_tasks.py | ✅ |
| 11 | e2e 20 任务 | ⬜（等 import 适配补丁） |

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

### 2026-09-23 · policy + confidence_gate 落盘（pre_execute 链 5/5）

- pre_execute 链组件齐：Policy → Validator → Runtime Guard → Confidence Gate → StepBudget
  （A2 四元组：Policy / Validator / Confidence 分立实现，TaskSuccess = evaluator.py）。
- **SENTINELS 同步点扩大**：`{"DONE", "BLOCKED"}` 现在在 decision_validator.py、
  policy.py、confidence_gate.py 三处独立定义（外加 model.py + questions.py）——
  改 sentinel 集合需同步，见上文同步点表。
- policy 黑名单调整规则（G3）：M1 跑 20 任务后按实际误杀/漏杀**只改词表、不改逻辑**；
  只匹配 action.label，不扫 page.text（避免说明文字误杀）。
- confidence_gate：§5bis 状态机唯一实现处（B4）；M1 `mode=fixed_high` 永不升级，
  M5 切换只改 `__init__` 参数；阈值从 StepBudget 读（degrade → 0.75，D1）。
- 冒烟：policy `SMOKE OK: 34/34`、confidence_gate `SMOKE OK: 40/40`。

### 2026-09-23 · Step 6→7 前置落盘：prompts×3 + decider×3（接口 B 确认）

- **接口边界（拍板 B）**：OpenAI-compatible HTTP 为唯一 Decider 边界——
  `POST {base_url}/chat/completions`；base_url / model 经 `DECIDER_BASE_URL` /
  `DECIDER_MODEL`（或构造参数）配置；**不绑定 llama-cpp-python**，后端
  （llama.cpp server / Ollama / vLLM / 任意兼容 API）可换，代码不随然后端变。
- **来源说明（重要）**：`questions.py` / `model.py` 原文不在两台机器——
  DE `find`（/root /opt /home /srv，depth 5，questions.py / model.py / jev*）零命中；
  LA 浅层 glob + grep `NEXT_ACTION`（排除会话日志）零命中；基座 Step 1（fork）仍 ⬜。
  三件 prompts **按已冻结文档契约新写、非逐字移植**（D8 / D9 / D13 / A7 / A8 / D17
  规则逐条落入）。questions.py 原文到位后必须对照合并。
- **同步点新增**：

  | prompts 文件 | 来源 |
  |---|---|
  | prompts/next_action.txt | questions.py:NEXT_ACTION（原文待对照） |
  | prompts/target.txt | questions.py:TARGET（原文待对照） |
  | prompts/text_value.txt | questions.py:TEXT_VALUE（原文待对照） |

- **两阶段协议（A7 落地）**：stage1 `next_action.txt` 选 operation → DOM 类 stage2
  `target.txt` 选 target + choice；control / sentinel 的 choice 由代码派生
  （`controls[op]["id"]` / operation，与 decision_validator 同源）；
  产出必经 `decision_validator.validate()`（D8）自检，不通过抛 `DecisionInvalid`。
- **HTTP 出口**：`Decider2B.infer()` 是唯一网络边界（stdlib urllib，零第三方依赖）；
  `field_text_2b` 复用同一通道，坏输出走 ValueError（D17 设计特性）。
- **接口未知项**：`model.py:choose()` / `field_text()` 原签名待基座 fork 后在 Step 7
  适配；现对外 `choose(page) -> decision dict`、`field_text(hint, page) -> str | None`。
- 冒烟：choose_2b `SMOKE OK: 39/39`（含 D8 拒绝、unknown_operation、
  HTTP connection-refused、模板缺失路径）、field_text_2b `SMOKE OK: 11/11`
  （含 D17 null / ValueError 路径）。
- 踩坑（测试侧）：D8 用例曾对同一 Fake 连调两次 `choose()` →
  `IndexError: pop from empty list`，且断言 `attr/want` 误传造成假 FAIL——
  每次调用前重建 Fake 后修复；非 choose_2b 逻辑问题。

### 2026-09-23 · Step 8 落盘：8 件对话原文交付（进度表修正 6/7 拆分）

- **进度表修正**：原表 Step 6 双行为笔误，按用户更正拆为 6 policy / 7
  confidence_gate，后续顺延到 11；本轮 Step 8 = decider/ + prompts/ 全部落盘，
  覆盖上一版按契约新写稿。
- **协议变更**：单次调用——`next_action.txt` 一次输出 `operation + target +
  双置信度`；choice 由 `_map_choice()` 代码推导（D8 天然成立：2B 从不输出
  choice）。`target.txt` 按 D16 保留为资产，M1 不加载。
- **新文件**：`decider/_http.py`（唯一 POST 实现，429/529/503 指数退避，失败抛
  RuntimeError——契约对齐 model.py:post_json）、`decider/action_space.py`
  （model.py:action_space() 移植副本而非 import，H2）。
- **同步点新增**：

  | 项 | 位置 | 来源 |
  |---|---|---|
  | action_space 三层结构 | decider/action_space.py | model.py:action_space()（任何差异都是 bug） |
  | prompts×3 | prompts/*.txt | 对话原文（2026-09-23 覆盖旧稿） |

- **运行依赖**：httpx（DE 装 `python3-httpx 0.22.0`，apt；DE 无 pip）。
- **env 契约**：`DECIDER_2B_BASE_URL`(required) / `DECIDER_2B_MODEL` /
  `DECIDER_2B_API_KEY`；`TEXT_HELPER_BASE_URL`(required) / `TEXT_HELPER_MODEL` /
  `TEXT_HELPER_API_KEY`。
- **接口**：`choose(state, goal, history) -> decision`（保留 choice / confidence /
  probabilities[choice] / operation / target / usage / latency_ms / request
  旧字段，agent.py 零改动）；`field_text(context) -> (text, helper)`——
  `{"text": null}` → ValueError（D17：nothing typed，不编造）。
- **冒烟踩坑（测试侧，非逻辑）**：
  1. `-m` 双模块副本：`mod.post_chat` patch 打在 `decider.choose_2b` 副本，
     裸调 `choose()` 走 `__main__` 副本 → 真发 HTTP `http://mock/v1` DNS 失败。
     修复：`_smoke` 内 `global choose; choose = mod.choose` 绑到被 patch 副本
     （field_text_2b 同款修法）。
  2. SELECT 索引 off-by-one：fixture 中 e1/e2 共享 node12 → e4 是 element
     `"3"`，合法 target 为 `"3:1"`（与 decision_validator 冒烟 `{"3:1","3:2"}`
     一致），原断言 `"4:1"` 会抛 ValueError。已改断言，非 action_space 问题。
- 冒烟：choose_2b `SMOKE OK: 19/19`（11 类路径）、
  field_text_2b `SMOKE OK: 8/8`（6 类路径）。

### 2026-09-23 · Step 9 落盘：agent.py 改造（唯一改基座处）

- **4 点改动**：① tick 内 predict 后插入 `_pre_execute()`（I1：tick = predict +
  pre_execute + act，不暴露为命令）② 新增 `_pre_execute()`，链序 StepBudget →
  DecisionValidator → Policy → ConfidenceGate → §5bis（M1 死代码保留）③
  run() / predict 首检终止条件加 `budget_exceeded`（共 3 处同步）④
  history.append 新增 `pre_execute` 字段（act 开头 `state.pop`，
  tick 的 StalePage 分支清空防跨 tick 残留）。
- **关键语义**：Validator 失败 → 抛 StalePage（重 observe → 重 predict，
  持续非法由 StepBudget abort 兜底）；Policy 拒绝 → 直接 blocked（G2 安全优先）；
  fixed_high 下 gate 恒不升级，§5bis 为 M5 挂钩（A5 / B4）。
- **向后兼容**：`task_spec=None` → `StepBudget(MAX_STEPS, MAX_STEPS * 2)`，
  与原硬上限行为等价；decider 契约核对一致——`choose(state, goal, history)`、
  history 旧字段（probabilities[choice] / confidence / latency_ms / usage /
  operation / target）全部命中 round-8 decider 输出。
- **基线说明**：agent.py 全文在本对话中首次出现（此前仅 recon-log 摘要），
  无本地版本可对比 drift；以本轮贴出版本为基准落盘。
- **验证边界**：`python3 -m py_compile agent.py` 通过（PY_COMPILE_OK）；
  e2e（浏览器 + mock decider）依赖基座包结构（`.browser / .model / .questions`
  相对导入）与浏览器——**Step 1 fork 仍 ⬜，运行级验证推迟到 fork 后**。
  **同步点**：fork 时须把根级模块（decision_validator / policy / step_budget /
  confidence_gate）安放进 `.xxx` 相对导入可达的同一包目录。
- **观察（供 Step 10 Logger）**：DONE / BLOCKED 终态 tick 的 act 走哨兵分支早返回，
  该步 `pre_execute` 不进 history（与基座"终态步无 history 行"一致）——
  Logger 若要终态预算快照需另取（`state["pre_execute"]` 在该分支 pop 后未写入任何地方）。

### 2026-09-23 · Step 10 落盘：logger.py（代码侧全部就位）

- **Step 9 两点观察的处置**：① 同步点（fork 包结构）记入本日志，不影响产出；
  ② 终态 pre_execute 丢失**不在 logger 里绕过**——用
  `task_result.final_budget`（`finalize(step_budget=...)`）补偿，
  设计边界不假装不存在。
- **设计要点**：四个数据源（history / decisions / text_calls / transitions）
  各自独立游标，重复 observe 返回 []；只读鸭子类型、不 import agent；
  白名单字段过滤（未知字段不进日志，冒烟测例 12 验证）；
  `page_changed=None` 保留（`k in h` 而非 `h[k] is not None`）；
  懒开文件（不 flush 不产生空文件）；5 类事件、一个 task 一个 JSONL。
- **接口**：`observe(state, *, step_budget=None) -> list[dict]`、
  `finalize(task_result, *, step_budget=None, final_page=None) -> dict`；
  task_result 兼容 dataclass（evaluator.TaskResult）与 dict。
- **与 evaluator 的衔接（Step 11 用）**：
  循环内 `logger.observe(agent.state, step_budget=agent.step_budget)` →
  终态 `result = evaluate(spec, page, history, status, meta=...)` →
  `logger.finalize(result, step_budget=agent.step_budget, final_page=page)`。
- 冒烟：`py_compile` 通过，`SMOKE OK: 40/40`（13 类路径：空 state / 游标重复 /
  增量抽取 / decisions·text_calls / budget_transition 增量 / finalize 双输入 /
  JSONL 内容 / flush_every=1 / close 幂等 / 参数校验 / 白名单过滤 / 非 dict state）。
- **Step 11 前置**：fork jev-ultrafast（全局卡点）+ m1/tasks.jsonl + m1/run_tasks.py。

### 2026-09-23 · Step 11 前置落盘 + 上游 fork 实测

- **落盘 3 件**：specs/task.schema.json v2（首个落盘的 spec）、m1/tasks.jsonl
  （20 任务完整版）、m1/run_tasks.py（benchmark runner，原稿外新增文件）。
- **api_teacher.py 更正**：移出 M1 → M5 产出（M1 Confidence Gate 恒 fixed_high
  永不升级）；清单 ⬜ 仅剩它一件。
- **5 代表 vs 完整版**：f001 / n001 / l001 / x001 四件在完整版中域/断言换成公开基准站
  （example-* 占位 → 真实站），以完整版为准；s001 两版一致。
- **dry-run（DE 实跑）**：`python3 -m m1.run_tasks --dry-run` → `Loaded 20 tasks`
  + `DRY RUN OK`；配额 grep 实测 search5 / form4 / navigate4 / list3 / toggle2 /
  negative2 = 20，与清单配额精确一致。
- **上游 fork 实测**（clone `github.com/browser-use/jev-ultrafast` → DE:/root/jev-ultrafast）：
  - **package 结构**：`jev_ultrafast/` 带 `__init__.py`；agent / browser / model /
    questions / demo 全在包内，agent.py 相对导入与我们 M1 版同源 →
    我们的根级模块须并入 `jev_ultrafast/` 包内（`from . import decision_validator` 即可直接工作）。
  - 工程形态：pyproject（hatchling）+ uv.lock，entry `jev = jev_ultrafast.demo:main`；
    **requires-python >= 3.12**（DE 系统 python3.10 —— e2e 需 uv 装 3.12）；
    依赖 browser-harness==0.1.13 + httpx[http2]（与 decider/_http 的 httpx 一致）。
  - env 差异：上游 .env.example 用 TYPESAFE_* / TEXT_MODEL_*（旧 model.py 契约）——
    整合时换成 decider 的 DECIDER_2B_* / TEXT_HELPER_*。
  - docs/ 与上游并存无文件名冲突（上游 = design.md / performance.md / 测量资产）。
  - MAX_STEPS=60 在 questions.py:26，与我们引用一致。
- **agent.py 漂移核验（关键）**：GitHub 上游基线 vs 落盘 M1 版——我们版从基线
  **删除的行仅 3 处**，全部在 4 点改动内（__init__ 签名、predict 首检、run() while）；
  其余全为 M1 标注新增（pre_execute 链）。**零意外漂移**，对话基线 == GitHub 上游。
- **下一步（A 路径）**：用户按实测包结构出 agent.py import 适配补丁 → 合并入库 →
  3.12 环境 + 真实 2B 后端 → e2e 20 任务。

### 2026-09-24 · M1 本地 3B LoRA 跑 20 任务（首跑 + 系统侧验收 PASS）

**背景**：M4a 本地 3B LoRA（`unsloth/Qwen2.5-3B-Instruct-bnb-4bit` + `m4a/adapter`）
经 OpenAI 兼容 server（`m4a/serve.py` @ :8000）作 decider/text-helper 后端，
跑 M1 公开站点 20 任务，验证"本地 3B 替代 API 支撑完整 Agent"。

#### 三轮对比

| 轮 | CDP reset | Loop Detection | DONE Guard 3/4 | PASS | fp | crash | ERROR | acceptance |
|---|---|---|---|---|---|---|---|---|
| v3 | ✗ | ✗ | ✗ | 4 | 2 | 1 | 3 | FAIL |
| v4 | ✗ | ✅ | ✅ | 6 | 0 | 1 | 1 | FAIL |
| v5 | ✅ | ✅ | ✅ | 6 | 0 | 0 | 0 | **PASS** |

**v5 最终 summary**（`reports/m1-local-v5.json`）：

```
PASS=6  FAIL=14  UNKNOWN=0  ERROR=0
quadrants: correct_abandon=14  false_negative=5  true_success=1
failure_modes: decision=6  budget_exceeded=8
acceptance: PASSED（system_modes 空，无 crash/无 fp/20 task 全有 TaskResult）
```

**v5 五条验收 PASS 证据**：
1. 20/20 task 全有 `TaskResult`（`error=0`）✅
2. 每个 FAIL 有唯一 `failure_mode`（decision / budget_exceeded）✅
3. `false_positive=0` ✅
4. `system_modes={}`（无 api_unavailable / crash）✅
5. 四象限有记录 ✅

#### ABC 三阶段改动（M1 本地跑的工程链路）

| 阶段 | 文件 | 改动 | 效果 |
|---|---|---|---|
| A | `decider/choose_2b.py` | f003 诊断（只读）：selenium.dev 首页 search 是键盘触发 button（无 fill input），`action_space` 只有 `[CLICK]` targets，3B 从 goal 推断 `TYPE_TEXT` → `_map_choice` 抛 unknown operation | 定位死循环根因，非代码 bug |
| B.1 | `agent.py:159` | **Loop Detection**：`_pre_execute` 里 StepBudget 后/Validator 前，连续 3 次同 `choice` → `state["status"]="blocked"` | crash 1→0（s001 救回）；治死点/死 op 循环 |
| B.2 | `agent.py:46-59` | **DONE Guard 规则 3/4**：submit 类 goal 必须见确认字样；scroll/find 类 goal 必须 history 有 scroll | **fp 2→0**（安全硬线达标）|
| f004 | `m1/run_tasks.py:56` | **CDP reset**：task 间杀 Chrome + 重启干净 CDP 实例 + 预热 daemon，`--task-delay` 3→5s | **ERROR 1→0**（f004 `no close frame` 崩）|

**其他工程链路（M1 本地跑前置，均已就位）**：
- `snapshot.js name()` 加 STYLE/SCRIPT/NOSCRIPT/TEMPLATE 四重过滤——Google 页 CSS 泄漏进
  element label 致 prompt 污染 → 3B 复读 CSS（M4a 数据 0%>20 elements vs 推理 52 的 OOD）
- `decider/choose_2b.py:159` `actions[:30]` 截断——对齐 M4a 训练分布（p90=13, max=14）
- `m4a/serve.py` force_json：非 JSON 输出（OOD 退化 ` release!!!`）立即回 WAIT 骨架，不重试
  （确定性模型重试无意义，避免 httpx 超时）
- 基座 `jev_ultrafast/` 包缝合（`from jev_ultrafast.agent import Agent`）+ `.env` 本地 3B 指向

#### 判决

- **系统侧（M1 验收）**：**PASS**——fp=0 / crash=0 / ERROR=0 / 20 task 全有 TaskResult
- **3B 决策推进力**：true_success=1，PASS=6/20=**30%**
- **对照 R5 API baseline = 12/20 = 60%** → **gap=30pp**

**gap 性质判定（需 decider-2B 对照区分，本轮未做）**：

本地 3B vs API 的 30pp gap 可拆两类：
1. **3B 能力 gap**：3B 面对复杂任务推进力不足（`correct_abandon=14`，多数任务正确放弃）
2. **decider 工程 gap**：3B 决策对但 decider 侧处理不当（如 f003 `TYPE_TEXT` 拒收、长页截断）

**本地 M1 的 6/20 无法直接对比 R5 的 12/20**——R5 用 API decider，本轮用本地 3B decider，
变量不单一。需 **API decider 在相同 20 任务跑一轮** 作对照（隔离出"3B 决策力" vs "decider 工程"
两个维度），才能定 M4b 方向。

#### 下一步（M4b / M5-M6 挂钩）

- **Loop Detection 调参**：`same_choice_3_times` 对"反复点同元素但可换 op"的任务偏激进，
  可能误伤推进类（v5 见 `false_negative=5`）。M5/M6 扩任务集时按实际误杀率细化（只拦
  DONE 循环 / 放宽到 5 次 / 按 op 类型分档）。
- **f003 的 `TYPE_TEXT` 拒收**：selenium.dev 类键盘触发搜索框无 fill input，3B 合理输出
  `TYPE_TEXT` 但 `_map_choice` 无该 op → 死循环。短期靠 Loop Detection 收口（已做），
  长期需 decider 侧对"operation 不在 action_space"降级为 BLOCKED（不抛 unknown operation）。
- **M4b 数据**：补真实网页 observe 数据（混入长 elements 页 + 推进类正样本）治
  `correct_abandon` 过高；补"submit 后必须见确认"负样本治 fp（本轮已 0，防回归）。

**f004 CDP 崩溃修复完成**（task 间 CDP reset + 5s delay，`m1/run_tasks.py:56`），无需重复。

### 2026-09-25 · D19 Candidate Filter 双层模型（L2 截断参数化）

- **现象**：decider-2B 长 state 任务（l003 等）单步决策 15–38s，20 任务整轮 89min；
  时间拆解显示 92.7% 墙钟在 decision latency，瓶颈在 decider 侧 token 数。
- **定位（离线 body dump）**：`state.elements_json` 占 body 76%（5,822 chars / 7,646 total），
  `page.text` 仅 47%（截 1500 后 20%）——**token 大头在 elements（候选元素列表），不是 page.text**。
  此前截 `page.text[:1500]` 无效（input_tokens 仍 2300+）。
- **L2 截断层**：`model.py:_candidate_filter(elements)` 集中化，env 参数化
  `DECIDER_MAX_ELEMENTS`（默认 25）/ `DECIDER_MAX_LABEL_CHARS`（默认 80）；
  截 elements 数量上限 + 单 label 长度，body 构造前调用。
- **双层模型（拍板）**：L2 为 L1（接口）/L3（实现）之间的**可替换截断层**——
  L2 截断参数化完成（DECIDER_MAX_ELEMENTS / DECIDER_MAX_LABEL_CHARS）。
  未来 L2 演进为相关性排序（M3）或模型判断（M8）时，**替换 `_candidate_filter` 实现，
  接口不变**（入参 `elements` 列表 → 出参截断后 `elements` 列表）。
- **禁忌遵守**：不动 decider 源码、不改断言。

---

### 2026-09-25 · M1 decider-2B 基线稳定 + 一键脚本就位

- **两次连续 M1 acceptance PASS**：v9（手动）和 v0925-1245（一键脚本）
- **最终数字**：PASS=7/20 (35%)、crash=0、fp=0、error=0
- **耗时**：25.6 分钟（一键脚本全流程）
- **方差**：±1 任务（f004/l003 在轮次间摆动，2B 级模型固有）
- **一键脚本**：`run_m1.ps1`
  - 自动禁锁屏
  - 杀旧进程（decider / CDP / runner）
  - 清 CDP profile + browser-harness state
  - 起 headless CDP Chrome
  - 后台起 decider-2B（含 DECIDER_MODEL 等 5 个 env）
  - 等待 /health 就绪
  - 设 benchmark env（含 DeepSeek text-helper）
  - 跑 20 任务
  - 自动停 decider + Chrome
- **遗留问题**：decider 长跑退化（~2h 后 10-20x 慢）——跑前重启可治
- **本轮改动汇总**：
  - model.py: timeout 25→90
  - model.py: page.text[:1500] 截断
  - model.py: _candidate_filter(25/80)
  - model.py: choose() 顶层 RuntimeError → StalePage（缺陷#9）
  - agent.py: 1.5b Loop Detection on decisions（缺陷#10）

---

### 2026-09-25 · M2 正式收口（ACCEPTED）

**五条判据全过**：
- M2.1 decision_total = 6044 (≥1000) ✅
- M2.2 c_pairs = 243 (≥200) ✅
- M2.3 contamination = 0 ✅
- M2.4 system_modes = {} ✅
- M2.5 dataset split reproducible（task_id-based, val=f010/n008/s011）✅

**数据集**：951 样本 = 837 train / 114 val
- a_positive 708 / c_pairs 243
- token p50=743 / p99=806

**验收报告**：`reports/m2_acceptance.json`
**数据源**：`reports/m2_final.json`（原始采集日志在服务器，不随仓库发布）

**已知 gap（保留）**：
1. user prompt 缺 Current page + Recent actions 段
2. c_pairs 的 target_confidence = api_confidence 行级近似

**reproducibility 边界**：
- acceptance 可复现（用 m2_final.json + report.json + train/val）
- 原始采集过程不可从 clone 重放（需服务器 logs/samples_final）

**下一步**：M3 (Reranker 条件性) / M4b (扩数据训练) / M5 (Confidence Gate 校准)
