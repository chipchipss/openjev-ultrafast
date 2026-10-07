# L2 真实站点使用日志

> 定位:第一层「用起来」的数据 accumulating 地。每个条目 = 一次真实批,数字全部
> 对应 `reports/*.json`(执行纪律⑤)。失败分类只在证据齐了之后下结论(法则①)。

## 批次 1 · 2026-10-07 · 10 任务可行性(`reports/real-1007-a.json`)

任务定义:`m2/tasks_real.jsonl`(r101–r110;选题来自计划书 1.2 候选方向,
goal/expect 遵守 1.2 经验:显式引标题、断言给终点证据)。
底座 StartLux-Decision-2B :8090;Chrome headless+代理 :2080;helper 全程未配置。

**结果:PASS 3 / FAIL 6 / ERROR 1;false_positive=0;崩溃=0;api_calls=0(逐任务 meta)。**

| 任务 | 站 | 判定 | 终态证据 | 失败分类 |
|---|---|---|---|---|
| r107 | news.ycombinator.com | PASS | /newest,1 步 | — |
| r108 | simple.wikipedia.org | PASS | /wiki/Photosynthesis,2 步 | — |
| r110 | doc.rust-lang.org | PASS | ch04-00-understanding-ownership,3 步 | — |
| r101 | pypi.org | FAIL | 搜索已提交(/search/?q=flask)但页面标题 **"Client Challenge"** | **A 反爬墙**(治理正确 BLOCK 0.56) |
| r104 | pubmed.ncbi.nlm.nih.gov | FAIL | term 已提交但页面是 **reCAPTCHA** | **A 反爬墙**(BLOCK 0.60) |
| r102 | arxiv.org | FAIL | steps=0、model_calls=5、全程首页 fp c376f57d | **B 地板空转**(first_action_floor 连发 SELECT e6,动作一次都未执行) |
| r105 | github.com | FAIL | steps=0、3× TYPE_TEXT e12 同指纹 | **B 地板空转**(同上,fill 无可派生文本/不可执行) |
| r106 | huggingface.co | FAIL | 已达 /search/full-text?q=llama.cpp,9× DONE 被拒后耗尽 | **C 过早 DONE 循环**(guard 拦住了假阳性,但不会换路) |
| r109 | openstreetmap.org | FAIL | fill 后停在首页 #map=,6× DONE(0.42) 被拒 | **C + D**(React 搜索框提交语义缺失:fill≠submit) |
| r103 | stackoverflow.com | ERROR | init `StalePage: Document is navigating`(3 次里 2 次复现) | **E init 竞态**(重定向型站点初始观测过期) |

r103 补充:`real-1007-rerun-r103.json` 再次 ERROR(同签名);第三次
`real-1007-rerun2-r103.json` 跑通但 FAIL——search_type 填了框,提交未生效,
模型 4× 重复往同一框 TYPE_TEXT,终态 /questions(Newest)。**E 与 D 并存**。

### 读法(这些数据说什么)

1. **测试集 19/19 ↔ 真实站 3/10**。差距不是模型退化(决策 p50 仍 ~0.8s 量级、
   0 假阳性),而是测试集里没有的四类真实墙:**反爬、地板可执行性、DONE 拒绝后的
   出路、React 控件提交语义**。这正是 L2 要买的单。
2. **治理层首战零失分**:两轮 reCAPTCHA/Client Challenge 全部诚实 BLOCK,
   九次假 DONE 全被拦——fp=0 硬线在真实站上同样成立,这是五家竞品都没考过的卷子。
3. **优先级(由频次×确定性决定,不由猜)**:
   - **B 地板空转**(2/10,确定性、可单测)→ 先修:floor 只许发可执行动作
     (CLICK 优先;TYPE_TEXT 需 goal 有引号文本;SELECT 需值可派生),否则让位模型。
   - **C DONE 拒绝循环**(2/10)→ 同指纹 DONE 被拒 ≥2 次后禁用 DONE,强制探索/BLOCK。
   - **D 提交语义**(2/10:r103/r109)→ search_type 提交后断言 URL/query 变化,
     未变则补 Enter keypress 再补按钮点击。
   - **E init StalePage**(1/3 次)→ Browser.__init__ 归静闸门捕获 StalePage 复观测一次。
   - **A 反爬墙**(2/10)→ 非纯框架可解;先做**墙页检测显式分类**
     (`blocked_by_bot_wall` 判定,和数据里"真失败"分开),策略(真实 profile/降速/
     API 兜底)等这类占比继续升高再投入。

