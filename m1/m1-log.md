# M1 实施日志

> **状态**：📝 草案（持续追加）
> **关联硬约束**：F1 / F5 / A9 / A10 / D8 / B2
> **用途**：M1 阶段实现过程记录——进度、踩坑、跨文件同步点。

---

## 一、进度

| Step | 文件/事项 | 状态 |
|---|---|---|
| 1 | fork + demo.py 跑通 | ✅（集成 + §八 全绿 + R1-R5 五轮实跑） |
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
| 11 | e2e 20 任务 | ✅（R5 验收 PASS，零放宽） |

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

### 2026-09-23 · 后端接入：agnes-3.0-flash + Thinking 关闭 + Chrome 就位

- **key 定位**：omp 配置 `~/.omp/agent/config.yml` 默认 `agnes-3.0-flash` 直连
  `https://apihub.agnes-ai.com/v1`，api_key 走 env
  `HERMES_CUSTOM_APIHUB_AGNES_AI_COM_API_KEY`（= `~/.hermes/.env:536`，sk-3eJ3…Y89）；
  `models.yml` 另一把 sk-vjep… 走 LA 本地 8787/bili 代理，DE 不可用，弃用。
  fork/.env 已配 `DECIDER_2B_*` + `TEXT_HELPER_*`（同端点同模型），chmod 600。
- **连通实测（走 decider 真实通道 `_http.post_chat`）**：plain `OK` 825ms；
  `response_format=json_object` → `{"ok": true}` 592ms，usage 正常返回。
- **Thinking 探针（6 候选，单发对比）**：
  - **默认即关**：无 reasoning_content、无 reasoning tokens；但不带 response_format
    时输出带 ```` ```json ```` 围栏。
  - 干净胜出者：`reasoning:{enabled:false}`（587ms、7 tokens、裸 JSON）、
    `reasoning_effort:none`、`thinkingLevel:off`。
  - **毒参数**：`thinking:{disabled}` 与 `enable_thinking:false` 反而触发 thinking
    （37 reasoning tokens + reasoning_content）——禁用这两个。
  - distributor 渠道会漂（在案教训）→ `_http.post_chat` 恒带
    `reasoning:{enabled:false}`（上游 TEXT_MODEL "none" 同款）做渠道无关保险。
- **叠加验证**：`response_format` + `reasoning` 关闭同发 → COMBINED_OK
  （parsed dict、reasoning_content=False）。注意：choose_2b 的 `_parse_response`
  是裸 `json.loads`、无围栏容忍——完全依赖 response_format 生效（已实测生效）。
- **Chrome**：DE 装 `google-chrome-stable 154.0.8037.57`（browser_harness 为本地
  CDP 模式、不自带浏览器）——e2e 浏览器前提就位。

### 2026-09-23 · e2e 首跑两层故障与修复

- **表层：runner 自己崩了**。s001 的 `Agent(...)` 构造失败 → `_run_one` 返回
  `{"result": "ERROR", ...}`（字符串）→ main 第 259 行对 str 调 `.get` →
  AttributeError，**init 的 traceback 没来得及打印**。
  修复：4 处同类地雷全加 isinstance 归一化（main 打印行、`_summarize`、
  验收 #2/#5 循环）；验收 #1 由 `"result" not in r` 改为"非 dict 即缺 TaskResult"
  （否则 "ERROR" 字符串会被误判为有结果、验收假绿）。两仓同步修，dry-run 复验 OK。
- **真根因：harness daemon 起不来**（`chrome-not-running`），排查链条：
  1. Chrome 装了但没跑 → 手起 headless：专用 profile `/root/.config/chrome-cdp`、
     CDP 9222、`--no-sandbox`（root 必需）→ `/json/version` 探活 OK、
     doctor `[ok] chrome running`；
  2. daemon 仍拒 → 读源码：`supported_browser_running()` 只扫 harness 自己的
     **PROFILES 目录的 SingletonLock**，不认自定义 profile → 检测永远 False；
  3. 解法：`BU_CDP_URL=http://127.0.0.1:9222`（写入 fork/.env）走 `get_ws_url()`
     第一优先级的外部托管直连（源码注释即"dedicated automation Chrome"场景）→
     **`AGENT_INIT_OK https://example.com/`**。
- **Chrome 常驻命令（重启机器后需重跑）**：
  `setsid nohup google-chrome --headless=new --remote-debugging-port=9222
  --user-data-dir=/root/.config/chrome-cdp --no-sandbox --disable-gpu
  --disable-dev-shm-usage --remote-allow-origins=* about:blank
  >/root/chrome-cdp.log 2>&1 &`

### 2026-09-23 · R3 结果与第 4 轮三决策（fp 硬线 + D17 同构）

- **R3 vs R1**：pass 6→10、crash 10→1、**429 归零**（退避 6 次 + task-delay 5 生效）、
  s001 从 fp→correct_abandon（撞 google sorry 页后合理 BLOCKED）、
  n004 从 crash→budget_exceeded（agent 类，按设计兜底）。
  结论：核心链路全部验证通过，剩余为边界问题而非结构问题。
- **fp=4 拆解**：真 fp 3（s003 1 步 DONE、l001 0 步 DONE、t001 0 步 DONE——
  全是 "availability 当 completion"）+ 断言过时 1（l002 真实 slug 带 `and_dependencies`）。
- **决策1（批）**：l002 pattern → `List_of_countries`（断言容忍已知 slug 变体，
  不追长匹配，未来再改名不再误报）。
- **决策2（批）**：**fp 不是 M2 原料**——"没做对还说做对了"不可训练（谎报成功需要
  证据验证机制而非训练数据）；**fp=0 是硬线（G2），不调口径**。
  修法 = 替换 `prompts/next_action.txt` 的 DONE 段（navigation / search / list /
  form 四类 end-state 校验 + "availability ≠ completion"）。
  R4 判定：fp ≤1 过（残留 s001 型环境 fp 单列）；fp ≥2 → M1 内加 rule-based
  DONE guard（**本轮不加**：模型对 availability vs completion 的区分力是 M1 观察对象，
  加 guard 会掩盖信号）；M5 接语义验证。
- **决策3（批）**：act fill 分支 `field_text` 的 ValueError → StalePage（与决策 2
  同构：无法执行 = 决策无效；兜底 = 重 observe → 重 predict → 持续失败
  StepBudget abort → agent 类）。R3 的 crash=1 根因即此（f002，非 429）。
- **n001 记档不改**：PASS + blocked = false_negative 是**正确**分类——断言过了但
  agent 主动放弃 = 过保守（agent 类决策问题），非 evaluator bug。
