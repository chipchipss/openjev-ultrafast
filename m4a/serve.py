"""最小 OpenAI 兼容 server。加载 base + LoRA adapter。

force_json：decider 要求严格 JSON。OOD 退化（!!!/复读/截断）时服务端做有界
自修复：同 prompt 重试，抽首个合法 {...}；仍失败回退 WAIT 骨架（让 agent
重新 observe，比静默错填安全）。
"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import json
import re
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import torch
from unsloth import FastLanguageModel
from peft import PeftModel

HERE = Path(__file__).parent

print("Loading model...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
    max_seq_length=1024,
    load_in_4bit=True,
    dtype=None,
)
model = PeftModel.from_pretrained(model, str(HERE / "adapter"))
FastLanguageModel.for_inference(model)
print("Ready.")


class ChatRequest(BaseModel):
    model: str = ""
    messages: list
    max_tokens: int = 512
    temperature: float = 0.0
    response_format: dict | None = None


app = FastAPI()


def _extract_json(text: str):
    """从模型输出里抽最外层 {...}，容错 markdown 围栏。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _generate(inputs: torch.Tensor, max_new_tokens: int):
    with torch.no_grad():
        out = model.generate(
            input_ids=inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=1.0,
            pad_token_id=tokenizer.eos_token_id,
        )
    return out[0][inputs.shape[1]:]


@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    inputs = tokenizer.apply_chat_template(
        req.messages, tokenize=True, add_generation_prompt=True,
        return_tensors="pt",
    ).to("cuda")
    gen = _generate(inputs, req.max_tokens)
    text = tokenizer.decode(gen, skip_special_tokens=True)
    usage_tokens = gen.shape[0]

    # 非 JSON → 立即回 WAIT 骨架（确定性模型重试无意义，避免 httpx 超时）
    if _extract_json(text) is None:
        text = ('{"operation": "WAIT", "target": null, '
                '"operation_confidence": 0.0, "target_confidence": null}')
        usage_tokens = 0

    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": inputs.shape[1],
                  "completion_tokens": usage_tokens},
    }


@app.get("/v1/models")
def models():
    return {"data": [{"id": "local-qwen-3b-lora"}]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
