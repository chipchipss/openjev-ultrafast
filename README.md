\# OpenJEV Ultrafast · README



```markdown

\# OpenJEV Ultrafast



\*\*一个跨平台、模型无关、可观测的 Browser Agent 框架。\*\*



不是"另一个 Browser Agent"。是"让任何模型都能插进 Browser Agent 的骨架"。



\---



\## 这是什么



OpenJEV Ultrafast = \*\*jev-ultrafast 的 Runtime + 可插拔的 Decision 层 + 工程化治理\*\*。



| 层 | 来源 | 特点 |

|---|---|---|

| Runtime（browser / snapshot / action space） | fork 自 \[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)（MIT） | 原子快照、索引化动作、新鲜度守卫 |

| Decision（模型） | \*\*可插拔\*\*：本地 / API / decider-2B / 任何 OpenAI 兼容或 TypeSafe wire 后端 | 换模型只改环境变量 |

| 治理（Policy / Validator / Runtime Guard / Confidence Gate / Budget） | 本项目 | 四元组职责正交、双预算分离、四级归因 |

| 数据飞轮（Logger / Evaluator / Sample Extractor） | 本项目 | 每一步可观测、四象限归因、DPO pair 抽取 |



\---



\## 为什么需要它



现有方案各自的限制：



| 项目 | 限制 |

|---|---|

| \*\*jev-ultrafast\*\* | Decision 绑定 TypeSafe 云 API（闭源，按调用付费） |

| \*\*Laya-ultrafast\*\* | 锁定 Apple Silicon（MLX） |

| \*\*OpenJEV\*\* | Decision 用 decider-2B，Runtime 用 browser-use（慢） |

| \*\*browser-use\*\* | 上游框架，不含 Decision |



\*\*没有一个\*\*：跨平台 + 模型无关 + Runtime 快 + 可观测。



\*\*OpenJEV Ultrafast 补的就是这块。\*\*



\---



\## 架构



```

&#x20;                   USER GOAL

&#x20;                       │

&#x20;                       ▼

&#x20;              ┌─────────────────┐

&#x20;              │ Browser Runtime │  fork jev-ultrafast

&#x20;              │  DOM + A11y     │  （未改）

&#x20;              └────────┬────────┘

&#x20;                       ▼

&#x20;              ┌─────────────────┐

&#x20;              │ Dynamic Action  │  索引化元素

&#x20;              │     Space       │  （未改）

&#x20;              └────────┬────────┘

&#x20;                       ▼

&#x20;              ┌─────────────────┐

&#x20;              │   Decision      │  ← 可插拔

&#x20;              │   Backend       │    · Local (llama.cpp / vLLM / Ollama)

&#x20;              │                 │    · API (OpenAI / DeepSeek / GLM / Anthropic)

&#x20;              │                 │    · TypeSafe wire (decider-2B)

&#x20;              └────────┬────────┘

&#x20;                       ▼

&#x20;       ┌───────────────┴───────────────┐

&#x20;       ▼                               ▼

&#x20; ┌──────────┐                  ┌──────────────┐

&#x20; │  Policy  │                  │  Validator   │  D8 三级一致性

&#x20; │  允许吗  │                  │  能不能执行  │

&#x20; └────┬─────┘                  └──────┬───────┘

&#x20;      └───────────────┬───────────────┘

&#x20;                      ▼

&#x20;              ┌─────────────────┐

&#x20;              │ Runtime Guard   │  新鲜度 / 遮挡 / 可用性

&#x20;              │  （不做语义）   │

&#x20;              └────────┬────────┘

&#x20;                       ▼

&#x20;              ┌─────────────────┐

&#x20;              │ Confidence Gate │  决定是否找 Teacher

&#x20;              └────────┬────────┘

&#x20;                       ▼

&#x20;              ┌─────────────────┐

&#x20;              │    Browser      │

&#x20;              └────────┬────────┘

&#x20;                       ▼

&#x20;              ┌─────────────────┐

&#x20;              │     Logger      │  四象限 + 四维失败分类

&#x20;              └─────────────────┘

```



\*\*关键设计原则\*\*（硬约束全文见 `docs/01-hard-rules.md`）：



\- \*\*A2\*\*：Policy（允许吗） / Validator（能不能执行） / Confidence（值得相信吗） / Task Success（成功了吗）四元组不可合并

\- \*\*A4\*\*：API Teacher 不豁免安全链——Teacher 输出重走 Policy + Validator

\- \*\*A6\*\*：Runtime Guard 与 Validator 分层独立——新鲜度检查不归 Validator

\- \*\*B1\*\*：Teacher Budget ≠ Recovery Budget——两个池分别计数、分别限额

\- \*\*B3\*\*：延迟不是验收门槛，是优化目标——Quality > Safety > API rate > Latency

\- \*\*C1\*\*：Benchmark 域 ≠ Training 域——按域名划分 train/val/test

\- \*\*E1\*\*：Uncertainty escalation ≠ State failure escalation——页面 loading 不走 Teacher



\---



\## 快速开始



\### 依赖



\- Python 3.12（推荐）

\- Chrome / Chromium（CDP 9222）

\- 一个 OpenAI 兼容模型端点（本地 llama.cpp / vLLM / Ollama / DeepSeek / GLM 等）



\### 安装



```bash