- **R4 预期**：pass 11-13、fp 0-1、crash 0、decision fail 7-9、budget_exceeded 0-1。
- **M1 判定边界（docs/09 §九）**：条款 1/2/5 已绿；条款 3 = fp=0（或仅 s001 型
  环境 fp 单列）；条款 4 = crash=0（再现 D17 型则按决策 3 同构修）。
  M1 产出 = 失败模式清单，8-9 个 decision fail 是 M2 原料，不是 M1 的失败。

### 2026-09-23 · R4 结果与 R5 三案（DoneGuard 落位 + 传输重试 + prompt 补句）

- **R4 vs R3**：pass 10→11、fp 4→**2**、budget_exceeded→0、decision 8（预期区间内）。
  修复实证：s003（2 点击真导航 PASS）、t001（0 步 fp 消失）、f002（决策 3 生效——
  无 crash，填错字段 → 正确分类 agent/decision）。s001 连续两轮 correct_abandon。
- **fp=2 拆解**：
  - **l001**：0 步 DONE，四条 end-state 规则全拦不住（顽固型）→ 只能 guard。
  - **n004**：回归——换 DONE 块时丢了旧句 "a matching link is not enough"，
    R3 它本不是 fp → 案 1 补回 + search 加强。
- **案1（批）**：Navigation 块第三行——`If the goal says "open a result",
  having search results is NOT having opened the result.`（R4 换文之失，R5 补回）。
- **案2（批，三定）**：
  - 落点：`_pre_execute` 单步，链序 StepBudget → Validator → **DoneGuard** →
    Policy → Gate；私有 `_done_guard(decision, state) -> str | None`，不进
    decision_validator（保纯结构语义 + decider 侧可独立单测）。
  - 规则：① `DONE 且 len(history)==0` → 拒；② `goal.lower()` 含
    `"open "`/`"navigate to "`/`"go to "`（带空格防 opener/navigational 误伤）
    且 url 含 `"?q="` 或 `"/search"` → 拒。
  - 拒绝 → `raise StalePage`（与决策 2/3 同构，不另立分支）；
    持续拒绝 → StepBudget abort → agent 类。
  - **已知误伤窗口（记档不修）**：初始 url 即目标页；goal 含 "open search page"。
    M1 20 任务均无；M6 扩任务再细化。
- **案3（批）**：backoff 移到循环顶，传输异常（`httpx.HTTPError` 基类覆盖
  Timeout/Connect/Read）与状态码共用同一计数器/退避；日志前缀区分
  `transport error` vs `HTTP <code>`（R5 一眼分网络 vs 限流）；
  累计 ≈47s + jitter。
- **R5 判定边界（提前明确）**：五条件——全 TaskResult / FAIL 唯一 failure_mode /
  **fp=0 硬线** / **crash=0 硬线** / 四象限有记录。
  **唯一放宽口径（显式记档）**：若 R5 后 fp=1 且为 l001 顽固型——不算 M1 通过、
  但不再加 guard：记档 "3B 对 scroll-goal 的 DONE 判定不可靠"，该任务标
  known_limitation 不进 M2 训练集，**以 fp_excluding_known_limitation = 0
  判定 M1 通过**。fp 是"说谎样本"，放宽的唯一理由是隔离而非接受。

### 2026-09-23 · R5：**M1 验收 PASS（零放宽）**

- **五条件全绿**：`acceptance {passed: true, notes: []}`，error fields = 0——
  20/20 全有 TaskResult、8 个 FAIL 全有唯一 failure_mode、**fp = 0**
  （象限表无 false_positive 键，**未动用 known_limitation 放宽口径**）、
  **crash = 0 / api_unavailable = 0**（`system_modes {}` 空）、
  四象限 ca 8 + ts 11 + fn 1 = 20 全记录。pass 11→**12**、fail 9→8。
- **案3 实证**：`[retry]` 日志 6× `HTTP 429` + 1× `transport error: read timed out`
  全部被重试环吸收、零外泄 → s004 由 R4 的 read-timeout crash 转 **PASS**。
- **案2 实证（l001 全量 8 事件，DoneGuard 指纹）**：模型连发 3 次 DONE
  （conf 0.99 / 0.95 / 1.0）全被拒——**3 个 decision 无对应 step** 即拦截铁证——
  第 4 次改选 SCROLL_DOWN → 真滚动 → `assertion "found in step 1"` →
  **PASS true_success**。guard 逼出了真实行为（model_calls 6/30，预算健康）。
- **案1 实证（n004 全量 30 事件）**：补句后模型不再在搜索页谎报 DONE——
  老实填框（helper "RFC 9110"）→ 提交 → 结果页反复尝试 →
  budget `normal→warn→degrade→abort` 三次 transition 全记录 →
  **correct_abandon / agent / budget_exceeded**——诚实失败，零谎报。
- **M1 失败模式清单 = M2 飞轮第一批原料（8 条）**：
  - `decision` ×7：s001（google sorry 环境基线，连续多轮 ca 非 fp）、
    s005、f001、f002、f004、t001、x001
  - `budget_exceeded` ×1：n004（rfc-editor 搜索页 10 步耗尽）
  - 附记档：x002 = false_negative（PASS + blocked 语义，agent 过保守）、
    s001 环境类不进训练集。
- **M1 进度表 11/11 全 ✅**——Step 1 fork 与 Step 11 e2e 同轮收口。
- **基准存档**：`reports/m1-r5.json` + `logs/r5/`（R5 = M1 判定基准轮）；
  主仓与 fork 已同步 R5 三案（prompt 补句 / DoneGuard / 传输重试）。
- M2 起点建议：7 条 decision fail 做失败归因分桶（字段填错 / 导航不足 /
  过早放弃）、budget_exceeded 1 条做预算调参观察；M6 扩任务前回看
  DoneGuard 两个已知误伤窗口（§2.4 记档）。

### 2026-09-23 · M1 收口确认 + A0.3 记档（规划错位）+ M2 启动

- **M1 收口确认（用户）**：R5 = 判定基准轮，归档为 M1 黄金证据。五条件全过、
  crash 归零、fp 归零、known_limitation 口径未动用——干净收口、无遗留债务。
  三铁证单独记档：
  | 证据 | 意义 |
  |---|---|
  | l001：3 次 DONE 被拒 → 第 4 次改 SCROLL | DoneGuard 是引导，不是拦截 |
  | n004：10 步尝试 → 老实失败 → budget abort | 诚实失败进 agent 类，不是 fp |
  | `[retry]` 前缀区分 transport vs 429 | 诊断层已分级，R6 一眼定位 |
  合并含义：**系统从"能跑"变成"可观测"。**
- **A0.3 记档（下一轮随改动一起执行）**：此前"api_teacher 归 M5"是规划错位——
  v3 规划 M2 数据飞轮 C 类（API 修正）就需要 Teacher。正确划分：
  **M2 首次接入（无条件全量调用，产 preference pair / shadow 数据）；
  M5 校准优化（按需调用，校准后 P(correct) 低才触发）**——Active Learning 两阶段。
  **执行阻塞**：docs/03-milestones.md 与 CHANGELOG.md 均 ✅ 未落盘（已落 docs 仅
  01/09/10），A0.3 的"更新 CHANGELOG + 修订 03"缺原文——两件贴入即执行。
  清单侧 api_teacher 注解已同步纠正（M2 接入·无条件全量；M5 转按需）。
