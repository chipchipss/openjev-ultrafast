"""M4b: 采集样本 → decider 原生训练缓存（Example/Q，供 decider/train.py 使用）。

动机：Mapika/decider-2b 是 decider-native 模型（systemone 类型化问答布局；
chat 布局零样本 0/20，native 13/20）。此前用 chat-SFT 微调 = 教它一个陌生
格式 + 窄域过拟合 → 能力被摧毁。本转换把同一批采集样本还原成**服务时真正
送给 decider 的 state/questions**，使微调留在分布内，并可直接由现有
decider serve 服务（无需 chat shim）。

构造逐字段复刻 jev_ultrafast/model.py::choose_typesafe 的 body：
  state = {page:{url,title,text[:1500]}, elements:_candidate_filter(...),
           recent_actions:[action/kind/text/outcome][-10:]}
  questions = {operation, <op>_target...}（criteria 排序与 context 同源）
  gold = 该行 decision/chosen 的 (operation, target)

输出：pickle = (train_examples, {"m4b": val_examples})
"""
import json
import glob
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"D:/openjev-models/decider")

from jev_ultrafast.model import action_space, _candidate_filter, _element_score  # noqa: E402
from jev_ultrafast.questions import NEXT_ACTION, TARGET  # noqa: E402
from decider.systemone import render_state, render_question  # noqa: E402
from decider.data.core import Example, Q  # noqa: E402

LABELS = {
    "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
    "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
    "SELECT": "Select an observed dropdown value.",
}
MAX_TARGETS_PER_OP = 20
MAX_LABEL_CHARS = 80


def _index_actions(log_dir: str) -> dict:
    """(task_id, step) -> actions_snapshot（取首个 agree，否则首个）。"""
    out = {}
    for f in sorted(glob.glob(f"{log_dir}/r*/*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            if not ln.strip():
                continue
            try:
                ev = json.loads(ln)
            except Exception:
                continue
            if ev.get("event") != "teacher_shadow":
                continue
            k = (ev.get("task_id"), ev.get("step"))
            if k not in out or (ev.get("agree") and not out[k][1]):
                out[k] = (ev.get("actions_snapshot") or [], bool(ev.get("agree")))
    return {k: v[0] for k, v in out.items()}


def _build(row: dict, actions: list) -> Example | None:
    d = row.get("decision") or row.get("chosen") or {}
    gold_op, gold_tgt = d.get("operation"), d.get("target")
    if gold_op is None or not actions:
        return None
    goal = row.get("goal") or ""
    snap = row.get("page_snapshot") or {}

    elements, targets, controls = action_space(actions)
    state = {
        "page": {
            "url": snap.get("url", ""),
            "title": snap.get("title", ""),
            "text": (snap.get("text") or "")[:1500],
        },
        "elements": _candidate_filter(elements, None),
        "recent_actions": [
            {k: h.get(k) for k in ("action", "kind", "text", "outcome")}
            for h in (row.get("history_snapshot") or [])[-10:]
        ],
    }
    valid_targets = {
        op: dict(sorted(c.items(), key=lambda kv: -_element_score(kv[1], None))[:MAX_TARGETS_PER_OP])
        for op, c in targets.items()
    }
    operations = {op: LABELS[op] for op in valid_targets}
    operations.update({op: v["label"] for op, v in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied: " + goal,
                      BLOCKED="No supported operation can progress.")

    questions = {
        "operation": {
            "type": "choice",
            "criteria": operations,
            "instructions": {"goal": goal, "rules": NEXT_ACTION},
        }
    }
    for op, cands in valid_targets.items():
        if len(cands) < 2:
            continue  # 单候选不发问（缺陷#11）
        questions[op.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                idx: {
                    "element": f"[{idx}] {a['label'].split(' → ')[0][:MAX_LABEL_CHARS]}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for idx, a in cands.items()
            },
            "instructions": {"goal": goal, "operation": op, "rules": [NEXT_ACTION, TARGET]},
        }

    qs = []
    for qid, spec in questions.items():
        rq = render_question(spec)
        names = rq["names"]
        gold = -1
        if qid == "operation" and gold_op in names:
            gold = names.index(gold_op)
        elif qid == gold_op.lower() + "_target" and gold_tgt is not None and str(gold_tgt) in names:
            gold = names.index(str(gold_tgt))
        qs.append(Q(text=rq["question"], options=rq["options"], gold=gold))

    if qs[0].gold < 0:
        return None  # operation 无 gold → 不可训练
    return Example(render_state(state), qs, row.get("category") or "m4b")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-tasks", default="")
    args = ap.parse_args()

    acts = _index_actions(args.log_dir)
    val_tasks = {t for t in args.val_tasks.split(",") if t}
    train, val = [], []
    n_rows = n_ok = n_noact = n_nogold = 0
    for name in ("a_positive.jsonl", "c_pairs.jsonl"):
        p = Path(args.samples) / name
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            n_rows += 1
            a = acts.get((row.get("task_id"), row.get("step")))
            if not a:
                n_noact += 1
                continue
            ex = _build(row, a)
            if ex is None:
                n_nogold += 1
                continue
            n_ok += 1
            (val if row.get("task_id") in val_tasks else train).append(ex)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        pickle.dump((train, {"m4b": val}), f)

    nq = sum(len(e.qs) for e in train)
    print(json.dumps({
        "source_rows": n_rows, "built": n_ok, "no_actions": n_noact,
        "no_gold": n_nogold, "train": len(train), "val": len(val),
        "train_questions": nq, "val_tasks": sorted(val_tasks),
    }, ensure_ascii=False))
    print("NATIVE_CACHE_OK")


if __name__ == "__main__":
    main()
