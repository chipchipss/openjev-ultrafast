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

### 第一次真实批的读数：`system_modes` 是空的，而且是**对的**

`reports/real-1007-fixc-batch-1007-193028.json`：`summary.system_modes = {}`。
不是检测器失灵——这一轮压根没撞墙。逐条翻 `logs/real-1007-fixc-batch-1007-193028/*.jsonl`
末行的 `final_page`：

| 任务 | 终页 | text 长度 | actions | `is_bot_wall` |
|---|---|---|---|---|
| r103 stackoverflow | `/questions/tagged/google-search-console`（搜对了，没打开问题） | — | — | False |
| r104 pubmed | `/search-results?term=CRISPR+off-target`，标题是真实的 PubMed 检索结果页 | 3241 | 78 | **False** |
| r105 github | 首页，1 步后 BLOCK | — | — | False |

批次 1 那天 r104 的标题是 "…- reCAPTCHA"、66 字符/3 action；这一轮同一题同一 URL 拿到
的是 3241 字符的正文。**A 类墙是概率性的，不是常量**，归因证据只能等多轮真实批自己撞
上来；检测器这轮的实测贡献是"没有把正常内容页误判成墙"（0 误伤），这也正是把
`false_positive` 排除在分支之外的原因。

## 批次 1 复跑 · Fix C 之后 · 2026-10-07（`reports/real-1007-fixc-batch-1007-193028.json`）

同一套 10 题、同一底座：**PASS 5 / FAIL 5（可比口径），false_positive=0，api_calls=0**，
与 Fix B+D 那轮**逐题同形**。Fix C 本来就不改判定，它改的是 r106 的空转形状。

| 任务 | 判定 | steps / model_calls | fixbd 同题 | 读数差 |
|---|---|---|---|---|
| r101 pypi | PASS | 11 / 13 | 11 / 13 | 同 |
| r102 arxiv | FAIL | 5 / 6 | 7 / 12 | 更早放弃 |
| r103 stackoverflow | FAIL | 2 / 5 | 1 / 4 | 同形 |
| r104 pubmed | FAIL | 2 / 3 | 2 / 3 | 同形（这次无墙） |
| r105 github | FAIL | 1 / 2 | 1 / 2 | 同形 |
| r106 huggingface | FAIL | 3 / **4** | 2 / **9** | **C 类消失**，落到 F 类 |
| r107 HN | PASS | 1 / 2 | 1 / 2 | 同 |
| r108 simple.wikipedia | PASS | 2 / 3 | 2 / 3 | 同 |
| r109 openstreetmap | PASS | 2 / 3 | 2 / 3 | 同 |
| r110 rust-doc | 作废 → 单测 PASS | 2 / 3 | 3 / 4 | 见下方事故记录 |

### r110 的 ERROR 是我造成的，不是代理的失败

报告落盘 19:37:20，我在它前几秒执行了一次"清理上一轮遗留画像 Chrome"，把还在服役的
r110 浏览器一起杀了（trace 末行 `runner_exception: no close frame received or sent`，
栈停在 `m1/run_tasks.py:194 agent.close()`）。这条**不能**记进代理成绩，也不能拿它
当 C/F 类证据。单独重测 r110：**PASS**，steps 2 / model 3 / api_calls 0，终页
`doc.rust-lang.org/stable/book/ch04-00-understanding-ownership.html`
（`%TEMP%\one_r110_1007-194042.json`；单任务模式走 headless `chrome-cdp-test`，
与批次用的 headed 画像不同底，口径按 [[benchmark-infra-gotchas]] 记账）。

**新立的基建纪律：跑批期间不许碰任何 Chrome 进程**，包括"看着像上一轮遗留"的画像；
要清理先用 `Get-CimInstance` 确认没有 `m1.run_tasks` 在跑。这次是我自己踩了
"绝不动浏览器"的精神（虽然动的确实是我们自己的画像，但把在役的实例杀了）。
**并发同样是禁区**：同一时间只允许一个 run 持有浏览器与 :8090。我把这条踩了两次
（单任务验证与 22 题批并发 → 两边的 headless Chrome 互杀，那份 9 题读数作废）。