- **M2 启动清单（依赖序，记档）**：

  | # | 文件 | 作用 | 依赖 | 状态 |
  |---|---|---|---|---|
  | 1 | api_budget.py | B1/B4：Teacher/Recovery 分池限额 | 无 | ✅ 本轮 |
  | 2 | api_teacher.py | 复用 decider/_http，decision 场景 → corrected decision | 1 | ⬜ |
  | 3 | confidence_gate.py 修订 | MODE_SHADOW：本地+Teacher 并行只记录不切换 | 1,2 | ⬜ |
  | 4 | sample_extractor.py | 抽 4 类训练样本，C1 污染控制 | 无 | ⬜ |
  | 5 | m2/run_tasks.py | --mode shadow + 多轮 + 数据量统计 | 3,4 | ⬜ |
  | C | docs/03 A0.3 修订 | api_teacher 归属 M5→M2 正式落笔 | 03+CHANGELOG 落盘 | ⬜ |

  核心设计：M2 = MODE_SHADOW（不改执行路径，影子并行 Teacher）→ 不影响 M1 执行质量、
  产 C 类 2B vs Teacher preference pair、为 M5 校准供 ground truth。
- **数据量目标**：1000+ decisions / 200+ corrected。路径 A+B：50 任务 × 3 轮
  ≈ 750 + M1 存量 100 ≈ 850~950，余量人工修正补。30 个新任务模板已产出
  （`m2/tasks_extra.jsonl`，📝 草案：占位域 `<REPLACE_DOMAIN_PER_C1>` +
  断言占位 slug，**域由用户按 C1 决定**——避开 M6 benchmark 域与训练域；
  M1 基准 20 任务文件不动，独立文件）。
- **本轮交付（A→B→C 推荐链）**：
  1. `api_budget.py`：分池消费/限额/成本累计、`APIBudgetExhausted`、
     `log_entry()` 与 step_budget 同风格；**smoke 内置 ConfidenceGate §5bis
     四分支真实集成**（teacher→recovery→local→abort 用真实 APIBudget 走通，
     鸭子契约 `teacher_available/recovery_available` 当场验证）。
  2. `m2/tasks_extra.jsonl`：30 模板（search8/form6/nav6/list4/toggle3/negative3），
     ID 续号 s006+/f005+/n005+/l004+/t003+/x003+，dry-run 校验。
  3. A0.3 记档（上）+ 清单注解纠正。

### 2026-09-23 · C 落笔：A0.3 四步走完 + M2 #2/#C 交付

- **A0.3 四步完成（docs/03 v1.2 冻结生效）**：
  ① 不新增 hard-rules 编号（纯 03 内容修订）→ ② 理由：M2 四类数据含"API 修正"，
  Teacher 必须 M2——原"M5 产出"错位 → ③ CHANGELOG `[M2-start]` 条目落笔 →
  ④ 冲突检查对照 01 六条（F2/B1/B4/C2/E1/H2）**全 ✅，无冲突**。
  docs/03-milestones.md（v1.2）与 CHANGELOG.md **首次落盘**（已落盘 24→26）。
- **#2 `api_teacher.py` 落盘，冒烟 19/19 双布局**：
  - `APITeacher(budget)` 强制持真实 `APIBudget`（B1：Teacher 池消费，耗尽在入口
    即抛 `APIBudgetExhausted`）；
  - `TEACHER_BASE_URL / TEACHER_MODEL / TEACHER_API_KEY` 全部 required 且与
    decider 分开——**禁止静默同源**：同模型问不出分歧信号，C 类数据即废；
  - HTTP 复用 `decider/_http.post_chat`（退避重试 / 关 Thinking / json_object 全继承）；
  - 输出带 C4 三字段（source / api_model / api_confidence——C5 仅记录，M5 才校准）
    + corrected / usage / latency_ms；HTTP 或响应损坏 → RuntimeError（E5 system 类），
    **坏响应不消费预算**（先验后消耗）。
  - 冒烟修了两轮**测试数据** bug（位置参数记录、"缺 operation"喂错 payload），
    实现零改动。
- **#C `m2/c1_check.py` 落盘并首跑 PASS（exit 0）**：
  - 20/20 声明域可解析、0 违规、占位符泄漏检查就位（tasks_extra 填域后可直接复验）；
  - **benchmark 域名足迹 11 hosts = M2 划训练域的排除清单**：
    chromewebdata（x001 DNS 错误伪域，剔除）、developer.mozilla.org、docs.python.org、
    en.wikipedia.org、google.com、httpbin.org、news.ycombinator.com、python.org、
    rfc-editor.org、selenium.dev、w3.org；
  - 5 个 0 动作任务（f001/f002/t001/x001/x002）info 注明。
  - **语义修正记档**：原设想"首 step url = 起始页"不成立——agent 在 act 后把
    `history[-1].url` 更新为**动作后**页面（n001 点击后 step1.url=docs.python.org
    即例证）；起始页域校验需 logger 增加 initial_page 事件 → **挂 M2 #5 一并做**。
- **M2 进度**：#1 api_budget ✅ / #2 api_teacher ✅（本轮）/ #3 MODE_SHADOW ⬜ /
  #4 sample_extractor ⬜ / #5 m2/run_tasks ⬜ / C 文档 A0.3 ✅（本轮）。
- 下一步：B（30 模板填域）等用户按 C1 拍板——足迹清单已备好作排除输入；
  代码侧推进 #3 MODE_SHADOW。

### 2026-09-23 · M2 #3：MODE_SHADOW + agent 影子接入（契约核对与缝合）

- **§四契约核对结论：签名不匹配，且存在规格漂移**——启动清单原话"输入 decision
  场景，输出 corrected decision"（= 已落盘的 `correct()` **评审模式**，把本地答案
  喂给 Teacher，有锚定效应）；§四却是 `choose(page, goal, history)` **独立作答**
  （无锚定，C 类 preference pair 更干净）。处置：**补 §四 `choose()`**（独立模式、
  扁平 decision 输出、**不自消耗**——消费权归 agent._run_shadow 在 Validator 通过后，
  先验后消耗），`correct()` 保留作评审模式；**agent 侧你的代码一字未改**。
