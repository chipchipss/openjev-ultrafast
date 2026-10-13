# OpenJEV Ultrafast

一个**全本地、模型无关、可观测**的 Browser Agent 框架:jev-ultrafast 的 Runtime + 可插拔的 Decision 层 + 工程化治理。

日常它替我操作浏览器做真实任务;项目本身的价值在治理层——**四象限归因、`false_positive=0` 硬线、零云端的证明方法、以及"一条读数不许事后解释"的验证链**。这些考卷生态里的其他项目都没考。

## 现在的实测状态(2026-10-11,每个数字都对得到一个 `reports/*.json`)

| 口径 | 读数 | artifact |
|---|---|---|
| **19 题基准(冻结三轮)** | **19 / 19 / 19**,`fp=0`,单轮 5–6 分钟 | `m1-baseline-1011-2251/2258/2304.json` |
| **真实站 50 题(L2 判据 ≥45)** | **45/50**(`error/crash/unknown=0`、`fp=0`、零云端、与 b20 配对 `LOST=∅`) | `real-1011-b24-ipc58-1011-015958.json` |
| **真实站 100 题回归(L3 吞吐)** | 墙钟 **20.7 分钟**、1.96 拍每行、`error=0`、`fp=0`、零云端;分数 **59/100**(基线,低分已按归责拆成四堆) | `real-1011-b33-100-1011-231042.json` |
| **50 题批的门控墙钟** | 27.8 → **8.2 / 8.7 / 9.5 分钟**(任务间复位改成"先问健康再付钱") | `real-1011-b27/b28/b29-gate*.json` |
| **3×100 行夜间档(L3 第二档,第一次真跑)** | 三轮 **66 / 69 / 65**,三轮全 `fp=0`、`error=0`,总墙钟 **61.4 分钟**(预算 95);同 build 的行级抖动是 **100 行里只有 5 行反复翻,95 行三轮不动** | `ci-1012-1908.json` + 三份 `nightly-1012-1908-r*.json` |
| **决策延迟** | 单决策中位 **0.64 s**(本机 2B GGUF,走产品原路) | `m2/probe_wire_parallel.py` 的并发 1 档 |
| **离线测试** | 32 个套件 **277 案全绿**（`scripts/smoke.ps1` tier1 一次跑完，2026-10-13 18:18 实跑；上一版读数停在 10-12 22:48 的 27 件 / 244 案；tier1 的证据是 runner 逐件打出的 `n/n passed`，`reports/smoke-*.json` 只有 -Live 第二级才写） | `tests/` |

**并行不做,是被读数判死的**:并发 1→4 的吞吐 1.55 → 1.58 决策/秒(**加速比 1.02x**),`llama-server --parallel 4` 的槽位没变成吞吐,多开 worker 只会在 wire 前排队。所以 100 题 ≤30 分钟靠串行就已达成(实测 20.7 分钟)。

**300 行不塞进 30 分钟,因为拆过账**:b33 每行 12.4 秒墙钟里,决策只占 **0.48 秒**(动作执行 5.81 秒、起点会话建立 2–5 秒、任务间健康探测 2.35 秒/断点 ≈ 3.9 分钟/批)。后端无限快也只把 300 行从 62 分钟降到 60 分钟——**"300 题要更快的决策后端"这句我撤回过**,它当时没量拆分。口径因此拆成两档:**每改必跑 = 100 行 ≤30 分钟;300 行 = 夜间档**——这一档已从预算变成读数:3×100 行实跑 **61.4 分钟**(`reports/ci-1012-1908.json`)。夜间档看的是漂移与下限,不看单轮分数:同一 build 三轮里 **只有 5 行翻动**(`r127`/`r129` 是环境,`r119`/`r187`/`r193` 是决策族),95 行三轮一模一样——所以任何改动只换来 1–3 行 GAIN 时,必须按这张表归因,不许记成收益。

## 快速开始

### 一条命令看它跑真实任务

```powershell
.\run_demo.ps1                       # Google Flights 端到端 12.4–14.0s(1007 四次实测,demo-flights-1007-16*.json)
.\run_demo.ps1 -Task wikipedia       # 另一个 demo(2.1s)
.\run_demo.ps1 -KeepOpen             # 跑完不关浏览器,自己看
.\run_demo.ps1 -KeepService          # 跑完不关 llama-server + wire(下次省 ~30s 加载)
```

