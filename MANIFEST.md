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

**清点快照**（2026-10-14 傍晚第十六次，`git ls-files` 实测；第十三次那次编辑留下过**两张重复的表**，已真删成一张 —— 同一份清单抄两遍正是本仓文档最反对的形状）：跟踪文件 **716**（10-14 一天里 661 → 679 → 694 → 705 → 716）。

| 顶层 | 跟踪文件 | 是什么 |
|---|---|---|
| `reports` | 463 | 实测报告，全部入库（逐任务的 step/decision jsonl 在 `logs/`，不入库，见 `.gitignore`） |
| `m2` | 109 | 真实站题集与测量工具：`tasks_real_100.jsonl`、**`tasks_real_50.jsonl`（#75 那天从 `%TEMP%` 钉进仓：50 行档的闸门一直读一份从未入库的 temp 题集）**、`batch_audit.py`、`b40_audit.py`、`smoke_tasks.py`、`smoke_gate.py`、`make_release_snapshot.py`（#79 的无历史发布快照）、Tier 3 的三件对照工具（`probe_tier3_corpus.py` 采语料、`golden_tier3.py` 逐字节摘要、`replay_two_builds.py` 判「是我还是站点」）、`tier3_batch_audit.py`、**`arrival_digest_scan.py`（#84 的阈值来自这里：扫所有带 `final_page` 摘要的 `task_result`）**、**#85 的两件：`probe_sqlite_reachability.py`（目标页单飞双臂可达性）与 `probe_sqlite_batch_context.py`（复现批内顺序并抓出 `ERR_SSL_PROTOCOL_ERROR`）**、**#46 的两件：`probe_r113_scroll_ladder.py`（逐格往下滚、每格当场重放地板，量出近似行劫持发生在哪一页）与 `probe_near_miss_tier_attribution.py`（186 页 × 71 次非弃权命中的档位分布，词重叠档 0 次）**、探针（**探针一个不删**） |
| `m4a` | 36 | M4a/M4b 本地训练线，**已关闭**（两次自训无增益） |
| `jev_ultrafast` | 33 | 主包：`agent.py` / `browser.py` / `snapshot.js` / `skills.py` / `evaluator.py` / `decider/`（含 `choose_2b.py` 这条 chat→decision 线） |
| `scripts` | 30 | `startlux_serve.ps1`、`run_one.ps1`（零云端单题/批）、`run_freecloud_19.ps1`（#80 的云端决策实验）、`smoke.ps1`、`ci_local.ps1`、`chrome_guard.ps1`、`ci_local.ps1` 的冻结档判据 `ci_freeze_gate.ps1`（#88：行数不足 ⇒ BLOCKED，纯函数所以能拿已入库的报告直接喂）、`text_helper.ps1`（**云端 URL 只在这一个文件里拼写**） |
| `tests` | 40 | 离线套件 **40 件 / 329 案全绿**（`scripts/smoke.ps1` tier1 逐件 `n/n passed` 相加，2026-10-14 22:2x 实跑；上一版是 18:0x 的 39 件 / 321 案）；含 `test_ci_freeze_gate.py`（#88：冻结档少行必须 BLOCKED，五案钉形状 + 一案当反向守卫（不许顺手改阈值）+ 两份已入库报告作见证，改前 3/8 ⇒ 改后 8/8）、含 `test_egress_retry.py`（#85 第二刀的四条硬线：无码不重跑、只一次、PASS 永不碰、痕迹穿白名单）；含 `test_explicit_target_near_miss.py`（#46：两页真实快照的形状，改前 3/5 ⇒ 改后 5/5）；含 `test_evaluator_arrival_shell.py`（#84a 的新档，正样本是 1066 行摘要里那 4 行同 sha 的 arXiv 空壳）、 `test_stuck_counters.py`（#83 的仪表，两条案专测「跨题按住」）、 `test_no_third_party_pii.py`（#79 的结构闸）、`test_task_id_uniqueness.py`（#81）、`test_prompt_operation_vocabulary.py`（#82）、`test_evaluator_app_error.py`（#78） |
| `m1` | 8 | 19 题基准 runner 与题集（`tasks-laya-19.jsonl`）+ 100 行题集生成器 |
| `docs` | 9 | `00-project-plan.md`（L1–L6 权威）、`01-hard-rules.md`、`03-milestones.md`、`09/10/11`、`12-upstream-license.md`（上游 MIT 原文归档） |
| `根目录` | 17 | `README.md`、`CHANGELOG.md`、`LICENSE`、本文件、`pyproject.toml`、若干 `run_*.ps1`（多数是已关闭训练线的入口） |

## `reports/` 的命名规则（数字必须能这样对回去）

- `m1-baseline-<MMdd-HHmm>.json` —— 19 题冻结轮；判定要求**同一 build 连续三轮**。
- `real-<MMdd>-b<序号>-<题数>-<MMdd-HHmmss>.json` —— 真实站批（例：`real-1011-b33-100-1011-231042.json` = b33，100 行）。
- `one-<task_id>-<MMdd-HHmmss>.json` —— 单任务读数；`x-check-*.json` —— x001/x002 安全复测；`ci-*.json` —— 闸门判定。
- **作废件也在仓里，但标题/`m2/real-log.md` 里写明"分数禁止引用"**（例：`real-1011-b30-100-*` 是代理死掉的环境阻断产物；`one-r152-1011-222908` 是撞号题集导致量错题的读数；`m1-baseline-1011-2235` 是缺 x001 的那轮）。
- 逐任务的 step/decision 事件 jsonl 落在 `logs/`（不入库）；**"零云端"只由这里的 `text_helper` 集合证明**，不由报告里的 `api_calls` 证明。
（10-12 的 573 之后新增的是测试套件、`m2/smoke_tasks.py`、`m2/b40_audit.py`、`m2/make_release_snapshot.py`、`docs/12-upstream-license.md` 与每天的 reports。）

**发布形态的账（#77 起，#79 结案，2026-10-13 深夜）**：`m2/fixtures/r142_arrival.json` 与
`m2/tmp_download.html` 里那条第三方个人邮箱**在工作树里已换成合成名**，但
① 那次改动的 diff 会把旧内容作为删除行显示，② **历史提交里它仍在**。
操作者 10-13 授权自选处置 ⇒ 选**不改写历史**（那要 force-push 已推出去的提交，属共享状态），
改为对外分发 `dist/…-snapshot.tar.gz`（无历史、`history_included: false`），
并用 `tests/test_no_third_party_pii.py` 的结构判据防它回来。
**因此本文件的口径是**：可以说"发布产物不含第三方标识"，**不可以**说"仓库历史干净"。
sha256 与文件数记在 `m2/real-log.md` 的 #79 那节，`dist/` 不入库。
