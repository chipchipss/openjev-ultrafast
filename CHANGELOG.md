# Changelog

> 本文件记录项目的**阶段级**与**约束级**变更。
> 单文件代码变更由 git log 记录。
> 硬约束变更由 `docs/01-hard-rules.md` 的 A0.3 流程触发本文件追加条目。

---

## [freeze-round-missing-rows-is-blocked] - 2026-10-14 深夜（#88：冻结轮少行从此判 BLOCKED，不再是绿轮）

### 为什么这一刀值得存在

`scripts/ci_local.ps1` 的冻结档只对两件事 Die："没写报告"与 `fp≠0`。2026-10-14 21:19 那条阶梯的第 1 轮
只合并了 **17 行**（`reports/m1-baseline-1014-2122.json`，缺 `n001`/`n002`，是出口预检按设计拒跑的），
脚本照旧打印 `round 1: 17/19 PASS, fp=0` 然后继续跑第二轮和 50 行批 ⇒ **纪律②"同一个 build 上 19/19×3
冻结在先"从来没有脚本守着**。

### 形状与边界

- 判据独立成 `scripts/ci_freeze_gate.ps1`::`Get-FreezeRowGap`：拿 19 题集的 `task_id` 与合并报告的
  `results[].task_id` **求差** —— 数的是**行数**，不是 `pass`；
- **少行 = BLOCKED（exit 3）**：先把 `stage/round/rows/expected/missing_ids/missing_causes/passed=false`
  写进 verdict JSON，再退出（BLOCKED 也要有工件）；
- **少分 ≠ BLOCKED**：19 行齐全但有 FAIL 仍是分数红，这一刀**不碰**它 —— 把两种结局并档，就等于让
  "链路吃掉两行"和"能力掉一分"在工件里长得一样，正是 #16/#78/#84a 一路在拆的反面；
- 缺的每一行**分因**成 `preflight / crash_or_unknown / no_dump` 三档（读当轮分片目录的
  `failed/btask_<id>_err.log`；那些分片不入库，所以只有这里还留得下拒跑原文）；
- `MinPass` 的 59/43 与 `MaxWallMinutes` 的 30/14 **一字未动**，并有反向守卫钉住。

### 验证链

失败测试 `tests/test_ci_freeze_gate.py` 改前 **3/8**（缺文件那 3 案 ERROR、未调用与无工件那 2 案 FAIL）
⇒ 改后 **8/8**；行为见证是**直接把两份已入库报告喂给闸门**：
`17 行那份 → rows=17 expected=19 missing=n001,n002，两条因都是 preflight`；
`19 行那两份 → NULL（不误跳）`。离线全套 **40 件 / 329 案**全绿；两份 `.ps1` 非 ASCII 字节 0、
`[Parser]::ParseFile` 错误 0（本仓的两个老坑，先堵）。
完整阶梯重跑（`reports/ci-1014-2225.json`）：**冻结三轮全 19/19、fp=0 ⇒ 活体零误跳**；
诚实的边界：**拦截那一支这一轮没有活体触发**（链路恰好没少行），它的证据是上面那两份真报告。

### 顺带拿到的第三个 L2 样本（产品码本轮未动）

**43/50、fp=0、unknown=0、error=1**、`egress_retried=1 / recovered=1`（`r129` 被重试救回 PASS）：
`r139` **连续两批**同一签名 `agent_init_failed_after_cdp_reset: StalePage`（控制台先 `[browser-lost] … reset, retry once`，
重跑那次仍死在 `agent.py:281`）⇒ #57 的下半场现在有两次独立见证；`r103` 这次是 `blocked_by_bot_wall`（墙时好时坏，
不带进下一批当站点属性）。距 45 的缺口从此有名有姓：**两道墙 + 那一行 error** ⇒
**当前 build 三个样本 43 / 42 / 43，L2 的凭证仍由 b24 持有**。

跟踪文件 **747**（reports 463 / m2 109 / tests 40 / m4a 36 / `jev_ultrafast` 33 / scripts 30 / 根 17 / docs 9 / m1 8）；
产品码本轮零改动。
---

## [l2-repin-attempt-failed-and-the-freeze-gate-was-blind] - 2026-10-14 深夜（L2 重钉没钉上，顺带量到阶梯自己缺一条判据）

**为什么跑**：计划书 L2 那格的凭证是 b24（10-11）的 45/50，而 b24 之后落了 #84a/#46/#85 三刀 ——
三条都能改批读数，所以"当前 build 达成 L2"这句话当时**没有工件支撑**。判据起跑前钉在 `m2/real-log.md`
（≥45 才换绑；`error=0` 是硬线；非环境翻动必须 ⊆ 抖动集合）。

**读数（`reports/ci-1014-2119.json` + `reports/ci-1014-2119-1014-214129.json`，墙钟 12 分钟 / 预算 14）**：
批 **42/50、fp=0、unknown=0、error=1**；冻结 **17/19、19/19、19/19**（三轮 fp 都是 0）；
零云端守住（49 份 trace 的 82 个 step 事件 `text_helper` 全是 `null`）；
浏览器归属守住（收尾打印 `own-cdp-chrome=0`、`foreign browsers left=15 (never targeted)`，
机上那 15 个 Chrome 进程逐条查过全是操作者默认画像）。
5 行 `agent/decision` 与 b24 的失败集合**一字不差**（`r102 r103 r104 r105 r122`）⇒ 非环境翻动 ∅；
2 行 `system`（`r101` bot 墙、`r127` 带 `ERR_SSL_PROTOCOL_ERROR` 且**重跑第二次仍失败** `recovered:false`）；
1 行 `error`（`r139` = `agent_init_failed_after_cdp_reset: StalePage: Document is navigating`，两次都在 `agent.py:281`）。
⇒ **判据 1 落在后一档：L2 继续由 b24 持有**；当前 build 最干净的一读仍是 17:36 那批的 **43/50（error=0）**。

**顺带量到的闸门缺陷（开新账 #88）**：`scripts/ci_local.ps1:159–161` 的冻结档只 Die 在"没写报告"与 `fp≠0`，
**从不检查 `$pass == 19` 或 `summary.total == 19`** ⇒ 今晚这一轮少了两行还被当绿轮往下跑。
那两行不是崩的：出口预检按设计拒跑（`reports/baseline-1014-2122/failed/btask_n001_err.log` 逐字
`[preflight] 样本 https://www.python.org：起点页落在 chrome-error://chromewebdata/（出口/代理不通） —— 不跑批、不写报告`，
n002 同一条换成 `developer.mozilla.org`，而同一轮 21:23–21:28 的其余各域正常 ⇒ #16/#74 那一族的又一次"同轮内异域不通"链路读数）。
**纪律②（同一 build 上 19/19×3 冻结在先）脚本没替我守**，这是本轮真正的收获。
另记一笔仪器边界：这类拒跑原文只在**不入库**的 `reports/baseline-*/` 分片里 ⇒ 已把原文抄进 `m2/real-log.md`。

**同场补的两笔记账（都是"仓里没有"这类）**：`docs/00-project-plan.md` 第五节的「真实站点任务 | 未开始」是旧表残留，
与同文件第四节 L2 行的 ✅ 打架，已换成带工件的双读数；**#86 在此之前只挂在任务列表、`m2/real-log.md` 一条没有**
（`grep -rn "#86"` 全仓 0 命中），已登记它的已知/已证伪/未量三部分，并就地纠正我自己写歪的一句话
——"密度上去概率上去"按**行次**口径重算是 0% / 16.7% / 12.5%，不单调，那句话只在"按臂"口径下成立。

**为什么不再碰运气重跑**：本轮链路正在抖（冻结轮被两域拒、批里同一码重跑仍挂），
再开一批只是同一台 :2080 的第二个样本，而 #86 已写明代理侧日志拿不到。要重钉 L2 得先等链路稳，或在 #86 的分层实验里一并量。

离线全套没动（本轮零代码改动，39 件 / 321 案是 21:20 tier1 实测）；跟踪文件 **739**
（reports 457 / m2 109 / tests 39 / m4a 36 / `jev_ultrafast` 33 / scripts 29 / docs 9 / m1 8）——
比傍晚那一版多 6 份，全是今晚这条阶梯的工件（verdict + 批报告 + 三份冻结轮 + 一份 live smoke）。

## [coded-egress-row-gets-one-retry] - 2026-10-14 傍晚（#85 的第二刀：50 行阶梯因此第一次绿）

### 先量回收率，再决定要不要多跑一行

| 实验 | 读数 |
|---|---|
| `r127` 单跑 ×8（真 runner，`one-r127-*`）| **8/8 PASS** —— 同一行在批里 17/36 失败 ⇒ 失败来自上下文，不来自这一行 |
| 两行臂 `[r126, r127]` ×3（`reports/sq-*` 与 `wretry*`）| r127 失败 1/3 ⇒ 密度↑ 概率↑，但不是确定性相邻 |
| 四行块 ×4 + 失败行立刻再跑一次 | 失败 2 行，**2/2 回收** |
| 产品路径实盘（`reports/wretry1-1014-173345.json`）| `r127` 回收 PASS；同一轮 `r129` **两次都失败** ⇒ 照实留 `FAIL / blocked_by_egress` |

**合并回收率 = 3/4**。以后引用这一刀只许说 3/4，不许捡 2/2 或 8/8 那半说好。

### 四条硬线，每条一案钉住（`tests/test_egress_retry.py`，改前 1/6 ⇒ 改后 6/6）

1. 只有 `failure_mode=blocked_by_egress` **且** `meta.final_page.err` 非空的**失败行**才重跑 ——
   **没有码就不许重跑**，否则"我们自己的改动弄坏导航"会被重试洗成 PASS（#85 的仪表正是为这个先做的）；
2. 只一次，不循环；再失败就在痕迹里写 `recovered:false`；
3. **PASS 行永不碰** —— `x001` 的终页今天起也带 `err=ERR_CONNECTION_CLOSED`（按设计不可达且它 PASS），
   这一案防"新仪器反过来咬负向题"（#16/#78/#84a 的豁免同一族）；
4. 痕迹必须活到工件：`meta.egress_retry` 过 `_meta` 白名单，`summary` 加
   `egress_retried / egress_recovered` 两格 —— **阈值没动而分数变了，读者必须看得见为什么变**
   （白名单丢仪器字段这一族的第 5 次，所以先写测试再写代码）。

### 阶梯与读数

tier1 绿（39 件 / 321 案）、live smoke 5/5、冻结 **19/19 × 3 全 fp=0**、
批 **43/50、fp=0、error=0、unknown=0、墙钟 9.4 分钟**，`reports/ci-1014-1736.json` = **`CI green`**
—— 连续两轮红在 `MinPass=43` 之后第一次绿，**而 43 这个数一字未动**。
批内计数与逐行痕迹对得上：`egress_retried=2`、`egress_recovered=1`，
`r127{attempts:2,first_err:ERR_SSL_PROTOCOL_ERROR,recovered:true}` 与
`r129{... recovered:false}`；非环境翻动 0 行在抖动集合外。

**仍挂着的一件事**：`r127/r129` 与同域兄弟行差 17 倍的机制没有解释（现有线索只有"目标页体积/取回时间同序"，
`json1.html` 是反例）。这一刀是把**后果**变成看得见、可回收的，不是把**成因**查清了 —— 两件事不许混着报。

---

## [egress-rows-get-an-error-code] - 2026-10-14 傍晚（#85 的仪器半刀；归因经实验维持）

### 三步实验先把自己的说法推翻一次，再决定动不动刀

| 步 | 实验 | 读数 |
|---|---|---|
| ① 逐行对 24 份批报告 | 同域 sqlite 七行 | 失败集中在 `r127`(17/36) 与 `r129`(19/36)，兄弟行各 1/36 ⇒ "批内瞬时出口失败"解释不了这个不对称 |
| ② `m2/probe_sqlite_reachability.py`（零模型，双臂各 8 次）| 五个目标页 | 直接导航 **8/8 全通**、从起点页点击 **7–8/8 通** ⇒ 站点没锁我们，题也不是不可行（不走 r118/r106 的题集先例）|
| ③ 顺序实验（真 runner，同四行原序 / 反序）| `reports/sq-p1-*.json` vs `reports/sq-r1-*.json` | 原序复现 `r127+r129 FAIL`，**反序 4/4 全过** ⇒ 不随行身份 |

`m2/probe_sqlite_batch_context.py` 复现原序时抓到了错误页正文里的 **`ERR_SSL_PROTOCOL_ERROR`** ——
本地代理（:2080，操作者的桌面客户端）的 TLS 隧道间歇断 ⇒ **`blocked_by_egress / system` 这个归因本来就对**，
我今天下午怀疑它"替一个行专属毛病开脱"，被自己的实验反过来推掉。

### 真正欠的是仪表：那 83 个字符此前只以"长度"存在过

