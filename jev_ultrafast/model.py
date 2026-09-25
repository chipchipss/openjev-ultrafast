"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import os
import time
import urllib.request

import httpx

from .questions import NEXT_ACTION, TARGET, TEXT_VALUE
from .decider.provider import register_provider, decide, list_providers

# --- M1: Decision 层替换为 decider ---
from .decider.choose_2b import choose as _choose_2b
from .decider.field_text_2b import field_text as _field_text_2b

CLIENT = httpx.Client(http2=True, timeout=90)


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            raise RuntimeError(
                f"Model provider returned HTTP {response.status_code}: {response.text[:500]}; no action executed."
            )
        data = response.json()
        return data
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-3
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls

def _candidate_filter(elements):
    """截断候选元素：数量 + label 长度。L2 截断层；未来 L2 演进为相关性排序（M3）或模型
    判断（M8）时替换本实现，接口不变。"""
    max_n = int(os.environ.get("DECIDER_MAX_ELEMENTS", "25"))
    max_l = int(os.environ.get("DECIDER_MAX_LABEL_CHARS", "80"))

    def trim(el):
        if isinstance(el, dict) and isinstance(el.get("label"), str):
            if len(el["label"]) > max_l:
                return {**el, "label": el["label"][:max_l] + "…"}
        return el

    return [trim(e) for e in elements[:max_n]]


def choose_typesafe(state, goal, history):
    """原 TypeSafe 实现。M1 保留为参考/回退。"""
    MAX_TARGETS_PER_OP = 20
    elements, targets, controls = action_space(state["actions"])
    # decider-2B 要求 choice criteria ≥ 2 项；单候选的 target 头会触发 422，先过滤。
    valid_targets = {op: dict(list(c.items())[:MAX_TARGETS_PER_OP]) for op, c in targets.items() if len(c) >= 2}
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in valid_targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in valid_targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": {"url": state.get("url"), "title": state.get("title"), "text": (state.get("text") or "")[:1500]},
            "elements": _candidate_filter(elements),
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    url = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1/systemone")
    key = os.environ.get("TYPESAFE_API_KEY", "local")
    started = time.perf_counter()
    try:
        result = post_json(url, key, body)
    except RuntimeError as e:
        import json as _json
        from pathlib import Path as _Path

        _Path(r"C:\Users\Administrator\openjev-ultrafast\m4a\_last_typesafe_body.json").write_text(
            _json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    # 被过滤的 target 头（< 2 候选）不出现在 questions 里；若模型仍选中它即契约违例。
    if operation in targets and operation not in valid_targets:
        raise ValueError(f"operation {operation} has < 2 targets; contract violation")
    target = None
    target_answer = None
    probabilities = {}
    if operation in valid_targets:
        # Unused target heads cannot cause an action. Validate against the criteria actually sent
        # (valid_targets is the truncated set decider scored), not the full targets dict.
        sent = valid_targets[operation]
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), sent)
        target = target_answer["choice"]
        choice = sent[target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in sent.items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text_typesafe(context):
    """原 TypeSafe 实现。M1 保留为参考/回退。"""
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in base else {"reasoning": {"effort": "low"}}
    if os.environ.get("TEXT_MODEL_REASONING") == "none":
        reasoning = {"reasoning": {"enabled": False}}
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
    )
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }


# --- M1: 委托给 decider（agent.py 的 import 不变） ---

def _typesafe_provider(state, goal, history):
    return choose_typesafe(state, goal, history)

def _openai_provider(state, goal, history):
    return _choose_2b(state, goal, history)

register_provider("typesafe", _typesafe_provider)
register_provider("openai", _openai_provider)

def choose(state, goal, history):
    from .browser import StalePage
    try:
        return decide(state, goal, history)
    except RuntimeError as e:
        raise StalePage(f"Decider connection failed: {e}") from None

def field_text(context):
    """M1: 委托给 Text Helper。见 decider/field_text_2b.py。"""
    return _field_text_2b(context)
