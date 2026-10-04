"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import os
import re
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
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[],
                           node=node)  # M1.5 机制②：scoring 需要判"本轮新出现"
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

# M16：展开/多选类控件是"同形诱饵"（与目标字段同 role 同位置，但语义是展开更多）。
_EXPANSION_RE = re.compile(
    r"\belse\b|select multiple|multiple airports|nearby airports|toggle nearby"
    r"|more options|add another|advanced",
    re.I,
)
# M16b：破坏性控件（Reset / Clear / Delete…）。点了会清空已填好的表单，
# 且往往看起来像个普通按钮（Flights v18 实况：模型连点 3 次 Reset，
# 把已填好的出发地/目的地/日期全清掉 → 全项检查 false）。
_DESTRUCTIVE_RE = re.compile(
    r"\breset\b|\bclear\b|\bdelete\b|\bremove\b|\btrash\b|start over",
    re.I,
)


def _element_score(e, new_nodes=None):
    """候选元素排序权重：可输入控件 > 按钮 > 其他 > 链接；新出现 node 加显著 bonus。

    缺陷#11 Fix2：context (_candidate_filter) 与 criteria (choose_typesafe)
    共用同一排序函数，保证模型看到的两个列表同源同序。
    M1.5 机制②：new_nodes（上一轮不可见、本轮出现的 node id 集合）加
    NEW_NODE_BOOST——autocomplete 建议/弹层是"世界刚提供的选项"，
    s002 实况：填入后建议项埋在 25 个元素里，2B 看不见。
    env M15_NEW_NODE_BOOST=0 关闭（默认 120：搜索框 100 < 新建议 220）。
    M16：展开/多选类控件（"Where else?"、"Select multiple airports"、"Add another"
    等）是诱饵——它们与目标字段同形但语义是"展开更多"，2B 常误选
    （Flights 实况：模型把 "Where else?" 当成目的地字段）。给负权把它们压到
    链接之下，但保留在候选里（不删，避免改变世界）。
    env M16_EXPANSION_PENALTY=0 关闭（默认 150）。
    """
    score = 0
    role = e.get("role", "")
    if role in ("textbox", "searchbox", "combobox"):
        score = 100
    elif role == "button":
        score = 50
    elif role == "link":
        score = -10
    if _EXPANSION_RE.search(e.get("label") or ""):
        score -= int(os.environ.get("M16_EXPANSION_PENALTY", "150"))
    if _DESTRUCTIVE_RE.search(e.get("label") or ""):
        score -= int(os.environ.get("M16_DESTRUCTIVE_PENALTY", "200"))
    return score


def _candidate_filter(elements, new_nodes=None):
    """候选元素排序 + 截断。

    保持接口不变。优先把可输入/可操作的控件放到前面，
    避免页面 logo、品牌链接等 DOM 前部元素抢占小模型注意力。
    排序权重与 criteria 同源（_element_score，缺陷#11 Fix2）。
    M1.5 机制②：new_nodes 本轮新出现的 node 加显著性权重（同源）。
    """
    max_n = int(os.environ.get("DECIDER_MAX_ELEMENTS", "25"))
    max_l = int(os.environ.get("DECIDER_MAX_LABEL_CHARS", "80"))

    ranked = sorted(elements, key=lambda e: _element_score(e, new_nodes), reverse=True)

    def trim(el):
        if isinstance(el, dict) and isinstance(el.get("label"), str):
            if len(el["label"]) > max_l:
                return {**el, "label": el["label"][:max_l] + "…"}
        return el

    return [trim(e) for e in ranked[:max_n]]