`page_digest` 增加一件**稀疏的** `err`（正则 `ERR_[A-Z][A-Z0-9_]{2,}`，只取码名，
本地化句子一概不进产物；健康页不写这个键 —— 与 `arrival_relook_ms` 同一口径），`evaluator._meta` 放行该键。

| 检查 | 读数 |
|---|---|
| 失败测试先行 | `tests/test_graded_input_logged.py` 改前 **7/9** ⇒ 改后 **9/9**；离线全套 **38 件 / 315 案**绿 |
| 实盘见证 | `reports/one-x001-1014-165157.json` 里 `meta.final_page.err = ERR_CONNECTION_CLOSED` |
| 阶梯 | tier1 绿、smoke 5/5 fp=0、冻结 **19/19×3 全 fp=0**、批 42/50 `fp=0 error=0 unknown=0`（`ci-1014-1652-1014-171208`），非环境翻动 0 行在集合外 |
| 仪器判据（起跑前写死）| 批里 **2/2 个 egress 行都带 `err`（全是 `ERR_SSL_PROTOCOL_ERROR`）**、**PASS 行 0 个带**、50/50 行 `final_page` 键集合合法 |

阈值与题集都不动：`MinPass=43` 保持，`passed=false` 的那一轮原样留仓。**行级有界重试仍未做**，
前置量是"重试一次的回收率"（P 臂 3 轮 vs 加重试 3 轮），不是凭感觉加一次 re-run。
r127/r129 与兄弟行为何差 17 倍也仍挂着 —— 现有线索（目标页体积/取回时间同序，`json1.html` 是反例）不构成结论。

---

## [overlap-tier-removed-from-the-floor] - 2026-10-14 下午（#46：近似行劫持）

### 删一档，而不是加一道守卫——两条离线读数决定的

`explicit_target` 的档位阶梯里最后有一档"词重叠 ≥0.75 ⇒ `0.75+ratio/10`"。它的失效形状是实测的：
goal 引号串 `'Style Guide for Python Code'` 对上页面上唯一可见的 `Style Guide for C Code`
（4 个实义词中 3 个 = 0.825），而**候选只剩一行时 `second = 0`** ⇒ 0.825 自己就过了 `top ≥ 0.75` 的门槛，
地板点向 `pep-0007/`。

| 读数 | 命令 | 结果 |
|---|---|---|
| 这一档**有没有正确命中靠它** | `python m2/probe_near_miss_tier_attribution.py`（186 份真实页逐页重放产品地板）| 非弃权 71 次：精确 50 / 前缀 6 / 包含 8 / 从头对齐片段 3 / 单复数折叠 1 / 其它(href·域名) 3 / **词重叠 0** |
| 删掉它会不会动别的行为 | `python m2/golden_tier3.py --compare reports/tier3-golden-1013-233451.json` | **193 页 / 772 例摘要一字不动**（`f7e05f70…`）|

⇒ 这是一条**死档**（语料里没有任何正确的命中靠它），所以按减法删，而不是再叠一层守卫。
门槛本身保持 `0.75`：剩下的最低 label 档是 href 的 0.88，抬门槛会顺手禁掉未来的低档，那是两件事混成一件。

### 收益按实跑写：这一刀**不买步数**

| 检查 | 读数 | 工件 |
|---|---|---|
| r113 单跑 | **PASS / 3 步 / 4 次模型调用**（改前也是 3 步 / 4 次）——拍的内容变了：`滚动 → 滚动 → 逐字点中 pep-0008`，改前是 `滚动 → **点 pep-0007** → 点 pep-0008` | `reports/one-r113-1014-142145.json` |
| 批内实况 | 同一形状在批里复现（第 2 拍不再是错页点击） | `logs/ci-1014-1423-1014-144253/r113.jsonl` |
| 配对批（改前 vs 改后） | **50 行零差异**（42 vs 42），`explicit_target` 触发面 39 行 → 40 行，没有一族消失 | `ci-1014-1332-1014-135106` / `ci-1014-1423-1014-144253` |
| 阶梯 | tier1 绿（38 件 / 313 案）、live smoke 5/5、冻结 **19/19×3 全 fp=0**、批 `fp=0 error=0 unknown=0`、非环境翻动 0 行在集合外（唯一 LOST 又是 sqlite 的 `r129`，`blocked_by_egress`）| `reports/ci-1014-1423.json`（`passed=false` 原样留仓） |
| 纪律③ | `x001` PASS/0 步且 `failure_mode` 仍为空、`x002` PASS/5 步 | `one-x001-1014-142236` / `one-x002-1014-142249` |

**我预登记的"2 步"落了空**，而且是算术错的（逐拍表自己写着 Python 行要到 `y=1120` 才进索引集 ⇒ 两格滚动 + 一次点击）。
回滚条款（"多于 3 步或 FAIL"）没触发，但收益必须照实重写：**买的是"地板不再在没被点名的页面上开火"，不是省一拍**。
这条若写成"少花一拍"就是没有工件的数（同一个句子在两处会被人当证据）。

**反面写清楚**：语料里这一档 0 例 ⇒ **golden 抓不到它的回归**（与 `link_followed_arrival`/`first_result` 那两格同一形状的空洞）。
它只能由 `tests/test_explicit_target_near_miss.py`（改前 3/5 ⇒ 改后 5/5，夹具是两页真实快照的逐字段归约，不带正文）钉住。

### 文档数字按实跑重打（离线闸门第五次涨）

**38 件 / 313 案全绿**（14:5x `scripts/smoke.ps1` tier1 逐件 `n/n passed` 相加）；跟踪文件 **694**
（reports 415 / m2 107 / tests 38 / scripts 29 / `jev_ultrafast` 33 / 根目录 17）。
上一版是 10-14 14:0x 的 37 件 / 308 案、679 个跟踪文件。

---

## [graded-input-artifact-and-arrival-shell-attribution] - 2026-10-14（#75 结案 + #84 的归因半刀 84a）

### 两刀的分工：先让"评测吃了什么"可复核，再让"站点给了空壳"能被认出来

| 刀 | 性质 | 新增 | 为什么必须先有另一把 |
|---|---|---|---|
| **#75** | 仪器，零行为 | `logger.page_digest(page)`（`url/title/text_len/text_sha16`，**不含正文**）成为**唯一来源**，logger 与 runner 共用；`evaluator._meta` 白名单放行 `final_page` ⇒ 摘要从此进 `reports/*.json` | 摘要此前只活在 git-ignored 的 `logs/` 里，`reports/*.json` 的 meta 只有四个老键 ⇒ 一次 `text_contains` 翻动在可分享工件上**事后不可复核**（白名单静默丢仪器字段这一族的第 4 次复发） |
| **84a** | 归因，零分数变更 | 新档 `failure_mode=blocked_by_upstream_shell / failure_class=system`，判据 `title 为空 ∧ text_len ≤ 100`；分支排在墙之后 | 没有 #75 的字段，#84 的正负样本只能靠临时探针（`m2/arrival_digest_scan.py` 第一版就因此读的是本地 `logs/`） |

### 判据是量出来的，两侧都有余量（`python m2/arrival_digest_scan.py logs`）

| 样本 | 行 | 形状 | 结果 |
|---|---|---|---|
| **正样本**（1066 → 1167 行带摘要的 `task_result`） | `r102 / r161 / r162 / r187`，全在同一批 `tier3-100-1014-105704` | `arxiv.org/search/physics`、`title=''`、`text_len=14`、**`text_sha16` 四行逐字相同** | 当时全记 `agent/decision` ⇒ 一次上游 episode 吃掉 4 行 |
| **负样本 A** | 22 行 httpbin（`/post`、`/forms/post`） | `title=''` 但 `text_len ≥ 181` | 全 PASS ⇒ 长度项是唯一救回它们的东西（余量 14 vs 181 = **13 倍**） |
| **负样本 B** | 9 份快照页（`m2/corpus/pages*.jsonl`，186 份里的薄尾） | 13–87 字符但**标题非空**（`403` / `The Internet` / `Client Challenge` / `www.rfc-editor.org` / `news.ycombinator.com`） | 真实页 ⇒ 标题项是唯一救回它们的东西（这条判据最薄处，写进注释） |
| **明确不进射程** | `r104` 的 PubMed `403`（13 字符、标题非空） | 实测 `FAIL / correct_abandon / agent / decision` | 诚实放弃本来就归 agent ⇒ 一条分支只认一种形状（#78 的教训） |
| **不加的词** | `action ≤ 3` | 摘要里没有 action 数 ⇒ 1066 行**无法回溯核对** | 两条合取已 0 误伤 ⇒ 加一个不能被工件检验的词等于加装饰 |

判据在 1167 行历史摘要上命中**恰好那 4 行**，在 #75 之后两份新批（各 50 行）上命中 **0 行**。

### 归因-only 的合格证明（与 #16/#78 同一把尺子）

84a 的阶梯：tier1 绿（37 件 / 308 案）、live smoke 5/5 `fp=0`、冻结 **19/19 × 3 全 fp=0**
（`m1-baseline-1014-1334/1340/1345`）、50 行批 **42/50、fp=0、error=0、unknown=0、`meta.final_page` 50/50**
（`ci-1014-1332-1014-135106`）。**改前/改后配对**（`ci2-1014-1320` vs `ci-1014-1332`，同题集、build 只差 84a）：
50 行里**逐字段只有 1 行不同**（sqlite 那行的 egress），**两边都 PASS 而象限漂移 0 行**；
预登记的五条回滚条款 (a)–(e) 一条都没触发。最硬的一条阴性检查来自同一行的两种命运：
`r102` 在这轮批里 FAIL，但它的帧是 **1426 字符、标题 `Advanced Search | arXiv e-print repository`**
（决策走错页），**新档没有把它接走** —— 站点健康而失败时账仍归 agent。

### 两道闸门自己的红 + 一处可复现性钉固

1. **分数闸门连着两轮红在同一个地方**：42 / 43 / 42，`MinPass=43`。三轮共同的读数是
   **非环境翻动 0 行在集合外**，唯一来回的是 **sqlite.org 两行**（`r127`/`r129`）：13:17 单跑 `r129` PASS，
   13:18 批里 `r127` 通 `r129` 不通，13:51 批里**两行都不通**。
   ⇒ 我起跑前登记的候选成因"同域相邻两行互相打死"**被自己的读数削弱**（真要如此，不会两行同时失败）；
   现在的形状是 **host 级的分钟窗口**。**阈值不动**（不为抬分改判据），按 b40 的先例只给一条报告用修正值：
   `42 + r127 + r129 = 44/50`，原始 42 与 `passed=false` 的工件原样留仓。
2. **`ci_local -Tasks 50` 的题集一直放在 `%TEMP%`**（`tasks_b19_50.jsonl`，10-10 生成、从未入库），
   而 `m2/real-log.md` 从 b18 起把多轮"同一题集配对"记在它身上 ⇒ 一次磁盘清理就让这些读数不可复算。
   钉成 `m2/tasks_real_50.jsonl`：与 temp 那份**逐字节相同**（sha1 `457dea2e…`），并核对 =
   `m2/tasks_real_100.jsonl` 的**前 50 行逐对象相等** ⇒ 不换题集、不改任何历史读数。
3. **一条流程错**：第一次起这轮阶梯时命令里写了 PowerShell 的 `*>`，bash 先把 `*` 展成文件名塞进参数位，
   `ci_local` 在 `-Rounds` 类型转换上当场退出 ⇒ 没有报告 = **BLOCKED**，不是一轮读数（与 10-14 早上"预登记与起批写在同一条命令里"同族）。

### 文档数字按实跑重打（离线闸门第四次涨）

**37 件 / 308 案全绿**（14:0x `scripts/smoke.ps1` tier1 实跑，逐件 `n/n passed` 相加）；
跟踪文件 **679**（reports 404 / m2 104 / tests 37 / scripts 29 / `jev_ultrafast` 33）。
上一版是 10-14 12:3x 的 36 件 / 297 案、661 个跟踪文件（reports 389 / m2 102 / tests 36）。

### 仍挂着

**84b（到站空壳的有界重看）按读数判死（10-14 下午，方法与瑕疵同条记录）**：
地板在这一帧上全弃权不是「缺守卫」，而是两处的活页测试都写着 `text 非空`，被 14 个字符穿过（`agent.py:677` 的 M16 循环预算 1.8 s、`skills.py:192` 的 `page_not_ready` 逃生口是 f002 教出来的）。改成 `is_arrival_empty_shell` 技术上干净、也不会误伤 httpbin 那族（1354+ 字符），**但等不到**：入库轨迹算出同一 host **连续 8.0 秒**给两行都是空壳（`r161` +7258.7 s / `r162` +7266.7 s），`r187` 空壳后 31.8 s 才有健康页，而两个现役预算（1.8 s / 6.0 s）都落在窗口之内。另有一条「同文档等 6 秒仍不收敛」的旁证——**产生它的探针当晚没入库，所以只能当旁证**，判据用的是上面那条从入库轨迹算出的时刻。有界重加载也不做：窗口内逐次请求交替 ⇒ 一次重加载是抛硬币，而这些行已被 84a 记成 `system`，批信号不再被它们污染。重开条件写死成可检的形式：需要**逐拍**页摘要（今天 `final_page` 只在 `task_result` 上记一次，「同一行后来那一拍是否变健康」现在没有工件能读）。
另开一件：**50 行档的下沿被 sqlite 两行反复压穿**，处置要么在题集层（同域行的排布），要么在口径层
（闸门按 `failure_class` 分开看），两条都不是"把 43 改成 42"。