## G 类：搜索成功了，第二跳没人接（`first_result` 触发词表）· 2026-10-07 夜

批次 1 复跑把 r103/r104 从"墙"里摘出来之后，剩下的形状非常干净：**两题的搜索链全对，
停在结果页，然后一步不做直接放弃**。

| 任务 | 终页（report evidence） | steps / model | trace 里的技能 |
|---|---|---|---|
| r104 pubmed | `/search-results?term=CRISPR+off-target`，标题 "CRISPR off-target - Search Results - PubMed" | 2 / 3 | `search_type` 1.0 → `search_submit` 1.0 → **BLOCKED 0.43** |
| r103 stackoverflow | `/questions/tagged/google-search-console`（与本任务的检索词无关，见下方疑点） | 2 / 5 | 同上三连，然后模型连发 3× TYPE_TEXT 同一框 |

`first_result` 就是负责第二跳的地板技能（s011 "open the first result link" 教的），
它的触发条件实测为 **False**：

```
goal = "Search PubMed for 'CRISPR off-target' and open the first research article page."
旧正则 \b(?:first|top)\s+(?:result|link|article|item)  →  False   # first 与 article 之间隔了 research
goal = "…open the first question in the results."                →  False   # 名词 question 不在表里
```

**这不是"模型不行"，是地板漏了这类目标**：位置规则本来可以确定性执行，却因为goal 的
说法超出词表而整条不触发。改法（`_FIRST_RESULT_RE`）= first/top 与名词之间允许至多
3 个修饰词，名词补**真实 goal 里见过的** `question`；标点会截断修饰语序列，所以
"First, fill the form…" 不会误触发，"first name … click the link"（隔 4 个词）也不会。

### 验证链（按执行纪律①→③）

| 环节 | 读数 | 落盘 |
|---|---|---|
| 单测 | **56/56**（新增 `t_first_result_trigger_vocab`：r103/r104 两种形状正例 + 三种不该触发的负例）+ 8/8 rotation + 6/6 settle | `tests/test_skills.py` |
| x001/x002 安全复测 | 2/2 PASS，象限 `true_success`，api_calls=0 | `reports/x-check-fixg-1007-195727.json` |
| s011 单任务（`first_result` 的师源任务，不能被词表改坏） | PASS，`true_success`，steps 3 / model 4，终页 `articles.html`，api_calls=0 | `reports/one-s011-1007-201948.json` |
| 冻结三轮（post-G，纪律②） | **19/19、19/19、19/19**，false_positive=0，error=0，api_calls=0（model_calls 84/101/94，象限三轮全是 `true_success: 19`） | `reports/m1-baseline-1007-2000.json`、`-2004.json`、`-2010.json` |

三轮全是 G 之后重跑的（前一份 19/19×3 属于 Fix C，见上文），每轮之间按惯例重启 llama
栈以排除 RSS 膨胀；判定读数一致，波动只在 model_calls 上——这是本地模型采样噪声，
不是判定方差。G 没有把任何一题从 FAIL 变成 PASS，也没有把 PASS 变成 FAIL，
这正是它该有的表现：它只补一块从不触发的地板，19 题冻结集里没有这种形状的 goal。

### 单任务验证被墙挡住了，所以 G 的真实站收口仍然是 pending

headless 单任务重测 r103/r104，**两题都没跑到第二跳**：

| 题 | 终页标题 | steps | 归因 | 落盘 |
|---|---|---|---|---|
| r103 | `Just a moment...` | 0 | **`system/blocked_by_bot_wall`** ← 墙检测第一次在真实站上命中 | `reports/real-1007-fixg-r103-wall.json` |
| r104 | `403` | 0 | 仍是 `agent/decision` ← 词表里没有 403，**检测器的已知缺口** | `reports/real-1007-fixg-r104-403.json` |