`run_demo.ps1` 是 L6 入口:决策栈不在线就自己拉起,权重/二进制缺失自动经代理下载,**只清理自己起的进程**。

### 日常任意任务

```powershell
.\scripts\startlux_serve.ps1                      # llama-server :8081 + /v1/systemone wire :8090

C:\Users\Administrator\miniconda3\envs\jev\python.exe scripts\run_task.py `
  --start-chrome `
  --url https://en.wikipedia.org/ `
  --goal "Open the article about the Apollo program" `
  --expect-text Apollo --expect-title Apollo
```

`--expect-url / --expect-title / --expect-text` 三类断言各自独立、彼此 `all_of`,**永远不进模型 prompt**,只做执行后核验(核验走的是评测器 `jev_ultrafast/evaluator.py`,与批判定 PASS 同一份代码)。`--goal` 的写法直接决定成败:**显式引用页面上的字面标题** > 模糊的排名描述("open the top story" 会失败,因为页面上没有叫 top story 的链接)。

### 挂进 Claude Code(MCP)

```powershell
claude mcp add openjev -- python C:\Users\Administrator\openjev-ultrafast\mcp_server.py
```

暴露 `agent_status` / `agent_run(url, goal, expect_url, expect_title, expect_text, steps)` / `demo_flights`;需要本地栈时它自己拉,不在线不会静默降级。

### 跑基准与回归

```powershell
.\scripts\smoke.ps1                  # 第一级闸门:32 个离线套件必须 n/n 全绿(现在 277 案)
.\scripts\smoke.ps1 -Live            # 第二级:5 题代表族(s005/n004/x001/x002/r142),判据读报告不读控制台
.\scripts\ci_local.ps1 -Tasks 50                                    # 每改必跑档:smoke → 冻结三轮 → 回归批 → 阈值判定(默认是 50 行口径:MinPass 43 / 墙钟 14 分钟)
.\scripts\ci_local.ps1 -Tasks 100 -MinPass 59 -MaxWallMinutes 30    # 同档跑 100 行:阈值自己给,且**跑之前先预登记**
.\scripts\ci_local.ps1 -Tier nightly -Rounds 3                      # 夜间档:同一份 100 行题集跑 N 轮。每轮下限 59 = 五次读数(59/61/68/65/64)的最小值,整夜预算 95 min = 3×观测最坏 20.7 + 复位余量。"300 行"在这台机器上就是 3×100——没有 300 行题集,也不造 200 道没核过的题当读数
python m2\batch_audit.py reports\<新批>.json --pair reports\<对照批>.json --log logs\<新批目录>
```

"没写报告"的轮次一律算 **BLOCKED(退出 3)**,不算通过也不算失败——环境阻断写成读数就会被后续引用。

## 三条硬线(违反任何一条,那一批的读数作废)

1. **`false_positive = 0`**。判定用四象限(`true_success / correct_abandon / false_negative / false_positive`),负向任务(故意做不到)有独立语义:正确放弃就是 `correct_abandon`。
2. **"零云端"只由步事件证明**:逐条检查 step 事件的 `text_helper` ⊆ `{null, startlux-decision-2b}`。`api_calls=0` **不是**证据——那个计数器只统计 teacher 升级路径,10-08 之前的入口脚本正是靠它把 `TYPE_TEXT` 的填值发给云端 Groq,逐 artifact 审计实测到 **56 次**云端供值(见下方"云端口径")。
3. **绝不动不是我们自己的浏览器**。自有画像只有两个:`chrome-cdp-test`、`chrome-jev-profile`(`jev_ultrafast/browser.py::OWNED_PROFILE_MARKERS`)。连接侧:`_pin_cdp_endpoint` 把 harness 钉在 :9222,`_assert_owned_browser` 在校验不过时抛 `foreign-browser:`/`no-browser:`;杀侧:`scripts/chrome_guard.ps1` 与 `_reset_cdp` 的 kill filter 只按这两个画像匹配,**仓里不存在任何裸 `Get-Process chrome | Stop-Process`**。曾有读数是在连着用户自己的浏览器跑出来的——那些已判作废,不引用。

## 架构

