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
