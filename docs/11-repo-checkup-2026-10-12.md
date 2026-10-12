# 外部体检报告存档（原文照录，一个字不改）

- 来源：Bot 团队双线审查（核心代码质量 + 架构与脚本债务），针对 commit `c26f250`；
  原文在仓外 `C:\Users\Administrator\.dsh\bot\workspace\openjev-ultrafast-体检报告.md`，那是个会被回收的临时位置，
  所以把原文录进来——任务描述里"某条来自体检报告"必须在仓内有落点。
- **我方核验（2026-10-12，每条自己量过，不照抄它的数）**：
  - 体量口径**准**（按字节）：`skills.py` 118.8 KB、`agent.py` 49.4 KB、`browser.py` 32.7 KB、`logger.py` 22.1 KB。
    行数**不准**：`agent.py` 实测 864 行（它写 1100+）、`browser.py` 606（写 700）、`logger.py` 564（写 480）。
  - **核实为真、且是整份报告最值钱的一条**：`jev_ultrafast/logger.py:228-239` 的 `_clean_step` 白名单只留 15 个键，
    `outcome` / `url_from` / `page_fp_before` 被静默丢弃——这三个恰是 #59 到达判据与"起点页 vs 落地页"推理所读的字段。
    2026-10-11 晚我因此没法从 jsonl 判断"结果文本何时出现"，只能重开一个自有浏览器做零模型复探。
    硬规矩写的是"反常指标第一动作是翻 jsonl 日志"，而日志缺的正是这些字段 ⇒ 这条转成 **#67，优先级高于一切重构**（#67 日志字段 / #68 静默异常 / #69 PowerShell 收敛 / #70 零行为重构 / #71 归档折中，编号即任务号）。
  - 宽 `except Exception` 实测 **29 处**（skills 9 / agent 7 / browser 12 / logger 1）；`browser.py` 里 `print(` **7 处**；
    `_STUCK` 确为模块级可变全局；`_smoke()` 夹具确占 `logger.py` 约三分之二；根目录确为 **9 个 `.ps1`**。
  - `run_demo.ps1` 的 `$helperUrl` 疑似笔误：两个标识都在，但**赋值链没读完，标"待核"，不标"确认"**。
- **两条不采纳，理由写在这份存档里，不留口头**：
  1. **"删 `m2/` 的 35 个 `probe_*.py` 与 355 KB `real-log.md`"不采纳**。README / CHANGELOG / 计划书里每个数字都写
     "见 `m2/real-log.md` 某节 / 见某探针"；删了就打断"文档里的数字必须对到产物"这条硬线。其中三个**作废仪器**
     （只看起点页的候选器、自填自点的 `echoed` 驱动器、用 urllib 探出口）是误诊记录本身，必须留。
     折中见 **#71**：可再生的 `out_*.txt` 交给 `.gitignore`；real-log 按季分卷 + 建索引（内容不改）；探针一律不动。
  2. **"把 `browser.py` 顶层的 `_pin_cdp_endpoint()` 收进显式初始化"要打折**。那行顶层调用现在是 P0 边界的一部分，
     "忘记也有效"就是它的功能；改成显式调用等于把"绝不驱动用户自己的 Chrome"从**机制**降级成**纪律**。
     真要做必须同时钉一条"仅 import 之后 `BU_CDP_URL` 已设"的测试（并入 **#68**）。
- **顺序与它分歧一处**：它把"拆 `skills.py` / 拆 `Agent.command()`"排在最前。那是**零行为变更重构**，
  本项目的法则下只有一种证明方式——同 build 配对批读数 `GAIN=LOST=∅`（`m2/batch_audit.py --pair`），
  100 行一次 ≈21 分钟、每步都要付。所以次序是：**先修仪器（#67 日志字段、#68 静默异常）→ 再收敛脚本（#69）→ 重构（#70）→ 归档清理（#71）**；#70 显式挂在 #16/#65/#67/#68 之后。

---

# openjev-ultrafast 全面体检报告

- 仓库：https://github.com/chipchipss/openjev-ultrafast（commit c26f250）
- 日期：2026-10-09（由 Bot 团队双线审查产出：核心代码质量 + 架构与脚本债务）
- 总评：整体架构没有硬伤——decider/、prompts/ 结构合理，README 与 pyproject 准确，依赖极简（browser-harness + httpx，Python ≥3.12）。问题集中在两类：**巨型文件**（skills.py 122KB / agent.py 50KB / browser.py 33KB）与**脚本重复**（9 个 PowerShell 脚本）。