```
User Goal
    ↓
Browser State (DOM + A11y)      ← 原子快照、新鲜度守卫;新文档归静;JS 对话框守卫(#60)
    ↓
Dynamic Action Space            ← 索引化动作摘要(不是 6000 字符全文)
    ↓
Skills (21 项确定性地板)          ← goal 字面可判的决策不进模型
    ↓ (未命中回落)
Decision Provider               ← StartLux-Decision-2B(默认)/ OpenAI 兼容 / 自定义
    ↓
DecisionValidator → Runtime Guard → Policy → Confidence Gate → Budget
    ↓
Browser Execute
    ↓
Logger → Evaluator(四象限)→ Dataset / Benchmark
```

**技能层现状(21 项,按优先级)**:`blocked_dead_page, page_not_ready, goal_reached, link_followed_arrival, stop_when_visible, confirm_then_done, scroll_to_target, first_result, goto_path, explicit_target, scroll_to_named_target, select_option, form_fill, form_submit, entity_fill, entity_confirm, trip_type, search_type, select_first, date_pick, search_submit`。

其中三条是这轮真实站调出来的关键判据:`goal_reached`(到达,C2b 会把 goal 头词的常见 URL 缩写展开且**只允许命中 host**)、`link_followed_arrival`(**到站即停**:goal 的"目的地短语"是刚点掉的链接标签、那一拍真的换了页、且仍停在落地页 ⇒ DONE,同时 DoneGuard 把它当作到达的第二判据)、`first_result`(结果页要先按 goal 词重叠筛"是结果的",页眉 chrome 不算结果)。

**一条浏览器教训**:`_reset_cdp` 重起的 Chrome 必须和 runner 起的是**同一个形状**(headless + `chrome-cdp-test` + `--proxy-server`)。2026-10-11 之前它起的是 headed 的另一画像且**不带代理**,于是"门控真付过一次复位"的批里,第 1 题走代理、后面的题直连——出口 IP 和浏览器一起换。所以**读 b18–b26 的批读数时要带着这条注意事项**;b27(0 次真复位)起才是单形状。跨批评一个 PASS→FAIL 之前,先确认两批跑在同一浏览器、同一条出口上。

## 治理与验证链(项目自己的法则)

1. **失败测试先行**:新测试必须能在改前代码上失败,并记下改前的读数(今晚三条仪器修复都是 6/7→7/7、4/6→6/6 这种形状)。
2. **单任务 → x001/x002 安全复测 → 冻结 19/19×3(同一 build)→ 才许跑真实批**。单次读数不作数,±1 是方差。
3. **判据在跑之前预登记**(`m2/real-log.md`),事后不改写;分数低先怀疑自己的题/仪器,不当 agent 的分数记账。
4. **一次运行独占浏览器和 :8090**;批在跑时闸门与探针拒绝启动。
5. **反常指标第一动作是翻 jsonl 日志,不是建假设**;仪器若被误读,结论比"未知"更糟,所以结论旁边要贴命令。
6. 命名规矩:**名词只收见过的,不许按想象扩充**。

## 接入一个新模型

决策层是插槽(`DECIDER_MODE`),换底座不改框架(M8 验收:换 Decider 只动 `.env` + runner 端口参数,Runtime/Validator/Policy/Logger/Benchmark **零修改**)。

```dotenv
# 方式 1(默认):TypeSafe wire,本机 StartLux gguf_server
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8090/v1/systemone
TYPESAFE_API_KEY=local

# Text Helper:必须是本机 llama-server(wire 后面那个同一个 GGUF);不可达就退出,不静默降级
TEXT_HELPER_BASE_URL=http://127.0.0.1:8081/v1
TEXT_HELPER_MODEL=startlux-decision-2b
```

方式 2 是 OpenAI 兼容端点(`DECIDER_MODE=openai`,须显式命名、从不默认;通用 LLM 在索引化选择题上契合度差,glm-5.3-flash 直插 12/20 vs 同期本地 2B 13–15/20)。方式 3 是在 `jev_ultrafast/decider/provider.py` 里 `register_provider("my_model", fn)`,契约 `(observation, goal, history) -> decision`。

