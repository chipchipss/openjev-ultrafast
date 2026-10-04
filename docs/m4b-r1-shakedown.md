# M4b Round 1: SFT Pipeline Shakedown (2026-09-29)

## 结果

| 项 | 值 |
|---|---|
| 训练行 | 655(589 train / 66 val,任务级隔离,val 任务 = l006, s007) |
| 数据来源 | 12 轮采集 833 shadow → a_positive 206 + c_pairs 449 |
| 训练 | QLoRA r=8, 2 epochs, 148 步,17m50s(4060 8GB,seq 1152) |
| train loss | 2.363 → 0.014(cosine,lr 1e-4,batch 8) |
| **val@20** | **adapter: op 20/20, op+target 20/20; base 零样本: 0/20** |
| 产物 | `m4a/adapter_m4b/`(21.8MB adapter + tokenizer) |

base 0/20 → adapter 20/20:格式遵循 + 决策全部由 adapter 学得,管线有效。
(20/20 满分含任务重复记忆成分,真实增益以 M1 20 任务实测为准。)

## 本轮修的 4 个 bug(全部已验证)

1. **`agent.py` shadow 置信度键名错位**(339 行):provider 返回 `confidence`,
   shadow 读 `operation_confidence` → 恒 None → a_positive 全被 prepare_sft 跳过。
   修复:回退读 `confidence`。影响未来所有采集轮。
2. **今晚 a_positive 206 行置信度回填**:从原始 shadow 日志按 (task_id, step) join
   teacher 背书置信度。注意 glob 用 `r*/*.jsonl`,勿用 `[st]*` 漏 2/3 文件。
3. **extractor benchmark 域误吞**:采集脚本未传 `--benchmark-domains`,833 事件全跳。
   重跑 extractor 带 `benchmark_domains=set()` → 655 行捞出。
4. **decider-2B 快照损坏**:D 盘 `b37f7e1...` config.json 被此前的 robocopy 中断清零。
   健康快照:`533964dae8be954c5b5e19fa4948e48408094c1e`(3.76GB 权重完整)。
   **所有训练/推理脚本必须指向新快照。**

## 环境注意(Windows 特有)

- `pip install unsloth` 会把 torch 降成 CPU wheel(`2.12.1+cpu`)。
  修法:`pip install --force-reinstall torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128`(2.7GB,~30min)
- 推理时 `TORCHDYNAMO_DISABLE=1`,否则 inductor 在 generate 路径崩溃(训练不受影响)
- HF_HOME 必须 `D:\openjev-models\hf` + `HF_HUB_OFFLINE=1` 显式传入子进程
  (用户级 env 不进 detached PowerShell)

## 下一轮采集命令

```powershell
# 改输出目录名,避免覆盖:run_m4b_collect.ps1 里 -LogDir samples/m4b-r2(若无此参则改脚本内路径)
powershell -File run_m4b_collect.ps1 -Rounds 12
# 晨报:samples/m4b-r2/manifest.json
# 提取(如脚本仍默认吞 benchmark):
#   jev python -c "... extract_all(..., benchmark_domains=set())"
# 训练(数据到 1000+ 行时):
#   cd m4a && python train_m4b.py   (改 train/val 路径指向新 data 目录)
```

## Laya v17s Kaggle 路线(数据已备好)

`m4a/data_m4b_r1/laya_cases_train.jsonl`(589)+ `laya_cases_eval.jsonl`(66),
格式 = laya-browser/code/finetune 的 cases.jsonl(goal/page_obj{url,title,text,actions}/
history/gold_op/gold_id,actions 含 node/kind/id,98.5% 可 gold 解析)。
上传 Kaggle → `build_items.py` 分词 → `train.py`(RLCD 配方,2×T4 ~1-2h)。

## 验收对照(M4 计划)

| 项 | 现状 |
|---|---|
| candidate accuracy > 80% | val@20 op+target 100%(待 M1 20 任务实测确认) |
| 数据量 3000-10000 | 655/3000 → 今晚挂 r2 采集(+600-900) |
| API < 30% | M5 阶段测 |