---

## 一、重构优先级清单

### 第一梯队：风险最实，先修

**1. 收敛 9 个 PowerShell 脚本**
- 9 个脚本（run_demo / run_baseline_19 / run_agentjev_19 / run_adapter_m4b / run_overnight_laya / run_m1 / run_m4b_collect / run_laya_subset / run_s004_history_test）共享 6 大块几乎逐字重复的逻辑：Log/Ok/Warn/Die、Set-Env、Cdp/Chrome 生命周期（Start-Chrome 已分叉出 3 个变体：无 proxy / 带 proxy / 老版 Wait-Url）、杀 python 残留进程（kill 正则已分叉 5 种）、.env 加载、GPU gate、Test-Report、Invoke-Task、finally 清理。
- 4 个"19 题 runner"是同一段 100+ 行主循环的四份拷贝，仅服务启动方式与 env 名不同。
- 建议：新增 `scripts/runner_common.ps1` 收敛公共函数；4 个 runner 合并为 1 个参数化 runner（差异只剩服务启动命令 + DECIDER_MODE env + 端口探测 URL）。已有 scripts/chrome_guard.ps1、text_helper.ps1 先例，路子现成。预计删 60%+ 脚本行数。

**2. 拆分 skills.py（122KB / 2100+ 行）**
- 20+ 个技能函数全混在单文件（SKILLS 元组见 ~L2087），应拆成 skills/ 包：判达 / 表单 / 搜索 / 日历 / 滚动分模块。
- `goal_reached()`（~L355-530，175 行）是全项目最长单函数：三套判据 + 深层嵌套，是 DONE 误判/漏判的共同根源，单独成模块并函数化。
- `route()`（~L2133）裸 `except Exception: d = None` 吞掉所有技能异常且无日志——技能 bug 静默变成"回落模型"。
- Google Flights 专属硬编码应下沉为可插拔站点适配层：`stop_when_visible` 里的 `/travel/flights/search`（~L1790）、trip_type/date_pick 整个技能、_ABBREV 词表。
- 模块级 `_STUCK: dict`（~L2117）跨 run 共享无锁无清理，多 Agent 并发会 fingerprint 冲突。
- `_decision()` 与 `_wait()` 手工拼同一 decision dict 的两份副本（L72-119），字段漂移风险。

**3. 拆分 Agent.command()（agent.py / 50KB / 1100+ 行）**
- tick/predict/act 三个分支各 150-300 行内联状态机，未拆方法。
- state 是字符串键大杂烩 dict（browser/page/history/decisions/teacher_decisions/visited_fps/prev_node_ids/…），应改 dataclass。
- `_run_shadow()`（~150 行）与 `_done_guard()`（~120 行）内联；_done_guard 调用 skills._phrases / goal_reached / link_followed_arrival 私有函数，与 skills 形成双向依赖环。
- _done_guard 靠英文关键词表判任务语义，规则 1-6 无优先级结构；注释自己承认存在"已知误伤窗口（记档不修）"。
- 魔法数字密集（退避 6×0.4s、重试 12、helper_fail_run>=3、MAX_STEPS*2…），且 wait 排除规则在 4 个文件各写一份，靠注释对齐。

### 第二梯队：小改动、高回报

**4. 裸 except 治理（至少加 debug 日志）**
- skills.route、agent._done_guard 末尾、agent._run_shadow 至少 4 处、browser 各 settle/注入点（Page.enable、MODAL_GUARD、_settle_patch、_await_settle、await_scroll_settle、await_dom_settle）。
- 该仓库注释里大量"实况考古"案例正是静默吞异常的代价。

**5. browser.py 顶层副作用（改动极小）**
- 模块顶层执行 `_pin_cdp_endpoint()` 改写 os.environ（BU_CDP_URL）——import 即改全局环境，收进显式初始化函数。

**6. 斩断 agent↔skills 双向依赖**
- _done_guard 对 skills 私有函数的调用移到独立 goal-arrival 判定模块。

**7. browser.py 其他**
- `_listener_cmdline` 用 netstat + Get-CimInstance，无平台分支，非 Windows 直接 fail。
- 诊断用 `print("FRESH_MISMATCH")` 而非 logger。
- browser_operation() 是 150 行闭包工厂，内嵌 60+ 行拼接 JS，不可单测。
- settle caps / 轮询间隔 / deadline 等常量集中配置。

