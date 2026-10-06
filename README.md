# OpenJEV Ultrafast

一个跨平台、模型无关、可观测的 Browser Agent 框架。

**Google Flights 端到端任务:10.4s**(2026-10-04 实测,当时底座为 decider-2B;**零云端调用**,7 项独立校验全过)。

```powershell
.\run_demo.ps1                      # 一条命令跑通上面这个任务
.\run_demo.ps1 -Task wikipedia      # 另一个 demo(1.4s)
.\run_demo.ps1 -KeepOpen            # 跑完不关浏览器,自己看
```

> `run_demo.ps1` 是历史 demo 入口,内部写死旧 decider-2B 服务(:8000)。日常使用走「快速开始」:`startlux_serve.ps1` + `run_task.py`。

M1 基准(19 任务集,冻结三轮 2026-10-06):

| 底座 | PASS | false_positive | 单轮耗时 |
|---|---|---|---|
| **StartLux-Decision-2B(当前默认)** | **17 / 17 / 17(三轮全同,零方差)** | 0 | 3.7–3.9 分钟 |
| decider-2B(旧默认) | 17 / 17 / 18(±1 方差,失败项轮换) | 0 | 6.0–8.9 分钟 |

两个底座全部 19 任务有效、全部零云端调用。失败项始终为 n001(Python docs 导航循环)与 n004(RFC 站搜索 SPA 结果页早读)。

## 这是什么

OpenJEV Ultrafast = **jev-ultrafast 的 Runtime + 可插拔的 Decision 层 + 工程化治理**。

| 层 | 来源 | 特点 |
|---|---|---|
| Runtime(browser / snapshot / action space) | fork 自 [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT) | 原子快照、索引化动作、新鲜度守卫 |
| Decision(模型) | **可插拔**:StartLux-Decision-2B(默认)/ 任意 OpenAI 兼容 / TypeSafe wire / 自定义 | 换模型只改环境变量(M8 实测验收:零修改换底座) |
| 治理(Policy / Validator / Runtime Guard / Confidence Gate / Budget) | 本项目 | 四元组职责正交、双预算分离、四级归因 |
| 技能层(skills.py) | 本项目 | M16 确定性技能(goal 字面可判的决策零模型调用)+ M18 探索地板 |
| 数据飞轮(Logger / Evaluator / Sample Extractor) | 本项目 | 每一步可观测、四象限归因、DPO pair 抽取 |

## 为什么需要它

现有方案各自的限制:

| 项目 | 限制 |
|---|---|
| jev-ultrafast | Decision 绑定 TypeSafe 云 API(闭源,按调用付费) |
| Laya-ultrafast | 锁定 Apple Silicon(MLX) |
| OpenJEV | Decision 用 decider-2B,Runtime 用 browser-use(慢) |
| browser-use | 上游框架,不含 Decision |

**没有一个同时满足**:跨平台 + 模型无关 + Runtime 快 + 可观测。

OpenJEV Ultrafast 补的就是这块。

## 架构

```
User Goal
    ↓
Browser State (DOM + A11y)
    ↓
Dynamic Action Space
    ↓
Skills (M16/M18)  ← 字面可判的决策直接短路,不进模型
    ↓ (未命中回落)
Decision Provider  ← 可插拔
    ├── StartLux-Decision-2B (TypeSafe wire,默认)
    ├── OpenAI-compatible (Groq / DeepSeek / GLM / Qwen / ...)
    └── 自定义
    ↓
DecisionValidator (D8 三级一致性)
    ↓
Runtime Guard (freshness / occlusion)
    ↓
Policy (permission)
    ↓
Confidence Gate (uncertainty)
    ↓
Browser Execute
    ↓
Logger → Dataset → Benchmark
```

关键设计原则(硬约束全文见 `docs/01-hard-rules.md`):