def choose_typesafe(state, goal, history):
    """原 TypeSafe 实现。M1 保留为参考/回退。"""
    MAX_TARGETS_PER_OP = 20
    # M1.5 机制②：本轮新出现的 node（上轮不可见）→ 显著性权重。
    # state["prev_node_ids"] 由 agent.predict 维护；离线/直调时缺省 None（关闭）。
    prev_ids = state.get("prev_node_ids")
    if prev_ids is not None:
        new_nodes = {str(a.get("node")) for a in state["actions"]} - {str(n) for n in prev_ids}
    else:
        new_nodes = None
    elements, targets, controls = action_space(state["actions"])
    # 缺陷#12（M1.5 机制①推广）：刚执行且无效果的 action（no_effect = 世界
    # 证明该动作无法推进，DOM/URL 均无变化）对应的 choice 本轮从 action space
    # 剔除——重做不可能推进，留它只会成为吸引子。原 #12 仅 fill；机制①推广到
    # 全部 kind（n001 重复点无变化链接 / l002 短页连滚同构）。
    # env 开关 M15_ALL_KIND_STALE=0 回退到 #12 原行为（fill only）。
    stale_kinds = ({"fill"} if os.environ.get("M15_ALL_KIND_STALE", "1") != "1"
                   else {"fill", "click", "scroll"})
    stale_ids = {
        h.get("choice")
        for h in history[-2:]
        if h.get("kind") in stale_kinds
        and h.get("outcome", {}).get("status") == "no_effect"
        and h.get("choice")
    }
    # M1.5 机制③（SPA toggle 破环）：某动作执行前的页态指纹在其执行时刻
    # 已存在于 visited_fps（该时刻之前见过的所有页态）→ 它把世界带回旧态，
    # 是环边，剔除——无论 pc 真假（MDN/w3c 下拉开合让 pc 恒 True，
    # no_effect 判据对 SPA toggle 失明，s003/s005 实况）。
    # 判据纯世界语言：回访已见状态 = 无进展。env M15_CYCLE_CUT=0 关闭。
    if os.environ.get("M15_CYCLE_CUT", "1") == "1":
        visited = state.get("visited_fps")
        if visited:
            for h in history[-3:]:
                fp_before = h.get("page_fp_before")
                if (fp_before is not None and fp_before in visited
                        and h.get("page_changed") and h.get("choice")):
                    stale_ids.add(h.get("choice"))
    if stale_ids:
        targets = {
            op: {t: a for t, a in c.items() if a.get("id") not in stale_ids}
            for op, c in targets.items()
        }
        targets = {op: c for op, c in targets.items() if c}
        # control 类（SCROLL_DOWN/WAIT 等）走 controls 字典，同样按 id 剔除
        controls = {op: a for op, a in controls.items() if a.get("id") not in stale_ids}
        # context 同步剔除（缺陷#11 Fix2 同源原则）：element.index 就是
        # action.node 的字符串形式，经 node→id 映射找到被剔除元素。
        dead_nodes = {a["node"] for a in state["actions"]
                      if a.get("id") in stale_ids and a.get("node") is not None}
        elements = [e for e in elements if e["index"] not in {str(n) for n in dead_nodes}]
    # 缺陷#11：不再按 len(c)>=2 过滤 operation——单候选 op 也必须保留在
    # action space（否则 Runtime 给模型的世界缺能力：首页唯一搜索框的
    # TYPE_TEXT 曾被整层删掉）。单候选 target 不发问（decider choice 需 ≥2 项），
    # 在响应解析处确定性落定。criteria 排序与 context 同源（_element_score）。
    valid_targets = {
        op: dict(sorted(c.items(),
                        key=lambda kv: -_element_score(kv[1], new_nodes))[:MAX_TARGETS_PER_OP])
        for op, c in targets.items()
    }
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in valid_targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE=f"Every requirement is visibly satisfied: {goal}",
                      BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    max_l = int(os.environ.get("DECIDER_MAX_LABEL_CHARS", "80"))
    for operation, candidates in valid_targets.items():
        # 缺陷#11：单候选 target 不发问——action space 已唯一，属确定性解析，
        # 不消耗模型不确定度。≥2 候选才作为独立 choice 问题交给模型。
        if len(candidates) < 2:
            continue
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    # 与 context 元素同一 label 来源：action_space 归一化
                    # （split(' → ')[0]）+ 同一 80 字符截断。不用 elements[int(index)-1]
                    # 位置反查——context 剔除（缺陷#12）后位置会漂移。
                    "element": f"[{index}] {a['label'].split(' → ')[0][:max_l]}",
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
            "elements": _candidate_filter(elements, new_nodes),
            "recent_actions": [
                {
                    "action": h.get("action"),
                    "kind": h.get("kind"),
                    "text": h.get("text"),
                    "outcome": h.get("outcome"),
                }
                for h in history[-10:]
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
    target = None
    target_answer = None
    probabilities = {}
    if operation in valid_targets:
        sent = valid_targets[operation]
        if len(sent) == 1:
            # 缺陷#11：单候选确定性解析——不是模型的选择，confidence 恒 1.0
            # 表示"由 action space 唯一决定"。
            target = next(iter(sent))
            target_answer = {"choice": target, "confidence": 1.0,
                             "probabilities": {target: 1.0}}
            choice = sent[target]["id"]
            probabilities = {choice: 1.0}
        else:
            # Unused target heads cannot cause an action. Validate against the
            # criteria actually sent (valid_targets is the truncated set decider
            # scored), not the full targets dict.
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

# Laya（encoder 决策头，~50-100ms/步，显存 ~2GB）：DECIDER_MODE=laya 启用。
# 延迟 import：未装 laya 包时不影响其他 provider。
def _laya_provider(state, goal, history):
    from .decider.laya_provider import decide_laya
    return decide_laya(state, goal, history)

register_provider("laya", _laya_provider)

# Laya 前置 + decider 回退：Laya 是 encoder 单前向（实测 32ms/步），decider-2B 是
# 自回归（实测 3.3~4.0s/步，慢 ~110×）。先问 Laya；它抛错 / 决策结构非法 / 置信度
# 低于阈值时才回退 decider。
# 为什么必须先校验再返回：agent 侧对非法决策走 StalePage 重试，而重试会再问同一个
# provider —— 这里放行非法决策就等于让同一个坏决策死循环（缺陷#18 同款教训）。
# 用 DECIDER_MODE=laya_decider 启用。
LAYA_MIN_CONF = float(os.environ.get("LAYA_MIN_CONF", "0.5"))
# 被 decider 否决过一次哨兵的 goal → 整轮降级为 decider-only（见下方注释）。
# 按 goal 记而不是全局单标志：一个进程一个 task（runner 就是这样跑的），但按 goal
# 记更稳——将来一个进程跑多 task 时不会互相污染。
_DEMOTED_GOALS: set = set()


def _laya_then_decider(state, goal, history):
    if goal in _DEMOTED_GOALS:
        return _typesafe_provider(state, goal, history)
    d = None
    try:
        d = _laya_provider(state, goal, history)
    except Exception:
        d = None
    if isinstance(d, dict):
        try:
            from .decision_validator import validate as _validate
            ok = _validate(d, state).valid
        except Exception:
            ok = False
        conf = d.get("confidence")
        # DONE/BLOCKED 决定整轮结束，不吃前置：交 decider 复核。
        # 依据（wiki-laya-v1~v3 实测）：laya 在**空搜索页**上以 conf=0.7395 判 DONE，
        # 0.5 门槛直接放行 → 3 步收口、目标 URL 没拿到；而 decider 同任务基线 20 步达成。
        # 置信度阈值挡不住"自信的错判"，规则性门槛才挡得住。
        serious = d.get("operation") in {"DONE", "BLOCKED"}
        if ok and not serious and (conf is None or conf >= LAYA_MIN_CONF):
            return d
        if serious:
            d2 = _typesafe_provider(state, goal, history)
            # 复核被否决（decider 说的和前端不一样）→ 整轮降级，别让前端反复提同一个
            # 哨兵（wiki-laya-v4 实况：22 次哨兵调用 / 229s，比纯 decider 的 138s 还慢）。
            if d2.get("operation") != d.get("operation"):
                _DEMOTED_GOALS.add(goal)
            return d2
    return _typesafe_provider(state, goal, history)


register_provider("laya_decider", _laya_then_decider)

# AgentJev-0.6B（aimeigaoshou/agent-jev，HTTP :8149，零解码单前向）：
# DECIDER_MODE=agentjev 启用。延迟 import：服务未起时其他 provider 不受影响。
def _agentjev_provider(state, goal, history):
    from .decider.agentjev_provider import decide_agentjev
    return decide_agentjev(state, goal, history)

register_provider("agentjev", _agentjev_provider)

def choose(state, goal, history):
    from .browser import StalePage
    from . import skills
    # M16：确定性技能层——goal 里字面可判的决策直接短路（省一次 2B 调用，
    # 且确定性正确）。未命中一律回落模型，行为不变。
    hit = skills.route(state, goal, history)
    if hit is not None:
        return hit
    try:
        result = decide(state, goal, history)
        return result
    except RuntimeError as e:
        raise StalePage(f"Decider connection failed: {e}") from None

def field_text(context):
    """M1: 委托给 Text Helper。见 decider/field_text_2b.py。"""
    return _field_text_2b(context)
