# OpenJEV Ultrafast · 仓库清单（MANIFEST）

- **用途**：仓库丢失后按此清单判断"该有什么、去哪里找权威"。
- **它不再是逐文件摘要**。2026-10-12 之前这里是 405 行、写着"已落盘 41 件 / 集成后的运行树在
  `DE:/root/jev-ultrafast`"的旧清单——那是仓库形状还没定型时的产物，之后每一步都在长新的东西，
  它却一个字没跟着变，于是它变成了**最容易让人误读仓库形状的那一个文件**——它最后一次被改动是
  `78a670b`，而那时 `m2/` 的真实站题集、两级闸门、`tests/` 的一半套件都还不存在。旧版全文在
  `git log -p -- MANIFEST.md`。
- **权威分工**（本文件只指路，不复制内容，避免长出第二份文档）：

  | 你想知道 | 权威在这里 |
  |---|---|
  | 仓库形状、目录职责 | `README.md`「项目结构」一节 |
  | 阶段状态（L1–L6 / M 系列） | `README.md`「现状」表 + `docs/00-project-plan.md` 的里程碑表 |
  | 硬约束与验证链 | `docs/01-hard-rules.md`、`README.md`「三条硬线」「治理与验证链」 |
  | 每个数字的出处 | `reports/*.json`（命名规则见下）；读数裁决过程在 `m2/real-log.md` |
  | 单个代码变更 | `git log`（阶段级/约束级变更才进 `CHANGELOG.md`） |

## 重新生成本节的命令（数字来自命令，不来自记忆，这样它不会再变旧）

```powershell
git ls-files | Measure-Object -Line                       # 跟踪文件总数
git ls-files | ForEach-Object { ($_ -split '/')[0] } | Group-Object | Sort-Object Count -Descending
```

**清点快照**（2026-10-12，`git ls-files` 实测）：跟踪文件 **533**。

| 顶层 | 数量 | 是什么 |
|---|---|---|
| `reports/` | 297 | 实测报告，全部入库（逐任务的运行产物目录不入库，见 `.gitignore`） |
| `m2/` | 86 | 真实站题集与测量工具：`tasks_real_100.jsonl`、`batch_audit.py`、`time_split.py`、`probe_*.py`（零模型探针）、`make_tasks_100.py`、`smoke_gate.py`、`real-log.md` |
| `m4a/` | 36 | M4a/M4b 本地训练线，**已关闭**（两次自训无增益） |
| `jev_ultrafast/` | 33 | 主包：`agent.py` / `browser.py` / `snapshot.js` / `skills.py`（21 项确定性地板）/ `model.py` / `policy.py` / `decision_validator.py` / `runtime_guard.py` / `confidence_gate.py` / `step_budget.py` / `api_budget.py` / `evaluator.py` / `logger.py` / `sample_extractor.py` / `decider/` |
| `scripts/` | 28 | `startlux_serve.ps1`（决策底座）、`run_one.ps1`（单题/批）、`run_task.py`（任意任务）、`smoke.ps1` + `ci_local.ps1`（两级闸门）、`chrome_guard.ps1`（杀侧归属）、以及 `probe_*.py` 系列 |
| `tests/` | 20 | 离线套件（不需浏览器与模型），**207 案**，逐件 `n/n passed` |
| 根目录 | 16 | `README.md`、`CHANGELOG.md`、本文件、`pyproject.toml`、9 个 `run_*.ps1` 入口、`mcp_server.py` |
| `m1/` | 8 | 19 题基准 runner 与题集（`tasks-laya-19.jsonl` 等） |
| `docs/` | 7 | `00-project-plan.md`（L1–L6 权威）、`01-hard-rules.md`、`03-milestones.md`、`09-task-success.md`、`10-step-budget.md`、m4b 两件 |
| `specs/` `config/` | 各 1 | decision schema / 配置 |

## `reports/` 的命名规则（数字必须能这样对回去）

- `m1-baseline-<MMdd-HHmm>.json` —— 19 题冻结轮；判定要求**同一 build 连续三轮**。
- `real-<MMdd>-b<序号>-<题数>-<MMdd-HHmmss>.json` —— 真实站批（例：`real-1011-b33-100-1011-231042.json` = b33，100 行）。
- `one-<task_id>-<MMdd-HHmmss>.json` —— 单任务读数；`x-check-*.json` —— x001/x002 安全复测；`ci-*.json` —— 闸门判定。
- **作废件也在仓里，但标题/`m2/real-log.md` 里写明"分数禁止引用"**（例：`real-1011-b30-100-*` 是代理死掉的环境阻断产物；`one-r152-1011-222908` 是撞号题集导致量错题的读数；`m1-baseline-1011-2235` 是缺 x001 的那轮）。
- 逐任务的 step/decision 事件 jsonl 落在 `logs/`（不入库）；**"零云端"只由这里的 `text_helper` 集合证明**，不由报告里的 `api_calls` 证明。
