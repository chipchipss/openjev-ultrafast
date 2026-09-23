# M1 实施日志

> **状态**：📝 草案（持续追加）
> **关联硬约束**：F1 / F5 / A9 / A10 / D8 / B2
> **用途**：M1 阶段实现过程记录——进度、踩坑、跨文件同步点。

---

## 一、进度

| Step | 文件/事项 | 状态 |
|---|---|---|
| 1 | fork + demo.py 跑通 | ⬜（集成 + §八 已全绿，demo 等 2B 后端） |
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
| 11 | e2e 20 任务 | ⬜（等 2B 后端资产） |

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

### 2026-09-23 · M1 集成执行：integrate.sh + 桥接 + 3.12 环境 + §八 全绿

- **冒烟可移植性修复（集成前置）**：decider 两冒烟的 `import decider.choose_2b as mod`
  在包结构下会 ModuleNotFoundError——改 `mod = sys.modules[__name__]` 自 patch，
  平铺（主仓）/ 包内（fork）两种布局通用；主仓平铺复验 19/19 + 8/8 不回归。
- **集成**：`scripts/integrate.sh`（入库存档）执行——agent.py 替换 + 7 模块 +
  decider/ + prompts/ 归位 `jev_ultrafast/` 包内；m1 / docs / specs 并入 fork 根，
  与上游 design.md 等无文件名冲突。
- **三处补丁（fork 实测标记）**：
  - model.py 桥接 4 处：decider import ×2、`choose`→`choose_typesafe`、
    `field_text`→`field_text_typesafe`（各加"原 TypeSafe 实现"docstring）、
    文件末尾委托函数（agent.py import 不变）。action_space 两份并存（H2：Decision 层
    不依赖 Runtime）。旧 TYPESAFE_* / TEXT_MODEL_* 默认不可达（M5 可加开关）。
  - m1/run_tasks.py 4 行 import → `jev_ultrafast.*`（fork 专用版）——**两仓该文件
    从此分叉**：主仓保留平铺 import（standalone dry-run 用），fork 用包内 import；
    重新 integrate 后需按 §四 重打此补丁（已入 integrate 提示语）。
  - .env.example 换 `DECIDER_2B_*` / `TEXT_HELPER_*`；pyproject 增
    `[tool.hatch.build.targets.wheel]` packages + prompts force-include（§六.1）。
- **环境**：uv 0.12.18 + CPython 3.12.14 + `uv sync`（httpx 0.28.1、
  browser-harness、项目本体 editable）。系统 python3.10 不再参与 fork 验证。
- **§八 验证全绿（.venv/bin/python）**：
  1. py_compile 15 文件 → STEP1_PY_COMPILE_OK
  2. 8 模块冒烟全过：step_budget 47/47、decision_validator 35/35、runtime_guard 40/40、
     policy 34/34、confidence_gate 40/40、logger 40/40、choose_2b 19/19、
     field_text_2b 8/8——与主仓数字逐一一致
  3. `bridge ok`（model 委托 ×5 符号 + agent 可 import，browser_harness 就位）
  4. `Loaded 20 tasks` + `DRY RUN OK`（包内 import）
- **RuntimeWarning 说明（外观性）**：上游 `jev_ultrafast/__init__.py` =
  `from .agent import Agent; from .browser import Browser` 急切导入，链到
  agent → model → decider 与 4 个 pre_execute 模块，`python -m` 复执行时 runpy
  提示 found in sys.modules——冒烟结果不受影响（sys.modules[__name__] 修复正为此）。
- **e2e 唯一阻塞**：DE 无 2B 后端资产（无 GGUF / Ollama 权重）——后端就位 →
  起服务 → `python -m m1.run_tasks` 跑 20 任务 → 按 §十一 报告
  （summary/acceptance + 前 3 个 jsonl + error/traceback）。