- **A2**:Policy(允许吗)/ Validator(能不能执行)/ Confidence(值得相信吗)/ Task Success(成功了吗)四元组不可合并
- **A4**:API Teacher 不豁免安全链
- **A6**:Runtime Guard 与 Validator 分层独立
- **A8**:Text Helper 独立于 Decision Model(换 helper 不影响决策行为,已行为级验证)
- **B1**:Teacher Budget ≠ Recovery Budget
- **B3**:延迟不是验收门槛,是优化目标
- **C1**:Benchmark 域 ≠ Training 域
- **H2**:Decision 层必须与 Runtime 解耦

## 快速开始

### 用它干你自己的事(任意任务)

```powershell
# 1) 一条命令把决策底座拉起来(StartLux-Decision-2B GGUF,llama.cpp + wire server)
.\scripts\startlux_serve.ps1        # llama-server :8081 + /v1/systemone :8090

# 2) Chrome(走你的出口代理;不需要代理就去掉最后一个参数)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new `
  --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-test `
  --no-first-run --proxy-server=http://127.0.0.1:2080
```

跑任意任务(`--start-chrome` 可以让脚本自己拉 Chrome,省掉上面第 2 步):

```powershell
cd C:\Users\Administrator\openjev-ultrafast
C:\Users\Administrator\miniconda3\envs\jev\python.exe scripts\run_task.py `
  --start-chrome `
  --url https://en.wikipedia.org/ `
  --goal "Open the article about the Apollo program" `
  --expect "Apollo"

# --expect 给「完成证据」:它会拿去匹配最终页面的 URL/正文,全中才算成功。
# 不给就只报告状态。--headed 可以看着它操作。
```

### 跑基准

```powershell
# StartLux-Decision-2B 底座(当前默认):先拉服务,再让 runner 用现成的 8090
.\scripts\startlux_serve.ps1
.\run_baseline_19.ps1 -NoService -SvcPort 8090

# 旧 decider-2B 底座(runner 默认走它,端口 8000):一条命令全包
.\run_baseline_19.ps1

# 或手动跑
python -m m1.run_tasks --tasks m1/tasks-laya-19.jsonl --log-dir logs/ --report reports/run.json
```

合并逐任务碎片报告(与基线差分、打印 fp 硬线判决):

```powershell
python -m m1.merge_reports
```

### 安装

```bash
git clone https://github.com/chipchipss/openjev-ultrafast.git
cd openjev-ultrafast
python -m venv .venv
source .venv/bin/activate
pip install httpx[http2] browser-harness==0.1.13
```

StartLux-Decision-2B 权重(Q8_0 GGUF,2GB)从 Hugging Face 拉取:
`startlux-models/StartLux-Decision-2B-Q8_0-GGUF`,放到 `D:\openjev-models\startlux-decision-2b`(或改 `scripts\startlux_serve.ps1` 里的 `$ModelDir`)。llama.cpp 用 CUDA 12.4 预编译版(`$LlamaDir`)。注意启动脚本用 `-lm none` 加载——默认 mmap 会把 2GB 文件计入 RAM 工作集,16GB 机器上会误触内存闸。

### 配置

`.env`(参考 `.env.example`;**key 只放这里,不要写进任何被提交的文件**):

```dotenv
# Decision:StartLux gguf_server(默认底座,TypeSafe wire 兼容)
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8090/v1/systemone
TYPESAFE_API_KEY=local

# Text Helper(TYPE_TEXT 时取字段值):任意 OpenAI 兼容端点
TEXT_HELPER_BASE_URL=https://api.groq.com/openai/v1
TEXT_HELPER_MODEL=openai/gpt-oss-120b
TEXT_HELPER_API_KEY=<your key>
# 可选:出口代理(部分网络直连 Groq 会 403)
HTTPX_PROXY=http://127.0.0.1:2080
```

本地服务端点请用 `http://127.0.0.1:PORT`,不要用 `localhost`(Windows 下会先试 IPv6 加约 2 秒延迟)。

helper 选型实测(单字段值抽取,中位延迟):Groq `gpt-oss-120b` **~1.6s**(免费 1,000 次/天)> DeepSeek v4.1-flash ~3.5s > GLM-5.3-flash ~5.6s。Groq 拒收 `reasoning` 字段,本框架已自动处理。基线实测中 helper 几乎不触发——大部分任务 skills 层直接从 goal 取字面值(三轮 60 任务仅 x002 用了 1 次)。

