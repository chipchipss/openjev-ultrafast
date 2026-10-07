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