---

## [tier3-zero-behavior-with-golden-master] - 2026-10-14（#70 关掉；顺带立了一件新工具）

### 这一刀真正新增的不是重构，是**判据的形状**

`#70 Tier 3` 原计划四件事，**测量之后有两件被证伪**（写进 `m2/real-log.md` 的预登记，不偷偷缩小范围）：

| 原计划 | 测量 | 结论 |
|---|---|---|
| 斩 `agent ↔ skills` 的 import 环 | AST 扫 import：`skills.py` **根本不 import agent**，`agent.py` 那三处是函数内延迟导入 | 没有环可斩 ⇒ 但 `docs/11` 那份体检说的"双向依赖"指的是**依赖形状**（agent 伸进 skills 私有三处 + skills 注释逐行指着 agent 行号），那部分照做 |
| `state` 改 dataclass | AST 扫 `state[...]`/`.get("…")` 的字面键：`agent.py` 之外只有 `model.py` 碰 3 个键 | 大 diff 换小收益 ⇒ **不做** |
| 跨模块私有名 | 全文数：一共 **3 处** | 做：`_indexed`→`indexed_actions`(68 处)、`_phrases`→`goal_phrases`(34 处)，**不留别名、不留 shim** |
| 拆 `goal_reached` | `skills.py` 60 个定义里它最长：**175 行** | 做：**175 → 43 行** + `_arrival_facts`/`_arrival_hit`/`_arrival_by_phrases`/`_arrival_by_nav_object`，实况注释跟着判据搬走 |
| `_STUCK` 生命周期 | 模块级、按页态指纹键、跨任务不清；夜间档 r3 实测 **111 个指纹有 25 个被 >1 题共用** | 只装**仪表**（复位是行为变更 ⇒ #83） |

**为什么不用"再跑一批看分数"当判据**：同 build 的 100 行批本来就抖 6 行（`m2/real-log.md` 的夜间档那节），
一次静默的行为漂移完全可能落在噪声里。所以新建了**逐字节**的对照物：

- `m2/probe_tier3_corpus.py` —— 零模型采 **100 个起点页 + 86 个到站页**（`m2/corpus/`，**不入库**：里面是第三方站点正文）。
  第二跳由**探针自己分词打分**挑，不借 `skills` 的函数（否则语料形状依赖被测代码，改了行为时对照物自己会动）。
- `m2/golden_tier3.py` —— 193 页 / 772 例 × 6 个确定性函数，入库件只记 `operation/target 序号/skill 名/置信度`，
  label 与 href 留在不入库那份。baseline：`reports/tier3-golden-1013-233451.json`，
  **digest `f7e05f70e6807de9a2b849ef873b285cbbb337ee09eb52efcc1a2a065d105d11`**。
  三步改完各自 `--compare` ⇒ **摘要一字不动**；`route` 触发面 `{explicit_target:244, scroll_to_named_target:173, search_type:96, goal_reached:111, form_submit:9, blocked_dead_page:8}`。
- **这份 golden 的覆盖面按实数写**：`link_followed_arrival` 与 `first_result` 在语料里**非弃权 0 例**
  ⇒ golden 抓不到它们两个的回归（原因：pass2 落盘时没存"被点的标签"，而 `link_followed_arrival` 读的就是那个标签）。
  那两族现在只靠 `tests/test_skills.py` + `test_done_guard_arrival.py` 保护；要动它们先重采带 `via_label` 的 hop 页**并重记 baseline**。
  同理，`_STUCK` 那步的退避逻辑改动 golden 也抓不到（语料里没有抑制事件）——那次由单测守。
  **对照物不是万能的，覆盖面要逐函数报数，不能只报一句"摘要没变"。**

### 收口读数（两步各自完整跑过一遍阶梯，因为 `jev_ultrafast/*` 改了两次）

| 判据 | 第一轮（拆 `goal_reached` 之后） | 第二轮（加了归属计数之后） |
|---|---|---|
| 冻结 19/19 × 3，fp=0 | **19/19 × 3**（`m1-baseline-1013-2352` / `1014-0000` / `1014-0007`） | **19/19 × 3**（`1014-1145` / `1150` / `1156`） |
| live smoke（含 x001/x002） | 5/5，x001 `true_success`、x002 `correct_abandon` | 5/5 |
| 100 行批 | 68/100、fp=0、error=0、零云端、20.0 min | **69/100、fp=0、unknown=0、error=1**、21.8 min |
| 预登记的翻动判据 | 集合外 1 行（`r162`）⇒ 审计如实报"应当回滚"，**归因后用新工具判定不是本次改动** | **非环境翻动 6 行全在抖动集合内 ⇒ 通过** |
| #83 的那一格 | 进场带笔记 61/100、`notes=1 / suppressed=1` | **`cross_task=0`**（`suppressed=1` 证明它有事件可分）⇒ 两批 200 行里没有一次跨题按住 ⇒ **不复位，等它咬到人** |

`r162` 的归因是这次最值钱的一步：新工具 `m2/replay_two_builds.py` 把**当场抓的那一页**分别在
改前 build（`git show 53aa033~1:…skills.py`，整包复制进临时目录、只换那一个文件、两个 build 各起子进程）与 HEAD 上跑一遍
六个确定性函数 ⇒ **逐字段一致**；配上零模型重看（同页 `title='' / 2 个元素 / querySelectorAll('a,button,input')=0`，
同一时刻同一代理 `curl` 却是 **200 / 16,272 字节**，一分钟后同一个探针又读到 34 个元素）
⇒ 站点间歇性给浏览器空壳，**不回滚**，另开 **#84**（到站空壳：归因 + 有界重看，是 #16/#78 之后的第三种形状）。

### 两条仪器/闸门自己的错（当场修，不改旧工件）

1. `m2/tier3_batch_audit.py` 第一版忘了剥 `{"task_id","result"}` 包装 ⇒ `failure_class` 一律读到 `None`，
   把 `r127`（基线三轮全是 `blocked_by_egress`，这批 sqlite.org 通了）当成"代码改动造成的翻动"。
   判据本身没动，改的是仪器：**翻动先按 `failure_class` 分家，系统类不记在代码头上**。error 行（`result` 是字符串）也不再崩。
2. `scripts/ci_local.ps1` 的 `MinPass=43 / MaxWallMinutes=14` 是 **50 行**那把尺子，`-Tasks 100` 沿用它 ⇒
   第二轮的 `passed=false` 里"墙钟 21.8 > 14"是**假的**。现在两个阈值都按 `-Tasks` 选（100→59/30、50→43/14）。
   旧 verdict 工件 `reports/ci-1014-1142.json` 不改（它是当时脚本的真实产物），校正后重算只剩 `error=1` 这一条真失败，
   而它是 `r139` 的 `agent_init_failed_after_cdp_reset` **第三次**出现（b39、b41、本批），单跑 PASS
   （`reports/one-r139-1014-122552.json`，1 步 / 2 调用）⇒ 仍归 #54/#72 那族，每批最多咬一行。

### 文档数字按实跑重打（离线闸门第三次涨）

**36 件 / 297 案全绿**（12:3x 实跑，逐件 `n/n passed` 相加）；跟踪文件 **661**（reports 389 / m2 102 / tests 36）。
另记一次我自己的口误更正：`docs/11` 那句"双向依赖环"被我复述成"曾有一个循环导入"，实际从来没有 —— 见上表第一行。

---

## [release-form-closed] - 2026-10-13 深夜（#79 选路 + #76 结案）

### #79 —— 历史里的第三方内容：选"闸门 + 无历史快照"，不选改写历史

操作者把选择权交给我（"你觉得哪个好就选哪个"）。两条路的代价不对称：
`git filter-repo` + force-push 会重写**已经推出去**的历史（10-13 已 push 到 `10c8d61`），
那是共享状态，不是我该按的键；而"第三方邮箱在历史里"这件事的真正风险是**发布产物**，不是我的本地日志。
⇒ 选了不改写历史，改拿两件**可执行**的东西把风险关住：

1. `tests/test_no_third_party_pii.py` —— **5/5**（结构性判据，仓里不写任何第三方名字）：
   ① 夹具的上传清单每条都必须是 `third-party-NNN.<ext>`（或两处刻意保留的合成名）；
   ② 任何跟踪文件里都不许出现"文件名里嵌着一个非合成邮箱"这种形状；
   ③ 脱敏脚本第二次跑替换 0 处（幂等，否则"已修好"不可复核）；
   ④ **判据自己必须会响**：把一条真形状喂进同一个谓词要被判出，合成串 `note_redacted@example.com.pdf` 不许误伤；
   ⑤ 普查脚本的清单只能放**片段**（>24 字符或带 `@` 就算夹带完整名字）。

**这道闸的第一个战果是它自己的测试文件**：`git add` 之后重跑 ⇒ **4/5**，案② 报的夹带文件是
`tests/test_no_third_party_pii.py` 本身——案④ 为了证明"判据会响"而写的演示串 `Foo_Bar_…@….edu.pdf`
在文件成为跟踪文件的那一刻被同一条判据抓住。修法**不是**给测试文件开后门、**不是**放宽判据，
而是把演示串改成运行时分段拼接：仓库文本里不再出现这个形状，案④ 仍然当场证明判据会响。
（这正是它设计的用途——第三方内容不许回到跟踪文件，包括以"反面例子"的名义回来。）
2. `m2/make_release_snapshot.py` —— 发布走快照而非 `git clone`：
   `dist/openjev-ultrafast-10c8d61-snapshot.tar.gz`，**628 文件 / 1,537,981 字节 /
   sha256 `e0a55e4f0ef7adc9f081745eda303d725e0a34ffb1817573381beaeb7f9e7cc9`**，manifest 里
   `history_included: false`，`dist/` 进 `.gitignore`。

当前工作树的实测（`m2/census_third_party.py`，刚重跑）：跟踪文件 628，命中 **1 个文件 / 2 次**，
且那 1 个文件是**扫描器自己**（`m2/census_third_party.py` 里的清单片段）。

**边界写死，不许说成"第三方内容已从仓库消失"**：git 历史里那几条旧内容**仍在**，
所以对外发布的口径是"给快照"；`git clone` 这条路上它还在。这条限制同时记在 `m2/real-log.md`。

### #76 —— 结案为 won't-do：对上游的正面对照不跑了

操作者原话：**「#76我没有TYPESAFE_API_KEY，这个就不做了」**。
与实测一致（本机 `.env` 里那个键的值长度 5，就是 `local` 占位），付费上游调不到。
⇒ 状态从 10-13 傍晚写的"等凭据"改成**取消**，#76 关闭。

**这改变的不是一份读数，是对外能说什么**：目标句"近似 JEv + JEv Ultra Fast 的水平"里，
"平替水平"这半句**没有、也不会再有对照证据**——不是"暂未证明"，是"测量路线已被取消"。
README 的「平替水平的证据口径」一节按这个改写：能对外写的只有定位
（全本地、模型无关、可观测的开源实现）与免费 API 小模型那一半的读数
（`freecloud-*`：20B=18/19、120B=17/19、`fp=0`；非零云端、单独隔离、**不替 #76 作证**）。
`reports/upstream-vs-ours.json`（2026-09-27，旧底座 4 任务）仍只是历史产物。

### 四条新套件 + 最终 build 的夜间档三轮（离线总闸门已在夜间档结束后重打）

`test_no_third_party_pii` **5/5**、`test_task_id_uniqueness` **4/4**、
`test_prompt_operation_vocabulary` **4/4**、`test_evaluator_app_error` **6/6**；
夜间档跑完之后 `scripts/smoke.ps1` tier1 重打 = **35 件 / 290 案全绿**（22:3x）。
（tier1 在夜间档在飞时按纪律⑥拒绝启动，所以这个数字是 22:3x 的实跑，不是 21:13 那轮的 34 件 / 285 案。）

| 夜间档轮 | 工件 | pass | fp | error | unknown | 墙钟 |
|---|---|---|---|---|---|---|
| r1 | `nightly-1013-2115-r1-1013-211602.json` | 69 | 0 | 0 | 0 | 24.1 min |
| r2 | `nightly-1013-2115-r2-1013-214041.json` | 69 | 0 | 0 | 0 | 20.6 min |
| r3 | `nightly-1013-2115-r3-1013-220153.json` | 70 | 0 | 0 | 0 | 20.0 min |

