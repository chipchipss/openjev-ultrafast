"""M4a: 评估 base vs LoRA 在 val 上的 candidate accuracy。"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import json
import re
from pathlib import Path

import torch
from unsloth import FastLanguageModel
from datasets import load_dataset

HERE = Path(__file__).parent
ADAPTER = HERE / "adapter"


def parse_json(text: str):
    """从生成文本里抽 JSON。容错 markdown 围栏。"""
    # 去 markdown 围栏
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # 找最外层 {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def gt_from_assistant(msg: dict):
    content = msg.get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


@torch.no_grad()
def predict_one(model, tokenizer, prefix_msgs: list) -> str:
    inputs = tokenizer.apply_chat_template(
        prefix_msgs,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to("cuda")
    out = model.generate(
        input_ids=inputs,
        max_new_tokens=128,
        do_sample=False,
        temperature=0.0,
        pad_token_id=tokenizer.eos_token_id,
    )
    gen = out[0][inputs.shape[1]:]
    return tokenizer.decode(gen, skip_special_tokens=True)


def evaluate(model, tokenizer, val_rows: list, tag: str) -> dict:
    stats = {
        "tag": tag,
        "total": 0,
        "valid_json": 0,
        "op_ok": 0,
        "target_ok": 0,
        "by_origin": {},
    }

    for i, row in enumerate(val_rows):
        msgs = row["messages"]
        if len(msgs) < 3:
            continue
        prefix = msgs[:2]  # system + user
        gt = gt_from_assistant(msgs[2])
        if gt is None:
            continue

        origin = (row.get("meta") or {}).get("origin", "unknown")
        stats["by_origin"].setdefault(origin, {"total": 0, "op_ok": 0, "target_ok": 0})

        output = predict_one(model, tokenizer, prefix)
        pred = parse_json(output)

        stats["total"] += 1
        stats["by_origin"][origin]["total"] += 1

        if pred is None:
            continue
        stats["valid_json"] += 1

        op_match = pred.get("operation") == gt.get("operation")
        if op_match:
            stats["op_ok"] += 1
            stats["by_origin"][origin]["op_ok"] += 1

            pred_t = pred.get("target")
            gt_t = gt.get("target")
            # None vs None 视为匹配（control / sentinel）
            t_match = (pred_t is None and gt_t is None) or \
                      (str(pred_t) == str(gt_t))
            if t_match:
                stats["target_ok"] += 1
                stats["by_origin"][origin]["target_ok"] += 1

        if (i + 1) % 20 == 0:
            print(f"  [{tag}] {i+1}/{len(val_rows)}  "
                  f"target_acc={stats['target_ok']}/{stats['total']}")

    return stats


def main():
    print("Loading val set...")
    ds = load_dataset("json", data_files={"val": str(HERE / "data" / "val.jsonl")})
    val_rows = list(ds["val"])
    print(f"val rows: {len(val_rows)}")

    print("\nLoading base model...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
        max_seq_length=1024,
        load_in_4bit=True,
        dtype=None,
    )
    FastLanguageModel.for_inference(model)

    print("\n=== Evaluating BASE ===")
    r_base = evaluate(model, tokenizer, val_rows, "base")

    print("\nLoading LoRA adapter...")
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, str(ADAPTER))
    FastLanguageModel.for_inference(model)

    print("\n=== Evaluating LoRA ===")
    r_lora = evaluate(model, tokenizer, val_rows, "lora")

    print("\n=== RESULTS ===")
    print(json.dumps({"base": r_base, "lora": r_lora}, indent=2))

    # 关键指标
    def pct(d, k, total_key="total"):
        t = d[total_key]
        return 100 * d[k] / t if t else 0

    print("\n=== SUMMARY ===")
    print(f"BASE:  op_acc={pct(r_base, 'op_ok'):.1f}%  "
          f"target_acc={pct(r_base, 'target_ok'):.1f}%  "
          f"valid_json={pct(r_base, 'valid_json'):.1f}%")
    print(f"LORA:  op_acc={pct(r_lora, 'op_ok'):.1f}%  "
          f"target_acc={pct(r_lora, 'target_ok'):.1f}%  "
          f"valid_json={pct(r_lora, 'valid_json'):.1f}%")

    delta = pct(r_lora, 'target_ok') - pct(r_base, 'target_ok')
    print(f"\nΔtarget_acc = {delta:+.1f}pp")

    out = HERE / "eval_result.json"
    out.write_text(json.dumps({"base": r_base, "lora": r_lora,
                                "delta_target_acc": delta}, indent=2),
                   encoding="utf-8")
    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
