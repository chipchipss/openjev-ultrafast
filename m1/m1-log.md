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
