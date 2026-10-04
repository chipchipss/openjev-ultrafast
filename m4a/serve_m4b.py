"""M4b: OpenAI 兼容 server，加载 Mapika/decider-2b base + adapter_m4b。
与 m4a/serve.py 同构，仅换 base/适配器/端口/model id，并禁用 torch.compile
（inductor 在 Qwen3_5 generate 路径崩溃；训练不受影响）。

运行时配合：
  DECIDER_MODE=openai
  DECIDER_2B_BASE_URL=http://127.0.0.1:8000/v1
  DECIDER_2B_MODEL=decider-2b-m4b
"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TORCHDYNAMO_DISABLE"] = "1"   # 绕开 inductor generate bug

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
BASE = os.environ.get(
    "M4B_BASE",
    r"D:/openjev-models/hf/hub/models--Mapika--decider-2b/snapshots/"
    r"533964dae8be954c5b5e19fa4948e48408094c1e",
)
ADAPTER = os.environ.get("M4B_ADAPTER", str(HERE / "adapter_m4b"))
MODEL_ID = os.environ.get("M4B_MODEL_ID", "decider-2b-m4b")
PORT = int(os.environ.get("M4B_PORT", "8000"))

print(f"Loading {BASE} + {ADAPTER} ...", flush=True)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE,
    max_seq_length=1152,
    load_in_4bit=True,
    dtype=None,
)
model = PeftModel.from_pretrained(model, ADAPTER)
FastLanguageModel.for_inference(model)
print("Ready.", flush=True)


class ChatRequest(BaseModel):
    model: str = ""
    messages: list
    max_tokens: int = 512
    temperature: float = 0.0
    response_format: dict | None = None


app = FastAPI()


def _extract_json(text: str):
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

    # 非 JSON → WAIT 骨架（确定性模型重试无意义）
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
    return {"data": [{"id": MODEL_ID}]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
