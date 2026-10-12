# Changelog

> 本文件记录项目的**阶段级**与**约束级**变更。
> 单文件代码变更由 git log 记录。
> 硬约束变更由 `docs/01-hard-rules.md` 的 A0.3 流程触发本文件追加条目。

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