### 复现命令

```powershell
# 栈:scripts\startlux_serve.ps1(:8090)+ headless Chrome CDP 9222 带 --proxy-server
python -m m1.run_tasks --tasks m2/tasks_real.jsonl `
  --log-dir logs/real-1007-a --report reports/real-1007-a.json
```
日志目录 `logs/`(gitignore)含逐任务 decision/step 流,取证按法则①先看它。

---

## 批次 1 的修复 · Fix B（地板空转）· 2026-10-07

### 改了什么（`jev_ultrafast/skills.py`）

根因按法则①从 `logs/real-1007-a` 的逐拍流里翻出来：`first_action_floor` 在模型
BLOCKED 时会挑"显著性+goal 重合"最高的控件发指令，但它不管动作**能不能执行**——
SELECT 发出去没有 value、TYPE_TEXT 发出去没有 text，执行层直接跳过，history 永远
是空，于是 `tried` 去重形同不存在，同一个指纹一拍一拍地重复（r102 连发 SELECT e6、
r105 连发 TYPE_TEXT e12，steps=0 而 model_calls=5）。

修法是让 floor 只发可执行动作：QUERY 派生从 `search_type` 里抽成 `_goal_query()`
复用；floor 按分数从高到低扫候选，CLICK 永远可执行，TYPE_TEXT 只有在 goal 能
确定性派生出文本时才可执行（带上 `text=query`），SELECT 需要值语义、floor 给不出
→ 跳过；一个可执行动作都没有就返回 None，把决策让回模型。

### 验证链（按执行纪律①→③）

| 环节 | 结果 | 证据 |
|---|---|---|
| 单测 | skills 51/51、rotation 8/8、settle 6/6 | `tests/test_skills.py` 新增"只发可执行动作"用例 |
| 单任务（原空转两题） | r102 7 步真跑到 `/search/physics?query=Attention+Is+All+You+Need`；r105 1 步真点击后诚实 BLOCK | `reports/real-1007-fixb.json` |
| 安全复测（纪律③） | x001/x002 2/2 PASS，fp=0 | `reports/x-check-fixb.json` |
| 冻结三轮（纪律②） | **19/19 × 3，false_positive=0，api_calls=0** | `reports/m1-baseline-1007-1737.json` / `-1741` / `-1747` |

三轮逐任务判定完全一致（19 个全 `true_success`），只有步数在 ±1~2 的正常方差内浮动
（n004 3/6/4、f004 6/8/8、t001 10/10/11）。

**注意读数口径**：r102/r105 在 fix 后仍是 FAIL，但象限从"基础设施空转"变成
`correct_abandon`——它们现在是真实的模型能力失败，而不是我们框架在原地打转。
B 类（2/10）到此清零；剩下的 C/D/E/A 才是下一批要买的单。

### 顺带修的基础设施（`run_baseline_19.ps1`）

前两轮跑完后发现：runner 的清理仍是无差别 `Get-Process chrome | Stop-Process`，
每轮都会把用户自己的浏览器一起杀掉——这和"绝不动用户 Chrome"的硬线冲突。三处
kill（`Start-Chrome`、Step 2 残留清理、finally 清理）与 verify 都改成只认
`chrome-cdp-test` 命令行。守卫做过对照实验：另起一个 `chrome-decoy-sim` profile 的
headless Chrome 当"用户的浏览器"，跑守卫后 CDP 侧 10 个进程全灭、decoy 存活。

每轮之间必须重启决策栈：llama-server 工作集会在跑完一轮后从 970MB 涨到 3.8~4.4GB，
把 runner 的 3000MB 内存门顶掉（第 1 轮就是这么死过一次）。

---

## 批次 2 前置 · 基础设施纠偏（Chrome 误杀与画像口径）· 2026-10-07

### 上一节的结论只说对了一半

Fix B 那节写着"runner 不再误杀用户浏览器"，依据是 PowerShell 侧三处 kill 改成了
`chrome-cdp-test` 画像匹配。**这个结论是错的**：真正每天在杀浏览器的是
`m1/run_tasks.py::_reset_cdp()` —— 它在每个任务之间执行
`taskkill /F /IM chrome.exe`，按镜像名无差别收割整台机器的 Chrome，脚本侧的画像守卫
被这条 Python 完全绕过。发现方式：批次 2 前的守卫复测里，decoy 画像的 Chrome 在
一轮真实批之后归零。

修法与证明（同一 `Get-CimInstance` 命令行过滤，画像为 `chrome-jev-profile` +
`chrome-cdp-test`，即工具真正拥有的两个画像）：

| 实验 | 前 | `_reset_cdp()` 后 |
|---|---|---|
| decoy 画像 Chrome（`chrome-decoy-sim`） | 8 进程 | **8 进程存活** |
| 非我方画像（`chrome-fake-user`） | 11 进程 | 同一条 kill 命令后 **11 进程存活** |

第二条是必要的对照：它排除"kill 命令本身泄漏到其他画像"。子进程（renderer/gpu）的
命令行同样带 `--user-data-dir`，画像匹配能把整棵树清干净，不会留孤儿。

### 读所有既有数字都要知道的画像口径

`_reset_cdp()` 起的是 **headed** Chrome（无 `--headless`）、画像
`C:\Users\Administrator\chrome-jev-profile`、且**从不删除该画像目录**。也就是说：

1. 一轮里只有第 1 个任务跑在 PS 脚本起的 headless `chrome-cdp-test` 上，第 2 个任务
   起就换成了 headed `chrome-jev-profile` —— 同轮内两种浏览器，第 1 题和其他题不同底。
2. `run_baseline_19.ps1` 冷启动删的是 `chrome-cdp-test`，而实际干活的是
   `chrome-jev-profile`，它跨轮、跨天累积（登录态、Cookie、HTTP 缓存、Service Worker）。
   所以"冷画像 vs 热画像"那套解释（n004 的两种页面指纹）**对冻结轮其实是热画像 vs
   热画像**，真正的冷/热开关从来没生效过。
3. 窗口是可见的：每次跑批桌面上会真的弹一个 Chrome 在翻页。

这三条先记账，不在批次 2 里顺手改（改了等于换测量底座，历史 19/19 全部要重跑）。
批次 2 的做法是把"哪一轮跑在哪个画像上"写进每份报告的取证段，等 L2 场景稳定后
再一次性收口：要么 `_reset_cdp` 也 headless + 用同一个画像，要么 PS 侧不再自己起
Chrome，二选一，然后重跑三轮基线作废旧数字。


---

## 批次 1 的修复 · Fix D（提交词表只认英文）· 2026-10-07

### 改了什么（`jev_ultrafast/skills.py`）

根因仍按法则①从 `logs/` 逐拍流翻出来。r109 的链条本身是对的：`search_type` 把
"Zurich" 填进了 OSM 的搜索框，接着轮到 `search_submit` 找提交控件——但它的候选
过滤用的是英文闭集 `{search, go, submit, send}`。**OSM 按出口 IP 本地化界面**，
这台机器上按钮 label 是"提交"，于是技能认为"页面没有提交控件"，让位给模型，
模型 6× DONE(0.42) 被 `_done_guard` 拦下（拦得对：确实没提交），然后把预算耗尽。
表单侧同病：`form_submit` / `confirm_then_done` 共用的 `SUBMIT_WORDS` 也只有英文。

修法是把两处词表补成双语（不是加特例）：`SUBMIT_WORDS` 增列
提交/发送/前往/搜索/查找/查询/继续/确定/确认/保存/更新；`search_submit` 单独抽出
`_SEARCH_SUBMIT_WORDS`（它的语义比表单窄，只收搜索类提交词），并把该函数里三处
英文集合（历史"已提交"扫描、候选 label 过滤、`_exact` 判定）统一换成它。分词器
`_tokens` 用 `\w`，本来就能切出 CJK 词，所以缺的只是词表项。

### 验证链（按执行纪律①→③）

| 环节 | 结果 | 证据 |
|---|---|---|
| 单测 | skills **52/52**、rotation 8/8、settle 6/6 | 新增 `t_search_submit_chinese_ui`（中文"提交"按钮要 CLICK，且点过之后不再重复提交） |
| 单任务（r109，冷 profile） | 2 步真提交到 `/search?query=Zurich`；`api_calls=0` | 首轮 `reports/real-1007-fixd-r109.json` FAIL → 断言修好后的 `reports/real-1007-fixd-r109b.json` **PASS true_success** |
| 安全复测（纪律③） | x001/x002 2/2 PASS，fp=0 | `reports/x-check-fixd.json` |
| 冻结三轮（纪律②） | **19/19、18/19、19/19；false_positive=0；api_calls=0**（model_calls 86/88/84） | `reports/m1-baseline-1007-1809.json` / `-1814` / `-1819` |

**单任务那次的 FAIL 不是代码的错，是我出的题**：断言写了
`url_matches openstreetmap\.org/search` + `text_contains "Zurich"`，而本地化页面
渲染的是"蘇黎世, Bezirk Zürich"——同一个本地化陷阱咬了技能又咬了断言。改成锚 URL
（`search\?query=Zurich`，query 参数是站点自己写的，与界面语言无关）后通过。
`m2/tasks_real.jsonl` 的 r109 已换成这个口径。

第 2 轮丢的 n004 不归 Fix D：trace 显示 `search_type` → `search_submit`
（CLICK e15 "Submit search"）全对，落在检索结果页之后模型连点 e10 三次触发循环检测
→ 诚实 BLOCK，象限 `correct_abandon`、fp=0。这条任务在内存里已记为已知模型方差
（冷/热两种页面指纹 + 结果页选择抖），三轮 2/3 属 ±1 容差内，判定为绿。

### 分类修正（批次 1 表里两行改判）

- **r103（stackoverflow）从 D+E 改判 A**：今天实测它给的是 Cloudflare 质询页
  （actions 只有 4 个），而 `Browser()` init 抛的
  `StalePage: Document is navigating` 正是墙页重定向的签名。所以它不是提交语义缺失，
  是反爬墙；init 竞态这一类（原 E）依然存在，只是要换一个非墙的站点复现（Fix E 的单）。
- **r109 的 D 到此清零**；同一行的 C（DONE 被拒后不会换路）仍开着——批次 1 里 r106
  那 9× DONE 被拒才是 C 的原型，属 #10（Fix C）未完。

真实站记分板（批次 1 的 10 题）：Fix B 清了 B 类（r102/r105），Fix D 清了
r109 的提交语义，r103 移入 A 类。剩下待买：A 反爬墙（r101/r104/r103）、
C DONE 出路（r106）、E init 竞态（#12）。

---

## 批次 1 复跑 · Fix B+D 之后 · 2026-10-07（`reports/real-1007-fixbd-1007-183303.json`）

同一套 10 题、同一底座重跑：**PASS 5 / FAIL 5 / ERROR 0，false_positive=0，
api_calls=0**（批次 1 是 3/10，且当时 r103 是 ERROR）。

| 任务 | 站 | 判定 | 终态证据 | 归因 |
|---|---|---|---|---|
| r101 | pypi.org | **PASS**（原 FAIL） | /project/Flask/，11 步 | 批次 1 那天的 "Client Challenge" 墙这次没触发：墙是概率性的 |
| r102 | arxiv.org | FAIL | **/login?next_page=/user/create** | 提交链全对（floor CLICK→search_type→search_submit 三连 1.0），结果页上模型点错进登录页：真·模型选择失败 |
| r103 | stackoverflow | FAIL | /questions，steps=1 | 没墙。`search_type` 填了框，`search_submit` 找不到可点提交控件后让位，模型连发 3× TYPE_TEXT 同一框 → **fill≠submit 缺 Enter 兜底**（新 D2） |
| r104 | pubmed | FAIL | title "…- reCAPTCHA" | A 反爬墙，决策仍诚实 BLOCK（要独立成 `blocked_by_bot_wall`） |
| r105 | github.com | FAIL | homepage，1 步后 BLOCK | floor 点了一发就 BLOCK：诚实放弃 |
| r106 | huggingface.co | FAIL | /search/full-text?q=llama.cpp | 搜索链对，`goal_reached` 技能在**结果页**连发 7× DONE 被 `_done_guard` 规则 2 拒 → **C 类的真身**（见下） |
| r107 | news.ycombinator.com | PASS | /newest，1 步 | — |
| r108 | simple.wikipedia | PASS | /wiki/Photosynthesis，2 步 | — |
| r109 | openstreetmap | **PASS**（原 FAIL） | /search?query=Zurich，2 步 | Fix D 的中文提交按钮，端到端确认 |
| r110 | doc.rust-lang.org | PASS | ch04-00-understanding-ownership，3 步 | — |

### C 类从"不会换路"改判成"技能自己跟自己打转"

批次 1 把 r106/r109 记成"DONE 被拒后不会换路"。复跑证据把因果看清楚了：发 DONE 的
不是模型，是 **`goal_reached` 技能**（trace 里 `skill=goal_reached`、confidence 1.0，
连发 7 次同一指纹），而 `_done_guard` 每次都正确拒绝——实测拒绝原因是规则 2
（`"DONE on search results page with navigation goal"`，用 r106 的 goal+终页直接调
`_done_guard` 复现）。这里不可能是规则 6：规则 6 把"到了没到"的否决权**交给**
`goal_reached`，而这一例正是 `goal_reached` 自己说"到了"。两个组件对同一个页面给出
**确定性相反**的判定，于是谁也不让步：技能每拍都重新提同一个 DONE。

所以 Fix C 的正确形状不是"禁掉 DONE"（那会误伤 f003/t001 这类连发 DONE 最终 PASS 的
合法路径），而是两件事：被拒的**技能来源** DONE 要进既有的技能停用/回退通道（让位
模型 2 拍），以及 `goal_reached` 自己要不再在搜索结果页上宣布到达——它内部本来就有
这条判据（缺陷#40 的 query 回声），只是被一个句点截断了（见下一节）。

## 批次 1 的修复 · Fix C（被拒的技能 DONE 每拍重发自己）· 2026-10-07

### 改了什么（`jev_ultrafast/skills.py`、`jev_ultrafast/agent.py`）

**(b) 根因：`_second_hop` 的句点截断。** `goal_reached` 本来就带了缺陷#40 的
"query 回声不算到达"判据，触发条件里有个 `_second_hop`（goal 明写"搜索之后再打开
某个东西"）。它用 `[^.;]*` 划句内范围，而 r106 的第二跳目标就叫
`ggml-org/llama.cpp`：正则走到 "llama" 后面的句点就断了，第二跳没认出来，于是
结果页（标题同样回声 "llama.cpp"）被当成已到达 → 连发 DONE。现在句子范围换成
`_HOP_SPAN = (?:[^.;]|\.(?=\S))*`——句点后面不接空格才算名字内部字符，接空格仍是
句子边界（新增单测把这条边界钉住：`"Open the docs. Then close the page."` 不许连成一片）。

**(a) 通用出路：拒绝要产生后果。** `agent.py::_pre_execute` 的 DoneGuard 站点原先
只 `raise StalePage`，下一拍同一页态上 `route()` 会重导出同一个技能决策——确定性
组件不会换主意，循环只能撞满 loop detection 变 blocked。现在**技能来源**的 DONE 被拒
时送进既有的有界停用通道 `skills.note_no_effect(fp, skill)`：同一指纹上该技能让位模型
2 拍后自动放回（`_STUCK_TICKS` 的有界性是被 8 个任务的教训教出来的，不许改成永久）。
模型来源的 DONE 被拒不进这个通道（没有技能可剥夺），判定口径一律不动。

### 验证链（按执行纪律①→③）

| 环节 | 读数 | 落盘 |
|---|---|---|
| 单测 | 55/55 skills + 8/8 rotation + 6/6 settle | 本轮新增 2 例（第二跳句点、停用出路） |
| 单任务 r106 ×3 | 被拒 DONE 从 7 次归零（三次 trace 里再无 `DONE … goal_reached`），模型 9 拍→4 拍；三次同形 | `reports/real-1007-fixc-r106.json`、`-r106b.json`、`-r106c.json`（`logs/real-1007-fixc/` 留 jsonl 与 stdout，logs 在 .gitignore 内） |
| x001/x002 安全复测 | 2/2 PASS，象限 `true_success`，fp=0、api_calls=0 | `reports/x-check-fixc-1007-190744.json` |
| 冻结三轮 | **19/19、19/19、19/19**，false_positive=0，api_calls=0，error=0 | `reports/m1-baseline-1007-1910.json`、`-1914.json`、`-1919.json` |

C 类在测试集上从来没有暴露过：19 题里发 DONE 的路径都被 guard 放行，所以"拒绝之后
技能还会重发"这条只在真实站上成立。三轮全绿说明出路没有将任何合法收口一起关掉。

### r106 没有变 PASS：它换到了新类（F · 动态列表句柄失效）

三次单任务读数完全一致（steps 2 / model 4 / `FAIL correct_abandon`），终页仍是
`/search/full-text?q=llama.cpp`。trace 形状：`search_type` 填词 → `search_submit`
点 "Use Full-text search" → 模型提 `CLICK target 8` → act 前 `fresh()` 抛
`FRESH_MISMATCH` → 重观察后模型 BLOCKED。第 3 次的原始输出留在
`logs/real-1007-fixc/run3_r106.out`：

```
FRESH_MISMATCH
  node: 8
  page_key_equal: True
  guard_equal: False
  current_page_key:  [1791372408917.7, 'https://huggingface.co/search/full-text?q=llama.cpp', 0, 0, 1120, 780]
  expected_page_key: [1791372408917.7, 'https://huggingface.co/search/full-text?q=llama.cpp', 0, 0, 1120, 780]
  current_guard: None
