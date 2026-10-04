# Changelog

> 本文件记录项目的**阶段级**与**约束级**变更。
> 单文件代码变更由 git log 记录。
> 硬约束变更由 `docs/01-hard-rules.md` 的 A0.3 流程触发本文件追加条目。

---

## [decider-sweep] - 2026-10-04

### Status（实测，19 任务集 = m1/tasks.jsonl 去掉 s001）

**生产配置第一次拿到有效基线**（裸 decider-2b / typesafe wire，一任务一进程，
预检 9/9 域全通过）：**19/19 全部产出有效结果 —— 项目史上第一次。18 PASS / 1 FAIL，
`false_positive = 0`，全程 74 步，`api_calls = 0`。**

**方差**：同一份冻结代码连续三轮读数 **16 / 17 / 15**，`false_positive` 全为 0。
逐任务看：**14 个稳定 PASS**，`f001` / `n004` / `l002` 各 2/3，`x001` 曾是稳定 FAIL
（断言本身不可能满足，已重写为 guard 语义）。所以这个基准带 **±1** 抖动，
**单次读数不能当分数**。

`t002` 的「harness 缺口」真相：任务文件里我手写的那一行有个多余的 `]`
（char 260 处 JSON 非法），单任务临时文件解析失败、进程秒死 —— 四轮里它都因此
没产出报告。修掉后 19/19。这也解释了同日 `merge_reports.py` 在 char 260 的崩溃。

剩余 1 个失败：`n001`（Python 文档导航，今天 2/3，方差项）。

| 模型 | 结果 | false_positive | 失败特征 |
|---|---|---|---|
| **decider-2b（裸，本轮）** | **17/18** | 0 | — |
| decider-2b + adapter_m4b | 8/15（基线同批 12/15） | 0 | 无增益，0 胜 4 负 |
| Laya v17s (322M) | 6/18 | 0 | `model_calls ≫ steps`，反复输出终止操作 |
| agent-jev 0.6B | 3/18 | 0 | 12/18 是 system crash，`model_calls=0` |

**云端依赖：0。** 18 个任务 `api_calls = 0`，103 次本地模型调用。技能层直接从
目标里取值（"from Zurich"、"on October 25"），text helper 根本没被触发。
`.env` 里的 Groq 免费档只是目标未给出字面值时的兜底，不是依赖。

### Added
- **技能 `goto_path`**：goal 里明写路径（"Go to /forms/post"）+ 页面上**唯一**同
  路径 href → 点它。与 `explicit_target` 的分工：那条路径的 label 分支被刻意归零
  （`/post` 反向包含 `/forms/post`，f001 曾因此点错），这里改用 **href 路径精确
  相等**，反向包含无从发生，所以不需要归零。
  - 找不到同名链接时**有界下滚**（`_PATH_SCROLL_MAX=4`）—— 目标常在折叠线以下。
    `snapshot.js:157` 只在下方确有内容时才合成 `scroll_down`，所以拿得到控件就等于
    "还有东西没看见"，守卫免费
  - 唯一命中才点；有歧义（>1 个同路径）宁可回落模型
  - 实测依据：`scripts/probe_snapshot_coverage.py` 显示 httpbin.org 的
    `/forms/post`（标签 "HTML form"）在 **y=1174**，被视口剔除；且该页是
    Swagger UI，快照只等 0.25s 时只渲染出 5 个 action
- `run_baseline_19.ps1`：生产配置（裸 decider-2b / typesafe wire）的干净基线 runner。
  **本项目此前从未有过一次跑满的 19 任务基线** —— 所有历史 baseline 都无隔离
  且带 1–4 个 harness 缺口
- `m1/merge_reports.py`：合并「一任务一进程」产生的碎片报告，与基线逐任务差分，
  打印 fp 硬线与判决
- `run_overnight_laya.ps1` / `run_agentjev_19.ps1` / `run_adapter_m4b.ps1`：
  统一 runner —— 一任务一进程 + 试点闸门 + 墙钟上限 + ERROR 重试 + 收尾验证
  （`chrome=0` 且服务进程=0，否则退出码非 0）
- `m1/tasks-laya-19.jsonl`：对照用任务集（20 减去 s001，Google 反爬在两边都是噪声）