### 第三梯队：清理债务

**8. 归档 m4a/**（训练线 README 已宣告 CLOSED）
- 仅 run_flights_ours.py 仍被 run_demo.ps1 调用 → 移到 scripts/ 或 demo/；其余 ~20 个文件（train.py、train_m4b.py、prepare_sft.py、augment_sft.py、data*/、eval_result.json、install_*.ps1）随训练线归档删除。

**9. m2/ 大扫除**
- 保留：run_tasks.py、batch_audit.py、time_split.py、make_tasks_100.py、tasks_real_100.jsonl、test-site/、sample_extractor.py。
- 清理：~35 个 probe_*.py 及 out_*.txt、355KB real-log.md、tmp_*.html → docs/archive 或删除。

**10. logger.py（质量最好，小修）**
- ~300 行 _smoke() 测试代码移入 tests/，生产文件只留 Logger 本体（~200 行，结构干净）。
- 白名单键与 agent 写入键靠约定同步：step 白名单缺 outcome / url_from / page_fp_before，agent 加新字段会静默丢日志。
- observe() 四段同构 cursor 遍历抽 _drain() 消重；flush 无异常处理无锁；EVENT_TEACHER_SHADOW 注释漂移（说 5 类实为 6 类）。

**11. m1/ 小整**
- 整体保留（run_tasks.py、merge_reports.py、tasks-laya-19.jsonl 是基准口径必需）。
- m1-log.md（71KB）与 regression_defects.py 属历史记录，移 docs/。

### 顺带发现

- **疑似 bug**：run_demo.ps1 中 `$helperUrl` 引用自 `$helper.Url`，疑似笔误，可顺带修。
- decider/ 唯一小债务：agentjev_provider.py、laya_provider.py、field_text_2b.py 属已关闭模型线，可标 deprecated，不碍事。
- prompts/ 结构合理（force-include 随 wheel 打包），不必动。

---

## 二、分文件发现明细

### skills.py（约 122KB / 2100+ 行）— 最严重
1. 20+ 技能函数单文件堆叠（死页检测、goal 判达、表单、搜索、date_pick ~L1592-1712 约 120 行状态机、票种、滚动、确认收口…）。
2. 大量站点专属硬编码（见优先级 2）。
3. route() 裸 except 无日志 + 函数内每次 import validator。
4. 模块级 _STUCK 全局可变状态。
5. goal_reached 175 行三套判据，几乎不可测。
6. _decision/_wait 重复拼 decision dict。

### agent.py（约 50KB / 1100+ 行）
1. command() 巨型分发器。
2. state 大杂烩 dict 无类型。
3. 职责混杂 + 与 skills 双向依赖。
4. _done_guard 关键词表判定，已知误伤窗口。
5. 裸 except 遍布。
6. 魔法数字密集，跨文件口径靠注释对齐。

### browser.py（约 33KB / 700 行）
1. import 副作用（_pin_cdp_endpoint 改 os.environ）。
2. Windows 专属探测无平台分支。
3. print 代替 logger。
4. 全部 JS 注入/settle 裸 except。
5. 150 行闭包工厂不可单测。
6. 常量内联靠"实测"背书。

### logger.py（约 22KB / 480 行）— 质量最好
1. _smoke 测试代码内嵌生产模块（占 2/3）。
2. 事件类型注释漂移。
3. 四段同构 cursor 遍历。
4. 白名单键静默丢字段。
5. flush 无异常处理无锁。
6. 好的一面：游标增量抽取、白名单、close 幂等规范。

### 架构层
- PowerShell 脚本：重复 + 分叉（见优先级 1）。
- m1/ 必需保留；m2/ 半数是探针残留；m4a/ 训练线已关闭应归档。
- decider/ 结构合理（provider 契约 + registry + _http 公共垫片）；prompts/ 合理。

---

## 三、建议执行顺序

1. 小改动热身：裸 except 加日志（#4）+ browser import 副作用（#5）+ run_demo.ps1 疑似 bug —— 风险低，立竿见影。
2. 收敛 PowerShell 脚本（#1）—— 单独一支，不影响 Python 代码。
3. 拆 skills.py（#2）→ 斩断双向依赖（#6）→ 拆 Agent.command()（#3）—— 相互关联，按此顺序做，每步跑 tests/ 回归（20 个测试文件在，安全网齐全）。
4. 债务清理（#8 #9 #10 #11）随时可穿插。