### 跑上游对照

`reports/upstream-vs-ours.json`(2026-09-27,旧 decider-2B 底座)生成方式:克隆上游、`TYPESAFE_BASE_URL` 指向同一本地 decider、每 run 前 kill chrome + harness daemon 保证隔离。结论见下文「与上游的正面对决」。

## 实测:与上游的正面对决(2026-09-27,decider-2B 底座)

同一本地 decider-2B 后端、同一批任务,pristine 上游 vs 本框架([完整数据](reports/upstream-vs-ours.json)):

| task | 上游(steps / wall / 决策延迟 p50) | 本框架 | 终点 |
|---|---|---|---|
| s004 Wikipedia 搜索(目标 Ada Lovelace) | 4 步 / 69.2s / **7025ms** | 2 步 / 24.8s / **1508ms** | 上游滞留首页;**仅本框架到达目标条目** |
| n003 W3C Standards | **60 步 / 94.4s,ValueError 崩溃,无终点** | 3 步 / 5.5s,正确 blocked 收口 | **仅本框架**到 /standards/ |
| n001 Python docs | 4 步 / 8.9s / 982ms | 3 步 / 11.5s / 987ms(更慢) | 上游到 /doc/;本框架到 docs.python.org/3/(更深一层) |
| f004 httpbin 表单 | 4 步 / 6.2s,**完成提交(终到 /post)** | 3 步 / 3.9s,停在表单页 /forms/post(**未提交**) | 上游更完整 |

任务级 wall time **3/4 更快,1/4 更慢**。本框架快的来源:决策输入小(动作空间摘要 vs 上游 6000 字符全文,p50 延迟 830–1508ms vs 上游 427–7025ms)、有死循环收口(n003 上游 60 步崩死 vs 本框架 3 步正确放弃)。**本框架并非处处更优**:n001 多走一层所以更慢;f004 上游完整提交而本框架停在表单页。

这是 2026-09-27 旧底座的历史读数,保留作框架增益的证据;当前默认底座的成绩见「实验数据」。

## 接入一个新模型

决策层是插槽(`DECIDER_MODE`),换底座不改框架。三种方式:

### 方式 1:StartLux-Decision(TypeSafe wire,当前默认)

开源决策模型,wire 格式与 jev 生态兼容,即插即用。`scripts\startlux_serve.ps1` 拉起后:

```dotenv
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8090/v1/systemone
TYPESAFE_API_KEY=local
```

M8 验收记录(docs/03-milestones.md v1.3):换底座只动了 `.env` + runner 端口参数 + 新增 M18 技能,Runtime / Validator / Policy / Logger / Benchmark **零修改**。

### 方式 2:OpenAI 兼容端点(任意通用 LLM)

只改 `.env`(注意:M1 实测通用 LLM 在索引化动作选择上契合度差,glm-5.3-flash 直插 12/20 vs 同期本地 2B 13–15/20——能用,不保证好使):

```dotenv
DECIDER_MODE=openai
DECIDER_2B_BASE_URL=http://127.0.0.1:8000/v1
DECIDER_2B_MODEL=your-model
DECIDER_2B_API_KEY=local
```

### 方式 3:自定义后端

在 `jev_ultrafast/decider/` 实现一个函数,契约(全文见 `jev_ultrafast/decider/provider.py`):

- 签名 `(observation, goal, history) -> decision`
- 返回值符合 decision 契约(choice/operation/target + 概率字段;schema 定义见 `provider.py` 头注,引用的 `specs/decision.schema.json` 未入库)
- 连接/服务失败抛 `RuntimeError`(agent 会转 StalePage 重试)

```python
from jev_ultrafast.decider.provider import register_provider
register_provider("my_model", my_decide_fn)   # 然后设 DECIDER_MODE=my_model
```

## 实验数据

### M1 基准:两个底座的冻结三轮(19 任务集 `m1/tasks-laya-19.jsonl`)