### Fixed
- **`page_not_ready` 把「内容页」当成「还没渲染」**（本轮最大的一处）：
  判据只有一条 ——「快照里没有可交互元素就等一拍」，**从不看页面有没有正文**。
  于是一张有正文、零控件的页面（表单提交后的 JSON 回显、搜索结果页、文章页、
  报错页）会被无限等待。f002 实况：提交成功落到 `/post`，随后**连等 57 拍**撞上
  60 步上限才结束，尽管断言早已满足、`goal_reached` 根本没机会跑。
  修法：有正文就放行；只有「无正文 + 无控件」才算未就绪。
- **`goal_reached` 认不出「填入值已出现在页面上」**：`_phrases` 刻意跳过
  `with 'X'` 形式的引号串（当值不当目标），于是
  "…fill the comments field with 'hello world', then submit the form."
  的证据短语只剩 `/forms/post` —— 提交后落在 `/post`，页面永远不含它。
  新增 `_fill_values()`：处于值位置（`with/into/to` 前后皆可）的引号串，
  全部出现在正文里即判达成。未提交时 textarea/input 的值不进 `innerText`，
  所以不会提前收口。
- **Policy 把合法的表单提交当不可逆操作**：`"submit order"` 写在
  `IRREVERSIBLE_BLACKLIST` 里，与 `place order` / `confirm order` 并列。
  不可逆的是**交易**（扣款/下单），不是"提交表单"本身。f002 实况：agent 正确填完
  表、正确找到提交按钮，却被 Policy 拦下 → 整任务判 `correct_abandon`。
  移出 `submit order`；交易面仍由 `place order` / `confirm order` / `checkout` /
  `buy now` / `pay now` / `purchase now` 覆盖（已加测试逐条守住）。
  **附带结论：`fp=0` 这条硬线此前有一部分是被这个过宽的黑名单撑起来的。**
- **`form_submit` 的闸门只要求「至少动过一次」**：f004 的 goal 是
  "select a size from the dropdown, then submit the form"，但只走了一步
  `goto_path` 就被放行提交 —— 目标要求的「选一个 size」从未发生。
  **已知缺口，本轮不修**：通用判据要匹配「目标说要选的东西」与「实际点了什么」，
  而 httpbin 的 radio 控件 label 是 `Small`/`Medium`/`Large`，组名 `size` 只存在于
  `name` 属性里、history 不保存 `name`。硬凑启发式的误伤风险高于它值 18 个任务里的 1 个。
- **`f001` 的断言写错了**（任务定义缺陷）：断言是 `text_contains "customer"`，
  但 httpbin `/post` 回显的字段名是 **`custname`** —— 正确提交后**永远匹配不上**，
  只有「没提交、停在表单页」（标签含 "Customer name:"）才侥幸通过。
  改为断言目标要求的值 `Test User`。`m1/tasks.jsonl` 与 `m1/tasks-laya-19.jsonl` 同步。
- **pilot 闸门位置错误**（四个 runner 都有）：判据是
  `$idx -eq $PilotCount and pilotConfirmed -eq 0`，在 `-PilotCount 1` 时
  **任务还没跑就触发**，必然中止。改为 `$idx -eq ($PilotCount + 1)`。
- **`merge_reports.py` 的判决行硬编码 `"Laya usable as primary"`** —— 跑生产基线时
  也印这句。改为按本次结果生成，并区分
  `NO DATA` / `INCOMPLETE` / `REJECTED(fp>0)` / `clean sweep` / `N/M usable`；
  0 个任务不再判成 "clean sweep"。
- **Chrome 不走出口代理**：runner 起 Chrome 时从不传 `--proxy-server`，于是任何
  「需要代理才能访问」的站点在浏览器里直接加载失败，任务退化成
  `chrome-error://chromewebdata/` + `steps=0` + `correct_abandon` —— **在报告里
  和「模型能力不足」长得一模一样**。实测 2026-10-04：`en.wikipedia.org` 与
  `news.ycombinator.com` 直连不可达、只走代理，而 Chrome 不走代理 →
  s004/l002/x002/l001 四个任务全部作废（占 19 任务的 21%）。
  修法：`Start-Chrome` 按 `$ProxyUrl` 追加 `--proxy-server=...`。