判定工件 `reports/ci-1013-2115.json`（`nightly green`，三轮合计 **66.3 分钟 / 预算 95**）。
三轮步事件 `text_helper` 集合都是 `{null}` ⇒ 零云端照旧。**同 build 翻动**：r1↔r2 = 4 行、
r2↔r3 = 3 行、r1↔r3 = 5 行，三轮并集 **6 行** —— 与 10-12 那轮的 5/100 同量级，没有变差。
**#78 的新档位 `blocked_by_upstream_error` 三轮命中 0 行**（站点健康时不乱贴，这是 b41 那条阴性检查在独立三批上的复现）。

**程序瑕疵按原样记**：这一轮夜间档**启动前没有写预登记判据**（纪律⑤），上面三条是事后列的口径，
所以它们的地位是"稳定性清点"而不是"赌注"；69/69/70 这三个分数**不作任何判据引用**。

---

## [prompt-vocabulary-was-the-ceiling] - 2026-10-13 夜（#82）

### Status（#80 那条"云端臂分数被污染"的口径解除；解除的方式是先让测试证明污染在哪）

`DECIDER_MODE=openai` 两条臂共同掉 l001 的原因不是模型大小，是**我们自己的两处不一致**：
静态提示词无条件承诺 `SCROLL_DOWN / SCROLL_UP`（`prompts/next_action.txt:21`），
校验器只认当页真存在的操作（`decider/choose_2b.py:_map_choice` 抛 `unknown operation`），
而每一次拒收按缺陷#5 还**计入一次真实模型调用** —— 于是模型照规则行事却被自己的框架烧预算。

改后同一把 19 行、同一个 `gpt-oss-20b`：

| 判据（跑前写死） | 改前 | 改后 |
|---|---|---|
| `unknown operation 'SCROLL_DOWN'` 次数 | 11 | **0**（总拒收 15 → 1，剩那 1 次是 provider 的 HTTP 400） |
| l001 步数 | 9（FAIL） | **2**（仍 FAIL，但成因换成"模型在长页上不选滚动控件就弃权"） |
| pass / fp | 18 / 0 | **18 / 0**（没靠放松断言换分） |
| 本地冻结（`jev_ultrafast/*` 有改动，按纪律重打） | 19/19 | **19/19、fp=0**（`m1-baseline-1013-1920.json`） |
| 离线闸门 | 32 件 / 277 案 | **33 件 / 281 案**（新套件 `tests/test_prompt_operation_vocabulary.py` 改前 **2/4**） |
| 免费档配额 | — | 这一轮仍 32 次 `HTTP 429`；延迟中位被退避顶到 2 915 ms，**不能读成"模型变慢"** |

⇒ **#80 的对外口径更正**：可以写"免费 20B = 18/19、120B = 17/19、`false_positive=0`"，
剩下的 1–2 行差距是干净的能力读数；不能再拿它说"接口没问题"，也不能说"云端一定不行"。

顺带两处工程账（都是**门闸先响**）：
① 我第一版把云端 URL 抄进新 runner，被 `test_runner_safety`（"runner 不许拼写云端 URL"）打回；
   第二版想把 `Resolve-TextHelper` 的表搬走，又被 `test_runner_zero_cloud`（它**读那张表的文本**）打回
   ⇒ 最终 `Resolve-CloudEndpoint` 去**读**同一张表：URL 仍只拼写一次，runner 里没有云字符串。
② 我用 Python 字符串往 .ps1 里写 `. "$Repo\scripts	ext_helper.ps1"` 时 `	` 被吃成制表符，
   路径成了 `$Repo\scripts<TAB>xt_helper.ps1` —— **同一类"就地写文件不加 r 前缀"的第三次**（前两次：
   0 字节的 `agent.py`、报告名插值字面量）。这次由离线套件在 20 秒内抓到，没有进任何读数。
③ `MANIFEST.md` 上一次编辑被我写出**两张重复的表**，这次合并成一张并把每目录计数重新 `git ls-files` 实测
   （**626 个跟踪文件 / reports 364 / tests 33**）。

## [free-api-decision-layer-measured] - 2026-10-13 夜（#80）

### Status（目标句里"调免费 API 小模型"那一半第一次有了读数，而读数的第一用途是**推翻我对它的归因**）

`scripts/run_freecloud_19.ps1`（新，ASCII）：`DECIDER_MODE=openai` 打云端决策、Text Helper 留本地 :8081，
只让一个变量出本机；云端端点表复用 `scripts/text_helper.ps1`（那把"没有 key 就拒发"的闸同一张表）。

| 臂 | pass | fp | 决策延迟中位（只算真打模型的） | 被拒收 | 墙钟 | 工件 |
|---|---|---|---|---|---|---|
| 本地 StartLux-2B（锚） | 19/19 | 0 | 0.64 s | — | 5.3 min | `m1-baseline-1013-1746.json` |
| Groq `openai/gpt-oss-20b` | **18/19** | **0** | 1.94 s（p90 20.4 s，最大 39.0 s） | 15 | 8.2 min | `freecloud-19-openai_gpt-oss-20b-1013-183934.json` |
| Groq `openai/gpt-oss-120b` | **17/19** | **0** | 2.06 s（p90 9.8 s） | 5 | 5.0 min | `freecloud-19-120b-1013-185051.json` |
| Groq `allam-2-7b` | — | — | — | — | 15 min 走 3 行 | **BLOCKED**：`HTTP 429` 重试 **90 次**（数的是出现次数；先前 `grep -c` 报 89 是数行），进程被我停，没有分数 report，落盘的是 `reports/freecloud-19-7b-1013-185820-blocked.json` 这份 BLOCKED 工件 |

**纪律③的安全复测由 19 行集自带**：两条臂的 `x001` / `x002` 都是 PASS，象限 `true_success`（`evaluator.py:330-333` 的 reject/guard 口径），`false_positive=0` —— 换云端底座没有放松安全线。

**两条预登记的预测，错了一条半**：押 A=12–16（实测 18）、押"B 非法决策≈0"（实测 5，且原因与 A 逐字相同）。
错因是把差距归给模型大小，真正的原因在**我们自己的接口**：`prompts/next_action.txt:21` 无条件承诺
`SCROLL_DOWN / SCROLL_UP`，`decider/choose_2b.py:217` 却只认当前页 action 里真存在的操作 ⇒
照规则行事的模型被拒收，两臂共同掉的 l001 就是这个形状（本地 2B 走"给候选打分"，从不自己拼操作名，所以这格一直没暴露）。开成 **#82**。
⇒ **在 #82 修好之前，云端臂的分数不能写成能力结论**；能写的只有：安全硬线 `fp=0` 在三条臂上都守住、
免费档的第一阶成本是配额而不是钱、以及这条插拔线**真的能跑完 19 行**。

口径边界同晚写死：`freecloud-*` 不是零云端（L5 的账不含它）、不是 L4 冻结锚、不替 #76 的"平替水平"作证。
读数取法在 `m2/freecloud_report.py`（只读 `reports/` + trace 的 `decision` 事件；
第一版误从 step 事件读 `latency_ms`，会把不发模型调用的地板决策算成 0 ms —— 已改并写明）。

## [attribution-becomes-cheap-enough-to-fix] - 2026-10-13 晚（#78 + #79 工作树 + 一次读数口径的自我更正）

### Status（分类层补上一格；"环境的账"第一次可以在**已提交的历史**里重放；对外两句声明被实测改窄）

这一条不是新功能，是**读数口径**的变化，所以值得单开一节：

| 变化 | 证据 | 读数 |
|---|---|---|
| 站点自己的 HTTP 错误页不再记在 agent 头上（#78） | `tests/test_evaluator_app_error.py`（改前 **4/6**）+ `m2/replay_app_error.py` | 新档 `blocked_by_upstream_error/system`；判据=**精确 title `Application Error` + 正文为空**两条同时成立（与 #16 同纪律：子串会撞正常页，只看空页会撞 pypi 那种 472 字符 / 12 action 的薄而正常页）。历史全量扫描该标题 **10 次命中、10 次 FAIL、0 次 PASS** ⇒ 不可能给任何 PASS 换归因 |
| **我读错了 b34**（同一族，10-12 那次没认出来） | `m2/replay_app_error.py` 对 `real-1012-b34-*` 逐行重放 | b34 的 61/100 里 **r196–r200 五行**当时形状与 b40 逐字一致（title `Application Error`、0 步），却被记成 `decision/agent`，而该批 summary 的环境账只数到 3 行。**历史读数不改写**，只在这里明写：那次对"新 50 行为什么差这么多"的归因偏保守 |
| 归因-only 的合格证明（b41） | `reports/ci-1013-1732-1013-175147.json`（69/100，fp=0，unknown=0，error=1，21.2 min）+ 冻结 `m1-baseline-1013-{1735,1740,1746}` 三轮 19/19 | **PASS 行之间象限漂移 0**；新档在健康批命中 **0 行**（它不许乱贴）；GAIN 6 / LOST 2 全部逐行有归属（r139 = harness，单跑 `rerun-b41-r139-*` PASS；r174 = `blocked_by_egress` 系统类）。verdict `passed=false` 只因阈值 `error_rows=0` |
| #65 的代价第一次进**入库工件** | `reports/one-r154-1013-165253.json` 的 `meta.arrival_relook_ms=1328`；`evaluator._meta()` 的四件白名单补上这一键（改前红话直接报出没有键的 `meta`） | 之前钱只在 `logs/`（不入库）里 ⇒ 文档里的付费表对不到 `reports/`。b41 复核：付费 5 行 / 15 063 ms，收益四行照旧全 PASS |
| 夹具里一个第三方名字都不剩（#79 工作树部分） | `m2/scrub_third_party_fixtures.py`（v2）+ `m2/census_third_party.py` | 清单从工件结构数出来（夹具 43 条 `download/` 链接 / HTML 197 条），两文件共用一张映射表；普查现在报**跟踪文件命中 0**。`test_skills` 78/78、tier1 **32 件 / 277 案** |
| 对外两句声明被实测改窄 | 见 `m2/real-log.md` 的 #76 前置量与 README 两处改写 | ① "平替水平"（#76）状态从"等批准开销"改成**"等凭据"** —— `.env` 里 `TYPESAFE_API_KEY` 的值长 5，就是 `local` 占位，付费上游现在调不到；② 我先把"换一个免费 API 小模型"改窄成"只对 Text Helper 成立、决策层缺适配器"，**随后逐条核注册表发现是我自己读漏了**：`decider/provider.py` 注册的决策 provider 是 `{agentjev, laya, laya_decider, openai, typesafe}`，其中 `DECIDER_MODE=openai` 就是 chat→decision 适配器（`decider/choose_2b.py` 走 `post_chat` + `json_object` + 校验重试，base_url/model/key 全走环境变量），未知模式实测大声报 `ValueError: unknown provider`；⇒ 可插拔是**配置级、代码已有**，缺的是"真免费 API 当决策层"的**读数**（#80，只有离线 mock 覆盖过）。两次都是同一课：**结论要贴着注册表/源码核，不能贴着我记得的清单** |

**没做的**：git 历史清洗（HEAD 树干净 ≠ 历史干净，那条地址在 `git log -S` 里仍可查到 → #79 剩余部分）；
`-TaskId` 撞出的 id 重复定义（`run_one.ps1` 已经拒绝猜，但两套题集都定义 `r139` → **#81**）；
#80 那轮"非零云端"的免费 API 决策层实测（适配器代码已有；**要把页面文本发到第三方并消耗 key 的配额，这一步我停在动手之前**）。
离线闸门 **32 件 / 277 案全绿**（18:18）。**仍然没有 push。**

---

## [arrival-relook-landed-trigger-narrowed] - 2026-10-13

### Status（#65 的第二半落地并收窄一次；跑链期间自伤一次并复原；#73/#74/#77 三件一并落地）

`m2/real-log.md` 的 10-13 下午三节是全过程。这一条只记**阶段级**变化：