| 底座 | PASS(三轮) | fp | 决策延迟(模型决策,实测) | 单轮 wall |
|---|---|---|---|---|
| **StartLux-Decision-2B + M18 floor** | **17 / 17 / 17** | 0 | p50 813ms / p90 1193ms / max 1615ms | 3.7–3.9 分钟 |
| decider-2B(收官三轮) | 17 / 17 / 18 | 0 | p50 779ms / p90 2220ms / max 34.2s | 6.0–8.9 分钟 |

诚实对比(StartLux vs decider-2B **最终轮** m1-baseline-1004-2311):**0 胜 1 负**(n004)。对 runner 内置参照 `m1-final3`(20 任务集映射到 19 集)则是 4 胜 0 负(f001/f002/l002/x001)。两个读数都对——区别只在参照系;稳定收益是真实的:**中位延迟持平(~0.8s)但长尾收敛(p90 2.2s→1.2s,max 34s→1.6s),且三轮失败项完全一致(零方差),这是本项目第一次拿到不带 ±1 注脚的读数**。

失败项(两底座共有,稳定):
- **n001**(Python docs 导航):模型在导航链接间循环,wait 收口
- **n004**(RFC 9110):RFC 站搜索是 SPA,结果页在加载后数秒才渲染;agent 早读得到"0 results"空页。这是 17→18 的下一个修复点

### M1 四路对照(2026-10-04,旧底座,模型线关闭的证据)

| Decision 后端 | 结果 | fp | 失败特征 |
|---|---|---|---|
| decider-2b(裸) | 13/17 ① | 0 | — |
| decider-2b + adapter_m4b | 8/15(基线同批 12/15,0 胜 4 负) | 0 | 3 任务 harness ERROR;M4b 655 行训练数据无增益 |
| Laya v17s (322M) | 6/18(其中 x001 正确拒绝计 1 个 true_success) | 0 | `model_calls ≫ steps`,反复输出终止操作;4 任务一次决策即终止 |
| agent-jev 0.6B | 3/18 | 0 | **12/18 任务 `model_calls=0`**(system crash) |

① 13/17 = `m1-final3`(15/20)折算到 Laya 的 17 个有效任务上,保证四路可比。

20 任务时代(m1-final 系列,评估器修正前):decider-2B 峰值 16/20(`m1-skills-v15`/`v20`),收官 15/20(`m1-final3`)。glm-5.3-flash 直插(零适配)12/20(`m1-decider2b-v0927-glm2.json`)。

**模型线关闭(M1 结论)——但换底座 ≠ 重开模型线**:M1 测的是模型与 action space 的契合度;通用 LLM 在索引化选择题上过度思考。StartLux 是在 TypeSafe wire 上专门训练的决策模型,wire 即插即用,半天接入(2026-10-06)。M18 探索地板(模型 BLOCKED 且页面有真实控件 → 有界强制探索)修掉了它唯一的坏习惯:首拍 0.74–0.77 置信度放弃。

**训练线关闭**:M4a 951 行 → 6/20、M4b 655 行 → 8/15(基线同批 12/15),两次自训均无增益;DONE 样本必须来自真实落地页(模板化 DONE 会教坏终止判断)。

**fp 硬线的适用范围**:fp=0 在全部 M1 基准轮成立(20 任务集与 19 任务集、四个模型、三个底座)。M2 数据飞轮的 500 任务自博弈轮(m2_final)有 8 条被旧版评估器标为 false_positive(l007 ×6、n003 ×2)——按现行 M1.6 象限语义复算,这些是 positive 任务 FAIL 的误标(现行为 correct_abandon),非真实伪造。M2 评估发生在 DoneGuard 与象限修正之前,数字不作硬线反证。

### M2 数据飞轮(历史,2026-09-28 前后)

- 10 轮 × 50 任务 = 500 任务轮(`m2_final`):309 true_success / 79 correct_abandon / 104 false_negative / 8 误标(见上)
- 6,044 decisions / 2,478 teacher shadow
- 243 个 C 类 preference pair / 708 个 A 类 positive 样本
- 验收通过(acceptance.passed=true);随训练线关闭而暂停——其唯一产出是训练数据