- **confidence_gate v2 落盘**：`MODE_SHADOW` / `GateResult.shadow_requested` /
  fixed_high 恒 False / shadow 恒 `go_teacher=False + shadow_requested=True`
  （不切执行路径，sentinel 也采集——DONE 过早是 M1 关键失败模式）/
  calibrated 下 sentinel 归 False、go_teacher=True 时 requested=True（校准数据持续采集）。
  **旧冒烟 1 处断言按 v2 语义调整**：fixed_high 分支先于 sentinel 判断 →
  g_high 下 DONE 的 reason 由 `sentinel_no_teacher` 改为 `mode_fixed_high`
  （sentinel_no_teacher 现仅存在于 calibrated 分支）。旧 40 + 新 9 = **49/49 双布局**。
- **agent 3 处增量落盘**：`__init__` 加 `api_teacher/api_budget`；gate_mode 自动
  （有 teacher → shadow，无 → fixed_high，**M1 调用行为零变化**）；
  `state.teacher_decisions=[]`；gate 后插 #5 shadow step；`_run_shadow()` 全异常
  吞掉（I1），分5 步：budget 检查 → 调用 → C2 Validator 校验（invalid 不消耗）→
  成功才 consume → 记录 local/teacher 对比（agree/operation_match/target_match + C4）。
  `_run_shadow` 不碰 `state["decision"]`——只记录不切换。
- **teacher choose() 冒烟 +11 → 30/30 双布局**：扁平字段、C4 三字段、
  **不自消耗**、goal+history 渲染、**无 "Local model" 字样（无锚定实证）**、
  耗尽抛 APIBudgetExhausted。
- py_compile ×3 双布局 ✓、`m1.run_tasks --dry-run` ✓。
- **选项C 启动**：M1 回归（20 任务无 teacher → 自动 fixed_high）验证 agent/gate
  改动对 M1 零影响。

### 2026-09-23 · M2 #3 收口三记档：契约漂移 + v2 断言语义 + teacher_decisions 落盘 gap

- **契约漂移（用户认领）**：启动清单版 = 评审模式（`correct()`，有锚定）、§四版 =
  独立作答——两版规格均用户所出，**定案：独立作答**。四维对照：

  | 维度 | 评审模式 | 独立作答 |
  |---|---|---|
  | 锚定效应 | 有（teacher 倾向微调本地答案） | 无 |
  | C 类 pair 质量 | 差（chosen/rejected 只差一步） | 好（两个独立最优解） |
  | DPO 训练价值 | 低（学不到全局偏好） | 高 |
  | 实现复杂度 | 略低 | 略高 |

  **C 类 pair 的训练价值取决于 chosen/rejected 的独立性，锚定污染独立性
  → 独立作答 = M2 正确选择。** `correct()` 保留为评审工具，但不产 C 类。
- **断言调整背书（v2 语义顺序）**：v1 sentinel 判断先于 mode；v2 mode 先于 sentinel。
  v2 更对：**fixed_high 是调度决策（此 mode 不采集），sentinel_no_teacher 是语义
  决策（DONE/BLOCKED 不需要 teacher）——调度层在语义层之上**；fixed_high 下任何
  decision 都不采集（含 sentinel）→ reason 必为 `mode_fixed_high`。
- **⚠️ 关键路径 gap：`teacher_decisions` 只在内存，到不了 logs**。
  `_run_shadow` 写 `state["teacher_decisions"]`，agent.close() 即丢；logger 不认识
  该字段（M1 时不存在）→ M2 百任务 × 每任务 5-10 条 → sample_extractor 从 logs/
  读不到 C 类 → **数据飞轮空转**。
  - **采纳选项 A（增量 `teacher_shadow` 事件）**：`observe()` 加第五游标 +
    `_clean_teacher_decision()` 白名单——与 step/decision/text_call 同构、按时间
    对齐（诊断哪一步分歧）、M5 校准需要 per-step 数据。放弃选项 B（finalize 批量）：
    无法按步对齐。
  - **M2 顺序修正**：#4a logger 扩展（阻塞点，~40 行）→ #4b sample_extractor →
    #5 m2/run_tasks。断言调整与本 gap 正交（gate 内部语义 vs logger 采集）。
- **#4b 设计对齐（不写码，待回归绿开工）**：
  - 输入 `logs/*.jsonl`（含 teacher_shadow）；输出 `samples/c_pairs.jsonl` /
    `a_positive.jsonl` / `b_reject.jsonl` + `manifest.json`（计数/域分布/污染检查）。
  - C 类筛选：agree → 不进 C；分歧且 teacher 有效 → **C 类（chosen=teacher，
    rejected=local，方向严格）**；teacher 输出无效 → teacher_invalid，不进任何集。
  - pair 结构：task_id / step / goal / `candidates_structured` + `candidates_rendered`
    （**C3 双份存储**）/ chosen / rejected / source=teacher / api_model /
    api_confidence / domain。
  - C1 流程（抽前过 c1_check）：**benchmark 域 → 跳过**；训练域 → 保留；
    未知域 → 保留但 `domain_unverified: true`，M2 结束人工复核。
  - **TRAINING_DOMAINS 待拍板（推荐已记）**：先"允许所有非 benchmark 域 + 标
    domain"，M2 结束按域分布再决定是否加白名单。BENCHMARK_DOMAINS 已由
    c1_check 从 M1 20 任务提取（11 hosts，剔除 chromewebdata 伪域）。
- **回归预期表（M1 回归 = M2#3 后零偏移验证）**：
  pass 12 / fp 0 / crash 0 / decision fail 7——任何偏移都是回归信号
  （M2#3 只加 shadow 分支，无 teacher 应走 fixed_high 完全不变）。

### 2026-09-23 · M1 回归诊断：机制零回归，fp=2 = 2B 内容层方差（待用户裁决）

- **回归结果**：PASS 11 / FAIL 9、**fp=2（预期0）**、decision 9（预期7）、
  crash 0 ✓、acceptance FAIL（仅 fp 一行 note）。
- **机制三不变量（全量 20 任务 step 事件扫描）**：
  `steps_with_shadow_key = 0`（_run_shadow 从未执行）、
  `gate_modes = ['fixed_high']` + `gate_reasons = ['mode_fixed_high']`（全轮无 shadow/
  mode_shadow 泄漏）、`teacher_decisions_in_pre = 0`；validator 全 ok。
  **→ M2#3 的 shadow 代码在 M1 路径零触碰，控制流无回归。**
