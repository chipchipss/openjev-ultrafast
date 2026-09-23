"""OpenAI-compatible chat HTTP client。被 choose_2b / field_text_2b 共用。

契约与 jev-ultrafast/model.py:post_json 对齐：
  - HTTP 失败抛 RuntimeError
  - 429 / 529 / 503 重试（指数退避）
  - 达到 max_retries 仍未成功 → RuntimeError
"""
from __future__ import annotations

import random
import sys
import time

import httpx

_CLIENT = httpx.Client(timeout=60.0)

_RETRYABLE = frozenset({429, 529, 503})


def post_chat(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    *,
    max_tokens: int = 512,
    response_format: dict | None = None,
    temperature: float | None = None,
    max_retries: int = 6,
) -> tuple[dict, int]:
    """POST {base_url}/chat/completions。返回 (response_json, latency_ms)。"""
    url = base_url.rstrip("/") + "/chat/completions"
    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if response_format is not None:
        body["response_format"] = response_format
    if temperature is not None:
        body["temperature"] = temperature
    # M1: 显式关闭 Thinking。实测 agnes-3.0-flash 默认已关，但 distributor 渠道
    # 会漂（探针见 m1/m1-log.md）；恒带此字段做渠道无关的 JSON 格式保险。
    # 注意：thinking:{disabled} / enable_thinking:false 在该端点反而会触发 thinking，禁用。
    body["reasoning"] = {"enabled": False}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    started = time.perf_counter()
    last_status: int | None = None
    for attempt in range(max_retries):
        backoff = min(1.0 * (2 ** attempt), 16.0) + random.uniform(0, 0.5)
        try:
            r = _CLIENT.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            if attempt < max_retries - 1:
                print(f"[retry {attempt+1}/{max_retries}] transport error: {e}",
                      file=sys.stderr)
                time.sleep(backoff)
                continue
            raise RuntimeError(
                f"Model connection failed after {max_retries} attempts: {e}"
            ) from None
        if r.status_code in _RETRYABLE and attempt < max_retries - 1:
            print(f"[retry {attempt+1}/{max_retries}] HTTP {r.status_code}",
                  file=sys.stderr)
            time.sleep(backoff)
            continue
        last_status = r.status_code
        if r.is_error:
            raise RuntimeError(
                f"Model provider returned HTTP {r.status_code}; no action executed."
            )
        latency_ms = round((time.perf_counter() - started) * 1000)
        return r.json(), latency_ms

    raise RuntimeError(
        f"Model unavailable after {max_retries} attempts (last HTTP {last_status})"
    )