权重与二进制不用手动拿:`startlux_serve.ps1` 缺啥下啥(GGUF 落 `D:\openjev-models\startlux-decision-2b`,CUDA 版 llama.cpp 落 `D:\openjev-models\llamacpp`);启动带 `-lm none`——默认 mmap 会把 2GB 文件计进 RAM 工作集,16GB 机器上会误触内存闸(那条闸门是 free<3000 MB 拦一轮)。本地端点写 `127.0.0.1` 别写 `localhost`(Windows 先试 IPv6,加约 2 秒)。

> 原生端点提示:llama.cpp 的 `/v1/systemone` 要求 GGUF 带 `{arch}.decision.type` 元数据(嵌入式决策头架构)。StartLux-2B 是因果模型 + letter-readout,GGUF 里没有这份元数据,所以 `gguf_server.py` 这层 wire 转换**不可删**;原生端点留给未来"转换过"的决策模型。

## 项目结构

```
openjev-ultrafast/
├── jev_ultrafast/          # 主包:agent.py / browser.py / snapshot.js / skills.py / model.py
│   └── decider/            # provider 契约 + registry、OpenAI 兼容 provider、HTTP 垫片
├── policy.py / decision_validator.py / runtime_guard.py / confidence_gate.py
├── step_budget.py / api_budget.py / evaluator.py / logger.py / sample_extractor.py
├── m1/                     # 基准 runner + 题集(tasks-laya-19.jsonl 等)
├── m2/                     # 真实站题集与测量工具:run_tasks 之外还有
│   │                         batch_audit.py(配对/射程审计)、time_split.py(墙钟分解)、
│   │                         probe_*.py(零模型探针)、make_tasks_100.py(题集生成 + 唯一性断言)
├── mcp_server.py           # Claude Code / 任意 MCP 客户端入口
├── scripts/                # startlux_serve.ps1 / run_one.ps1 / run_task.py / smoke.ps1 / ci_local.ps1 / chrome_guard.ps1
├── tests/                  # 32 个离线套件(不需要浏览器或模型,277 案)
├── reports/                # 实测报告入库;逐任务运行产物目录不入库
├── docs/                   # 01-hard-rules.md(硬约束全文)、03-milestones.md、00-project-plan.md(L1–L6)
├── run_baseline_19.ps1     # 19 题冻结 runner(一任务一进程 + 逐域预检 + 收尾验证)
└── run_demo.ps1            # L6 一条命令入口
```

## 历史读数与已关闭的线(保留证据,不作当前成绩)

- **与上游 jev-ultrafast 正面对决**(2026-09-27,旧 decider-2B 底座,`reports/upstream-vs-ours.json`):任务级 wall time **3/4 更快、1/4 更慢**;本框架快在决策输入小(延迟 p50 830–1508ms vs 上游 427–7025ms)与死循环收口(n003 上游 60 步崩死 vs 本框架 3 步正确放弃)。诚实边界:n001 本框架多走一层所以更慢;f004 上游完整提交表单而本框架停在表单页。
- **M1 四路对照**(2026-10-04):decider-2b 裸 13/17、+adapter_m4b 8/15(基线同批 12/15)、Laya 322M 6/18、agent-jev 0.6B 3/18 ⇒ **模型线关闭**;换底座(M8 起用 StartLux)不等于重开模型线。
- **训练线关闭**:M4a 951 行 → 6/20、M4b 655 行 → 8/15,两次自训无增益。关闭时写下的方向性修正(确定性求解器 + 环境验证轨迹 + 任务族扩充)在生态项目 jeva 那里有完整实现,若重启先抄它。
- **M2 数据飞轮**:500 任务轮 309 true_success / 79 correct_abandon / 243 preference pair,验收通过;其唯一产出是训练数据,随训练线关闭而暂停。其中 8 条被旧评估器标为 false_positive 的记录属误标(发生在 DoneGuard 与象限修正之前),不构成硬线反证。
- **云端口径更正(2026-10-08)**:10-08 Fix N 之前三个入口脚本把 Text Helper 指向云端 Groq,历史 baseline 里实测 56 次云端供值;Fix N 起 helper 默认本机 :8081,此后每轮 `text_helper` 只出现 `null`(技能供值)或本地模型名。基线实测里 helper 几乎不触发——大部分任务的填值由技能层从 goal 字面直接取。

## 现状

