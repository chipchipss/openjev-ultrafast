# OpenJEV Ultrafast

一个跨平台、模型无关、可观测的 Browser Agent 框架。

**Google Flights 端到端任务:10.4s**(本地 2B 决策模型,**零云端调用**,7 项独立校验全过)。

```powershell
.\run_demo.ps1                      # 一条命令跑通上面这个任务
.\run_demo.ps1 -Task wikipedia       # 另一个 demo(1.4s)
.\run_demo.ps1 -KeepOpen             # 跑完不关浏览器,自己看
```

M1 基准(19 任务集):**16/18,`false_positive = 0`**,全程本地,整轮 5.8 分钟。

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

### 依赖

- Python 3.11+
- Chrome / Chromium(CDP 9222)
- 一个 OpenAI 兼容模型端点或 decider-2B

### 安装

```bash
git clone https://github.com/chipchipss/openjev-ultrafast.git
cd openjev-ultrafast
python3 -m venv .venv
source .venv/bin/activate
pip install httpx[http2] browser-harness==0.1.13
```

### 配置

`.env`(参考 `.env.example` 结构;**key 只放这里,不要写进任何被提交的文件**):

```dotenv
# Decision:本地 decider 服务(TypeSafe wire)
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8000/v1/systemone
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

```bash
# 一键(Windows):起 decider + 全环境隔离 + 跑 20 任务
./run_s004_history_test.ps1

# 或手动
python3 -m m1.run_tasks --tasks m1/tasks.jsonl --log-dir logs/ --report reports/run.json
```

### 跑上游对照

`reports/upstream-vs-ours.json` 生成方式:克隆上游、`TYPESAFE_BASE_URL` 指向同一本地 decider、每 run 前 kill chrome + harness daemon 保证隔离。

## 接入一个新模型

### 方式 1:OpenAI 兼容端点(Decision)

只改 `.env`:

```dotenv
DECIDER_MODE=openai
DECIDER_2B_BASE_URL=http://127.0.0.1:8000/v1
DECIDER_2B_MODEL=your-model
DECIDER_2B_API_KEY=local
```

### 方式 2:TypeSafe wire 格式(如 decider-2B)

```dotenv
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8000/v1/systemone
TYPESAFE_API_KEY=local
```

### 方式 3:自定义后端

在 `jev_ultrafast/decider/` 实现一个函数,签名 `(observation, goal, history) -> decision`,然后:

```python
from jev_ultrafast.decider.provider import register_provider
register_provider("my_model", my_decide_fn)
```

## 实验数据

### M1 benchmark(20 任务:search / form / navigate / list / toggle / negative)

| Decision 后端 | 训练数据 | PASS | false_positive | crash |
|---|---|---|---|---|
| DeepSeek Flash(API) | — | 12/20 (60%) | 0 | 0 |
| decider-2B(Mapika) | ~1,000,000 | 13/20 (65%) | 0 | 0 |
| glm-5.3-flash 直插(零适配) | — | 12/20 (60%) | 0 | 0 |
| Qwen2.5-3B-LoRA(本项目 M4a) | 951 | 6/20 (30%) | 0 | 0 |

decider-2B 13/20 为框架增益后读数(M1.5 三机制 + 评估器修正,全程零训练);false_positive 全线为 0 = DONE Guard 有效;FP 安全硬线在任何后端下都不破。

关键观察:

1. 框架增益 +7 PASS(6→13),零训练——Runtime 保证 action space 正确性与安全硬线,模型只负责排序
2. 即插即用成立:glm-5.3-flash 零适配接入即达 12/20;接入任意 OpenAI 兼容模型 = 改 3 个环境变量
3. 两个本地模型 false_positive 都是 0 —— DONE Guard 起作用

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
├── reports/               # benchmark 报告
├── run_m1.ps1             # 一键跑 M1
└── run_s004_history_test.ps1  # 一键 decider + 环境隔离 + 基准
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
| M4b 扩数据训练 | ⏳ 剩余差距的唯一主通道(2B 复杂弹层推进力) |
| M5 Confidence 校准 | ⏳ 架构就位 |
| M6 Benchmark | ⏳ |
| M7 Ultrafast | ⏳ |

## License

MIT(继承自 jev-ultrafast)。
