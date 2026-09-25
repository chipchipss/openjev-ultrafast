"""Text Helper。替换 jev-ultrafast 的 model.py:field_text()。

关联硬约束：
  A8  Text Helper 独立于 Decision Model
  D17 Text Helper null 语义：找不到值时必须返回 null → raise ValueError
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ._http import post_chat

_PROMPTS = Path(__file__).parent.parent / "prompts"


def _env(name: str, default: str = "", *, required: bool = False) -> str:
    v = os.environ.get(name, default)
    if required and not v:
        raise RuntimeError(f"Missing required env var {name}")
    return v


def _load_prompt(name: str) -> str:
    p = _PROMPTS / name
    if not p.exists():
        raise RuntimeError(f"Prompt file not found: {p}")
    return p.read_text(encoding="utf-8").strip()


def field_text(context: dict) -> tuple[str, dict]:
    base_url = _env("TEXT_HELPER_BASE_URL", required=True)
    model = _env("TEXT_HELPER_MODEL", "text-helper")
    api_key = _env("TEXT_HELPER_API_KEY", "")

    system = _load_prompt("text_value.txt")
    user = json.dumps(context, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    started = time.perf_counter()
    result, _ = post_chat(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=messages,
        max_tokens=256,
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Text helper returned unexpected response shape") from None

    try:
        output = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Text helper returned non-JSON: {e}") from None

    # D17: 严格要求 {"text": ...}
    if not isinstance(output, dict) or set(output) != {"text"}:
        raise ValueError("Text helper must return exactly {'text': ...}")

    value = output["text"]
    if value is None:
        raise ValueError("Text helper returned null; nothing typed.")
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Text helper returned invalid text; nothing typed.")

    return value, {
        "model": model,
        "latency_ms": latency_ms,
        "usage": result.get("usage", {}),
    }


# ---------------------------------------------------------------------------
# Smoke（mock post_chat，无网络依赖）
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import sys

    # 直接 patch 当前执行模块自身（-m 时即 __main__），不 import 具名副本——
    # 平铺（decider/）与包内（jev_ultrafast/decider/）两种布局通用。
    mod = sys.modules[__name__]

    os.environ["TEXT_HELPER_BASE_URL"] = "http://mock/v1"
    os.environ["TEXT_HELPER_MODEL"] = "mock-helper"

    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def fake_post(content_obj):
        def _f(*, base_url, model, api_key, messages, **kw):
            return ({"choices": [{"message": {"content": json.dumps(content_obj)}}],
                     "usage": {}}, 5)
        return _f

    ctx = {"goal": "搜索 OpenAI", "field": {"label": "Search"},
           "page": {"title": "Google", "text": ""}, "recent_actions": []}

    # --- 正常路径 ---
    mod.post_chat = fake_post({"text": "OpenAI"})
    value, helper = field_text(ctx)
    check("value OpenAI", value == "OpenAI")
    check("helper has model", helper["model"] == "mock-helper")
    check("helper has latency_ms", isinstance(helper["latency_ms"], int))

    # --- 空 text 拒绝 ---
    mod.post_chat = fake_post({"text": ""})
    try:
        field_text(ctx)
        check("empty text raises", False)
    except ValueError:
        check("empty text raises", True)

    # --- null 拒绝（D17） ---
    mod.post_chat = fake_post({"text": None})
    try:
        field_text(ctx)
        check("null text raises", False)
    except ValueError:
        check("null text raises", True)

    # --- 多字段拒绝 ---
    mod.post_chat = fake_post({"text": "ok", "extra": 1})
    try:
        field_text(ctx)
        check("extra key raises", False)
    except ValueError:
        check("extra key raises", True)

    # --- 超长拒绝 ---
    mod.post_chat = fake_post({"text": "x" * 2001})
    try:
        field_text(ctx)
        check("too long raises", False)
    except ValueError:
        check("too long raises", True)

    # --- 缺 env ---
    saved = os.environ.pop("TEXT_HELPER_BASE_URL", None)
    try:
        field_text(ctx)
        check("missing env raises", False)
    except RuntimeError:
        check("missing env raises", True)
    if saved is not None:
        os.environ["TEXT_HELPER_BASE_URL"] = saved

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    _smoke()