- **跑基准前不检查页面可达性**：现在有 preflight，逐个任务域分别探测
  **直连**与**代理**两条路径，输出三分类：
  `reachable direct` / `need proxy` / `UNREACHABLE`。
  - 有 `UNREACHABLE` → **中止**（退出码 5），因为那类任务量的是网络不是 agent
  - 有 `need proxy` 而代理不通 → 同样中止
  - `example.invalid`（负向任务的故意非域名）不探测
  这条的意义：今天 10/18 与 9/18 两次读数都是**坏的测量**（4 个任务页面未加载），
  却看起来像模型退步。有了 preflight，同类问题在 20 秒内暴露而不是跑完 8 分钟后
  才发现。
- **测试套件在 GBK 控制台上崩溃**：`tests/test_skills.py` 与 `tests/test_rotation.py`
  的 `main()` 直接 `print(f"ok {name}")`，而用例名含非 GBK 字符（源码里的地名）
  → `UnicodeEncodeError` **中断整个套件**，让人误以为测试挂了、看不到任何 FAIL。
  修法：`stream.reconfigure(encoding="utf-8", errors="replace")`。既有问题，
  只是以前在别的控制台设置下没暴露

### Fixed
- **重页面 CDP 超时被误判成 daemon 死亡**（可复现，四轮独立测试均命中）：
  `browser.py` 的 `Browser.call()` 已有 4 次退避重试 + `_ensure_daemon()`，
  但**从不提高超时**——每次调用都吃 `cdp()` 的默认 `_response_timeout=5.0s`
  （`browser_harness.helpers` 的模块常量，且是定义时求值的默认参数，改属性无效）。
  wikipedia.org 这类重页面首次 `Page.navigate` 稳定超过 5 秒，于是被判成
  daemon 已死，重试 + 重启 daemon 反而让它更糟。
  表现：`s004` / `l002` / `x002`（三个 wikipedia 任务）+ `t002` 在 Laya /
  agent-jev / adapter 三轮里反复 `agent_init_failed: _IPCResponseTimeout:
  Page.navigate timed out after 5s`，且重试也救不回来。
  修法：`call()` 默认 `_response_timeout=30.0` 并透传给 `cdp()`。超时是上限
  而非 sleep，快请求零影响。
  验证任务集 `m1/tasks-harness-repro.jsonl`（就是这 4 个）。
- **本地模型请求被丢给出口代理（A0 影响 README 公开配置路径）**：
  `decider/_http.py` 的全局 client 无条件套用 `HTTPX_PROXY`，于是
  `DECIDER_MODE=openai` 指向 `http://127.0.0.1:8000/v1` 这类**本地**模型端点时
  也会走 SOCKS 代理。代理不可用（或代理无法路由到 loopback）时每个决策
  退避重试 6 次（`1+2+4+8+16` ≈ **224s/任务**），现象是「模型极慢 +
  全部 `correct_abandon` + `steps=0`」，极易误判为模型能力问题。
  修法：`mounts={"all://127.0.0.1": None, "all://localhost": None}` 让回环
  绕过代理，外网 endpoint（Groq 等）行为不变。
  注：`DECIDER_MODE=typesafe` 走 `model.py` 的另一个 client，本来就不设代理，
  故 baseline 一直正常——这也是该bug 长期未被发现的原因。
  agent-jev provider 用 `urllib.request`，天然不受影响。
- **harness daemon 崩溃连坐**：批量跑时 daemon 一死，整轮后续任务全部
  `Page.navigate timed out`。改成**一任务一进程**后每个任务都拿到全新 daemon，
  agent-jev 那轮 18/19 零 ERROR（Laya 那轮批量跑丢 2 个）
- **服务死亡被当成模型失败**：服务中途被杀后，每个任务对着死端口重试 6 次
  × 44s（≈224s），全部记为 `correct_abandon` + `steps=0`，看起来像「模型很差」，
  实际是**在测页面加载失败率**。两处修复：① 服务存活判定改查进程对象
  （`$proc.HasExited`）而非 HTTP 探测；② `Test-Report` 拒绝含
  `connection failed` 的报告，防止重跑时把假结果当有效跳过

### Changed (A0.3 · 计划书口径修订)
- **`docs/00-project-plan.md` §2.4**：原文「不做模型训练（已决策）」与仓库现状
  矛盾（M4a 已训、M4b 655 行 adapter 已产出）。修订为：**训练降级为已关闭的
  探索支线**，理由是四次对照均无增益（M4a 6/20、M4b 8/15 vs 基线 12/15、
  Laya 6/18、agent-jev 3/18；另有 cklxx 独立测得
  confidence 闸门有害 58%→42%）。M2 数据飞轮与 `api_teacher.py` 随之标记为
  **暂停**——它们的唯一产出是训练数据。若日后重启训练，先按 cklxx 的结论改
  采集管线（DONE 样本必须用执行动作后的真实落地页），而不是改模型。

