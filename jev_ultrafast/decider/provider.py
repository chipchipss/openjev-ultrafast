"""Decision Provider registry.

关联硬约束：
  H2  Decision 层必须与 Runtime 解耦
  A7  Decision Contract = (operation, target)

目标：Runtime 不再知道具体模型是谁。
"""
from __future__ import annotations

import os
from typing import Callable, Protocol


Decision = dict  # 见 specs/decision.schema.json
DecideFn = Callable[[dict, str, list], Decision]


class DecisionProvider(Protocol):
    """Decision Provider 契约。

    任何 provider 必须：
      - 接受 (observation, goal, history)
      - 返回符合 specs/decision.schema.json 的 dict
      - 抛 RuntimeError 表示连接/服务失败（agent 会转 StalePage）
    """
    name: str
    def decide(self, observation: dict, goal: str, history: list) -> Decision:
        ...


_PROVIDERS: dict[str, DecideFn] = {}


def register_provider(name: str, fn: DecideFn) -> None:
    """注册 provider 实现。fn 签名 (observation, goal, history) -> decision。"""
    if not name:
        raise ValueError("provider name required")
    if not callable(fn):
        raise TypeError(f"provider {name!r}: fn must be callable")
    _PROVIDERS[name] = fn


def list_providers() -> list[str]:
    return sorted(_PROVIDERS.keys())


def get_provider(name: str) -> DecideFn:
    if name not in _PROVIDERS:
        raise ValueError(
            f"unknown provider: {name!r}. registered: {list_providers()}"
        )
    return _PROVIDERS[name]


def decide(
    observation: dict,
    goal: str,
    history: list,
    mode: str | None = None,
) -> Decision:
    """Decision 层统一入口。

    按 mode（默认 DECIDER_MODE env）选择 provider 并返回 decision。
    Runtime 只调 decide()，不知道具体 provider 是谁。
    """
    name = mode or os.environ.get("DECIDER_MODE", "openai")
    fn = get_provider(name)
    return fn(observation, goal, history)