git clone https://github.com/chipchipss/openjev-ultrafast.git

cd openjev-ultrafast

python3 -m venv .venv

source .venv/bin/activate          # Windows: .venv\\Scripts\\activate

pip install httpx\[http2] browser-harness==0.1.13

```



\### 配置



`.env`：



```dotenv

\# Decision 后端（以 DeepSeek 为例）

DECIDER\_2B\_BASE\_URL=https://api.deepseek.com/v1

DECIDER\_2B\_MODEL=deepseek-chat

DECIDER\_2B\_API\_KEY=<your key>



\# Text Helper（填表单用，可指向同一后端）

TEXT\_HELPER\_BASE\_URL=https://api.deepseek.com/v1

TEXT\_HELPER\_MODEL=deepseek-chat

TEXT\_HELPER\_API\_KEY=<your key>

```



\*\*重要\*\*：本地服务端点请用 `http://127.0.0.1:PORT`，\*\*不要用 `localhost`\*\*——后者在 Windows 会先尝试 IPv6 `::1` 回退，加约 2 秒延迟。



\### 跑一个任务



```bash

\# 起 Chrome（CDP）

chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-jev --no-first-run



\# 跑单个任务

python3 -m m1.run\_tasks --tasks m1/tasks.jsonl --log-dir logs/ --report reports/run.json

```



\### 跑 M1 benchmark（20 个任务）



```bash

python3 -m m1.run\_tasks \\

&#x20;   --tasks m1/tasks.jsonl \\

&#x20;   --log-dir logs/m1 \\

&#x20;   --report reports/m1.json \\

&#x20;   --task-delay 5

```



输出（`reports/m1.json`）：



```json

{

&#x20; "summary": {

&#x20;   "total": 20, "pass": 6, "fail": 14, "error": 0,

&#x20;   "quadrants": {

&#x20;     "true\_success": 1, "false\_positive": 0,

&#x20;     "correct\_abandon": 14, "false\_negative": 5

&#x20;   },

&#x20;   "failure\_modes": { "decision": 6, "budget\_exceeded": 7 },

&#x20;   "system\_modes": {}

&#x20; },

&#x20; "acceptance": { "passed": true, "notes": \[] }

}

```



\---



\## 接入一个新模型



\### 方式 1：OpenAI 兼容端点（最简单）



只改 `.env`：



```dotenv

DECIDER\_2B\_BASE\_URL=http://127.0.0.1:8000/v1

DECIDER\_2B\_MODEL=your-model-name

DECIDER\_2B\_API\_KEY=local

```



已验证：DeepSeek Flash、GLM、本地 Qwen2.5-3B-LoRA（Unsloth serve）。



\### 方式 2：TypeSafe wire 格式（如 decider-2B）



```dotenv

DECIDER\_MODE=typesafe

TYPESAFE\_BASE\_URL=http://127.0.0.1:8000/v1/systemone

TYPESAFE\_API\_KEY=local

```