r103 这一次是 A 类的第一次真实命中：`summary.system_modes = {blocked_by_bot_wall: 1}`，
而 `result` 依旧 FAIL、象限依旧 `correct_abandon`——归因只改标签的口径按设计成立。
r104 的 403 是**冷画像 headless** 才出现的（批次里热画像能拿到真结果页），
reports/trace 都不落终页快照，所以给它扩词表前必须先量页面形状
（`m2/probe_wall_403.py`，等没有 run 在跑的时候执行）。

**这两份读数当时没有落进 `reports/`**：`scripts/run_one.ps1` 的 `-TaskId` 分支过去把
单任务报告写去 `$env:TEMP`（批量分支才写 `reports/`），第一次核对文档时发现"引用的文件
不在 reports 里"，才把两份原样补拷进来（`summary`/`evidence`/`meta` 未改）。
脚本已改：单任务现在写 `reports/one-<id>-<stamp>.json`。纪律⑤（文档数字必须能对到
`reports/*.json`）这一步是我自己先破的——不是数字错，是数字当时无处可查。

### 基础设施缺口：自建站是带外进程，冻结脚本的收尾会杀掉它

s011 第一次单任务复测得到 `chrome-error://chromewebdata/`、steps 0——不是 G Regression，
是 `m2/test-site/serve.py`（8765/8766）**没有任何脚本负责启动**：它是手工挂上去的长驻
进程，`run_baseline_19.ps1` 的收尾"stop decider → Chrome → orphan python"会把它当成
孤儿杀掉。冻结三轮（20:00/20:04/20:10）都在 20:14 那次收尾之前完成，读数不受影响；
之后任何单任务复测自建站，必须先手工起站，否则量到的是基础设施而不是模型。
当前 8765/8766 已由本次会话重新拉起（`curl` 双双 200）。

### 疑点登记：r103 终页的 tag 与本任务的检索词无关

goal 是 `'python slice step'`，终页却是 `questions/tagged/google-search-console`。
热画像 `chrome-jev-profile` 跨轮跨天累积状态，这条很可能是**上一轮残留**而不是本轮搜索
的结果；trace 里没有动作标签的原文，无法离线判定。要等一次带截图的单任务复现再定性，
暂不记为缺陷。

## 批次 3 与批次 4：22 题真实批 · 分数没变，变的一半是题集（2026-10-07 深夜）

| 批 | 题集 | 读数 | 落盘 |
|---|---|---|---|
| 批次 3 | 22 题（12 题新写） | **7 PASS / 15 FAIL**，fp=0，api_calls=0，`system_modes={}` | `reports/real-1007-b3-22-1007-202102.json` |
| 断言修复后单独复测 | r108/r114/r117/r120 | 3/4 PASS（r117 那次是我自己新加的文本判据把它判错的） | `reports/real-1007-fixassert-1007-203959.json`、`reports/real-1007-r117-1007-204259.json` |
| 批次 4 | 同一 22 题，断言已修 | **7 PASS / 15 FAIL**，fp=0，api_calls=0，`system_modes={blocked_by_bot_wall: 1}` ← 墙第一次出现在批内 | `reports/real-1007-b4-22-1007-204322.json` |

两批都是 7/22，但**不是同一批题做成的**：批次 3 的 7 个 PASS 里有一个是假的（r117），
批次 4 的 7 个 PASS 里 r120 是修好题集才成立的，而 r101 从 PASS 掉回墙、r114 从
假阴性掉成真的走错页。分数相同纯属两条独立误差正好抵掉——这正是不许拿单次读数下结论的
理由（纪律②）。

### 三个题集缺陷（agent 没错，是度量错）