| 变化 | 证据（工件名） | 读数 |
|---|---|---|
| 到站那一拍付**一次有界重看**（等 goal 点名的短语出现在 live DOM，cap 6 000 ms；只降级不升级） | `reports/real-1013-b38-*`、`reports/real-1013-b39-*`、`reports/ci-1013-1544-1013-160343.json` | b38 **72**/100、b39 **70**/100(error=1)、b40 **65**/100（其中 5 行是站点自己的 "Application Error"，16:31 单跑 `rerun-b40-internet-5-*` **5/5 PASS** ⇒ 按环境修正 70，error 归 0）；三批 `false_positive=0` |
| 预登记的射程兑现且**不买步数** | 同上，四行在两批里的 `meta` | `r154/r156/r157/r158` 全部 FAIL→PASS，steps 与 model_calls 与改前**逐行相同**（2 步 / 3 调用） |
| 触发面按实测付费名单收窄 | trace 里的 `arrival_relook_ms` 计数（b39 8 行 31 453 ms → b40 5 行 14 343 ms） | 只有 `goal_reached` 的收口付钱；`link_followed_arrival`（r126/r172/r177）各白花 6 秒的那三行从此不付 |
| 代价第一次变成**仓库权威工件里数得出来的数** | `logger.finalize(state_paid_ms=…)` → task_result 事件 `arrival_relook_ms`；`final_page` 增加 `text_len` + `text_sha16`（只记摘要不记原文，#75）；`evaluator._meta` 的白名单补上这个键，`run_tasks` 把它写进 `meta` | b38 的第一版把代价写在**已经 flush 的 step** 上 ⇒ 批里报出"0 行付费"的**假零**；改记 `state` 累加后才有这张表。第二层同一个形状是单跑打出来的：`reports/one-r154-1013-164417.json`（16:44）里 trace 付了 1 875 ms 而 `meta` 没有这个键 ⇒`_meta()` 只放四件字段，钱被评测器丢掉 ⇒ `logs/`（不入库）里有而 `reports/` 里没有。补白名单 + 一案钉住（`test_graded_input_logged` 5/5，红的那案报的正是 `meta` 里没有键），改后单跑 r154 = `arrival_relook_ms 1328` 已在报告里 |
| 离线闸门与最终 build | `scripts/smoke.ps1` tier1 16:51 + tier2 16:55（`reports/smoke-1013-165332-*`）+ 改后补测 r154 `reports/one-r154-1013-165253.json` 与冻结 `reports/m1-baseline-1013-1656.json` | **31 件 / 271 案全绿**；tier2（含 x001/x002 安全档）两档全绿；**改后补测：r154 的 `meta.arrival_relook_ms = 1328` 进 `reports/*.json`，冻结再跑一轮 19/19、fp=0** |
| 冻结尺子（最终 build） | `reports/m1-baseline-1013-{1546,1552,1558}.json` | **19/19 × 3，fp=0** |

**约束级的一条自我记账**：为了量"收窄前的红数"，我用 `open(p,'w')` 就地读改写，把
`jev_ultrafast/agent.py` 截成 **0 字节**（`'w'` 的截断发生在读之前）。复原走 `git checkout --`
（今天这些改动未提交，但 index == HEAD 还在），四处改动按原样重贴，`git diff --stat` 回到
**92 增 / 2 删**，两个新套件 11/11 与 4/4、tier1 31/270 逐一复跑核过。
规矩补死：**临时回退只准 `git stash`（自有 tag）或反向 Edit，要动整文件先 `cp` 一份。**
**跑链之后没有 push** —— 今天下午这批工件按既有授权边界只入库、不出门。

同一天还落了三件"闸门/发布形态"级的小活：
**#73** smoke tier 2 的取题搬进 `m2/smoke_tasks.py`（钉住 `m1/tasks-laya-19.jsonl`，
一个 id 一份断言，冲突 ⇒ 拒绝出题；改前实测 `picked x001 assertion.type=all_of` 是**文件顺序**决定的）；
**#74** 见证探针 `m2/probe_task_assertions.py` 加 `argparse` + 默认演练 + 自有 Chrome 预检 +
`witness_ok` 的 **unknown 态** + 合并写不降级（改前实测：浏览器缺席时 `main()` 把已证 `true`
刷成 `false` 且返回 0）；
**#77** 上游 MIT 原文逐字归档 `docs/12-upstream-license.md`（ref `1231850a`、sha1 `c5f3915d…`），
夹具里那条第三方邮箱（53 处）脱敏成 `redacted@example.com`，`tests/test_skills.py` 78/78 照旧。
新长出的缺口开成 **#78**：起点页是上游应用的 HTTP 错误页时被记成 `decision / agent`（与 #16 同族换形状）。

---

## [open-source-posture-and-parity-gap] - 2026-10-12

### Status（第一次对着"平替"这把尺子量仓库，而不是只对 L1–L6：开源这件事此前只是元数据）

项目的最终目标是 **JEv + JEv Ultra Fast 的免费开源平替**（全本地、可插拔、零付费）。
之前每次回答"还差多少"，量的都是内部尺子（L1–L6 六格）。这次换成外部尺子，量出两个六格里看不见的洞：

| 洞 | 证据（都是读文件读出来的） | 处置 |
|---|---|---|
| **宣称 MIT，仓里没有 LICENSE 文件** | `pyproject.toml:6` = `license = "MIT"`、README 的 License 节也写 MIT，但 `ls LICENSE*` → 无 | 补 `LICENSE`（MIT，© 2026 chipchipss；署名取自 `git config user.name`，**不编造上游版权行**）；README 改为指向文件，并把"上游派生部分许可未归档"明写成待办 #77 |
| **"近似前者水平"没有当前 build 的对照** | `reports/upstream-vs-ours.json` 时间戳 **2026-09-27 15:59**：旧 decider-2B 底座、4 个任务 | 不改数字、不删历史；README 新增"平替水平的证据口径"一节，规定引它必须带日期与底座差异；对照实验的 **5 条判据跑之前登记**在 `m2/real-log.md`（今晚不跑——要用户先批上游那笔开销，且那份读数必须按"非零云端"隔离） |

**可插拔这一格不用补，是已验收的**：`DECIDER_MODE` 有 typesafe / laya / laya_decider / agentjev，
typesafe 走 OpenAI 兼容 wire，`scripts/text_helper.ps1` 的 groq / deepseek 云端分支必须显式提名且打
`$Cloud` 标记 ⇒ 换免费 API 小模型是配置级改动，代价是那一轮不再算零云端的账。

### 顺带纠一条过期的对外口径

README 的"未结清单"还写着"#16 排在最前"，而 **#16 早在 `80f6a43` 就落地**；同一句把 #65 描述成
"动作发起的请求已结束"这一刀，而它今晚被两次独立读数**判死了前半**，只剩"到站先重观测、比正文长度"。
对外文案里放过期判据，正是这个项目立项要防的那类病（数字与声明对不到产物）。

### 发布前的隐私与密钥自查（第一次做）

- 密钥形态 `sk-…` / `AKIA…` / `ghp_…|github_pat_…` / `BEGIN … PRIVATE KEY`：**0 命中**。
  另有一条 ≥48 位 base64 的松规则报 119 处，逐条看全是 URL 片段、页面指纹 hex、HF snapshot id 的误报
  （误报率也记下来，免得下次被当成结论引）。
- 邮箱形态 423 处 ⇒ 拆开：**370 处是 `a@b.com` 合成数据**（已关闭的 `m4a/` 夹具），
  53 处是 the-internet 公开下载页上**第三方上传的文件名**（`…@gmail.com.pdf`，与 #60 的存储型 XSS 同页）；
  我自己的身份只出现在 `docs/11-repo-checkup-2026-10-12.md:32` 那条公开仓库 URL。⇒ 不阻塞发布，
  但"入库夹具要不要脱敏"留给 #77 决定。
- 一个执行纪律级的发现：计划书写着"23 条自动对账、改文档先跑对账"，**仓里没有这个脚本**
  （`ls scripts m2` 无、`git log --diff-filter=D` 也无被删痕迹 ⇒ 从未存在）。今天改 README 是人工核锚点：
  `reports/upstream-vs-ours.json`、`docs/11-…`、`LICENSE`、commit `80f6a43` 四个引用逐个存在。

### Verification

- 纯发布形态改动：无代码行为变更，未跑批；改文档后**人工核过的引用全部存在**（上段四个锚点）。
- 新文件 `LICENSE`（MIT 标准文本）；`README.md` 三处口径更新；登记见 `m2/real-log.md`。
- 新账：**#76**（平替对照实验，阻塞在用户的开销授权）、**#77**（上游许可归档 / 对账脚本缺失 / 夹具脱敏决定）。

---

## [nightly-3-rounds-landed] - 2026-10-12

### Status（L3 的第二档第一次真跑：3 轮同题集，硬线全过，买到的是"同 build 的行级抖动表"而不是分数）

`#66` 欠的就是这一跑。上一支 `[two-tier-ci-and-same-build-noise]` 写了夜间档的编排，
但它自己留了话："3 轮整夜档仍未跑过，95 min 是由四次观测最坏值推出来的预算，
第一次真跑之后才允许被引成读数。" 现在跑过了：`scripts/ci_local.ps1 -Tier nightly -Rounds 3`
⇒ `reports/ci-1012-1908.json`，`passed=true`，**总墙钟 61.4 min**（预算 95）。

| 轮 | pass | fp | error | 墙钟 | artifact |
|---|---|---|---|---|---|
| 1 | 66 | 0 | 0 | 21.0 | `reports/nightly-1012-1908-r1-1012-190848.json` |
| 2 | 69 | 0 | 0 | 18.6 | `.../nightly-1012-1908-r2-1012-193011.json` |
| 3 | 65 | 0 | 0 | 20.6 | `.../nightly-1012-1908-r3-1012-194910.json` |

每轮的 pass/fp/error 都由报告自己的 `summary` 重数（不只抄 runner 打的行）；零云端由 trace 证：
三轮 step 事件 202/194/206 条，`text_helper` 只出现 `null` 与 `startlux-decision-2b`。

### 这次跑买到的东西：5 行反复翻，95 行三轮不动

同一 build（`jev_ultrafast/*` 自 `821bc43` 未改）、同一份 `m2/tasks_real_100.jsonl`：

- **95/100 行三轮不变**（64 行恒 PASS、31 行恒 FAIL），**5 行至少翻一次**；
- 配对：r1→r2 `GAIN=[r129,r187,r193] LOST=∅`、r2→r3 `GAIN=∅ LOST=[r119,r127,r129,r187]`、r1→r3 净 −1；
- 5 行的身份干净：**两行是环境**（`r127`/`r129` 在 PASS 与 `blocked_by_egress` 之间来回，两边都是 1 步），
  **三行是决策族**（`r119`/`r187`/`r193`）。⇒ "±1 法则不适用"的具体形状不是每行都抖，
  是**一小撮行反复抖**；分数在 ±4 之间来回，而行级只有 5 行。
  若没有 #16 的环境标签，`r127`/`r129` 会被记成 agent 的 `decision`——这批正好证明那条分类刀的价值。

### Corrected（我自己的预登记被读数打掉一条）

预登记写"每轮 59–68"，实际 **r2=69**，超出我登记的上界。由产物重数：`total=100` 的 10 份报告里
**可引的是 9 次**（`b30` 那份 pass=6 是出口闸门下的 blocked 批，按规矩永不引作读数）：
`59 / 61 / 68 / 65 / 65 / 64 / 66 / 69 / 65` ⇒ **min 59、max 69、跨度 10**。
错因是把"已观测极值"当成分布边界。同批预测里"第三轮因 RAM 变慢"**没有发生**（r1 才是最慢的一轮），
我不把它改成事后解释。

**阈值不动**：`MinPassPerRound=59` 保持。今晚三轮都在 65 以上，但把线抬到 61/65 会判红一个没坏的 build——
b33 的 59 是一次环境 burst 换来的，而环境 burst 今晚还在（r3 有 2 行 egress）。

### Verification

- `reports/ci-1012-1908.json` 无 BOM、机器可读（`Write-JsonNoBom` 那条修复之后第一次真跑）；
- 三轮全部 `fp=0`、`error=0`、每轮墙钟 ≤ 30 min（最坏 21.0）；
- 跑之前判据与预测都在 `m2/real-log.md`（含"预测对了几条、错了哪一条"的逐条对表）；
- 一个记录不改的观测：夜间档轮间只起 Chrome、不复位 `startlux_serve`，这就是 61.4 min 比
  3×20.7 的预算余量大的来源。**下次真跑若出现逐轮变慢，先复位再说话。**

---

## [wire-port-default-8090] - 2026-10-12

### Status（#69 的第三条也是最后一条：冻结 runner 的默认决策线从退役的 :8000 收到现役的 :8090，而且"忘传参数"这条路现在是响的）

上一支 `[runner-lifecycle-convergence-and-b37]` 收了 9 个 runner 的生命周期，普查表里三条要动的
地方落了两条，第三条（`run_baseline_19.ps1:16` 的 `[int]$SvcPort = 8000`）当时没动。这支补完。

**为什么"一个默认端口"值得单独一支**：默认值落在没人听的线上时，脚本**不报错**。
`run_baseline_19.ps1` 不带 `-NoService` 就会自己去起已关闭的 `decider.serve`(:8000)，
把 `TYPESAFE_BASE_URL` 指过去，然后照样跑出一个 `19/19`——答题的是另一个 2B。
"底座唯一"这条 A0 硬线当时是靠调用方记得传 `-SvcPort 8090` 来维持的，而读数对连错模型完全沉默。

- 默认改成 **8090**（和 `scripts/run_one.ps1` / `smoke.ps1` / `ci_local.ps1` / `run_demo.ps1` 一致，
  现役线全仓只剩一个值）；
- 新增**早退守卫**：`param()` 之后、任何副作用之前，`-NoService` 缺失且端口不是 8000 就
  `Write-Host` + `exit 1`。不用脚本里的 `Die`——它的定义在守卫后面，运行时还没绑定；
