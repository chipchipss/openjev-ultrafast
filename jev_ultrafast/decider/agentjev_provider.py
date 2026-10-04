"""AgentJev-0.6B decision provider (aimeigaoshou/agent-jev, HTTP :8149).

Server: clone github.com/malevrigns/agent-jev, wrap FP32 weights into a torch
checkpoint, then `python -m jev_service.server --checkpoint ... --model-path
Qwen/Qwen3-0.6B --temperatures temperatures.json --port 8149`.

Contract mapping (same semantics as laya_provider):
  - operation choice over multi-candidate ops + controls + DONE/BLOCKED
  - single-candidate target ops: deterministic, no question (缺陷#11 rule)
  - target invalid -> ValueError (Runtime turns it into StalePage)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from .action_space import action_space

AGENTJEV_URL = os.environ.get("AGENTJEV_URL", "http://127.0.0.1:8149")


def _post(payload: dict, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(
        AGENTJEV_URL.rstrip("/") + "/api/evaluate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _state_payload(state: dict, history: list) -> dict:
    return {
        "page": {"url": state.get("url"), "title": state.get("title"),
                 "text": (state.get("text") or "")[:1500]},
        "recent_actions": [
            {"action": h.get("action"), "kind": h.get("kind"), "text": h.get("text"),
             "outcome": h.get("outcome")}
            for h in history[-10:]
        ],
    }


def _opt(label: str, a: dict) -> str:
    v = a.get("current_value", a.get("value", ""))
    return f"{label} | current: {v}" if v else label


def decide_agentjev(state: dict, goal: str, history: list) -> dict:
    actions = state.get("actions", [])[:30]
    elements, targets, controls = action_space(actions)

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

    questions = [
        {"id": "operation", "type": "choice",
         "question": f"Advance the goal: {goal}. Pick ONE operation.",
         "options": operations},
    ]
    for op, cands in multi.items():
        questions.append({
            "id": op.lower() + "_target", "type": "choice",
            "question": f"Which element is the best target for {op}? Goal: {goal}",
            "options": {idx: _opt(a["label"].split(" → ")[0][:80], a)
                        for idx, a in cands.items()},
        })

    started = time.perf_counter()
    result = _post({"state": _state_payload(state, history), "questions": questions})
    latency_ms = round((time.perf_counter() - started) * 1000)

    answers = {a["id"]: a for a in result["answers"]}
    op_answer = answers["operation"]
    operation = op_answer["value"]
    op_probs = {k: float(v) for k, v in op_answer["distribution"].items()}

    target = None
    target_answer = None
    probabilities = dict(op_probs)
    if operation in multi:
        sent = multi[operation]
        tgt_answer = answers.get(operation.lower() + "_target")
        if tgt_answer is None or tgt_answer["value"] not in sent:
            raise ValueError(f"agentjev target {tgt_answer['value'] if tgt_answer else None!r} not in {op} candidates")
        target = tgt_answer["value"]
        tgt_probs = {k: float(v) for k, v in tgt_answer["distribution"].items()}
        target_answer = {"choice": target, "confidence": max(tgt_probs.values()), "probabilities": tgt_probs}
        choice = sent[target]["id"]
        probabilities = {a["id"]: tgt_probs.get(idx, 0.0) for idx, a in sent.items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = op_probs.get(operation, op_answer.get("top_probability", 0.0))

    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": op_answer.get("top_probability", max(op_probs.values())),
        "probabilities": probabilities,
        "operation_probabilities": op_probs,
        "target_probabilities": (target_answer or {}).get("probabilities", {}),
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "model": "agentjev-0.6b",
        "usage": result.get("server_usage", {}),
        "latency_ms": latency_ms,
    }
