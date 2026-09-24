"""M4a 数据准备：samples_final/{a_positive,c_pairs} → Qwen2.5 SFT（messages 格式）。

设计契约（与运行时 decider 逐字对齐）：
- system     = jev_ultrafast/prompts/next_action.txt（部署侧真源，逐字节复用）
- user       = "Goal: …" + Available operations + Elements + 收口句——复刻
               _build_user_prompt 的段落顺序；samples 无 url/title/text/history
               → Current page / Recent actions 两段省略（记档 gap；下轮采集给
               logger shadow 补 page/history 字段后出 v2 补齐）。
- assistant  = {"operation","target","operation_confidence","target_confidence"}
               a_positive → decision（教师背书的本地动作，真值 oc/tc）
               c_pairs    → chosen=teacher（oc=api_confidence 行级真值，
                            tc=oc（target 非 null 时）——记录级近似，记档）
               任何 oc 缺失的行 → 跳过并计数（不造数）。
- meta       = C4 来源标记（origin/task_id/step/domain/category/high_variance/api_model）
- 切分       = domain 全量单域 localhost → 域级无从隔离 → **按 task_id 隔离**
               （防任务级泄漏：同任务跨 step 的 goal/candidates 高度重复）。
               任务排序后每 10 个取 1 进 val（确定性、可复现）。

输出：m4a/data/{train,val}.jsonl + m4a/data/report_base.json
"""
import json
from pathlib import Path

ROOT = Path("/root/jev-ultrafast")
OUT = ROOT / "m4a" / "data"
CLOSING = "Choose the next operation and target. Reply with one JSON object only."

SYSTEM = (ROOT / "jev_ultrafast" / "prompts" / "next_action.txt").read_text(
    encoding="utf-8").rstrip("\n")


def _user_prompt(goal: str, rendered: str) -> str:
    """把样本的 rendered（Elements 块 + Operations 块）重排成 runtime 段落顺序。"""
    marker = "\nOperations:"
    if marker in rendered:
        elems, ops = rendered.split(marker, 1)
        ops_block = "Available operations:" + ops.strip()
        elems_block = "Elements:\n" + elems.strip()
    else:  # 容错：无 Operations 块则整段当 Elements
        ops_block = ""
        elems_block = "Elements:\n" + rendered.strip()
    parts = [f"Goal: {goal}", ""]
    if ops_block:
        parts += [ops_block, ""]
    parts += [elems_block, "", CLOSING]
    return "\n".join(parts)


def _rows(path: Path, origin: str, skipped: dict) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            goal, rendered = r.get("goal"), r.get("candidates_rendered")
            if origin == "a_positive":
                d = r.get("decision") or {}
                op, tgt = d.get("operation"), d.get("target")
                oc, tc = d.get("operation_confidence"), d.get("target_confidence")
            else:
                ch = r.get("chosen") or {}
                op, tgt = ch.get("operation"), ch.get("target")
                oc = r.get("api_confidence")
                tc = oc if tgt is not None else None
            if op is None or not goal or not rendered or oc is None:
                skipped[origin] += 1
                continue
            if tgt is not None and tc is None:
                tc = oc
            asst = {
                "operation": op,
                "target": tgt,
                "operation_confidence": round(float(oc), 4),
                "target_confidence": (round(float(tc), 4) if tc is not None else None),
            }
            out.append({
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": _user_prompt(goal, rendered)},
                    {"role": "assistant",
                     "content": json.dumps(asst, ensure_ascii=False)},
                ],
                "meta": {
                    "origin": origin,
                    "task_id": r.get("task_id"),
                    "step": r.get("step"),
                    "domain": r.get("domain"),
                    "category": r.get("category"),
                    "high_variance": bool(r.get("high_variance")),
                    "api_model": r.get("api_model"),
                },
            })
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    skipped = {"a_positive": 0, "c_pairs": 0}
    rows = _rows(ROOT / "samples_final/a_positive.jsonl", "a_positive", skipped)
    rows += _rows(ROOT / "samples_final/c_pairs.jsonl", "c_pairs", skipped)

    # --- 按 task_id 隔离切分（单域 → 域级隔离退化为任务级）---
    # hv（fp_rate>0.3）任务**强制入 train**（docs: "仍进集, M6 优先处理"=训练队列
    # 语义；val 求干净）。normal 层 ~10%（每层≥1，单任务不可分则整只入 train）。
    hv_tasks = sorted({r["meta"]["task_id"] for r in rows if r["meta"]["high_variance"]})
    normal_tasks = sorted({r["meta"]["task_id"] for r in rows} - set(hv_tasks))

    def _pick(group: list[str]) -> set[str]:
        if len(group) < 2:
            return set()  # 组<2 不切（整只留 train，避免单任务独占 val）
        k = max(1, round(len(group) * 0.1))
        idx = [(i + 1) * len(group) // (k + 1) - 1 for i in range(k)]
        return {group[i] for i in idx}

    val_tasks = _pick(normal_tasks)
    train = [r for r in rows if r["meta"]["task_id"] not in val_tasks]
    val = [r for r in rows if r["meta"]["task_id"] in val_tasks]

    for name, part in (("train", train), ("val", val)):
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _origin(part: list[dict]) -> dict:
        c = {"a_positive": 0, "c_pairs": 0}
        for r in part:
            c[r["meta"]["origin"]] += 1
        return c

    def _domains(part: list[dict]) -> dict:
        c: dict = {}
        for r in part:
            d = r["meta"]["domain"]
            c[d] = c.get(d, 0) + 1
        return c

    report = {
        "counts": {
            "total": len(rows),
            "train": len(train),
            "val": len(val),
            "by_origin_train": _origin(train),
            "by_origin_val": _origin(val),
            "skipped_no_target": skipped,
        },
        "split": {
            "unit": "task_id (domain=单域 localhost, 域级隔离退化为任务级)",
            "rule": "hv 任务强制入 train（M6 队列+val 求干净）; normal 层 sorted 取 ~10% -> val",
            "tasks_total": len(normal_tasks) + len(hv_tasks),
            "tasks_hv_total": len(hv_tasks),
            "tasks_val": len(sorted(val_tasks)),
            "val_task_ids": sorted(val_tasks),
        },
        "domains": {"all": _domains(rows), "train": _domains(train),
                    "val": _domains(val)},
        "high_variance": {
            "train": sum(1 for r in train if r["meta"]["high_variance"]),
            "val": sum(1 for r in val if r["meta"]["high_variance"]),
        },
        "gaps": [
            "user prompt 缺 Current page(url/title/text) 与 Recent actions 段——"
            "samples/日志未采集；v2 需 logger shadow 增记 page+history（弱 decider 对照轮顺带）",
            "c_pairs 的 target_confidence = api_confidence 行级近似（shadow chosen 未存 tc）",
        ],
    }
    (OUT / "report_base.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    print("split:", report["split"]["unit"],
          f"tasks={report['split']['tasks_total']} "
          f"hv={report['split']['tasks_hv_total']} "
          f"val_tasks={report['split']['tasks_val']}")
    print("domains:", report["domains"]["all"])
    print("PREPARE_OK")


if __name__ == "__main__":
    main()
