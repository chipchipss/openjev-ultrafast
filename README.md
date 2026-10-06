# OpenJEV Ultrafast

一个跨平台、模型无关、可观测的 Browser Agent 框架。

**Google Flights 端到端任务:10.4s**(本地 2B 决策模型,**零云端调用**,7 项独立校验全过)。

```powershell
.\run_demo.ps1                      # 一条命令跑通上面这个任务
.\run_demo.ps1 -Task wikipedia       # 另一个 demo(1.4s)
.\run_demo.ps1 -KeepOpen             # 跑完不关浏览器,自己看
```

M1 基准(19 任务集,冻结三轮):**decider-2B 15-17 PASS(±1)**;**StartLux-Decision-2B(接入 2026-10-06)17/17 PASS 三轮全稳、`false_positive = 0`、热决策 ~65ms、整轮 3.7 分钟**,全程零云端调用。

## 这是什么

OpenJEV Ultrafast = **jev-ultrafast 的 Runtime + 可插拔的 Decision 层 + 工程化治理**。

| 层 | 来源 | 特点 |
|---|---|---|
| Runtime(browser / snapshot / action space) | fork 自 [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT) | 原子快照、索引化动作、新鲜度守卫 |
| Decision(模型) | **可插拔**:本地 / API / decider-2B / 任何 OpenAI 兼容或 TypeSafe wire 后端 | 换模型只改环境变量 |
| 治理(Policy / Validator / Runtime Guard / Confidence Gate / Budget) | 本项目 | 四元组职责正交、双预算分离、四级归因 |
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

## 实测:与上游的正面对决

同一本地 decider-2B 后端、同一批任务,pristine 上游 vs 本框架([完整数据](reports/upstream-vs-ours.json)):

| task | 上游(steps / wall / 每步延迟) | 本框架 | 终点 |
|---|---|---|---|
| s004 Wikipedia 搜索 | 4 步 / 69.2s / **7.0s/步** | 2 步 / 24.8s / **1.5s/步** | 上游滞留首页;本框架到达目标条目 |
| n003 W3C | **60 步 / 94.4s**(烧满 120 次调用后崩溃) | 3 步 / 5.5s,正确 blocked 收口 | 都到 /standards/ |
| n001 Python docs | 4 步 / 8.9s | 3 步 / 11.5s | 都到文档区 |
| f004 httpbin 表单 | 4 步 / 6.2s | 3 步 / 3.9s | 都提交 |

决策延迟同量级(0.4-1.1s vs 上游云端 178ms),任务级 wall time **4/4 更快或持平**。差距来源:上游把 6000 字符页面文本整体塞进决策 state(输入大一个数量级),且没有死循环收口(靠 MAX_STEPS 烧步数)。

框架增益换来的:决策输入小 → 单步快 → 收敛早 → 总时间短,外加循环检测 / 窗口 / 预算三层安全收口。

## 架构

```
User Goal
    ↓
Browser State (DOM + A11y)
    ↓
Dynamic Action Space
    ↓
Decision Provider  ← 可插拔
    ├── decider-2B (TypeSafe wire)
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

### 用它干你自己的事（任意任务）

```powershell
# 一条命令把决策底座拉起来（StartLux-Decision-2B GGUF，llama.cpp + wire server）
.\scripts\startlux_serve.ps1        # llama-server :8081 + /v1/systemone :8090

# Chrome（走你的出口代理；不需要代理就去掉最后一个参数）
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new `
  --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-test `
  --no-first-run --proxy-server=http://127.0.0.1:2080
```

跑任意任务：

```powershell
cd C:\Users\Administrator\openjev-ultrafast
C:\Users\Administrator\miniconda3\envs\jev\python.exe scripts\run_task.py `
  --url https://en.wikipedia.org/ `
  --goal "Open the article about the Apollo program" `
  --expect "Apollo"

# --expect 给「完成证据」：它会拿去匹配最终页面的 URL/正文，全中才算成功。
# 不给就只报告状态。--headed 可以看着它操作，--start-chrome 让脚本自己拉 Chrome。
```

### 跑基准

```bash
# 默认底座（旧 decider-2B）：一条命令全包——起服务 + 环境隔离 + 一任务一进程跑 19 任务
./run_baseline_19.ps1

# StartLux-Decision-2B 底座：先把服务拉起来，再让 runner 用现成的 8090
.\scripts\startlux_serve.ps1
./run_baseline_19.ps1 -NoService -SvcPort 8090

# 或手动
python3 -m m1.run_tasks --tasks m1/tasks-laya-19.jsonl --log-dir logs/ --report reports/run.json
```