- 新闸门 `tests/test_wire_port_default.py`（3 案，改前实测 **0/3**，改后 3/3）：活 runner 的默认必须
  相等、退役端口不许以任何默认值形式复活、守卫必须早于第一个 `Get-CimInstance`/`Start-Process`。
  退役线（`m4a/`、`run_m1.ps1`、`run_m4b_collect.ps1`、`run_adapter_m4b.ps1`、
  `run_s004_history_test.ps1`、`m1/run_suite.ps1`）走白名单——它们的病是"这条线关了"，不是"端口写错"。

### Corrected（闸门顺手逮到普查表自己漏的一行）

#69 的普查表把 `run_s004_history_test.ps1` 的端口栏记成"—"，实际 `:39` 就把 `TYPESAFE_BASE_URL`
钉在 :8000。表错了；脚本本身属退役线，不改它，但这条是**对普查的更正**，不是对新改动的描述。

### Verification

- 裸调用 `run_baseline_19.ps1` ⇒ **1 行 FATAL、exit 1、一个新进程都没起**（驻留的 llama/wire 仍是
  18:17 那一套的 PID）。
- **只用新默认**跑整轮冻结：`run_baseline_19.ps1 -NoService` ⇒ `reports/m1-baseline-1012-1858.json`
  **19/19、`error=0`、`fp=0`**，6.1 分钟；跑完 `netstat` 显示 :8000 无 LISTENING、`curl :8000/health`
  返回 000，:8090 回 `startlux-decision-2b`——所以这轮证的确实是"默认 = 现役线"。
  **这支不带 `-SvcPort` 的轮子是默认值的见证件，不是第四个冻结读数**，不进 #69 的判定。
- 离线全套 **27 件 / 244 案全绿**（`scripts/smoke.ps1` tier1 于 19:05:57 实跑，逐件 `n/n passed`
  机器相加；上一轮 18:40 是 26 件 / 241 案）。`run_baseline_19.ps1` 仍纯 ASCII 无 BOM。
- 不受影响的两处已核：`scripts/ci_local.ps1:134` 一直显式传 `-SvcPort`；`.env.example` 里
  "run_baseline_19.ps1 默认起 :8000"那句随本次改动更新。

---

## [runner-lifecycle-convergence-and-b37] - 2026-10-12

### Status（#69 的下半件落地并用 b37 收了口：runner 的浏览器生命周期只剩一份判据，100 行配对批六条判据全过，分数一分没记在它名下）

上一支 `[kill-scope-ownership-and-65-falsified]` 把**杀侧归属**装上了闸门，但自己在末尾写明
"这一支没跑 100 行配对批……要件留给真正收敛生命周期那半件"。这支就是那半件，欠的批也还了。

改的是 9 个根目录/`scripts/` runner 的**生命周期**，`jev_ultrafast/*` 一字未改（`git status` 可核）：

| 收之前 | 收之后 |
|---|---|
| 各 runner 自己抄一遍"哪个浏览器是我们的"（`-like "*chrome-cdp-test*"`） | 全部 `Stop-CdpChrome { Stop-OwnedChrome }` 一行委托 `scripts/chrome_guard.ps1`；判据只有一份，测试第 5 案守这条 |
| `Stop-CdpChrome` 只认 `chrome-cdp-test`，`chrome-jev-profile` 靠手工清 | 按 guard 的清单收，暖画像并入常规收尾（**这是故意变的唯一一处行为**） |
| llama-server 的清理按裸名砍、python 清理含裸 `serve`/`uvicorn` | llama 只认 `*startlux-decision-2b*`；python 只认自己起的命令行签名（闸门从 16 处命中收到 0） |
| `run_demo.ps1` 自己起停浏览器、helper 配置是散变量 | dot-source guard；`$helper.Url/.Model/.Key`，配置漂移有测试第 3 案管 |

**两处故意不收**（`run_one.ps1:86`、`start_owned_chrome.ps1:15`）：它们问的是"我刚起的那个画像起来
没有"，不是"这个浏览器是不是我们的"。合并就等于要求它们用一份**更宽**的清单，反而把 P0 那条
"端口有人应答 ≠ 是我们起的"弄坏。测试第 5 案因此只审**发杀语句附近**的判据，探测侧留窄必须写理由。

### b37 判定（判据跑之前登记在 `m2/real-log.md`）

`reports/real-1012-b37-100-1012-181811.json`，与 b36 只差这一支 runner 收敛，墙钟 18.3 min（每改必跑档 ≤30）：

- 判据 1 `error=0` ✅ ／ 2 `[dbg]` 0 次（`JEV_DEBUG` 不设）✅ ／ 3 `false_positive=0`（硬线）✅
  ／ 5 零云端：190 条 step 事件 `text_helper = {None:188, startlux-decision-2b:2}` ✅
- 判据 4 环境行只记录：egress 2 + bot_wall 1 = 3（b36 = 4，nightly-r1 = 3），"显著减少"的怀疑分支不触发。
- 判据 6 分数不参与：65 vs b36 65 ⇒ **净 0，翻 2 行**。逐行读完 trace 后各自归因：
  `r195` GAIN 是 `text_contains "python"` 喂进半帧正文（动作、URL、标题逐拍与 b36 相同），
  `r178` LOST 是滚动停在第几拍不同 ⇒ 同一个 e6 编号指向了别的链接。两条都属**取帧时机**族（#65），
  和杀侧没有因果路径；**不许记成 #69 的收益**。这两行本来就在翻：CHANGELOG 上一条已记
  r195 今晚翻过两次，nightly 那对同 build 批的 LOST 里就有 r177/r178。

### 量出来的一个仪器洞（记账为 #75，这支不动手）

`text_contains` 的**输入**从不进 trace：`final_page` 只有 url/title，step 事件的 `text` 是 Text Helper
要*输入*的串（#68 误读过同一个字段），`page_fp_before` 是不可逆哈希。⇒ 一行因正文取帧翻动时，
我只能证明"动作与落点相同"，证不到"哪一帧不同"。和 #67 同类：缺的是能区分两种解释的字段。

### Verification（数字都取自产物，非手加）

- 离线全套 **26 件 / 241 案全绿**（`scripts/smoke.ps1` tier1 于 2026-10-12 18:40 实跑，逐件
  `n/n passed` 由机器相加 = 241；**tier1 在仓里不留产物**——`reports/smoke-*.json` 只有 `-Live`
  第二级才写，所以这行的凭据是 runner 输出本身，重跑一条命令即可复现。
  前面两条 2026-10-12 条目里的"240 案"是它们各自 append 时的清点，`test_ps_kill_scope.py` 从 4 案长到 5 案）。
- 同一份 `jev_ultrafast/*` 上三轮 19/19、`error=0`、`fp=0`：`reports/m1-baseline-1012-1713.json`、
  `reports/m1-baseline-69guard-1012-180450.json`、`reports/m1-baseline-69final-1012-181250.json`（后两轮跑在收敛后的 runner 上）。
  "同一份"是可核的：`jev_ultrafast/` 最后一次改动是 16:22 的 `821bc43`（#68），此后该路径工作树干净，
  三支 runner 改的全在 `.ps1`。两轮收尾都是 `cdp-chrome=0 (must be 0), non-cdp chrome left=0`。
- `run_demo.ps1 -Task wikipedia` 在收敛后仍 `status done` / 2 步 / 2.65s：`reports/demo-wikipedia-1012-1809.json`。
- `tests/test_ps_kill_scope.py` **5/5**；第 1/2 案先前对 `git show HEAD` 版本实测会红（16 处裸砍命中），不是空转的闸门。

---


## [two-tier-ci-and-same-build-noise] - 2026-10-12

### Status（约束级：L3 的两档编排真的能跑了，而且阈值有出处；同 build 的行级噪声第一次被量出来）

`scripts/ci_local.ps1` 拆成 `-Tier perchange|nightly`。夜间档不是"再跑大一点的分"，是
**同一份 100 行题集跑 N 轮**（这台机器没有 300 行题集，也不去造 200 道没核过的题当读数），
看的是漂移与下限。阈值全部有出处：

- 五次同题集读数 `b33=59, b34=61, b35=68, b36=65, nightly-r1=64` ⇒ **每轮下限 = 59 = 观测最小值**。
  高于它会判红一个没坏的 build（b33 就是 59），低于它这条线形同虚设。
- 单轮墙钟 30 min = L3 口径本身（观测最坏 20.7）；整夜 95 min = 3 × 20.7 + 复位余量。
  预算不是判据：单轮超时只记读数，"跑不完"由 blocked 语义（没写报告 = exit 3）兜。

**白送的一条标定**：nightly-r1 与 b36 之间 `jev_ultrafast/` 一字未改（中间那支只动 runner 清理），
所以它是一对**同 build 配对批**：分数 65 → 64（−1），行级却 GAIN=`[r195]` / LOST=`[r177, r178]`。
⇒ **没改决策的两次跑之间也会翻三行**。以后任何改动如果只换来 1–3 行 GAIN，必须按这一对归因，
不许算收益。（`r195` 自己今晚就翻了两次：b35 PASS → b36 FAIL → nightly PASS，而它正是 #65 的早读行。）

### Corrected（我自己在这支里造的三个工具性错误，都由现成的闸门或见证抓回）

1. **PowerShell 变量名大小写不敏感**：局部 `$rounds = @()` 撞上参数 `[int]$Rounds`，
   报"Object[] 转不成 Int32"。现在注释里钉着这条。
2. **`Set-Content -Encoding UTF8` 写 BOM**，而我新写的裁决 `reports/ci-*.json` 是要被机器读的——
   第一份 nightly 产物用 `json.load(..., encoding='utf-8')` 直接炸。记忆里第 8 条的老坑
   （当年坑题集加载）这次轮到我自己。改成 `Write-JsonNoBom`，两处写裁决都换；
   用 `-Rounds 0` 走了一遍写文件路径做见证（`reports/ci-1012-1756.json`，`BOM? False`）——
   **那份是管线见证件，不是读数，不许引它的 0**。
3. **`nohup … &` 起的长跑批会被这个 shell 收掉**：前两次 nightly 各跑到一半静默消失，
   我先怀疑批、再怀疑出口闸门，最后才看清父进程。第三次改用受管后台任务才跑到出报告。

### Verification

- 离线全套 **26 件 / 240 案全绿**；`ci_local.ps1` `PARSE OK` 且纯 ASCII（新增的
  `tests/test_ps_kill_scope.py` 第 4 案会盯编码）。
- nightly 1 轮实跑：`pass=64 fp=0 error=0 wall=19.7 min`，`total=20.1 min`，`passed=True`，
  阈值与逐轮读数一起落进 `reports/ci-1012-1731.json`。
- **3 轮整夜档仍未跑过**：95 min 是由四次观测最坏值推出来的预算，第一次真跑之后才允许被引成读数。

---

## [kill-scope-ownership-and-65-falsified] - 2026-10-12

### Status（约束级：杀侧硬线补到剩下三种形状；#65 的第一刀被自己的读数否掉）

1. **"硬线必须在真正发出杀动作的那一层生效"从今天起有仪器**。此前 `Stop-Process` 在批路径上有 16 处，
   其中三形状完全没有归属判据：按进程名直连砍 llama-server（`startlux_serve.ps1`、`run_demo.ps1`）、
   **一点判据都没有的 Chrome 全清**（`test_n001.ps1` 两处——那一刀会关掉你自己的浏览器）、
   以及按**库名/裸词**砍 python（`browser_harness` / `serve` / `uvicorn`，匹配一切 import 过它的进程
   和一切 server）。现在分别收到脚本名与模块身份上，并由 `tests/test_ps_kill_scope.py`（4 案）钉住。
   负例见证用同一份仪器跑 `git show HEAD:<文件>`：**改前 16 → 改后 0**。
2. **新规矩（写进仪器，不写进注释）**：`Get-Process … | Stop-Process` 这种直连管道只看自己那条管道，
   别处再近的 `CommandLine` 都不算证据；`-Id $x` 才允许同语句上文的过滤条件作证据，
   且窗口先剔掉 `Log`/注释行——**打印出来的判据不叫判据**（第一版仪器就是被
   `run_demo.ps1` 里那句打印给用户的"手工清理建议"骗过，把唯一真正的裸杀判成了有据）。
   裸词判据只审发杀语句附近：`serve|uvicorn` 同时出现在 Step 2 的**探测**里，那条不砍进程，
   把它一起骂会让整条规则失去可信度。
3. **daemon 仍按模块名杀**——这不是完整归属证明（共享基础设施）。完整解法是 runner 落 pidfile、
   只杀自己写下的 PID，留在 #69 下半场。

### Corrected（一支我自己想做成的"修复"，被实测判死）

#65 原本写着"settle 只等 DOM 归静，覆盖不到动作发起的请求"。带刀实现之后（失败测试 2/5→6/6、
离线全套、单任务 r154），**它没修好靶子，而且前提本身是错的**，三组实测：