- **fp=2 归属与 R5 逐行对照（差异全部在 2B 决策内容层）**：
  - **f004**：REG 3 次点击到 post_post 页后 **DONE conf 1.0** → fp；R5 同起点
    低置信探索（0.55）后 **BLOCKED** → ca。同链路、同 gate，唯 DONE 时机不同。
  - **n003**：REG step2 点进 **w3.org/TR/**（错页）→ DONE×2 → fp（断言 /standards 未达）；
    R5 step2 点进 **w3.org/standards/** → DONE → PASS。同一步模型选了不同元素。
- **方差历史佐证**：fp 曲线 R3=4 → R4=2 → R5=0 → REG=2、pass 10→11→12→11——
  DONE 时机与 target 选择本就在轮间摆动（temperature=0 但 distributor 后端非确定 +
  页面内容微变）。**M1 基线存在 run-to-run 方差，本轮把方差摆到了 fp 上。**
- **新覆盖缺口（诚实记档）**：n003 型 = **导航到错误页面后 DONE**（非搜索页形态）——
  DoneGuard 规则2 只拦 `?q=`/`/search` 型，拦不住此形态；要拦需目标 URL 比对
  （= 断言进控制面，**A2 红线**）→ 归 **M5 语义验证**地盘。f004 型 = 页内探索后
  过早 DONE（form end-state 规则未奏效）——同属 prompt/guard 现有边界。
  两缺口记为 M2 已知边界，不加规则（与 R4 时"guard 会掩盖信号"同一判断）。
- **待裁决**：a) 接受机制诊断 → 开 #4a/#4b；b) 再跑一轮取方差分布（~8min）；
  c) 任务级确定性加固。倾向 a：三不变量 + 逐行对照的证据链完整。

### 2026-09-23 · M2 #4a + #4b 一轮落盘：teacher_shadow 落链 + sample_extractor

- **裁决**：a 批准（+ 监测约束）。
- **架构洞察（记档）**：确定性 2B = 数据飞轮死锁——local 总对 → 无分歧无 pair；
  local 总错 → 单调 pair。**方差 = 数据飞轮的生命线。**
- **监测约束（记档，纯统计不碰执行路径）**：`fp_rate = fp 次数 / 任务轮次`
  （Logger append 模式 → 同任务多轮追加在同一 jsonl）；**fp_rate > 0.30** →
  pair 打 `high_variance: true`（仍进训练集）、manifest 标 `high_variance_task`，
  M6 优先处理（域调整 or 语义验证）。
- **M1 known_limitations 新增两条**：n003 型（导航到错误页后 DONE——DoneGuard
  规则2 只拦 `?q=`/`/search`）、f004 型（页内探索后过早 DONE——end-state 规则
  未奏效）；**归属 M5 语义验证**（URL 目标比对 = 断言进控制面 = A2 红线）。
- **方差接受声明**：M1 R5 的 fp=0 是**该轮次的值，非机制保证**；M2 起以分布
  （多轮统计）作为判定。
- **#4a logger 落盘（冒烟 50/50 双布局）**：`EVENT_TEACHER_SHADOW` +
  `_teacher_cursor` + observe 4b 抽取块 + `_clean_teacher_decision` 白名单
  （保留 actions_snapshot）；agent entry 增
  `actions_snapshot: list(state["page"]["actions"])`——**浅拷贝假设记档**：
  基座约定 page 对象不被就地修改（browser.observe 每次返回新对象），
  未来若出现就地改 action dict 的路径必须改 deepcopy；M1 已知路径均不违反。
- **C3 数据流闭环（trade-off 记档）**：_run_shadow 快照原始数据（不加工）→
  logger 白名单搬运 → sample_extractor 重放 action_space + **decider 的 prompt
  渲染函数**（同源防漂移）重建 structured/rendered。
  大小评估：action ≈200-500B × 20-50/步 × 5-10 步 ≈ 25-300KB/任务 →
  100 任务 ≈ 2.5-30MB——可接受。
- **#4b sample_extractor 落盘（冒烟 17/17 双布局 + 真实回归日志 EXTRACT_OK）**：
  - **两遍扫描**：pass1 收 events / fp_stats / final_quadrant，pass2 处理
    shadows——单遍会让 high_variance 恒 False（fp_stats 文件尾才写）、
    a_positive 时机错（final_quadrant 未定）——自查修正。
  - **A 类映射（设计决策）**：`agree ∧ task true_success`——唯一既满足 A 定义
    又带 actions_snapshot 可重建 candidates 的来源。
  - **B 类接线就位但预期 0（采集缺口记档）**：local validator 拒绝走 StalePage、
    pre 被清、不落 step——真正产出 B 类需 decision 级采集扩展（#4a 同类）。
  - **C 类**：chosen=teacher / rejected=local 方向严格 + C4 三字段 + domain +
    high_variance 标记。
  - **域门**：默认 benchmark = --tasks 域（M1 集即 benchmark）；
    `--benchmark-domains` / `--training-domains` 显式清单；占位域 →
    unverified + placeholder。**M2 混合任务集必须显式传 benchmark 清单**——
    默认推导会把训练域也算成 benchmark（smoke 白名单用例已验证）。
  - **真实回归日志实跑**：teacher_shadow=0（M1 轮无 teacher，符合预期）、
    **fp_rate 机制当场工作：high_variance_tasks=['f004','n003']**。
- **冒烟侧 4 个自查修正（全为测试/装配问题，实现逻辑零改）**：tempfile 作用域、
  fixture e1/e2 kind 记反、domain_distribution 双行计数（c_pair+a_positive）、
  pass1/pass2 时序。
- **C1 域语义提醒（影响数据量规划）**：M1 20 域 = benchmark 不进训练集 →
  **现有全部日志对 C 类产出 = 0 是 C1 设计使然**；pair 生产依赖训练域任务——
  **B（30 模板填域）是 C 类产出的真前置**。1000-decision 目标里"M1 存量 ≈100"
  按 C1 只能计入 decision 总量、不能计入 C 类 pair——域划分口径请在填域时一并明确。
- **M2 进度**：#1✅ #2✅ #3✅ **#4a✅ #4b✅** #5（m2/run_tasks --mode shadow）⬜ +
  文档 C✅；下一步 = #5 + B 填域。

### 2026-09-23 · M2 #5 落盘 + A0.3 双口径 + benchmark 清单防漂移

- **A0.3 双口径修订落笔（按 §一原文执行）**：docs/03 §5.6 拆
  `decision_total ≥ 1000（M1 存量可计入）` / `c_pairs ≥ 200（仅非 benchmark 域，
  M1 存量不计入）` + 口径表；CHANGELOG `[M2-start]` 增 "Changed (A0.3 · 口径修订)"。
  Rationale：C1 = benchmark 输出不进训练集，M1 20 域即 benchmark。
- **#5 `m2/run_tasks.py` 落盘——对原稿的四处缝合修正（核对 #4b 实际代码所得）**：
  1. extractor 导入 = `m2.sample_extractor`（#4b 在 m2/，不在 jev_ultrafast 包内）；
  2. `extract_all` 签名 = (log_dir, samples_dir, *, **tasks 必传**（pair 的
     goal/domain/category 只在任务表，日志不携带）, benchmark_domains, training_domains)；
  3. `_summarize` 的 result 归一化——init 失败 result 是 str，原
     `tr = r.get(...) or {}` 会对 str 调 .get 崩（m1 runner 同款地雷同款修法）；
  4. **域集合接缝**：#5 传原始行（带 www.），域门用归一 host 比较 →
     extract_all 入口统一 `_host()` 归一，双向消除格式错位（smoke 用
     `www.bench.example.com` 专测）。
- **#4b 增库接口 `extract_all()` + `contamination_check`**：manifest 增
  `contamination_check.violations`（输出行域 ∈ benchmark = 违规），#5 验收第3条
  读它；文件名轮次后缀 `{tid}_r{N}` → 还原任务 id（smoke 专测）。
- **`m2/benchmark_domains.txt` 实测生成**：从 m1/tasks.jsonl 提取 **11 域**，
  与文件 **match: True（零差异）**——含 R5 域替换（s002 docs.python.org /
  s003 www.w3.org / s005 developer.mozilla.org），剔除替换前旧域 duckduckgo/bing
  （原稿清单12行为过时版）。防漂移方案记档：c1_check 默认推导即是动态基准，
  此文件为 #5 required 参数的手工镜像——tasks 变更时重生成。
- **dry-run 双侧通过（§六验证序列）**：`Loaded 50 tasks, 1 rounds` /
  `Benchmark domains: 11` / 域分布 B×11 + **`[T] <REPLACE_DOMAIN_PER_C1>: 30`**
  占位一眼可见 / `DRY RUN OK`；extractor smoke **20/20 双布局**。
- **TEACHER_* env 未设 = e2e 前置**：#5 运行时需
  `TEACHER_BASE_URL / TEACHER_MODEL / TEACHER_API_KEY`——Teacher 模型必须区别于
  本地 decider（agnes-3.0-flash），候选：agnes-2.5-pro（models.yml 在册，上下文
  512k）——**等拍板后写入 fork/.env**。
- **M2 进度**：#1✅ #2✅ #3✅ #4a✅ #4b✅ **#5✅** 文档 C✅；
  剩：B 填域（C1 三选项待拍板）+ TEACHER 模型拍板 + 首轮 `--rounds 3` e2e。

### 2026-09-23 · 选项 3 落地：自建 test-site + 30 本地域任务（等 GLM key 解锁 5.3/5.4）

- **GLM key 搜索收口（step4 阻塞，todo 已 block）**：.env 注释态（`# GLM_API_KEY=`）、
  omp config.yml 无 provider 段、models.db 仅 model_cache 表、omp 进程不在且环境无
  命中、hermes custom_providers 只有 nvidia+agnes——**key 不在盘上，需 GLM 控制台
  三值**（base_url / model id / key）写入 fork/.env 的 `TEACHER_*`。
  候选形态（以控制台为准）：`https://open.bigmodel.cn/api/paas/v4` + `glm-5.3-flash`。
- **test-site 9 件落盘（双仓）**：index（6 导航 + broken link + 3000px spacer +
  footer）、search（GET `?q=` 跳转 + JS 渲染 "Search results for: {q}"）、
  form（3 字段 + preventDefault → "Thank you"）、technology（3 文章）、
  products（48 li 带 padding 可滚）、articles（8 篇）、settings（2 checkbox +
  2 radio + select + Save → "Settings saved."）、empty（Page Not Found）、
  serve.py（stdlib ThreadingHTTPServer，`--port 8765`，安静日志）。
  约束达成：纯 `<a href>` 导航 / form preventDefault / 零 CDN。
- **30 任务落盘（替换占位版）**：配额配平 s006-013 / f005-010 / n005-010 /
  l004-007 / t003-005 / x003-005；domain 带 path 定起始页
  （`http://localhost:8765/search.html` 等，_resolve_start_url 对 http 前缀原样返回）；
  negative×3 用 text_not_contains + notes（**正确行为是 BLOCKED**）。
  `training_domains.txt` = localhost / 127.0.0.1。
- **5.1 ✓**：index/form 200、HTML 正常服务。search 的结果文案是 **JS 渲染**，
  curl 看不到属预期——浏览器 agent 运行时可见。
- **5.2 ✓**：`Loaded 50 tasks, 1 rounds` + **`[T] localhost: 30 tasks`** +
  B×11 + `DRY RUN OK`——与预期输出逐字一致，占位域已被真实本地域替换。
- **运维教训记档（pkill 两次自杀）**：`pkill -f` 的模式会匹配**自己所在 ssh
  命令行的字面量**（含 nohup 路径里的裸 `serve.py`）→ 杀掉自身 shell →
  exit 255 且后续命令全没执行。修法：① 模式用括号 trick（`serve[.]py`）**且
  同一命令行不得再出现裸 serve.py**；② 能确认进程不在就别 pkill。
- **下一步**：等 GLM 控制台三值 → 写 TEACHER_* → 5.3（s006 单任务探针：
  decider 200 / teacher 无 429·401 / teacher_shadow 事件出现）→ 5.4
  `--rounds 3` 全量 M2 首轮 → 按五条判据读 reports/m2.json。

### 2026-09-23 · zhipu key 搜索收口 + choose() 三缺陷修复 + agnes-2.5-pro 教师验证通过

- **zhipu provider 八路搜索结论（key 不在盘上，证据链完整）**：
  omp config.yml（仅 modelRoles 引用）/ models.yml + bili-bak2（仅 agnesai）/
  hermes custom_providers（nvidia+agnes，GLM_API_KEY 注释态）/ .env（无活跃 GLM 键）/
  models.db（仅 model_cache）/ omp 进程（不在+环境无命中）/ billion-context.json
  （`providers: {}` 空）/ opencode·zcode·codex 客户端（无配置文件）。
  **`zhipu-coding-plan` 的运行时鉴权 = ZCode MITM 登录态**（billion-context README：
  `mitm://open.bigmodel.cn`，登录态走 LA 本地代理）——**不是可移植 sk- key**，
  无法写进 DE 的 TEACHER_*。bili-bak2 里那把 sk-vjep 是 agnes 的 key，非 zhipu。
  → step4 的 GLM 路径唯一解 = 用户从 bigmodel 控制台拿独立 API key（选项 B 待选）。
- **choose() 三个真缺陷修复（探针逼出来的，冒烟 30→36 双布局）**：
  1. **候选可见性**：`_scenario_choose` 原本不渲染 elements/operations——教师盲答，
     D8 会全拒、c_pairs 恒 0；
  2. **字段语义**：教师把 target 答成标签（"Guide"）、choice 答成 index（"1"）——
     根因①decider 的 `_render_elements` **不含 choice id**（decider 自己靠
     _map_choice 推导、不需要），教师需要 → 新增 `_candidate_block()` 教师专用渲染
     （`target="1" → choice="e1" label="..."` + controls + sentinels）+ SYSTEM 增
     Field contract（target=index 原样、choice=id 原样、仅用候选内值）；
  3. **解析脆性**：`_extract_json`（剥围栏 + 定位 braces），choose/correct 共用——
     渠道偶发围栏/前缀不炸链（空 content 仍 RuntimeError，冒烟双测覆盖）。
- **`TEACHER_PROBE2_2/2_OK`（agnes-2.5-pro 真实全链 ×2）**：
  `target=1 choice=e1 D8=True/ok`，1702ms / 1288ms，conf 0.99，budget 消费口径正常
  （choose 不自消耗 ✓）。key 有效（零 401/429）。
- **thinking 不可关（记档）**：2.5-pro 对 `thinking:{disabled}` 与
  `thinkingLevel:none` 都无视（reason_tok 仍 37-47）——接受开销：
  每次约 +40~90 思考 token + 1~7s，M2 量级（≈1000 次 shadow）成本可忽略。
  （`reasoning:{enabled:false}` 是 3.0-flash 的开关，2.5-pro 不认——两模型参数不通用。）
- **教师选型两路（待拍板）**：
  **A. agnes-2.5-pro（已全链验证、零等待）**——与 decider(3.0-flash) 不同模型，
  分歧信号成立，盘上已有 key；
  **B. GLM glm-5.3-flash（原计划）**——需控制台三值，多等一轮。

### 2026-09-23 · key 落点：omp auth_credentials + 5.3 s006 探针 PASS + 缺陷#4

- **用户指路命中——zhipu key 就在 omp 配置里**：`/root/.omp/agent/agent.db`
  （SQLite）→ `auth_credentials` 表 id=2：`provider=zhipu-coding-plan,
  credential_type=api_key, data={"key":"e1dd655…d2FyvWI3rrWPt8Ls","source":"login"}`。
  同表另有 deepseek / xiaomi 两把。baseUrl 取自 omp 二进制内置目录：
  `https://open.bigmodel.cn/api/coding/paas/v4`（`zhipu-coding-plan` → bigmodel coding
  端点，与 billion-context OpenCode 卡片一致）。config.yml 只有角色引用
  （`smol: zhipu-coding-plan/glm-5.3`），models.yml 仅 agnesai——**凭据真身在
  agent.db，此前八路漏搜了 SQLite 凭据表**。
- **TEACHER_* 三值落 fork/.env（LA↔DE 同步）**；端点探针：coding / paas 两 URL 均
  HTTP 200（key 有效），教师全链 `TEACHER_GLM_2/2_OK`：`target=1 choice=e1
  D8=True/ok ×2`（3.6/3.4s，conf 1.0/0.98）。
- **5.3 s006 单任务探针 PASS**：task PASS=true_success（final_url `?q=testing`
  命中断言）；`teacher_shadow_total=2` 且两事件 `agree=true, operation_match=true,
  target_match=true`（glm-5.3-flash，5666/4264ms，reasoning 123/90 tok）；
  budget teacher 2/10000；decider 零错误；429/401 零；验收闸按预期报
  `decision_total=3 < 1000`（单任务探针不构成全量判据）。
- **缺陷#4（探针暴露、已修）**：line1 嵌套 `shadow.status=failed,
  RuntimeError: Teacher returned non-JSON`——glm-5.3-flash 默认开思考，
  `max_tokens=512` 被 reasoning 吃光 → `finish_reason=length` → content 空。
  choose/correct 两处调用 `max_tokens 512→4096`，冒烟 36/36 双布局。
- **下一步**：5.4 `--rounds 3`（m1 20 + m2 30 = 50 任务 ×3 轮）→
  reports/m2.json 五判据 + 抽取 manifest（c_pairs / contamination）。

### 2026-09-23 · agnes 全换 deepseek-flash + 预飞 3/3 全绿 + 5.4 重启

- **触发**：5.4 首启跑到 r0 第46任务时 agnes-3.0-flash 渠道挂死
  （对照判据复现：3.0 = `000/15s`、2.5 = `200/1.66s`、`/models` GET `200`——
  活着列模型 = 渠道级挂；日志48×`HTTP 429` +19×read-timeout，任务卡重试环
  15min+）。kill 止血，残局归档 `logs/m2_429abort/` + `reports/m2_run_429abort.out`。
- **决策（用户拍板"干脆全换了"）**：agnes 套餐级限流，换模型治标 →
  **DECIDER_2B_\* + TEXT_HELPER_\* 全切 deepseek-flash**
  （`https://api.deepseek.com/v1`；key = omp `auth_credentials` id=1
  `sk-506c…`；`/models` 实测200列 **DeepSeek-V4.1-Flash**，chat `200/0.98s`）。
  .env 三块现状：decider/text helper = deepseek-flash，**teacher = glm-5.3-flash
  不换**（与 decider 异模型是分歧信号前提，否则 c_pairs 恒 agree 作废；
  GLM 同轮验证 `200/3.0s` 健康）。
- **预飞 s006（新栈，换模型后单任务）**：**PASS**；decision_total=3 /
  teacher_shadow_total=3（**每步都影子**，512→4096 修复生效）；
  **`agree: true ×3、failed shadow =0**；budget teacher 3/10000；**26s**
  （旧栈 92s，无重试内耗）。
- **可比性记档**：M1 e2e/R5 基线打在 agnes-3.0-flash 上；本轮起 decider =
  deepseek-flash（换模型是 env 级行为，设计允许；后续 R5 复测以新栈为准）。
- **下一步**：5.4 重启 `--rounds 3` → reports/m2.json 五判据。

### 2026-09-23 · 缺陷#5：predict 拒收不入账 → t004 死循环（卡 70min+）；修复 + 5.4 重启

- **实况**：r0 完成45任务后 t004（settings 页 plan SELECT）卡死。strace 教科书级
  证据：~1.1s/圈 "CDP observe → 拼 prompt → deepseek 调用**成功**（0.3-0.9s）→
  丢弃 → observe"，70min+ ≈3800 次空烧；零 step 日志、stderr 停 16:41、
  429=0、双端探测 200——**非网络问题，是循环 bug**。
- **根因**：`agent.py` predict 的 `except ValueError → raise StalePage` 发生在
  `decisions.append` **之前** → 破坏 docs/10 契约
  `model_calls = len(decisions)（含 StalePage 重试）` → StepBudget(40) 与
  `MAX_STEPS*2` 两道兜底**全部数不到** → temp=0 确定性输出同一非法 target →
  无限重试。R5 基线（agnes）少踩此路径；deepseek-flash 在 SELECT 任务上稳定
  非法 → 引爆潜伏雷。
- **修复（3处）**：
  ① 拒收**先入账再抛**（记录带 `rejected` 理由、None 化语义字段，logger 白名单
  `if k in d` 天然兼容）；
  ② `MAX_STEPS*2` 上限从 `raise ValueError`（逃逸 tick = crash，违反 system 空
  判据）改为 `status=budget_exceeded + return`——由 `_pre_execute` 的
  StepBudget ABORT 收口（**ABORT 分支先于 decision 访问**，decision=None 安全，
  已核代码序）；
  ③ `_clean_decision` 白名单补 `rejected`。
  extractor 不读 decision 事件（grep 零命中）——零迁移风险；拒收按契约计入
  `decision_total` ✓。
- **现场归档**：`logs/m2_r0prefit`（45任务）、`reports/m2_run_r0prefit.out`；
  连同 `m2_429abort / m2_53probe / m2_preflight` 全套留证。
- **密度实测→轮次判断**：r0 =254 decisions/45 任务 =**5.65/任务**；150 runs
  下限≈848；拒收入账后 t004/t005/x003-005 每个将贡献 40-80（temp=0 确定性）→
  **rounds3 预计 900-1440，有望自然过1000**；实测不足再补轮（届时单轮 ≈83min）。
- **运维复盘**：`pkill -f` 又踩自身 ssh 命令行字面量（本 log 早已记档）——
  改 `[t]` 括号防自匹配后一次成功。
- **5.4 重启**：修复栈 + `--rounds 3` 全量（50×3），单轮实测 ≈83min，
  ETA（19:00 起）≈ **21:45** 出 `reports/m2.json`。

### 2026-09-23 夜 · 缺陷#6（extractor 平层 glob）+ c_pairs 真实数学 + 过夜补 7 轮

- **5.4 三轮收官**：PASS=122 / FAIL=28 / **ERROR=0**；四判据全绿
  （decision_total **1813** ✓ 含 rejected 960；影子 **725** ✓（agree 567）；
  system 空 ✓；contamination **0/271 实检** ✓）→ 唯 **c_pairs=0 → FAIL**。
- **缺陷#6**：`sample_extractor` 用平层 `log_dir.glob("*.jsonl")`，而 m2 落盘在
  **轮次子目录 `logs/m2/rN/`** → 一个文件没读到（manifest
  `teacher_shadow_events=0` vs grep 实数 725）。修 `rglob` + **隔离式轮次子目录
  回归块** → 冒烟 **21/21 双布局**。重抽 = 同一 `extract_all` + runner 自己的
  `_m2_acceptance` 复算，仅覆写报告 manifest+acceptance（数据零改动）。
- **重抽真实数学**：725 影子 = benchmark 剔 251（C1 ✓）+ 训练域
  recorded 384 / invalid 12 / failed 1；**agree ≈84%**（a_positive 195 +
  agree 未成功 203）→ **c_pairs = 76**。**数据真相非 bug**：deepseek-flash 占位
  太强，与 GLM 分歧稀缺——设计中 decider=弱 2B 占位，弱才有错、教师才有得纠。
  **M2 关键发现**（影响后续本地 2B 接入与飞轮数据预期），非代码缺陷。
- **决策（用户征询）**：**过夜同栈补 7 轮**，不深夜换弱模型——temp=0 可复现 →
  ~25 对/轮 → 76+175≈**251** 过线有余；换弱模型=第三栈新雷风险+分歧率不保证+
  不省时；弱 decider 纯度实验留白天做第二数据集。
- **执行**：`--rounds 7 --log-dir logs/m2_more --report reports/m2_more.json`
  （≈83min/轮，ETA ≈08:30）+ DE 远端 marker watcher（`reports/overnight_done`）。
  **其 runner 自带抽取的 acceptance 会 FAIL（175<200）——忽略，只取 summary 合并。**
- **晨间合并 runbook**：
  1. `mkdir logs/m2final && cp -r logs/m2/r{0,1,2} → r0..r2 && cp -r logs/m2_more/r{i} → r$((i+3))`（i=0..6 → r0..r9）
  2. 合并两份 report 的 summary（整型字段相加；per_round 键 +3 重编号；
     budget used 相加、limit 取值）
  3. `extract_all(logs/m2final, samples, tasks, benchmark, training)` →
     `_m2_acceptance(merged, manifest)` → 写 `reports/m2_final.json`
- **现场归档不动**：`m2_r0prefit / m2_429abort / m2_53probe / m2_preflight`；
  `logs/m2_more` 为新 7 轮独占目录。

#### 晨间 runbook 补充（用户校订）：合并前两道预检 + 三档决策树

**预检（任何目录 <50 = 该轮中途 abort，先诊断，禁止直接合并）**：
```bash
# 1) 每轮目录应有 50 个 jsonl（50 任务 ×1 文件）
for d in logs/m2/r0 logs/m2/r1 logs/m2/r2; do echo "$d: $(ls $d/*.jsonl 2>/dev/null | wc -l)"; done   # 预期每行 50
for i in 0 1 2 3 4 5 6; do d=logs/m2_more/r$i; echo "$d: $(ls $d/*.jsonl 2>/dev/null | wc -l)"; done   # 预期每行 50
# 2) 合并后总数核对
ls logs/m2final/r*/ | grep -c jsonl   # 预期 500（10 轮 ×50）；不等 = 漏拷，先补齐再抽
```

**三档决策树（合并+重抽后按 c_pairs 总数走；三档都不下调门槛）**：
- **≥200** → 五判据全绿正式收口；记档"强 decider baseline"；
  白天可选跑弱 decider 作对照（**不必等对照结果才进 M3**）。
- **150-200** → 接受"强 decider 天然稀缺"结论 + 记档发现，**不追加轮次**
  （时间成本 > 边际收益）；弱 decider 实验提上日程（真正的 M2 补完）。
- **<150** → "decider 太强"结论更硬；直接进弱 decider 实验，
  补轮这条死路放下；**M2 收口口径改为"两个 decider 的对照实验"而非硬凑 200 pair**。

#### M2 核心发现·正式提炼（本条比 c_pairs=200 重要）

| 假设 | 现实 | 后果 |
|---|---|---|
| decider 弱 → 多分歧 → 多 c_pairs | decider 强 → **84% agree** | c_pairs 天然稀缺 |
| teacher 越强越好 | teacher 太强也死：一致率↑ | **两个模型能力要匹配** |
| M4 用 c_pairs 训 2B | 能力差不足 → 训练信号不足 | **M4 数据源要重新设计** |

- **结论**：M2 的价值不在"够不够 200 pair"，在发现——
  **两个模型的能力差才是数据飞轮的燃料**。
- **对 M4 的直接影响，两条路**：
  **A.** 用更弱的 decider 再跑一轮 M2（产 c_pairs）；
  **B.** M4 改用 SFT（a_positive + 人工修正）替代 DPO。
- **过夜补轮的真正定位**：不是凑数字，是**给弱 decider 实验准备 baseline**——
  76（+过夜增量）个 c_pairs = 强 decider baseline，白天弱 decider 那轮 =
  弱 decider baseline，两条曲线对比才是"decider 能力 vs 分歧率"的关系本身。
  **对照实验 = M2 最有价值的产出**；验收不让路，让发现说话。