### 兼容性贡献

- 本地 decider 服务端 choice 校验从 2..255 放宽到 **1..255**(上游 TypeSafe wire 允许单候选 target,原实现会 422)
- 发现并修复 3B 级文本模型的"字段值复制"bug(recent_actions 显示 origin 已填时把 Zurich 复制进 destination;anti-copy 提示后 5/5)

## 项目结构

```
openjev-ultrafast/
├── jev_ultrafast/         # 主包
│   ├── agent.py           # Agent loop(pre_execute 链 + 收口)
│   ├── browser.py         # Runtime
│   ├── snapshot.js        # 原子快照
│   ├── model.py           # Decision 入口(provider registry + M1.5 机制 + M18 地板挂点)
│   ├── skills.py          # M16 确定性技能层 + M18 first-action floor
│   ├── decider/           # Decision Provider 实现
│   │   ├── provider.py    # 契约 + registry
│   │   ├── choose_2b.py   # OpenAI 兼容 provider
│   │   ├── _http.py       # 共享 HTTP(代理 / 重试 / 兼容垫片)
│   │   └── action_space.py
│   ├── policy.py          # Permission
│   ├── decision_validator.py
│   ├── runtime_guard.py
│   ├── confidence_gate.py
│   ├── step_budget.py / api_budget.py
│   ├── api_teacher.py
│   ├── evaluator.py / logger.py / sample_extractor.py
├── m1/                    # M1 benchmark + 回归 harness
├── m2/                    # M2 数据飞轮
├── m4a/                   # M4a/M4b 本地训练(已关闭)
├── scripts/               # startlux_serve.ps1(决策底座)/ run_task.py / 工具脚本
├── specs/                 # JSON Schema
├── docs/                  # 硬约束 + 架构 + 里程碑(03-milestones.md 为阶段权威记录)
├── reports/               # 实测报告(逐任务运行产物目录不入库,见 .gitignore)
├── run_baseline_19.ps1    # 基线 runner(一任务一进程 + 逐域预检 + 收尾验证)
├── run_demo.ps1           # 历史 demo 入口(写死旧 decider-2B :8000)
└── scripts/run_task.py    # 跑任意任务 + 完成证据校验
```

## 硬约束

全部硬约束见 `docs/01-hard-rules.md`。

## 现状

| 阶段 | 状态 |
|---|---|
| M-1 可行性评估 | ✅ |
| M0 接口与指标 | ✅ |
| M1 最小闭环 | ✅ ACCEPTED(R5 收口轮) |
| M1.5 结构优化 | ✅(框架增益 +7 PASS 零训练;上游 A/B 3/4 更快) |
| M2 数据飞轮 | ✅ ACCEPTED(500 任务 / 6044 decisions / 243 c_pairs;随训练线关闭暂停) |
| M3 Reranker | ⏸ SKIP(M1 probe 无 cap-failure 相关性) |
| M4a 本地训练诊断 | ✅ COMPLETED(Δtarget_acc +61.4pp,`m4a/eval_result.json`) |
| M4b 扩数据训练 | ⏸ CLOSED(adapter 8/15 无增益;两次自训均无增益) |
| **M8 Decision 换底座** | ✅ **StartLux-Decision-2B 接入(2026-10-06),17/17×3 轮(fp=0),成为默认**;"换 Decider 不动其他"验收成立 |
| M18 探索地板 | ✅ 随 M8 引入(skills.first_action_floor);s005 由 0 步放弃翻成 PASS |
| M5 Confidence 校准 | ⏸ 架构就位;StartLux 概率输出已逐决策落日志,输入现成 |
| M6 Benchmark | ✅ 19 任务集两底座冻结轮完成 |
| M7 Ultrafast | ⏸ 自用已达标,不做产品 |

下一步(未动):n004 SPA 结果页等待判据(17→18 的现实路径);L2-L6(真实站点 50 任务、回归 CI 化、helper 本地化)。

## License

MIT(继承自 jev-ultrafast)。