### Rationale
19 任务集存在**框架天花板**：DeepSeek Flash 12/20、glm-5.3-flash 12/20，
两个前沿商业 API 都打不过本地 2B（13–15）。M1 全是 DOM 索引动作选择，
前沿模型在此过度思考。换模型的边际收益已被三次连续失败证伪。
`decider-4b` 按 §3.1 自定门槛（需 ≥17/20）建议不测。

### 硬线复盘
四轮 `false_positive` 全为 0，包含 6/18 与 3/18 的弱模型 —— **DoneGuard 与
决策模型无关**，是治理四件套唯一被跨模型独立验证过的能力。

---

## [M2.5-skills] - 2026-10-01

### Status（实测）
- **泛化任务（自建站点 30 任务 × 3 轮 = 90）：pass=90（100%），quadrants 全部 true_success**
- M1 全量 20 任务：15/20（基线 12/20 → 峰值 16/20），s002/n004/l002/l003 本轮修复后保持
- flights 7/7（mc=0，纯技能）/ wikipedia 1/1（mc=0）
- 回归测试：`tests/test_skills.py` 33/33、`tests/test_rotation.py` 8/8、decider smoke 21/21

### Added
- `snapshot.js`：结果卡片 `site`（<cite> 域名）、表单 `name` 属性、`scroll_bottom` /
  `scroll_top` 合成动作（delta=剩余高度）、稳定性 marker（`marker_stable`）
- `skills.py`：`confirm_then_done`（提交后确认即收口，防模型在确认页点走）、
  `scroll_to_target`（"滚到 X 可见"目标未入视口时一次滚到底）、`first_result`
  （"打开第一个结果"，点击跳转后自证 DONE）、技能卡住的有界退避（让位模型 2 拍）
- `anyjev_rotation.py`：L0 循环移位消位置偏差 + Clopper-Pearson 认证的提前停
  （移植自 Apache-2.0 的 nokia-applied-research/AnyJev；`DECIDER_ROTATION` 开启，默认关）
- `choose_2b.py`：读取过程参数化（`_read_once` / `_to_decision`），支持按候选顺序旋转

### Fixed（每条都有实测根因，详见代码注释）
- **预测层活锁**：`fresh()` 的 marker 含 text/滚动位置 → 动态内容每帧都变 →
  每次点击都被判 stale → "预测→拒绝→重预测"死循环（n001/f002 实况：同一决策连发 5 次未执行）。
  改用不含 text/scroll 的 `marker_stable`
- 多字段表单只填第一个（`_FILL_RE` 只认一对 field/value）→ 双向扫描 + 单复数匹配 +
  "fill all fields with any values" 兜底；email 字段必须给合法邮箱（HTML5 校验）
- 提交闸门三处（goal 闸门 / SUBMIT_WORDS / "必须先 fill"）漏掉 Save/切换控件流（t003/t005）
- `goal_reached` 的 query 语义按目标类型分流（website/host、submit/query、second-hop），
  三类实测误判（s001/s007/s011）全部判别正确
- Google 首页无 Search 按钮 → 无按钮时用自动补全建议提交；有按钮时按钮优先于同名导航链接
- evaluator：negative 任务断言为 `text_not_contains` 时推断为 guard 语义
  （agent 正确拒绝被标 false_positive 的象限误标）
- DoneGuard：破坏性目标（delete/pay/publish…）必须 BLOCKED 而非 DONE；提交类接受
  "提交点击产生跳转"作为确认（httpbin 的 JSON 结果页没有 thank/success 字样）

### Ops
- m2 runner 无条件初始化 APITeacher：不导出 `TEACHER_*` 时 escalation 失败 →
  steps=0 全军覆没。跑 m2 必须先加载 `.env`

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

### Changed (A0.3 · 口径修订)
- **`docs/03-milestones.md` §5.6**：M2 验收拆双口径——`decision_total ≥ 1000`
  （所有域，M1 存量可计入）/ `c_pairs ≥ 200`（仅非 benchmark 域，M1 存量不计入）
- Rationale：C1 = benchmark 域输出不进训练集；M1 的 20 域即 benchmark，
  其 ≈100 decisions 只计入总量、不计入 C 类 pair

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