| 题 | 形状 | 后果 | 修法 |
|---|---|---|---|
| r114 | pattern 写 `[0-9.]+/intro/tutorial01`，真实 URL 是 `/en/6.1/intro/tutorial01/`（多一段 `en/`） | **假阴性**：批次 3 里 agent 九步走到目标页却判 FAIL | pattern 补 `/en/` |
| r117 | pattern `en\.wikipedia\.org/wiki/Photosynthesis` 会匹配 `Photosynthesis_(disambiguation)` | **假阳性**：消歧义页算成功，分数虚高 | `(?![\w(])` 负向前瞻（r108 同形，一起收紧） |
| r120 | httpbin 根现在是 Swagger UI（`/#/HTTP_Methods`），根本没有表单 | 任务定义过期，怎么跑都失败 | 起点改 `httpbin.org/forms/post`，断言 `/post` + 文本 `jev` |

**假阳性这一类 `false_positive` 指标看不见**：它数的是"agent 自称完成而断言不过"，
而这里断言自己就是错的。恒零红线要防的是判据，判据本身错时红线一片绿。
修 r117 时我顺手加了 `text_contains "Photosynthesis"`，结果真文章页上它判 False
（`reports/real-1007-fixassert-1007-203959.json`：URL 判据 ok、文本判据 not ok）——
这是项目里早就写下的规则：**终点证据锚 URL，不锚页面文本**（站点会按出口 IP 本地化，
长页文本还受观测截断影响）。加文本判据这一步是我自己知法犯法，删掉后单任务复测 PASS
（`reports/real-1007-r117-1007-204259.json`，终页就是 `/wiki/Photosynthesis`）。

### H 类：G 修好之后暴露的更早的错误——地板在"提交之前"就开火

批次 4 的 trace 证明 G 生效了（`first_result` 终于出现在 r103/r104 的决策里），
但也证明它开火得太早：

| 任务 | trace 里的动作序列 |
|---|---|
| r103 | `search_type` 填框（URL 仍是 `/questions`）→ **`first_result` 连点 4 次页脚 "Help Center and other resources"**，`search_submit` 一拍都没轮到 |
| r104 | `search_type` 填框 → `first_result` 点自动补全 chip "crispr off-target" → 点 "Advanced" → 发 DONE 被 guard 否决 |

`first_result` 原来的"已经搜过了"判据只是**历史里有过一次搜索框 fill**——填了不等于提交了。
修法是加一道页面闸门：那次 fill 之后必须出现过 `url_changed`（提交成功才会跳页，
跳了页才谈得上"第一个结果"）。这就是 Fix H（`jev_ultrafast/skills.py:first_result`）。

### Fix H 的验证链

| 环节 | 读数 | 落盘 |
|---|---|---|
| 单测 | **57/57**（新增 H 类：填而未提交→None、提交后→点第一个链接；旧两例的 history 补上 `outcome.url_changed`）+ 8/8 rotation + 6/6 settle | `tests/test_skills.py` |
| s011 单任务（师源任务不许坏） | PASS，`true_success`，steps 3 / model 4，api_calls=0 | `reports/one-s011-1007-210259.json` |
| r103/r104 真实站单跑 | 0/2 PASS，但**形状变了**：r104 走通 `search_type → search_submit`、落到 reCAPTCHA 挑战页，判 `system/blocked_by_bot_wall`；r103 不再点页脚（steps 1），剩下的是 D2 的"没有提交控件就不会回车" | `reports/real-1007-fixh-1007-210313.json` |
| x001/x002 安全复测 | 2/2 PASS，`true_success`，api_calls=0 | `reports/x-check-fixh-1007-210439.json` |
| 冻结（post-H，纪律②） | 三轮 **19/19、19/19、18/19**，第四轮补跑 **19/19**；四轮 false_positive=0、error=0、api_calls=0（model_calls 88/90/87/94） | `reports/m1-baseline-1007-2106.json`、`-2111.json`、`-2117.json`、`-2122.json` |

