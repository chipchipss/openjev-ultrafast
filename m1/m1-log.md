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
| 6 | policy.py | ✅ |
| 7 | confidence_gate.py | ✅ |
| 8 | decider/ + prompts/ | ✅ |
| 9 | pre_execute 接入 agent.py | ⬜ |
| 10 | Logger 统一 | ⬜ |
| 11 | 20 tasks | ⬜ |

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