合并逐任务碎片报告(与基线差分、打印 fp 硬线判决):

```bash
python3 -m m1.merge_reports
```

### 安装

```bash
git clone https://github.com/chipchipss/openjev-ultrafast.git
cd openjev-ultrafast
python3 -m venv .venv
source .venv/bin/activate
pip install httpx[http2] browser-harness==0.1.13
```

StartLux-Decision-2B 权重（Q8_0 GGUF，2GB）从 Hugging Face 拉取：
`startlux-models/StartLux-Decision-2B-Q8_0-GGUF`，放到 `D:\openjev-models\startlux-decision-2b`（或改 `scripts\startlux_serve.ps1` 里的路径）。llama.cpp 用 CUDA 12.4 预编译版（`scripts\startlux_serve.ps1` 里的 `$LlamaDir`）。

### 配置

`.env`(参考 `.env.example` 结构;**key 只放这里,不要写进任何被提交的文件**):

```dotenv
# Decision:StartLux gguf_server（默认底座,TypeSafe wire 兼容）
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

helper 选型实测(单字段值抽取,中位延迟):Groq `gpt-oss-120b` **~1.6s**(免费 1,000 次/天)> DeepSeek v4.1-flash ~3.5s > GLM-5.3-flash ~5.6s。Groq 拒收 `reasoning` 字段,本框架已自动处理。

### 跑 M1 benchmark

见上面「跑基准」一节。`run_baseline_19.ps1` 是生产配置的干净基线 runner(一任务一进程 + 逐域预检 + 收尾验证);StartLux 底座加 `-NoService -SvcPort 8090`。

### 跑上游对照

`reports/upstream-vs-ours.json` 生成方式:克隆上游、`TYPESAFE_BASE_URL` 指向同一本地 decider、每 run 前 kill chrome + harness daemon 保证隔离。

## 接入一个新模型

决策层是插槽(`DECIDER_MODE`),换底座不改框架。已验证的三种方式:

### 方式 1:StartLux-Decision(TypeSafe wire,默认,推荐)

开源决策模型,wire 格式与 jev 兼容,即插即用。`scripts\startlux_serve.ps1` 拉起后:

```dotenv
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8090/v1/systemone
TYPESAFE_API_KEY=local
```

### 方式 2:OpenAI 兼容端点(任意通用 LLM)

只改 `.env`(注意:M1 实测通用 LLM 契合度差,详见实验数据——这条路能用,不保证好使):

```dotenv
DECIDER_MODE=openai
DECIDER_2B_BASE_URL=http://127.0.0.1:8000/v1
DECIDER_2B_MODEL=your-model
DECIDER_2B_API_KEY=local
```

### 方式 3:自定义后端

在 `jev_ultrafast/decider/` 实现一个函数,签名 `(observation, goal, history) -> decision`,然后:

```python
from jev_ultrafast.decider.provider import register_provider
register_provider("my_model", my_decide_fn)
```

## 实验数据

### M1 四路模型对照(19 任务集 `m1/tasks-laya-19.jsonl`,全部实测)

| Decision 后端 | 结果 | false_positive | 失败特征 |
|---|---|---|---|
| **StartLux-Decision-2B(Q8_0 GGUF + M18 floor)** | **17 PASS 三轮全稳**(1845/1910/2033) | 0 | n001 导航循环、n004 SPA 结果页早读 |
| decider-2b(裸) | 15-17(三轮 16/17/15,±1 抖动) | 0 | — |
| decider-2b + adapter_m4b | 8/15(同批基线 12/15) | 0 | 无增益,0 胜 4 负 |
| Laya v17s (322M) | 6/18 | 0 | `model_calls ≫ steps`,反复输出终止操作 |
| agent-jev 0.6B | 3/18 | 0 | 12/18 是 system crash,`model_calls=0` |
| DeepSeek Flash(API) | 12/20 | 0 | — |
| glm-5.3-flash 直插(零适配) | 12/20 | 0 | — |
| Qwen2.5-3B-LoRA(本项目 M4a) | 6/20 | 0 | — |

关键结论:

1. **默认底座 = StartLux-Decision-2B + skills 层(含 M18 探索地板)+ 治理四件套**:对 decider-2b 4 胜(f001/f002/l002/x001)2 负,热决策 ~65ms(旧底座 0.4-1.1s),整轮 3.7 分钟,`false_positive = 0` 三轮全守,`api_calls = 0`(全程零云端)。**17/17 零方差是本项目第一次拿到不带 ±1 注脚的读数**
2. **模型线关闭(M1 结论)——但换底座 ≠ 重开模型线**:M1 测出"通用 LLM 契合度不行";StartLux 是在 TypeSafe wire 上专门训练的决策模型,wire 即插即用,半天接入。M18 探索地板(BLOCKED 前必须探索)修掉了它唯一的坏习惯:首拍 0.74-0.77 置信度放弃
3. **训练线关闭**:两次自训均无增益;DONE 样本必须来自真实落地页(模板化 DONE 会教坏终止判断)
4. `fp = 0` 的注脚:一部分是被 Policy 黑名单拦下的合法动作(误杀)撑起来的假象——模型被拦导致任务失败,失败自然不产生假阳性。查硬线时同时查误杀率

### 航班 demo:helper 后端四方案对决(同一任务)

| 方案 | 决策合计 | 文本合计 | 总耗时 |
|---|---|---|---|
| **Groq gpt-oss-120b**(本地 decider + 云 helper) | 2.5s | 2.6s | **13.6s** |
| GLM-5.3-flash 网关 | 2.4s | 11.3s | 25.6s |
| 本地 Qwen3B(CPU) | 2.3s | 52.0s | 102.1s |
| 本地 Qwen3B(GPU 共驻) | 89.8s | 2.1s | 152.4s |

教训:8GB 消费级 GPU 无法同时舒适承载 decider-2B + 3B helper(大 state 下显存挤压,决策 0.5s→20s);helper 单独跑 CPU 又太慢。**decider 独占 GPU + helper 走快云**是消费级硬件最优解。三种 helper 下决策行为完全一致(3 步收口同位置)= A8 独立性被行为级验证。

### 兼容性贡献

- 本地 decider 服务端 choice 校验从 2..255 放宽到 **1..255**(上游 TypeSafe wire 允许单候选 target,原实现会 422)
- 发现并修复 3B 级文本模型的"字段值复制"bug(recent_actions 显示 origin 已填时把 Zurich 复制进 destination;anti-copy 提示后 5/5)

M2 数据飞轮(历史):

- 10 轮 × 50 任务 = 500 任务轮
- 6,044 decisions / 2,478 teacher shadow
- 243 个 C 类 preference pair / 708 个 A 类 positive 样本

## 项目结构

```
openjev-ultrafast/
├── jev_ultrafast/         # 主包
│   ├── agent.py           # Agent loop(pre_execute 链 + 收口)
│   ├── browser.py         # Runtime
│   ├── snapshot.js        # 原子快照
│   ├── model.py           # Decision 入口(provider registry 转发 + M1.5 机制)
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
├── m4a/                   # M4a 本地训练
├── scripts/               # 本地 text helper 服务等
├── specs/                 # JSON Schema
├── docs/                  # 硬约束 + 架构 + 阶段
├── reports/               # benchmark 报告(运行产物目录已不入库,见 .gitignore)
├── run_baseline_19.ps1    # 生产配置 19 任务基线(一任务一进程 + 预检 + 收尾验证)
├── run_demo.ps1           # 一条命令 demo(flights / wikipedia)
└── scripts/run_task.py    # 跑任意任务 + 完成证据校验
```

## 硬约束

全部硬约束见 `docs/01-hard-rules.md`。

## 现状

| 阶段 | 状态 |
|---|---|
| M-1 可行性评估 | ✅ |
| M0 接口与指标 | ✅ |
| M1 最小闭环 | ✅ ACCEPTED |
| M1.5 结构优化 | ✅(+7 PASS 零训练;上游 A/B 4/4 更快或持平) |
| M2 数据飞轮 | ✅ ACCEPTED(6044 decisions / 243 c_pairs / split 可复现) |
| M3 Reranker | ⏸ SKIP(M1 probe 无 cap-failure 相关性) |
| M4a 本地训练诊断 | ✅ COMPLETED(Δtarget_acc +61.4pp) |
| M4b 扩数据训练 | ⏸ CLOSED(adapter_m4b 8/15 无增益;两次自训均无增益) |
| M18 Decision 换底座 | ✅ StartLux-Decision-2B 接入,17/17 三轮全稳(fp=0、~65ms/步),成为默认 |
| M5 Confidence 校准 | ⏸ 架构就位;StartLux 概率输出已逐决策落日志,输入现成 |
| M6 Benchmark | ✅ 19 任务集 + 四路对照完成(StartLux 17/17 零方差) |
| M7 Ultrafast | ⏸ 自用已达标,不做产品 |

下一步(未动):n004 SPA 结果页等待判据(17→18 的现实路径);L2-L6(真实站点 50 任务、回归 CI 化、helper 本地化)。

## License

MIT(继承自 jev-ultrafast)。
