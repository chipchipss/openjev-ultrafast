"""OpenAI-compatible chat HTTP client。被 choose_2b / field_text_2b 共用。

契约与 jev-ultrafast/model.py:post_json 对齐：
  - HTTP 失败抛 RuntimeError
  - 429 / 529 / 503 重试（指数退避）
  - 达到 max_retries 仍未成功 → RuntimeError
"""
from __future__ import annotations

import os
import random
import sys
import time

import httpx

# Optional egress proxy (env HTTPX_PROXY). Groq 等 endpoint 在部分网络下
# 需要走本地代理；未设置时行为不变。
#
# 关键：回环端点（本地 decider / laya-serve / 自托管 :8000）绝不能走出口代理。
# 否则本地模型服务在线也会连接被拒（WinError 10061），并退避重试 6 次
# （≈224s/任务），表现为「模型极慢 + 全部 correct_abandon + steps=0」——
# 实为代理不可用，不是模型或框架问题（2026-10-04 adapter 对照实测）。
_PROXY = os.environ.get("HTTPX_PROXY") or None
_CLIENT = httpx.Client(
    timeout=60.0,
    proxy=_PROXY,
    mounts={"all://127.0.0.1": None, "all://localhost": None} if _PROXY else {},
)

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
    extra_body: dict | None = None,
) -> tuple[dict, int]:
    """POST {base_url}/chat/completions。返回 (response_json, latency_ms)。

    extra_body：provider 专有参数透传（如本地端点的 reasoning_effort）。
    最后合并，可覆盖上面任何字段——换端点不必改代码。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if response_format is not None:
        body["response_format"] = response_format
    if temperature is not None:
        body["temperature"] = temperature
    # M1: 显式关闭 Thinking。实测 agnes-3.0-flash 默认已关，但 distributor 渠道
    # 会漂（探针见 m1/m1-log.md）；恒带此字段做渠道无关的 JSON 格式保险。
    # 注意：thinking:{disabled} / enable_thinking:false 在该端点反而会触发 thinking，禁用。
    # Groq 拒收 reasoning 字段（HTTP 400: property 'reasoning' is unsupported）——
    # 仅对非 groq 端点发送；gpt-oss 系默认无 thinking，输出即最终答案。
    # 注意：该字段对部分端点（本地 :7863）无效但无害；真正的开关是
    # extra_body 里的 reasoning_effort（见下）。
    if "api.groq.com" not in base_url:
        body["reasoning"] = {"enabled": False}
    if extra_body:
        body.update(extra_body)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    started = time.perf_counter()
    last_status: int | None = None
    for attempt in range(max_retries):
        backoff = min(1.0 * (2**attempt), 16.0) + random.uniform(0, 0.5)
        try:
            r = _CLIENT.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            if attempt < max_retries - 1:
                print(f"[retry {attempt + 1}/{max_retries}] transport error: {e}", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise RuntimeError(f"Model connection failed after {max_retries} attempts: {e}") from None
        if r.status_code in _RETRYABLE and attempt < max_retries - 1:
            print(f"[retry {attempt + 1}/{max_retries}] HTTP {r.status_code}", file=sys.stderr)
            time.sleep(backoff)
            continue
        last_status = r.status_code
        if r.is_error:
            raise RuntimeError(
                f"Model provider returned HTTP {r.status_code}: {r.text[:500]}; no action executed."
            )
        latency_ms = round((time.perf_counter() - started) * 1000)
        return r.json(), latency_ms

    raise RuntimeError(
        f"Model unavailable after {max_retries} attempts (last HTTP {last_status})"
    )
