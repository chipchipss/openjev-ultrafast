"""Laya 决策 provider（laya-browser 微调 checkpoint，encoder 单前向）。

关键差异 vs decider-2B：
  - 非自回归 encoder：一次前向出全部问题答案，~50-60ms/步，显存 ~2GB
  - 官方 /v1/systemone 兼容（laya-serve），但 serve 子进程在本机起不来
    （uvicorn lifespan gate 问题），故走进程内 SDK 直调
  - laya 的 state 结构与 TypeSafe wire 的 state 结构不同：elements 必须在
    option list 里（不在 state JSON 内）——这是 laya-browser 训练时最大的
    input-format 教训（docs/finetune_browser_agent.md），照做
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .action_space import action_space

LAYA_DEVICE = os.environ.get("LAYA_DEVICE", "cuda")
LAYA_MODEL = os.environ.get(
    "LAYA_BROWSER_MODEL",
    # 默认 v17s（322M, 官方 live suite 62%）：比 421M 快 2 倍、同档准确率
    str(Path(__file__).resolve().parents[2] / "models" / "laya-browser" / "v17s"),
)

_agent = None


def _agent_cached():
    global _agent
    if _agent is None:
        import laya

        _agent = laya.load(LAYA_MODEL, device=LAYA_DEVICE)
        # laya-browser 训练时 head 上限 768（默认 256 会截断候选 label）
        _agent.cfg["head_max_len"] = _agent.cfg.get("head_max_len_train", 768)
    return _agent


def _laya_state(state: dict, history: list) -> dict:
    return {
        "page": {"url": state.get("url"), "title": state.get("title"),
                 "text": (state.get("text") or "")[:1500]},
        "recent_actions": [
            {"action": h.get("action"), "kind": h.get("kind"), "text": h.get("text"),
             "outcome": h.get("outcome")}
            for h in history[-10:]
        ],
    }


def _opt(label: str, a: dict) -> dict:
    return {"element": f"{label}", "current_value": a.get("current_value", a.get("value", ""))}


def decide_laya(state: dict, goal: str, history: list) -> dict:
    """provider 契约实现：(observation, goal, history) -> decision。"""
    import laya as _laya_mod  # noqa: F401  (确保依赖在)

    actions = state.get("actions", [])[:30]
    elements, targets, controls = action_space(actions)
    agent = _agent_cached()

    # 单候选 op 不发问（与 choose_typesafe 缺陷#11 同规则）
    multi = {op: c for op, c in targets.items() if len(c) >= 2}
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {k: labels[k] for k in multi}
    operations.update({k: v["label"] for k, v in controls.items()})
    operations.update(DONE=f"Every requirement is visibly satisfied: {goal}",
                      BLOCKED="No supported operation can progress.")

    questions = {
        "operation": {"type": "choice", "instructions": f"Advance the goal: {goal}",
                      "criteria": operations},
    }
    for op, cands in multi.items():
        questions[op.lower() + "_target"] = {
            "type": "choice",
            "instructions": f"Which element is the best target for {op}? Goal: {goal}",
            "criteria": {idx: _opt(a["label"].split(" → ")[0][:80], a)
                         for idx, a in cands.items()},
        }

    started = time.perf_counter()
    result = agent.predict(_laya_state(state, history), questions)
    latency_ms = round((time.perf_counter() - started) * 1000)

    answers = result["answers"]
    op_answer = answers["operation"]
    operation = op_answer["choice"]
    probabilities = dict(op_answer.get("probs") or {})

    target = None
    target_answer = None
    choice: str
    if operation in multi:
        sent = multi[operation]
        tgt_answer = answers.get(operation.lower() + "_target", {})
        tgt_choice = tgt_answer.get("choice")
        if tgt_choice not in sent:
            # target 无效 → 决策非法（与 choose_2b 同语义，Runtime 转 StalePage）
            raise ValueError(f"laya target {tgt_choice!r} not in {op} candidates")
        target = tgt_choice
        target_answer = {"choice": target, "confidence": tgt_answer.get("confidence", 0.0),
                         "probabilities": tgt_answer.get("probs") or {}}
        choice = sent[target]["id"]
        probabilities = {a["id"]: (tgt_answer.get("probs") or {}).get(idx, 0.0)
                         for idx, a in sent.items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = op_answer.get("confidence", 0.0)

    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": op_answer.get("confidence", 0.0),
        "probabilities": probabilities,
        "operation_probabilities": op_answer.get("probs") or {},
        "target_probabilities": (target_answer or {}).get("probabilities", {}),
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "model": "laya-browser/v17s",
        "usage": result.get("usage", {}),
        "latency_ms": latency_ms,
    }