已验证：\[Mapika/decider-2b](https://huggingface.co/Mapika/decider-2b)（本地部署，`decider.serve`）。



\### 方式 3：写一个新后端



实现两个函数，加入 `decider/` 目录：



```python

\# decider/choose\_custom.py

def choose(state: dict, goal: str, history: list\[dict]) -> dict:

&#x20;   """

&#x20;   state:    page dict（含 url / title / text / actions）

&#x20;   goal:     任务目标

&#x20;   history:  历史步骤

&#x20;   返回:     {choice, operation, target,

&#x20;              operation\_confidence, target\_confidence, ...}

&#x20;   """

&#x20;   ...

```



在 `model.py` 的 `choose()` 里加路由。



\---



\## 实验结果（诚实数据）



\*\*M1 benchmark：20 个任务，覆盖 search / form / navigate / list / toggle / negative。\*\*



| Decision 后端 | 训练数据量 | PASS | false\_positive | crash |

|---|---|---|---|---|

| \*\*DeepSeek Flash\*\*（API） | — | \*\*12/20 (60%)\*\* | 0 | 0 |

| \*\*decider-2B\*\*（Mapika，1M 样本） | \~1,000,000 | \*\*7/20 (35%)\*\* | 0 | 1 |

| \*\*Qwen2.5-3B-LoRA\*\*（本项目 M4a，951 样本） | 951 | \*\*6/20 (30%)\*\* | 0 | 0 |



\*\*关键观察\*\*：



1\. \*\*数据差 1000 倍，任务成功只差 1 个\*\*——本地 2B-3B 规模的瓶颈不在训练数据量

2\. \*\*本地模型都卡在 30-35%，API 在 60%\*\*——差距在模型规模（API 后端可能是更大模型）

3\. \*\*两个本地模型的 false\_positive 都是 0\*\*——DONE Guard 起了作用

4\. \*\*Runtime 层是共用的\*\*——三个后端的差异只来自 Decision，不是 Runtime



\*\*未验证\*\*：



\- \*\*TypeSafe Jev API\*\*（jev-ultrafast 原版后端）的真实 20 任务成绩——本项目未测

\- Linux / macOS 上的完整 e2e——目前只在 Windows 上跑通



\*\*数据飞轮验证\*\*（M2）：



\- 10 轮 × 50 任务 = \*\*500 任务轮\*\*

\- 6,044 decisions

\- 2,478 teacher shadow 事件

\- 243 个 C 类 preference pair（DPO 训练材料）

\- 708 个 A 类 positive 样本



\---



\## 项目结构



```

openjev-ultrafast/

├── jev\_ultrafast/         # 主包（fork 的 Runtime + 本项目新增）

│   ├── agent.py           # Agent loop（唯一改基座的文件）

│   ├── browser.py         # Runtime（fork，未改）

│   ├── snapshot.js        # 原子快照（fork，未改）

│   ├── model.py           # Decision 层入口（桥接 + 路由）

│   ├── decider/           # Decision 后端实现

│   ├── prompts/           # Prompt 模板

│   ├── policy.py          # Permission：允许吗

│   ├── decision\_validator.py  # Permission：能不能执行

│   ├── runtime\_guard.py   # Runtime Guard：新鲜度 / 遮挡

│   ├── confidence\_gate.py # Uncertainty：是否找 Teacher

│   ├── step\_budget.py     # 预算：steps + model\_calls

│   ├── api\_budget.py      # 预算：Teacher + Recovery 双池

│   ├── api\_teacher.py     # Teacher 后端

│   ├── evaluator.py       # Task Success 判定

│   ├── logger.py          # 事件落盘

│   └── sample\_extractor.py # 数据飞轮：抽训练样本

├── m1/                    # M1 benchmark（20 任务）

├── m2/                    # M2 数据飞轮 runner

├── m4a/                   # M4a 本地训练（LoRA）

├── specs/                 # JSON Schema（action / decision / observation / task）

├── docs/                  # 硬约束 + 架构 + 阶段 + 各专项文档

└── reports/               # benchmark 报告

```



\---



\## 硬约束



全部 60+ 条硬约束见 \[`docs/01-hard-rules.md`](docs/01-hard-rules.md)。这是项目的"宪法"——任何代码、设计、实验若与它冲突，必须先改约束，再改实现。



编号规则：一旦分配永不复用。废弃标记 `\[DEPRECATED]`，保留原文。



\---



\## 现状



| 阶段 | 状态 |

|---|---|

| M-1 可行性评估 | ✅ |

| M0 接口与指标 | ✅ |

| M1 最小闭环 | ✅ 完成（decider-2B 基线：PASS=7/20、acceptance PASS、无 crash） |

| M2 数据飞轮 | ✅ 完成（6044 decisions / 243 c_pairs / 951 训练样本 / split 可复现） |

| M3 Reranker | ⬜ 未启动（D2 条件性，需先证明 Filter+ActionSpace+Decider 不足） |

| M4a 本地训练诊断 | ✅ Δtarget\_acc +61.4pp |

| M4b 扩大训练 | ⬜ |

| M5 三级路由 | ⬜ Confidence Gate 已就位（三种模式），校准未做 |

| M6 Benchmark | ⬜ 100-300 任务集未建 |

| M7 Ultrafast | ⬜ 延迟优化待做（长 state 是当前瓶颈） |

| M8 模型扩展 | ⬜ |



\*\*架构已定型\*\*。剩下的工作是参数调优 / 数据积累 / 规则细化。



\---



\## License



MIT（继承自 jev-ultrafast）。



\## 引用



```

OpenJEV Ultrafast — A cross-platform, model-agnostic browser agent framework.

https://github.com/chipchipss/openjev-ultrafast

```



基于：

\- \[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)（MIT）

\- \[Mapika/decider-2b](https://huggingface.co/Mapika/decider-2b)

```