| 阶段 | 状态 |
|---|---|
| M-1 / M0 / M1 / M1.5 / M2 | ✅(M2 随训练线暂停) |
| M3 Reranker | ⏸ SKIP(probe 无 cap-failure 相关性) |
| M4a 诊断 ✅ / M4b 扩数据 ⏸ CLOSED | 两次自训无增益,训练线关闭 |
| M5 Confidence Gate | ⏸ 架构就位,概率信号已逐决策落日志;等"低置信 DONE 误判/高置信 BLOCKED 误放弃"的真实模式出现再动 |
| M6 Benchmark | ✅ 基准 + 真实站回归都有配对审计工具 |
| M7 Ultrafast | ⏸ 自用已达标,不做产品 |
| M8 换底座 | ✅ StartLux-Decision-2B 为默认 |
| **L1 文档/可复现** | ✅ 本文 + `docs/00-project-plan.md`,数字均可对账 |
| **L2 真实站鲁棒性** | ✅ **45/50 达标**(b24);残余失败行各有名姓,不再挡里程碑 |
| **L3 回归体系** | ✅ **100 题 20.7 分钟**、两级闸门 + `ci_local.ps1`、断言拆分；并行被 1.02x 读数判死；300 行改判**夜间档**（≈62 分钟，决策只占每行 0.48 秒，换后端救不了它） |
| **L4 稳定性** | ✅ 冻结 19/19×3、`fp=0` 全程 |
| **L5 全本地** | ✅ 栈里没有任何云端调用点(helper 本机化 + 云端默认显式化) |
| **L6 一条命令** | ✅ `run_demo.ps1` 冷启全绿、自动供给 |

**未结清单**(都有证据在 `m2/real-log.md`,2026-10-13 傍晚刷新):~~`chrome-error://` 起点被记成 `failure_mode=decision`~~ —— **#16 已落地**(`80f6a43`):新增 `failure_mode=blocked_by_egress`,象限一字不动,负向任务显式豁免(x001 的起点域按设计就不通,它不能被重贴环境标签)。~~**#65 的那半件**~~ —— **也已落地**(`m2/real-log.md` 的 10-13 两节):「CDP Network 层数在途请求」被两次独立读数判死,留下的是**到站那一拍付一次有界重看**(等 goal 点名的短语出现在 live DOM,不等正文变长;cap 6 000 ms 的出处是两支零模型探针里 docs 族的短语出现时刻 4.6–8.9 s)。三批实跑:b38 72/100、b39 70/100、b40 65/100(其中 5 行是 the-internet 那台 Heroku 应用当场挂了,trace 时刻 16:23–16:24、16:31 单跑 5/5 PASS、同时刻 curl 已回到 HTTP 200 ⇒ **按环境修正后 70/100,error 从 1 降到 0**);预登记的四个射程 `r154/r156/r157/r158` 在三批里全部 FAIL→PASS,且**步数与模型调用一行没变**。触发面按 b39 的付费名单收窄过一次(8 行 / 31 453 ms → 5 行 / 14 343 ms,b40 实测),只保留 `goal_reached` 的收口。~~#78~~ —— **也已落地（10-13 晚）**：起点页是站点自己的 HTTP 错误页（title 逐字等于 `Application Error` 且正文为空）时改记 `failure_mode=blocked_by_upstream_error / failure_class=system`，result 与象限一字不动、负向题豁免、fp 永不豁免。射程是**扫已提交历史扫出来的两批各 5 行**（b34 的 61/100 里那 5 行当时被记在 agent 头上 —— 历史读数不改写，事实记在 `m2/real-log.md`）；证据两半：`m2/replay_app_error.py` 对这 10 行逐行打印"改前 vs 改后"（四字段一字不动，只换归因），b41（`reports/ci-1013-1732-1013-175147.json`：69/100、fp=0、unknown=0、PASS 行之间象限漂移 0）里这一档**命中 0 行** = 站点健康时它不乱贴。另有地板空点击占拍、`explicit_target` 近似行劫持两条老账，以及一次实跑撞出来的 #81（同一个 task_id 在两套题集里都有定义，`run_one.ps1 -TaskId` 已经会拒绝猜，但重复定义还在）。StartLux-Decision-4B 是**分数实验**(看那 18 行真决策缺口能不能被更大的模型过掉),不是吞吐路径,且等归因干净了再跑一晚才有意义;**对上游的正面对照(#76)的状态从"等你批准开销"改成"等凭据"** —— 本机 `.env` 里 `TYPESAFE_API_KEY` 的值长 5(就是 `local` 占位),付费上游现在**调不到**,"近似前者水平"这句话在拿到 key 之前不能对外写;而目标里"接免费 API 小模型"那一半，代码已经具备（`DECIDER_MODE=openai` 就是 chat→decision 适配器），缺的是真实读数（#80）。

