# OpenJEV Ultrafast

一个跨平台、模型无关、可观测的 Browser Agent 框架。

## 这是什么

OpenJEV Ultrafast = **jev-ultrafast 的 Runtime + 可插拔的 Decision 层 + 工程化治理**。

| 层 | 来源 | 特点 |
|---|---|---|
| Runtime（browser / snapshot / action space） | fork 自 [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)（MIT） | 原子快照、索引化动作、新鲜度守卫 |
| Decision（模型） | **可插拔**：本地 / API / decider-2B / 任何 OpenAI 兼容或 TypeSafe wire 后端 | 换模型只改环境变量 |
| 治理（Policy / Validator / Runtime Guard / Confidence Gate / Budget） | 本项目 | 四元组职责正交、双预算分离、四级归因 |
| 数据飞轮（Logger / Evaluator / Sample Extractor） | 本项目 | 每一步可观测、四象限归因、DPO pair 抽取 |

## 为什么需要它

现有方案各自的限制：

| 项目 | 限制 |
|---|---|
| jev-ultrafast | Decision 绑定 TypeSafe 云 API（闭源，按调用付费） |
| Laya-ultrafast | 锁定 Apple Silicon（MLX） |
| OpenJEV | Decision 用 decider-2B，Runtime 用 browser-use（慢） |
| browser-use | 上游框架，不含 Decision |

**没有一个同时满足**：跨平台 + 模型无关 + Runtime 快 + 可观测。

OpenJEV Ultrafast 补的就是这块。

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
    ├── OpenAI-compatible (DeepSeek / GLM / Qwen / ...)
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

关键设计原则（硬约束全文见 `docs/01-hard-rules.md`）：

- **A2**：Policy（允许吗）/ Validator（能不能执行）/ Confidence（值得相信吗）/ Task Success（成功了吗）四元组不可合并
- **A4**：API Teacher 不豁免安全链
- **A6**：Runtime Guard 与 Validator 分层独立
- **B1**：Teacher Budget ≠ Recovery Budget
- **B3**：延迟不是验收门槛，是优化目标
- **C1**：Benchmark 域 ≠ Training 域
- **H2**：Decision 层必须与 Runtime 解耦

## 快速开始

### 依赖

- Python 3.12
- Chrome / Chromium（CDP 9222）
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

`.env`：

```dotenv
DECIDER_2B_BASE_URL=https://api.deepseek.com/v1
DECIDER_2B_MODEL=deepseek-chat
DECIDER_2B_API_KEY=<your key>

TEXT_HELPER_BASE_URL=https://api.deepseek.com/v1
TEXT_HELPER_MODEL=deepseek-chat
TEXT_HELPER_API_KEY=<your key>
```

本地服务端点请用 `http://127.0.0.1:PORT`，不要用 `localhost`（Windows 下会先试 IPv6 加约 2 秒延迟）。

### 跑 M1 benchmark

```bash
python3 -m m1.run_tasks --tasks m1/tasks.jsonl --log-dir logs/ --report reports/run.json
```

## 接入一个新模型

### 方式 1：OpenAI 兼容端点

只改 `.env`：

```dotenv
DECIDER_2B_BASE_URL=http://127.0.0.1:8000/v1
DECIDER_2B_MODEL=your-model
DECIDER_2B_API_KEY=local
```

### 方式 2：TypeSafe wire 格式（如 decider-2B）

```dotenv
DECIDER_MODE=typesafe
TYPESAFE_BASE_URL=http://127.0.0.1:8000/v1/systemone
TYPESAFE_API_KEY=local
```

### 方式 3：自定义后端

在 `jev_ultrafast/decider/` 实现一个函数，签名 `(observation, goal, history) -> decision`，然后：

```python
from jev_ultrafast.decider.provider import register_provider
register_provider("my_model", my_decide_fn)
```

## 实验结果

M1 benchmark：20 个任务，覆盖 search / form / navigate / list / toggle / negative。

| Decision 后端 | 训练数据 | PASS | false_positive | crash |
|---|---|---|---|---|
| DeepSeek Flash（API） | — | 12/20 (60%) | 0 | 0 |
| decider-2B（Mapika） | ~1,000,000 | 7/20 (35%) | 0 | 0 |
| Qwen2.5-3B-LoRA（本项目 M4a） | 951 | 6/20 (30%) | 0 | 0 |

关键观察：

1. 数据差 1000 倍，任务成功只差 1 个 —— 本地 2B-3B 规模的瓶颈不在训练数据量
2. 两个本地模型 false_positive 都是 0 —— DONE Guard 起作用
3. Runtime 层共用 —— 三个后端的差异只来自 Decision

M2 数据飞轮：

- 10 轮 × 50 任务 = 500 任务轮
- 6,044 decisions / 2,478 teacher shadow
- 243 个 C 类 preference pair / 708 个 A 类 positive 样本

## 项目结构

```
openjev-ultrafast/
├── jev_ultrafast/         # 主包
│   ├── agent.py           # Agent loop
│   ├── browser.py         # Runtime
│   ├── snapshot.js        # 原子快照
│   ├── model.py           # Decision 入口（provider registry 转发）
│   ├── decider/           # Decision Provider 实现
│   │   ├── provider.py    # 契约 + registry
│   │   ├── choose_2b.py   # OpenAI 兼容 provider
│   │   └── action_space.py
│   ├── policy.py          # Permission
│   ├── decision_validator.py
│   ├── runtime_guard.py
│   ├── confidence_gate.py
│   ├── step_budget.py / api_budget.py
│   ├── api_teacher.py
│   ├── evaluator.py / logger.py / sample_extractor.py
├── m1/                    # M1 benchmark
├── m2/                    # M2 数据飞轮
├── m4a/                   # M4a 本地训练
├── specs/                 # JSON Schema
├── docs/                  # 硬约束 + 架构 + 阶段
├── reports/               # benchmark 报告
└── run_m1.ps1             # 一键跑 M1
```

## 硬约束

全部硬约束见 `docs/01-hard-rules.md`。

## 现状

| 阶段 | 状态 |
|---|---|
| M-1 可行性评估 | ✅ |
| M0 接口与指标 | ✅ |
| M1 最小闭环 | ✅ ACCEPTED（decider-2B：PASS=7/20、acceptance PASS、无 crash） |
| M2 数据飞轮 | ✅ ACCEPTED（6044 decisions / 243 c_pairs / split 可复现） |
| M3 Reranker | ⏸ SKIP（M1 probe 无 cap-failure 相关性） |
| M4a 本地训练诊断 | ✅ COMPLETED（Δtarget_acc +61.4pp） |
| M4b 扩数据训练 | ⏳ |
| M5 Confidence 校准 | ⏳ 架构就位 |
| M6 Benchmark | ⏳ |
| M7 Ultrafast | ⏳ |

架构已定型。剩下的工作是参数调优 / 数据积累 / 规则细化。

## License

MIT（继承自 jev-ultrafast）。