```

`current_guard=None` 而 page_key 逐字段相等，意思是文档身份没变但节点句柄在 observe→act
窗口里没了——HF 全文检索结果表是 React 重渲染的列表，行会被换掉。这既不是 C（没有
DONE 循环了）也不是 E（E 是初始观测竞态），记作 **F**：点击目标在两次观察之间失效。
待办形状是"新鲜度失败后带同一意图重选一次"，而不是直接放弃；F 目前是单站点单点，
等第二个真实站样本再动（r106 三次同形只证明它在这页上是确定性的，不证明它普遍）。

### 顺带修的基建：PS 5.1 的 BOM 让单任务模式加载不了

`run_one.ps1 -TaskId` 自己抽单行任务时用 `Set-Content -Encoding UTF8`，在 PS 5.1 下
**必写 BOM**，`m1`/`m2` 的 `_load_tasks()` 用 `encoding="utf-8"` 读，第一行直接
`invalid JSON: Unexpected UTF-8 BOM`。修在读取侧（`utf-8-sig`，无 BOM 的文件行为完全
一样），两个 runner 各一处——任何外部编辑器留下的 BOM 也一并免疫。

## A 类落地：墙检测只做归因，不改判定（`jev_ultrafast/evaluator.py`，commit 0693419）

`is_bot_wall(page)`：标记命中（"just a moment" / "client challenge" / "recaptcha" /
"checking your browser" / "正在检查浏览器" / captcha 字符输入提示）**并且**页面薄
（≤400 字符、≤12 个 action）才算墙。阈值两侧都按当天实测快照留了 3 倍以上余量：
墙页 66/3（pubmed）与 82/6（pypi），对照正常内容页 1416/52（"reCAPTCHA - Wikipedia"
真的是一篇文章的标题）、1351/37、1325/61。词表只收见过的，开发期猜进去的
（captcha-delivery.com、/_flowds_/、"access denied"）已全部删掉。

命中后只把 `failure_class/failure_mode` 换成 `system/blocked_by_bot_wall`；
`result` 仍是 FAIL、象限仍是 `correct_abandon`，pass/fail 口径一点没松，
`false_positive` 被分支条件排除在外——外因永远不能替假阳性开脱。reports 里不落终页
快照，所以这道归因要到下一次真实批才看得见（`summary.system_modes`）。