## 平替水平的证据口径(对外声明时请注意)

本仓库的定位是 **jev-ultrafast 的开源平替**(全本地、模型无关、可观测)。这个定位**当前 build 还没有对照证据**:唯一一份正面对决 `reports/upstream-vs-ours.json` 的时间戳是 **2026-09-27**,跑在旧 decider-2B 底座、4 个任务上(结论:任务级 wall time 3/4 更快、1/4 更慢)。现役底座是 StartLux-Decision-2B,题集已扩到 100 行真实站 ⇒ **那份读数不能当作今天的平替水平证明**,引它时必须带上日期与底座差异。补齐这份对照现在**卡在凭据而不是批准**:本机没有任何可用的 `TYPESAFE_API_KEY`(`.env` 里那个键的值就是 `local` 占位,长度 5,18:1x 实测),所以"平替水平"在拿到 key 之前**只能写成未证**;那份读数将来也必须按"非零云端"单独隔离,不许混进 L5 的账。登记在 `m2/real-log.md` 与 #76。

**可插拔两层都是代码级的**(10-13 18:3x 逐条核注册表;我上一段把它写窄了,纠正在 `m2/real-log.md` 的 #80 那节):`jev_ultrafast/decider/provider.py` 注册的决策 provider 是 `{agentjev, laya, laya_decider, openai, typesafe}` —— 其中 **`DECIDER_MODE=openai` 就是 chat→decision 的适配器**(`decider/choose_2b.py`:`post_chat` + `response_format=json_object` + 解析后校验重试,base_url / model / api_key 全走环境变量),未知模式大声失败(实测 `ValueError: unknown provider: …` 并列出已注册的名字);Text Helper 层同理,`scripts/text_helper.ps1` 里 groq / deepseek 两个云端分支必须显式提名且各自打 `$Cloud` 标记。⇒ "换一个免费 API 小模型"是配置级改动,**不需要写代码;缺的是读数**:这条决策线此前只有 `choose_2b.py` 末尾那节 mock `post_chat` 的离线 smoke。**读数今晚拿到了**(18:39–19:0x,`m2/freecloud_report.py` 只读产物,`DECIDER_MODE=openai` 打 Groq 免费档跑同一把 19 行冻结集,Text Helper 一律留本地 —— 只让一个变量出本机):**20B=18/19、120B=17/19,`false_positive=0` 两臂都守住**,本地 2B 的锚是 19/19;决策延迟中位 0.64 s → **1.94 / 2.06 s**;7B 那条臂被免费档 **429 掐死**(90 次 429 重试、15 分钟只走完 3 行,没有 report ⇒ BLOCKED,不是读数)。**共同掉的那一行 l001 不是模型弱**:提示词(`prompts/next_action.txt:21`)无条件承诺 `SCROLL_DOWN/SCROLL_UP`,而校验器(`decider/choose_2b.py:217`)只认本页真存在的操作 —— 两臂因此被拒收 11 / 5 次,**在 #82 修好之前,云端臂的分数不能当能力结论**。这三份 `freecloud-*` 报告不是零云端、不是 L4 冻结锚,也不替 #76 作证(口径写死在 `m2/real-log.md`)。唯一**没有**现成路的是付费上游 `typesafe` 那条:本机没有它的凭据。

## License

MIT —— 见仓库根目录 `LICENSE`(© 2026 chipchipss),与 `pyproject.toml` 的 `license = "MIT"` 一致;此前只有元数据没有文件,2026-10-12 补上。上游 jev-ultrafast 的 MIT 原文**已于 2026-10-13 逐字归档**在 `docs/12-upstream-license.md`(带取文命令、ref `1231850a`、字节数与 sha1),因为本仓的定位是"fork 基座"(H3),MIT 的条件句要求上游告示跟着分发走。**仍未核证的是逐文件对应关系**——仓内文档只说"基座 = fork",没有留下那次 fork 的 commit,所以对外声明"derived from 的具体清单"这件事现在不能写。