- 带刀的 r154 仍 FAIL，且 `JEV_DEBUG=1` 下 `[dbg]` **0 次** ⇒ 那条"上下文被炸掉 ⇒ 重跑"的路径
  根本没触发；trace 相对 b35 的变化来自站点当时回得快，**不是这一刀**（不许记假账）。
- 零模型复现产品 `act()`：提交后 +781ms 就已有 9706 字符但**不含目标词**，
  `+1.2/1.6/2.0/2.4/2.8/3.2/3.6s` 一直是 9706，**+4.0s** 才跳到 1454 并含词。
- 终点页资源时间戳：`searchindex.js` 是 **`<script>`**（+198→870ms），正文由之后的 fetch 取
  （+2180ms、+2359ms）。⇒ 脚本波与正文波之间有 **1.3 秒真正的平静**，
  期间 DOM 静默 / 在途 fetch=0 / 无 transition **三条页内判据同时为真**。

结论写死：**"页内归静 + readyState"在数学上不可能等到这批结果**；早读不是"等得不够久"，
是"读到一段合法的平静就宣布结束"。改动已回滚（现场在 `m2/pending_65_settle_rerun.patch` 与
`m2/probe_navigation_timing.py`），下一刀必须来自 **CDP Network 层**的请求收支表，
并且要再带一条"落点页 near-empty 时不许定案"的判据，否则只是把早读从 0.8s 推到 1.0s。

### Verification

- 离线全套 **26 件 / 240 案全绿**；`scripts/check_all_syntax.ps1` 全部 `syntax OK`
  （中途我自己在 `run_baseline_19.ps1:209` 拼丢过一个闭合引号，是这道闸门抓的）。
- `run_demo.ps1 -Task wikipedia` 实跑 `status done` / 2 步 / 2.67s，收尾 `cdp-chrome=0`
  ——顺带把 #71 欠的"m4a 归档之后 demo 还能不能跑"还上。
- `run_baseline_19.ps1 -NoService -SvcPort 8090` 实跑一轮 **19/19、error=0**，
  收尾 `own-cdp-chrome=0, foreign browsers left=12 (never targeted)`。
- 这一支**没跑 100 行配对批**并在此说明理由：动的全是 runner 清理与过滤，`jev_ultrafast/*` 一字未改，
  "读数没变"不在其射程内；配对批的要件留给真正收敛生命周期那半件。

---

## [diagnostics-channel-and-gates] - 2026-10-12

### Status（约束级：诊断仪器补齐，并且两道闸门被证明曾经不可信）

这一支不涨分，它买的是"下一次诊断不用再猜"。四件事（#67 / #16 / #72 / #68）合起来把
"日志里看得见什么""环境失败归谁""静默降级要不要留痕""离线闸门是否真跑完"这四条定了下来。

### Added（约束级）

- **step 事件必须带到达判据在读的四个字段**：`outcome` / `url_from` / `page_fp_before` / `skill`
  （#67）。以前白名单只留 17 个键，把这三件丢在了日志外，于是"这一拍到底动了什么"只能重开浏览器复探。
  约束由 `tests/test_logger_step_fields.py` 的第 2 案守住：**白名单与 agent 写入点的差集必须恰好等于
  显式的 `STEP_DROP_KEYS`**——将来 history 再加字段，不写进丢弃清单就当场红，不会再静默漏。
- **新的系统类失败模式 `blocked_by_egress`**（#16）：起点落在 `chrome-error://` / `about:neterror`
  的行不再记成 agent 决策失败。负向题豁免（`category=="negative"` 不适用），因为它们**本来就该**进不来。
- **`JEV_DEBUG` 留痕通道**（#68）：`logger.dbg(site, detail)` 只在环境变量非空时往 stderr 写一行。
  八个点接上：`skills.route()` 的技能异常（吞成 `d = None` 的那处，#59 整轮误诊的形状）+
  browser 的六处安装/自愈降级 + `FRESH_MISMATCH` 诊断块。`browser.py` 的裸 `print` 现在 **0 处**。
  边界写死：**不动控制流、默认零输出、不改日志与报告格式**——`tests/test_debug_channel.py` 第 4 案
  逐块断言装了 `dbg` 的 except 分支里没有 `raise` 语句。
- 新落 `tests/test_logger_smoke.py`（`logger.py` 里那 270 行 `_smoke()` 夹具的家；旧位置**没有任何调用方**，
  50 项检查挂在没人执行的 `__main__` 上）、`tests/test_run_demo_helper_wiring.py`、
  `tests/test_debug_channel.py`、`tests/test_evaluator_egress_class.py`。

### Corrected（两处"我们以为已经成立"的话，实测不成立）

1. **`scripts/smoke.ps1` 的离线 tier1 会中途死掉，而且死得很安静。** 它跑在
   `$ErrorActionPreference="Stop"` 下，而 `2>&1` 把子进程每一行 stderr 变成终止错误——
   `test_runner_egress_gate.py` 恰好把它要验的那句 `[preflight] 出口不通` 打在 stderr 上，
   于是今晚那次只报出前 **15** 个套件就断了。口径要说清：自 `aae2754`（10-11 晚，出口预检落地的同一提交）
   起这条闸门就是坏的；此前 CHANGELOG 里的"离线全套 N 案"出自**逐文件计数**，两者不是一回事，
   那些数字本身不因此作废，但"smoke 全绿"这句话在那之后不能按字面读。
   修法：套件期间把 EAP 降回 `Continue`，裁决行从整段输出里挑最后一处 `k/n passed`，
   挑不到=FAIL（崩溃也算）。修后 **25 件 / 236 案**跑完。
2. **`run_demo.ps1` 的 Text Helper 注入是三个从未赋值的变量名**（体检报告"待核"那条点验为真）：
   Step 0 用 `Resolve-TextHelper` 得到 `$helper` 表并写进 `$env:`，Step 3 却写
   `$helperUrl/$helperModel/$helperKey`。PowerShell 未定义变量=$null，而 `Set-Item env:X -Value $null`
   是**删除**——demo 实际跑在"没有 helper"的形状上，看着正常。失败测试 `1/3 → 3/3`，
   并用 PowerShell 自己的 AST 独立复核过该文件的未定义引用。

### Verification（验证链，全部对得上产物）

- 失败测试先行，四条各测一次改前红：`test_logger_step_fields` **0/2 → 2/2**、
  `test_evaluator_egress_class` **2/4 → 4/4**、`test_debug_channel` **0/4 → 4/4**（HEAD 的三份
  生产文件重跑修好的仪器）、`test_run_demo_helper_wiring` **1/3 → 3/3**。
- `#16` 的归属核对是配对批做的，不是推理：b34 对 b33 **92/92 行同结果**（象限零漂移），
  x001 的豁免在实盘里成立。
- `#68` 的实盘见证：零模型把 `SKILLS` 换成一个必抛的探针技能，`JEV_DEBUG=1` 下
  `route()` 打印一行 `[dbg] skill_raised: ...` 且**照旧返回 `None`**。
- 冻结与批次：#68 这一支 **19/19 / 19/19 / [17/19 判废：n003 起点 `chrome-error`、t001 站点 502] / 19/19**
  （`reports/m1-baseline-68r1..r4-*.json`），活体 5 行 `s005 n004 x001 x002 r142` **5/5、fp=0**
  （`reports/smoke-1012-153040-1012-153049.json`）；b36 **65/100、error=0、fp=0、`[dbg]` 0 次、
  零云端 ⊆ {null, 本地}、墙钟 18.1 min**（`reports/real-1012-b36-100-1012-155239.json`）。
- **真实站 100 行的噪声带是量出来的，不是沿用来的**：同题集三连 b33/b34/b35 = **59 / 61 / 68**（跨度 9），
  所以 19 题时代的 ±1 法则**不迁移**；#66 夜间档的 `-MinPass` 阈值必须有 ≥3 次同题集读数才能写数字。
  b36 的 -3 逐行归因（r129 环境；r187/r195 用产品评测器复探终点页 **PASS**、text 3954/2190 字符 ⇒
  批里那次 DONE 的快照早于页面归静，属 #65 那一族），因此 b36 的结论只能是
  "观测层改动没有代价"，**不许**写成收益。

---


## [L2-L3-real-web-and-regression] - 2026-10-11

### Status（阶段级：真实站达标 + 100 行回归体系成立，并补了一条"批形状必须唯一"的硬约束）

**L2 达标**：真实站 50 题拿到 **45/50** 的干净读数（`reports/real-1011-b24-ipc58-1011-015958.json`：`error/crash/unknown=0`、`fp=0`、零云端、与 b20 配对 `LOST=∅`）。
**L3 达标**：100 行回归集 `m2/tasks_real_100.jsonl` + 两级闸门（`scripts/smoke.ps1`、`scripts/ci_local.ps1`）+ 断言拆分（`--expect-url/--expect-title/--expect-text`，判据改调产品评测器），100 题墙钟 **20.7 分钟**（`reports/real-1011-b33-100-1011-231042.json`，1.96 拍每行、`error=0`、`fp=0`、零云端）。50 题批的墙钟被"任务间先问健康再付复位"从 27.8 压到 **8.2/8.7/9.5 分钟**（b27/b28/b29）。

### Rejected（不是没做，是被自己的读数判死）

**并行 runner 不做**：`m2/probe_wire_parallel.py`（走产品原路 `model.choose_typesafe`）并发 1/2/4 的中位延迟 0.64/1.20/2.46 s、吞吐 1.55/1.57/1.58 决策/秒 ⇒ **加速比 1.02x**。`llama-server --parallel 4` 的槽位不变成吞吐，多开自有 profile 的 worker 只会在同一个共享后端前排队。结论写进 `docs/00-project-plan.md` 的 L3 格：**300 题需要的是更快的决策后端，不是并行的 runner**。瓶颈在 shim 的 HTTP 层还是后端本身**未量到**（对照探针直连 :8081 `/completion` 全 400），按纪律记为未量、不猜。

### Added（约束级）

- **一批只许一个浏览器、一条出口**。`_reset_cdp` 之前重起的是 headed 的另一画像且不带 `--proxy-server`，于是"门控真付过一次复位"的批里第 1 题走代理、后面的题直连——出口 IP 与渲染器一起换，站点反爬跟着换，而这与 agent 的决策无关。**读 b18–b26 的历史读数必须带这条注意事项**；b27（0 次真复位）与 b33 起是单形状。
- **题号是读数的地址**：`scripts/run_one.ps1 -TaskId` 遇到多文件重号改为**拒绝启动**（先前 `Select-Object -First 1` 会静默量另一道题并且照样打印 PASS）；新 50 行改号 r153–r202，生成器带全仓唯一性断言。
- **出口预检的取样规则**：负向题的起点（`example.invalid`）设计上就打不开，闸门取样必须跳过 `category=negative`——先前它把 x001 读成"环境阻断"，制造了一份 18/18 的假冻结轮。
- **`m2/real-log.md` 新增 b33 的七条判据对表**：低分按归责拆到具体那一方（环境 `chrome-error` 6+2 行、n004 早读族 4 行、我自己的 arXiv 断言太窄 2 行、题面太死 2 行、真决策缺口 18 行），**没有为了让新题过线而放宽任何断言**。

### Correction（同一条目写完之后的自我更正，2026-10-12 凌晨）

上面"Rejected"里我写的结论**后半句是错的**，在此更正：并行被 1.02x 判死那半句仍然成立，但
**"300 题需要的是更快的决策后端"没有量过拆分就写了**。拆完之后（数据源：b33 的 `logs/` 逐拍 `latency_ms`
与逐步 `executed_ms`，加两次零模型直测）：每行 12.4 秒墙钟里 **决策 0.48 秒**、动作执行 5.81 秒、
起点会话建立 2–5 秒（`Browser(url)` 直测 2.14/4.84/5.07 s）、任务间健康探测 2.35 秒/断点（×99 ≈ 3.9 分钟）。
⇒ 后端无限快只把 300 行从 62 分钟降到 60 分钟。**L3 的验收口径因此拆成两档**：每改必跑 = 100 行 ≤30 分钟（实测 20.7）；
300 行 = 夜间档（预算 ≈62 分钟）。同一批里顺手修正了题集的一处真错：arXiv 两行的结果页 URL 断言写窄了，
改成 `arxiv\.org/search/[^\s]*\?query=` 之后由见证器 + 产品评测器复验（agent 当年到的页面确实写着
`Showing 1–50 of 810 results`），URL 形状核对 7/7 正确、四个负例仍然拒收。**b33 的 59/100 不改**——
那是改前题集上的读数；b34 才是改后题集的第一个读数。

### Verification（验证链，全部对得上产物）

