"""M4b 数据增强：元素索引置换 + 置信度中和。

动机（M1 实测三条根因中的两条）：
1. 位置先验：训练目标 CLICK 索引高度集中 8/10/6（localhost 固定布局），
   模型学成"点第 N 个元素"。置换元素顺序 + 同步重编号 → 目标索引随之变化，
   模型必须按 label+goal 选择，无法记忆位置。
2. 假置信度：标签的 operation_confidence 是教师自报值（恒 0.95），模型学成
   "永远 0.95"。此处统一置 0.5（诚实"未知"），置信度交给 M5 校准层。

输入：samples/<tag>/{a_positive,c_pairs}.jsonl（含 candidates_structured/
     page_snapshot/history_snapshot）
输出：<out>/{train,val}.jsonl（messages 格式，与 prepare_sft 逐字节同构）+ report.json
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


import importlib.util

_ps_spec = importlib.util.spec_from_file_location(
    "prepare_sft", str(ROOT / "m4a" / "prepare_sft.py"))
_ps = importlib.util.module_from_spec(_ps_spec)
_ps_spec.loader.exec_module(_ps)
SYSTEM, _user_prompt = _ps.SYSTEM, _ps._user_prompt

K_PERMS = 4          # 每行生成 4 个置换变体（含恒等）
SEED = 20260929
CONF_NEUTRAL = 0.5

def _render_elems(els: list[dict]) -> str:
    """复刻 choose_2b._render_elements（structured 元素 → 文本行）。"""

    if not els:
        return "(no interactive elements)"
    lines = []
    for el in els:
        ops = "/".join(el.get("operations") or [])
        parts = [f"[{el['index']}] {el['label']} [{ops}]"]
        if el.get("value"):
            parts.append(f'value="{el["value"]}"')
        for key in ("checked", "selected", "expanded"):
            if key in el:
                parts.append(f"{key}={el[key]}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _permute(els: list[dict], rng: random.Random):
    """返回 (新元素列表, 旧 index -> 新 index 映射)。"""
    order = list(els)
    rng.shuffle(order)
    mapping = {}
    new = []
    for pos, el in enumerate(order, start=1):
        mapping[str(el["index"])] = str(pos)
        new.append({**el, "index": str(pos)})
    return new, mapping


def _variant(row: dict, origin: str, rng: random.Random):
    d = (row.get("decision") if origin == "a_positive" else row.get("chosen")) or {}
    op, tgt = d.get("operation"), d.get("target")
    if op is None:
        return None
    rendered = row.get("candidates_rendered") or ""
    marker = "\nOperations:"
    if marker not in rendered:
        return None
    elems_text, ops_text = rendered.split(marker, 1)
    els = ((row.get("candidates_structured") or {}).get("elements")) or []
    if not els:
        return None

    new_els, mapping = _permute(els, rng)
    new_rendered = _render_elems(new_els) + marker + ops_text
    new_tgt = mapping.get(str(tgt)) if tgt is not None else None
    if tgt is not None and new_tgt is None:
        return None

    asst = {
        "operation": op,
        "target": new_tgt,
        "operation_confidence": CONF_NEUTRAL,
        "target_confidence": (CONF_NEUTRAL if new_tgt is not None else None),
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _user_prompt(row.get("goal"), new_rendered, row)},
            {"role": "assistant", "content": json.dumps(asst, ensure_ascii=False)},
        ],
        "meta": {
            "origin": origin,
            "task_id": row.get("task_id"),
            "step": row.get("step"),
            "domain": row.get("domain"),
            "category": row.get("category"),
            "high_variance": bool(row.get("high_variance")),
        },
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-tasks", default="", help="逗号分隔的 val task_id")
    ap.add_argument("--k", type=int, default=K_PERMS)
    args = ap.parse_args()

    samples = Path(args.samples)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    val_tasks = {t for t in args.val_tasks.split(",") if t}

    rows = []
    for name, origin in (("a_positive.jsonl", "a_positive"), ("c_pairs.jsonl", "c_pairs")):
        p = samples / name
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                rows.append((json.loads(ln), origin))

    train, val = [], []
    rng = random.Random(SEED)
    made = skipped = 0
    for row, origin in rows:
        for k in range(args.k):
            v = _variant(row, origin, rng)
            if v is None:
                if k == 0:
                    skipped += 1
                continue
            made += 1
            (val if v["meta"]["task_id"] in val_tasks else train).append(v)

    for name, part in (("train", train), ("val", val)):
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    report = {
        "source_rows": len(rows),
        "variants_per_row": args.k,
        "made": made,
        "skipped_rows": skipped,
        "train": len(train),
        "val": len(val),
        "val_tasks": sorted(val_tasks),
        "conf_neutral": CONF_NEUTRAL,
        "seed": SEED,
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    print("AUGMENT_OK")


if __name__ == "__main__":
    main()