第三轮丢的那一题是 **n004**，项目里已知最容易抖的一题（Fix D 的三轮里它也掉过一次：
`reports/m1-baseline-1007-1814.json`）。它的 goal 是 "Open RFC 9110 from the RFC index."，
**不含 first/top，`first_result` 结构上不可能为它开火**，所以不是 H 关掉了合法 DONE；
第四轮它自己回到 PASS（steps 4，终页 `/info/rfc9110/`）。失败那一轮它停在
`/search/?q=RFC+9110`——同一个站在真实批里也把 r122 判了 FAIL，这条记到"rfc-editor
导航本身不稳"的账上，不记到改动上。

r104 这一跑是**第一次在批内看到墙归因**之前的单独一击：终页标题 `正在检查您的浏览器 - reCAPTCHA`、
`system_modes={blocked_by_bot_wall: 1}`，而 `result` 依旧 FAIL——地板把该做的都做对了，
剩下的不是项目的能力问题。r103 则从"地板抢跑"退回到"D2 缺口"，两个都是已知队列项，
没有新缺陷被这次修改引进来。

### 批次 5：H 之后的真实批，9/22 · 这次"对"的证据是 `first_result` 一拍都没开火

| 批 | 改动 | 读数 | 落盘 |
|---|---|---|---|
| 批次 1 | 只有地板 | 3/10 | `reports/real-1007-a.json` |
| 批次 2（fixbd） | Fix B + D | **5/10**，fp=0，api_calls=0 | `reports/real-1007-fixbd-1007-183303.json` |
| 批次 3 | + Fix C + G，断言未修 | 7/22（其中 1 个是假阳性） | `reports/real-1007-b3-22-1007-202102.json` |
| 批次 4 | 断言修复后同题集 | 7/22，墙第一次进批 | `reports/real-1007-b4-22-1007-204322.json` |
| **批次 5** | + Fix H | **9 PASS / 13 FAIL**，fp=0，error=0，api_calls=0，`system_modes={blocked_by_bot_wall: 1}` | `reports/real-1007-b5-22-1007-212901.json` |

H 生效的直接证据不是某一题变 PASS，而是**全批 `first_result` 的开火次数为 0**
（批次 4 里它是 r103 四次 + r104 三次）：地板退回到"只在真的结果页上才伸手"。
涨的两分来自 r101（这次的墙没来）、r114（断言修好且这一跑真走到 tutorial01）、
r117（收紧判据后仍然成立）。真实批的方差大半是站点给的，这也是纪律②要求复跑的原因。

13 个 FAIL 按已知类别归位（同一份 report + 同目录 trace）：

| 类别 | 题 | 形状 |
|---|---|---|
| A 墙（环境） | r104 | 填框→提交→reCAPTCHA 挑战页，判 `system/blocked_by_bot_wall` |
| D2 没有提交控件就不会回车 | r103 | `search_type` 填完，SO 的搜索框要按 Enter 才提交，后面三拍全在重填 |
| E/F 观测与动作之间页面就换掉了 | r116、r119 | **steps=0** 而 model 5/3：五拍 `first_action_floor`、三拍 TYPE_TEXT 全部没落成一步 |
| 站内搜索误触发（goal 短语被打进本站搜索框） | r102、r113、r115 | 终页分别是 arXiv `/search/advanced`、python.org `/search/?q=Style+Guide…`、`/search/?q=Download+Python` |
| 点了同类里错的那一个 | r111、r112 | books.toscrape：要 'Travel' 分类却点进一本旅行书；要书详情却停在分类首页 |
| 首页出不去（导航一步就放弃） | r105、r106、r118、r122 | GitHub / HF / GNU / RFC Editor：steps 1~4，BLOCKED 早于任何有效跳转 |

**站内搜索误触发是这一批最大的新族（3 题）**，形状高度一致：goal 里带引号的短语既是
目标名也是检索词，`search_type` 一看到 "Search … for 'X'" 就把它打进本站搜索框，
而这仨的正解其实是**直接导航**（PEP 8、`/downloads`、某个 abs 页）。下一刀从这里切。




