"""Text Helper。替换 jev-ultrafast 的 model.py:field_text()。

关联硬约束：
  A8  Text Helper 独立于 Decision Model
  D17 Text Helper null 语义：找不到值时必须返回 null → raise ValueError
"""
from __future__ import annotations

import json
import os
import sys
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


class NullValue(ValueError):
    """D17：助手明确回答"没有可填的值"。

    这是**结论**不是故障——不能触发兜底（换个 provider 问一遍可能被编出一个值）。
    """


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _json_env(name: str) -> dict:
    try:
        v = json.loads(os.environ.get(name) or "{}")
    except json.JSONDecodeError:
        return {}
    return v if isinstance(v, dict) else {}


def _providers() -> list[dict]:
    """助手 provider 链，按序尝试：主用 TEXT_HELPER_*，兜底 TEXT_HELPER_FALLBACK_*。

    约定：主用 Groq，兜底本地端点（:7863 + cn:glm-5.3-flash）。Groq 限额/抖动时
    自动落兜底，不需要改代码。
    """
    has_fallback = bool(os.environ.get("TEXT_HELPER_FALLBACK_BASE_URL"))
    out: list[dict] = []
    if os.environ.get("TEXT_HELPER_BASE_URL"):
        out.append({
            "name": "primary",
            "base_url": os.environ["TEXT_HELPER_BASE_URL"],
            "model": _env("TEXT_HELPER_MODEL", "text-helper"),
            "api_key": _env("TEXT_HELPER_API_KEY", ""),
            "max_tokens": _int_env("TEXT_HELPER_MAX_TOKENS", 256),
            "extra_body": _json_env("TEXT_HELPER_EXTRA_BODY"),
            # 有兜底时主用快速失败：默认 6 次指数退避要 ~45s 才落到兜底，
            # 对"限额"这种确定性失败毫无意义（实测 45.3s → 2 次后 ~3s）。
            "max_retries": _int_env("TEXT_HELPER_MAX_RETRIES", 2 if has_fallback else 6),
        })
    if os.environ.get("TEXT_HELPER_FALLBACK_BASE_URL"):
        out.append({
            "name": "fallback",
            "base_url": os.environ["TEXT_HELPER_FALLBACK_BASE_URL"],
            "model": _env("TEXT_HELPER_FALLBACK_MODEL", "text-helper"),
            "api_key": _env("TEXT_HELPER_FALLBACK_API_KEY", ""),
            "max_tokens": _int_env("TEXT_HELPER_FALLBACK_MAX_TOKENS", 256),
            "extra_body": _json_env("TEXT_HELPER_FALLBACK_EXTRA_BODY"),
            "max_retries": _int_env("TEXT_HELPER_FALLBACK_MAX_RETRIES", 6),
        })
    return out


def _call(cfg: dict, messages: list) -> tuple[str, dict]:
    started = time.perf_counter()
    result, _ = post_chat(
        base_url=cfg["base_url"],
        model=cfg["model"],
        api_key=cfg["api_key"],
        messages=messages,
        max_tokens=cfg["max_tokens"],
        response_format={"type": "json_object"},
        temperature=0.0,
        extra_body=cfg["extra_body"],
        max_retries=cfg.get("max_retries", 6),
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Text helper returned unexpected response shape") from None
    # 推理模型把 max_tokens 全吃在 reasoning 上时 content 为空（Flights v11/v12
    # 实况）——这是 provider 配置问题，视为故障走兜底，而不是"没有值"。
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Text helper returned empty content")

    try:
        output = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Text helper returned non-JSON: {e}") from None

    # D17: 严格要求 {"text": ...}
    if not isinstance(output, dict) or set(output) != {"text"}:
        raise ValueError("Text helper must return exactly {'text': ...}")

    value = output["text"]
    if value is None:
        raise NullValue("Text helper returned null; nothing typed.")
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Text helper returned invalid text; nothing typed.")

    return value, {
        "model": cfg["model"],
        "latency_ms": latency_ms,
        "usage": result.get("usage", {}),
    }


def field_text(context: dict) -> tuple[str, dict]:
    providers = _providers()
    if not providers:
        raise RuntimeError("Missing required env var TEXT_HELPER_BASE_URL")

    messages = [
        {"role": "system", "content": _load_prompt("text_value.txt")},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]

    errors: list[str] = []
    for i, cfg in enumerate(providers):
        try:
            text, helper = _call(cfg, messages)
        except NullValue:
            raise                                  # D17 结论：不兜底
        except Exception as e:                     # noqa: BLE001
            errors.append(f"{cfg['name']}({cfg['model']}): {type(e).__name__}: {e}")
            if i + 1 < len(providers):
                print(f"[text-helper] {cfg['name']} 失败 → 落兜底: {e}", file=sys.stderr)
            continue
        if cfg["name"] == "fallback":
            helper["fallback"] = True
        return text, helper

    raise ValueError("Text helper unavailable: " + " | ".join(errors))


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