失败测试先行：`tests/test_runner_reset_policy.py` 6/7 → **7/7**、`tests/test_runner_egress_gate.py` 4/6 → **6/6**（两案都在改前实测失败）；离线全套 **20 件 / 207 案全绿**；实盘见证：真实复位 8.9 s 后 `:9222` 的浏览器带 `--headless=new --user-data-dir=C:\chrome-cdp-test --proxy-server=…:2080`；`-TaskId r152` 打印 `defined in 2 files -- refusing to guess` 并退出 2；**前置冻结 19/19×3**（`m1-baseline-1011-2251/2258/2304.json`，每轮 x001 6 秒真跑）。作废件一并留档且不引用其分数：`m1-baseline-1011-2235.json`（18/18，闸门误判负向题）、`one-r152-1011-222908.json`（重号导致量错题）。

---


## [fix-c-rejected-done-exit] - 2026-10-07

### Status（实测，真实站批次 1 的第三个修复：C 类拒绝循环有了出路）

**C 类的根因是一个句点**。`goal_reached` 早已有"搜索词回声不算到达"的判据
（缺陷#40），但它的 `_second_hop`（goal 明写"搜完再打开某物"）用 `[^.;]*` 划句子范围，
而 r106 的第二跳目标名叫 `ggml-org/llama.cpp`：正则走到名字里的句点就断，第二跳没被
认出来，结果页（标题同样回声 "llama.cpp"）被判已到达 → 连发 7× DONE，全被
`_done_guard` 拒掉。句子范围改用新增的 `_HOP_SPAN = (?:[^.;]|\.(?=\S))*`
（句点后不接空格属于名字，接空格仍是句子边界）。

**并且拒绝要产生后果**：DoneGuard 站点原先只 `raise StalePage`，而确定性技能不会换
主意——下一拍同一指纹上 `route()` 重导出同一个 DONE，循环只能撞满 loop detection 变
blocked。现在**技能来源**的 DONE 被拒时送进既有的有界停用通道
（`skills.note_no_effect`，同指纹上让位模型 2 拍后自动放回；有界性是 8 个任务的教训，
没改成永久），模型来源的 DONE 被拒不剥夺任何技能。判定口径一点没动：该拒的照拒。

验证链全绿：单测 55/55（skills，新增第二跳句点与停用出路两例）+ 8/8（rotation）+
6/6（settle）；r106 单任务三次同形读数——被拒 DONE 从 7 次归零、模型 9 拍降到 4 拍
（`real-1007-fixc-r106.json`、`-r106b.json`、`-r106c.json`）；x001/x002 安全复测 2/2 PASS
（`x-check-fixc-1007-190744.json`）；**冻结三轮 19/19、19/19、19/19，false_positive=0、
api_calls=0、error=0**（`m1-baseline-1007-1910/1914/1919.json`）。C 类在 19 题测试集上
从未出现（那里发 DONE 的路径都被放行），所以"出路"没有关掉任何合法收口这件事，
只有三轮全绿才算证明。

**r106 没因此变 PASS，它换到了新类 F**：三次都在 `CLICK target 8` 上报
`FRESH_MISMATCH`（`page_key` 相等、`guard` 不等且 `current_guard=None`）——文档身份没变
但节点句柄在 observe→act 窗口里被 React 结果列表换掉了。E 是初始观测竞态，F 是点击目标
在两次观察之间失效，处理形状是"新鲜度失败后带同一意图重选"，先等第二个真实站样本再动。

**基建纠偏**：`run_one.ps1 -TaskId` 用 PS 5.1 的 `Set-Content -Encoding UTF8` 落单任务
文件，必带 BOM，而 `m1`/`m2` 的 `_load_tasks()` 用 `utf-8` 读 → 单任务模式直接
`invalid JSON: Unexpected UTF-8 BOM`。读取侧改 `utf-8-sig`（无 BOM 文件行为不变）。

---

## [chrome-kill-scope] - 2026-10-07

### Status（实测，硬线纠偏）

**A0 硬线"绝不动用户自己的 Chrome"此前只在脚本层成立**：`m1/run_tasks.py::_reset_cdp()`
每个任务之间执行 `taskkill /F /IM chrome.exe`，按镜像名收割整台机器的 Chrome，
`run_baseline_19.ps1`/`run_demo.ps1`/`run_task.py`/`mcp_server.py` 的 `chrome-cdp-test`
画像守卫全部被这条 Python 绕过。上一节 [fix-b-floor-executable] 里"runner 不再误杀
用户浏览器"的结论因此只对脚本层成立，实测被证伪（decoy 画像 Chrome 跑完一批后归零）。

改为只杀工具自己拥有的两个画像（`chrome-jev-profile`、`chrome-cdp-test`），两条对照
实验：decoy 画像（`chrome-decoy-sim`）8 进程在 `_reset_cdp()` 后存活；第三个画像
（`chrome-fake-user`）11 进程在同一条 kill 命令后存活——排除 kill 语句本身泄漏。
`scripts/run_one.ps1` 的 2 处全量 Chrome kill 同样收进同一守卫，并加了批量模式
（`-TasksFile`/`-Tag`）与收尾 verify 行。

**顺带记账的测量口径（未改，改了等于换测量底座）**：`_reset_cdp` 起的是 headed
Chrome、画像 `chrome-jev-profile`、且从不删目录。因此每轮只有第 1 题跑在 PS 起的
headless `chrome-cdp-test` 上，第 2 题起就换成 headed `chrome-jev-profile`；而
`run_baseline_19.ps1` 冷启动删的是后者用不到的 `chrome-cdp-test`——所谓"冷/热画像"
在冻结轮里其实是热/热。批次 2 收口这一口径后，历史基线数字要重跑作废。

---

## [fix-d-submit-vocab] - 2026-10-07

### Status（实测，真实站批次 1 的第二个修复）

**提交词表双语化**：`search_submit` 只认英文 label（`{search, go, submit, send}`），
而 **站点界面语言跟出口 IP 走**——OSM 在这台机器上把提交按钮渲染成"提交"，于是技能
判定"页面无提交控件"并让位模型，真实站 r109 填完查询后 6× DONE 被拒到耗尽预算。
`SUBMIT_WORDS`（`form_submit`/`confirm_then_done` 共用）与 `search_submit` 的三处
英文集合补入中文提交词，`search_submit` 改用独立的 `_SEARCH_SUBMIT_WORDS`（只收搜索类）。

验证链全绿：单测 52/52（skills）+ 8/8（rotation）+ 6/6（settle，新增中文界面提交用例）；
r109 冷 profile 单任务 2 步真提交（`real-1007-fixd-r109b.json`）；x001/x002 安全复测
2/2 PASS（`x-check-fixd.json`）；**冻结三轮 19/19、18/19、19/19，false_positive=0、
api_calls=0**（`m1-baseline-1007-1809/1814/1819.json`；第 2 轮 n004 丢在模型结果页
选择抖，技能链正确，象限 `correct_abandon`，属 ±1 容差）。

**测试集口径教训**：同一本地化陷阱也咬了断言——`text_contains "Zurich"` 在本地化页面
渲染成"蘇黎世"，任务在代码修好后仍 FAIL。真实站断言一律锚 URL（`m2/tasks_real.jsonl`
的 r109 已改为 `search\?query=Zurich`），不锚页面英文字面量。

**分类修正**：批次 1 的 r103（stackoverflow）按实况改判为 A 反爬墙（当日实测是
Cloudflare 质询页，4 个 action），不是 D；A 类占比在真实站已升到 3/10，墙页检测
（`blocked_by_bot_wall` 独立失败类）排进下一批。

---

## [fix-b-floor-executable] - 2026-10-07

### Status（实测，真实站批次 1 的第一个修复）

**地板空转清零**：`first_action_floor` 现在只发**可执行**动作——CLICK 永远可执行，
TYPE_TEXT 必须能从 goal 确定性派生出文本（`_goal_query()`，从 `search_type` 抽出复用），
SELECT 需要值语义因此 floor 不发；一个都没有就返回 None 让位模型。修复前 floor 会发
无 text 的 TYPE_TEXT / 无 value 的 SELECT，执行层跳过 → history 恒空 → 去重失效 →
同指纹无限重复（真实站 r102/r105 实测 steps=0、model_calls=5）。

验证链全绿：单测 51/51（skills）+ 8/8（rotation）+ 6/6（settle）；r102/r105 复跑不再
空转（r102 7 步真到 arXiv 检索结果页），象限诚实降为 `correct_abandon`（`real-1007-fixb.json`）；
x001/x002 安全复测 2/2 PASS（`x-check-fixb.json`）；**冻结三轮 19/19 × 3、false_positive=0、
api_calls=0**（`m1-baseline-1007-1737/1741/1747.json`）。

**runner 不再误杀用户浏览器**：`run_baseline_19.ps1` 的三处全量 Chrome kill 与 verify
改成只认 `chrome-cdp-test` 命令行（与 run_demo/run_task/mcp_server 同一守卫），并用
decoy profile 做了对照实验（守卫杀掉 CDP 侧 10 个进程、decoy 存活）。运维注意：每轮之间
要重启决策栈，llama-server 工作集单轮后涨到 ~4GB，会顶掉 runner 的 3000MB 内存门。

---

## [l6-one-command] - 2026-10-07

### Status（实测，Flights 端到端，StartLux-Decision-2B）

**L6 达成：`.\run_demo.ps1` 一条命令冷栈全绿**。四次实测 7/7 校验全过、exit 0：
热复用 12.37s（`demo-flights-1007-1617`）、冷自启 12.99s（`-1620`，栈从停机到
wire ready 24s）、`-KeepService` 13.95s（`-1622`）、复用后外部栈存活 12.87s
（`-1623`，跑完 wire :8090 仍 200）。`text_helper` 全程未触发（11 条 history 全
`None`），api_calls=0 硬线保持。

**run_demo.ps1 迁底座**：旧版写死 decider-2B uvicorn :8000；现检测 :8090 wire，
在线复用、停机则 detached 拉起 `scripts\startlux_serve.ps1`（900s 健康闸门，
覆盖首启下载耗时）；`-KeepService` 控制栈去留；清理只杀自己拉起的 llama/wire，
python 侧只杀 `run_flights|browser_harness`。

**自动供给**（startlux_serve.ps1，冷机器 bootstrap）：缺 `llama-server.exe` →
GitHub Releases 拉 b11433 CUDA 12.4 zip 解压；缺 cublas DLL → 拉
`cudart-llama-bin-win-cuda-12.4-x64.zip`；缺 GGUF → `huggingface_hub.snapshot_download`
拉 `startlux-models/StartLux-Decision-2B-Q8_0-GGUF`（含 `startlux_decision` 包）。
代理优先（`-ProxyUrl`，默认 :2080）、直连兜底；`-SkipEnsure` 跳过。实测删掉
llama-server.exe 后 serve 自愈重装并 healthy 起栈（build 11433 一致）。
**踩坑记录**：供给段最初排在"清理旧实例"之前，运行中的 llama 锁着 ggml DLL，
Copy-Item 直接 IOException——顺序改为先杀进程再供给。

**Chrome 误杀修复**（run_demo）：旧版 `Stop-Process` 杀**所有** chrome（含用户
自己的浏览器，此前已向用户承认的已知缺陷）；现只按命令行 `chrome-cdp-test` 画像
清理（`Get-CdpChrome`），verify 计数也只数 CDP 进程，用户浏览器永不入靶。

---

## [settle-detection] - 2026-10-07

### Status（实测，19 任务集，StartLux-Decision-2B）

**L4 钉死：19/19 × 3 轮全满分，fp=0，`api_calls=0`**（冻结码
`m1-baseline-1007-1552/1557/1601`，各 3.9–4.1 分钟）。n004 三轮首拍全部落在完整
页态（指纹 4e60613d），`search_type` 技能 4 步直取。

**n004 根因改判**（比计划书 2.1 的"SPA 结果页早读"更靠前）：病在**初始拍**——冷
profile（runner 每轮删 profile 重启 Chrome）下 RFC 首页 readyState=complete 时
异步 bundle 还没挂载头部控件，23 元素残缺页 → 模型 BLOCKED 0.77（合理判断）→
`first_action_floor` 按 goal 词重叠选 "Subscribe to new RFCs" 走死路。三个冻结轮
首决策**逐字节同指纹**复现：确定性 bug，不是模型方差。诊断关键：run_one 不清
profile（热态）单任务 3/3 PASS 与冻结轮 FAIL 并存，差异只剩页态缓存——反常指标
组合先翻日志（法则①）抓到。

**机制**：`Browser.__init__` readyState 后加归静闸门（floor 1200ms——HTML 静止/JS
未到之间存在"假静止"，纯归静判据会被骗过；quiet 250ms；cap 5000ms）；动作后新增
settle detection（`await_action_settle`：DOM 连续归静 + fetch/XHR 在途计数归零 +
无未完成 CSSTransition，click 1500ms / select·fill 800ms 上限，静止页面只付归静
窗口）。`tests/test_settle.py` 6/6 新增；skills 50/50、rotation 8/8 不回归。

**基准成本**：+0.3–0.5 分钟/轮（3.3–3.6 → 3.9–4.1 分钟），距 30 分钟闸门很远。

**runner 修复**（同批）：`-NoService` 收尾不再误杀外部 wire（与 Step 2 守卫对齐）。

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
