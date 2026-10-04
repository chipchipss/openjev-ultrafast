"""2B Decider。替换 jev-ultrafast 的 model.py:choose()。

关联硬约束：
  A7  operation / target 分离
  D8  三级一致性（由 _map_choice 保证）
  D9  operation_confidence / target_confidence 分层
  H2  Decision 层与 Runtime 解耦

接口契约（与 model.py:choose 对齐）：
  choose(state, goal, history) -> decision
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ._http import post_chat
from .action_space import action_space

from ..anyjev_rotation import DEFAULT_LOG_MARGIN, rotate_vote

_PROMPTS = Path(__file__).parent.parent / "prompts"
SENTINELS = frozenset({"DONE", "BLOCKED"})

_OPERATION_DESCRIPTIONS = {
    "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
    "TYPE_TEXT": "Enter or replace text in an editable field. A helper supplies the value from the goal.",
    "SELECT": "Select an observed dropdown value.",
}
_CONTROL_DESCRIPTIONS = {
    "SCROLL_DOWN": "Scroll the page down.",
    "SCROLL_UP": "Scroll the page up.",
    "WAIT": "Wait for the page to update.",
}
_SENTINEL_DESCRIPTIONS = {
    "DONE": "Every requirement is visibly satisfied.",
    "BLOCKED": "No supported operation can progress.",
}


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


def _render_elements(elements: list[dict]) -> str:
    if not elements:
        return "(no interactive elements)"

    lines = []

    for el in elements:
        ops = "/".join(el["operations"])
        parts = [f"[{el['index']}] {el['label']} [{ops}]"]

        if el.get("value"):
            parts.append(f'value="{el["value"]}"')

        for key in ("checked", "selected", "expanded"):
            if key in el:
                parts.append(f"{key}={el[key]}")

        lines.append(" ".join(parts))

    return "\n".join(lines)


def _render_operations(targets: dict, controls: dict) -> str:
    lines = []

    for op in targets:
        lines.append(
            f"- {op}: {_OPERATION_DESCRIPTIONS.get(op, op)}"
        )

    for op in controls:
        lines.append(
            f"- {op}: {_CONTROL_DESCRIPTIONS.get(op, op)}"
        )

    for op in ("DONE", "BLOCKED"):
        lines.append(
            f"- {op}: {_SENTINEL_DESCRIPTIONS[op]}"
        )

    return "\n".join(lines)


def _render_history(history: list[dict], limit: int = 10) -> str:
    if not history:
        return "(no actions yet)"

    lines = []

    for h in history[-limit:]:
        parts = [
            f"{h.get('step', '?')}.",
            h.get("kind", "?"),
            h.get("action", "?"),
        ]

        if h.get("text"):
            parts.append(f'text="{h["text"]}"')

        if h.get("page_changed") is not None:
            parts.append(
                f"page_changed={h['page_changed']}"
            )

        lines.append(" ".join(parts))

    return "\n".join(lines)


def _render_page(state: dict) -> list[str]:
    """Current page 段——与 m4a/prepare_sft._user_prompt 逐字节对齐（SFT 训练格式）。
    缺 url/title/text 则整段省略（旧页态无快照时保持向后兼容）。"""
    if not (state.get("url") or state.get("title") or state.get("text")):
        return []
    return [
        "Current page:",
        f"url: {state.get('url', '')}",
        f"title: {state.get('title', '')}",
        "text:",
        (state.get("text") or "")[:1500],
        "",
    ]


def _build_user_prompt(
    state: dict,
    goal: str,
    history: list[dict],
    elements: list[dict],
    targets: dict,
    controls: dict,
) -> str:
    return "\n".join(
        [
            f"Goal: {goal}",
            "",
            *_render_page(state),
            "Recent action history:",
            _render_history(history),
            "",
            "Available operations:",
            _render_operations(targets, controls),
            "",
            "Elements:",
            _render_elements(elements),
            "",
            "Choose the next operation and target. Reply with one JSON object only.",
        ]
    )


def _parse_response(content: str) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Decider returned non-JSON: {e}"
        ) from None

    if not isinstance(parsed, dict):
        raise ValueError(
            "Decider response must be a JSON object"
        )

    if "operation" not in parsed:
        raise ValueError(
            "Decider response missing 'operation'"
        )

    return parsed


def _map_choice(
    operation: str,
    target,
    targets: dict,
    controls: dict,
) -> tuple[str, str | None]:
    """D8 三级一致性的实现处：由 (operation, target) 唯一确定 choice."""

    if operation in SENTINELS:
        return operation, None

    if operation in targets:
        if target is None:
            raise ValueError(
                f"operation {operation} requires a target"
            )

        if target not in targets[operation]:
            raise ValueError(
                f"target {target!r} not in {operation} candidates"
            )

        return targets[operation][target]["id"], target

    if operation in controls:
        return controls[operation]["id"], None

    raise ValueError(
        f"unknown operation {operation!r}"
    )


def _confidence(parsed: dict) -> tuple[float, float | None]:
    oc = parsed.get("operation_confidence")
    tc = parsed.get("target_confidence")

    oc = (
        float(oc)
        if isinstance(oc, (int, float))
        else 0.0
    )

    oc = max(0.0, min(1.0, oc))

    if tc is not None and isinstance(tc, (int, float)):
        tc = max(0.0, min(1.0, float(tc)))
    else:
        tc = None

    return oc, tc


def _read_once(
    actions: list[dict],
    state: dict,
    goal: str,
    history: list[dict],
    *,
    base_url: str,
    model: str,
    api_key: str,
    system: str,
) -> dict:
    """一轮读取：按给定顺序给候选编号后问一次 decider。

    `actions` 的顺序决定 action_space 的编号（1..N），也就是模型看到的**选项位置** ——
    这正是 L0 旋转要置换的东西，所以整轮读取必须按 actions 参数化。
    """
    elements, targets, controls = action_space(actions)

    user = _build_user_prompt(
        state,
        goal,
        history,
        elements,
        targets,
        controls,
    )

    messages = [
        {
            "role": "system",
            "content": system,
        },
        {
            "role": "user",
            "content": user,
        },
    ]

    started = time.perf_counter()

    result, _ = post_chat(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=messages,
        # 可插拔模型：思考型（glm/kimi/deepseek-reasoner 等）的 reasoning
        # token 也计入 max_tokens，512 会被截断。默认 2048 覆盖绝大多数
        # OpenAI 兼容模型；旧 2B 本地服务不受影响（输出远小于此）。
        max_tokens=int(os.environ.get("DECIDER_MAX_TOKENS", "2048")),
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    latency_ms = round(
        (time.perf_counter() - started) * 1000
    )

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(
            "Decider returned unexpected response shape"
        ) from None

    parsed = _parse_response(content)

    operation = parsed["operation"]
    target = parsed.get("target")

    choice, norm_target = _map_choice(
        operation,
        target,
        targets,
        controls,
    )

    oc, tc = _confidence(parsed)

    return {
        "parsed": parsed,
        "operation": operation,
        "choice": choice,
        "target": norm_target,
        "operation_confidence": oc,
        "target_confidence": tc,
        "result": result,
        "messages": messages,
        "latency_ms": latency_ms,
    }


def _to_decision(
    read: dict,
    *,
    model: str,
    extra: dict | None = None,
) -> dict:
    """把一轮读取摊平成 agent 期望的 decision dict。"""
    operation = read["operation"]
    norm_target = read["target"]
    oc = read["operation_confidence"]
    tc = read["target_confidence"]
    choice = read["choice"]

    confidence = (
        oc
        if tc is None
        else min(oc, tc)
    )

    out = {
        "choice": choice,
        "operation": operation,
        "target": norm_target,

        # D9：operation / target 分层置信度
        "operation_confidence": oc,
        "target_confidence": tc,

        # ★ 新增：前端 app.js 所需要的概率字段
        #
        # 当前 2B Decider 返回的是单一最终选择，
        # 因此这里采用 sparse representation：
        # 只记录模型实际选择的 operation / target。
        "operation_probabilities": {
            operation: oc,
        },
        "target_probabilities": (
            {
                norm_target: tc,
            }
            if norm_target is not None and tc is not None
            else {}
        ),

        # 兼容 agent.py 旧字段
        # （M5 校准接入后可废弃）
        "confidence": confidence,
        "probabilities": {
            choice: confidence,
        },

        # 元数据
        "raw_answers": read["parsed"],
        "model": model,
        "usage": read["result"].get("usage", {}),
        "latency_ms": read["latency_ms"],
        "request": {
            "model": model,
            "messages": read["messages"],
        },
    }
    if extra:
        out.update(extra)
    return out


def choose(
    state: dict,
    goal: str,
    history: list[dict],
) -> dict:
    actions = state.get("actions", [])[:30]

    base_url = _env(
        "DECIDER_2B_BASE_URL",
        required=True,
    )

    model = _env(
        "DECIDER_2B_MODEL",
        "decider-2b",
    )

    api_key = _env(
        "DECIDER_2B_API_KEY",
        "",
    )

    system = _load_prompt("next_action.txt")

    first = _read_once(
        actions,
        state,
        goal,
        history,
        base_url=base_url,
        model=model,
        api_key=api_key,
        system=system,
    )

    # L0 旋转（AnyJev，见 anyjev_rotation）：候选的**先后**会影响答案（上游实测 raw
    # 顺序翻转率 0.230），把候选循环移位各问一遍即可精确抵消位置偏置。只对"选某个
    # 元素"的决策有意义 —— DONE/BLOCKED 没有位置可换，首轮给出就直接采纳。
    # 默认关闭（DECIDER_ROTATION 未设 = 0）；打开后每步多花 1..S-1 次 decider 调用。
    try:
        shifts = int(os.environ.get("DECIDER_ROTATION", "0"))
    except ValueError:
        shifts = 0
    if shifts <= 1 or first["choice"] in SENTINELS:
        return _to_decision(first, model=model)

    index_of = {a.get("id"): i for i, a in enumerate(actions)}
    base_pos = index_of.get(first["choice"])
    seen: dict[int, dict] = {}
    if base_pos is not None:
        seen[base_pos] = first
    identity = list(range(len(actions)))

    def read_one(order: list[int]) -> int | None:
        if order == identity:
            return base_pos               # 原序那一轮 = 首轮，复用，不重复调用
        permuted = [actions[i] for i in order]
        r = _read_once(
            permuted,
            state,
            goal,
            history,
            base_url=base_url,
            model=model,
            api_key=api_key,
            system=system,
        )
        if r["choice"] in SENTINELS:
            return None                   # 这一轮改判哨兵 → 弃权，不投票
        pos = index_of.get(r["choice"])
        if pos is None:
            return None
        seen.setdefault(pos, r)
        return pos

    winner, info = rotate_vote(
        len(actions),
        read_one,
        shifts=shifts,
        threshold=float(
            os.environ.get("DECIDER_ROTATION_MARGIN", DEFAULT_LOG_MARGIN)
        ),
    )

    chosen = seen.get(winner) if winner is not None else None
    return _to_decision(chosen or first, model=model, extra={"rotation": info})


# ---------------------------------------------------------------------------
# Smoke（mock post_chat，无网络依赖）
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import sys

    # 直接 patch 当前执行模块自身（-m 时即 __main__），不 import 具名副本——
    # 平铺（decider/）与包内（jev_ultrafast/decider/）两种布局通用。
    mod = sys.modules[__name__]

    os.environ["DECIDER_2B_BASE_URL"] = "http://mock/v1"
    os.environ["DECIDER_2B_MODEL"] = "mock"

    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total

        total += 1

        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def fake_post(payload):
        def _f(
            *,
            base_url,
            model,
            api_key,
            messages,
            **kw,
        ):
            return (
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(payload)
                            }
                        }
                    ],
                    "usage": {},
                },
                1,
            )

        return _f

    def make_state():
        return {
            "url": "https://example.com",
            "title": "t",
            "text": "",
            "actions": [
                {
                    "id": "e1",
                    "kind": "fill",
                    "node": 12,
                    "role": "textbox",
                    "label": "Search",
                    "value": "",
                },
                {
                    "id": "e2",
                    "kind": "click",
                    "node": 12,
                    "role": "textbox",
                    "label": "Open Search",
                    "value": "",
                },
                {
                    "id": "e3",
                    "kind": "click",
                    "node": 42,
                    "role": "button",
                    "label": "Search",
                    "value": "",
                },
                {
                    "id": "e4",
                    "kind": "select",
                    "node": 88,
                    "role": "combobox",
                    "label": "Country → CH",
                    "value": "CH",
                    "current_value": "",
                },
                {
                    "id": "scroll_down",
                    "kind": "scroll",
                    "label": "Scroll down",
                    "delta": 560,
                },
                {
                    "id": "wait",
                    "kind": "wait",
                    "label": "Wait",
                },
            ],
        }

    # --- 1. CLICK ---
    mod.post_chat = fake_post(
        {
            "operation": "CLICK",
            "target": "2",
            "operation_confidence": 0.9,
            "target_confidence": 0.85,
        }
    )

    d = choose(
        make_state(),
        "search",
        [],
    )

    check(
        "CLICK choice",
        d["choice"] == "e3",
    )

    check(
        "CLICK operation",
        d["operation"] == "CLICK",
    )

    check(
        "CLICK target",
        d["target"] == "2",
    )

    check(
        "CLICK confidence min",
        d["confidence"] == 0.85,
    )

    check(
        "CLICK probabilities has choice",
        "e3" in d["probabilities"],
    )

    # 新增字段检查
    check(
        "CLICK operation probabilities",
        d["operation_probabilities"] == {
            "CLICK": 0.9
        },
    )

    check(
        "CLICK target probabilities",
        d["target_probabilities"] == {
            "2": 0.85
        },
    )

    # --- 2. TYPE_TEXT ---
    mod.post_chat = fake_post(
        {
            "operation": "TYPE_TEXT",
            "target": "1",
            "operation_confidence": 0.9,
            "target_confidence": 0.9,
        }
    )

    d = choose(
        make_state(),
        "search",
        [],
    )

    check(
        "TYPE_TEXT choice e1",
        d["choice"] == "e1",
    )

    # --- 3. SELECT ---
    mod.post_chat = fake_post(
        {
            "operation": "SELECT",
            "target": "3:1",
            "operation_confidence": 0.9,
            "target_confidence": 0.9,
        }
    )

    d = choose(
        make_state(),
        "x",
        [],
    )

    check(
        "SELECT choice e4",
        d["choice"] == "e4",
    )

    check(
        "SELECT target 3:1",
        d["target"] == "3:1",
    )

    # --- 4. SCROLL_DOWN ---
    mod.post_chat = fake_post(
        {
            "operation": "SCROLL_DOWN",
            "target": None,
            "operation_confidence": 0.7,
            "target_confidence": None,
        }
    )

    d = choose(
        make_state(),
        "x",
        [],
    )

    check(
        "SCROLL_DOWN choice scroll_down",
        d["choice"] == "scroll_down",
    )

    check(
        "SCROLL_DOWN target None",
        d["target"] is None,
    )

    check(
        "SCROLL_DOWN confidence = oc",
        d["confidence"] == 0.7,
    )

    # --- 5. WAIT ---
    mod.post_chat = fake_post(
        {
            "operation": "WAIT",
            "target": None,
            "operation_confidence": 0.8,
        }
    )

    d = choose(
        make_state(),
        "x",
        [],
    )

    check(
        "WAIT choice wait",
        d["choice"] == "wait",
    )

    # --- 6. DONE ---
    mod.post_chat = fake_post(
        {
            "operation": "DONE",
            "target": None,
            "operation_confidence": 0.95,
        }
    )

    d = choose(
        make_state(),
        "x",
        [],
    )

    check(
        "DONE choice DONE",
        d["choice"] == "DONE",
    )

    check(
        "DONE target None",
        d["target"] is None,
    )

    # --- 7. 非法 operation ---
    mod.post_chat = fake_post(
        {
            "operation": "HOVER",
            "target": None,
            "operation_confidence": 0.9,
        }
    )

    try:
        choose(
            make_state(),
            "x",
            [],
        )
        check(
            "unknown op raises",
            False,
        )
    except ValueError:
        check(
            "unknown op raises",
            True,
        )

    # --- 8. 非法 target ---
    mod.post_chat = fake_post(
        {
            "operation": "CLICK",
            "target": "99",
            "operation_confidence": 0.9,
        }
    )

    try:
        choose(
            make_state(),
            "x",
            [],
        )
        check(
            "bad target raises",
            False,
        )
    except ValueError:
        check(
            "bad target raises",
            True,
        )

    # --- 9. 非法 JSON ---
    def fake_bad_json(
        *,
        base_url,
        model,
        api_key,
        messages,
        **kw,
    ):
        return (
            {
                "choices": [
                    {
                        "message": {
                            "content": "not json"
                        }
                    }
                ],
                "usage": {},
            },
            1,
        )

    mod.post_chat = fake_bad_json

    try:
        choose(
            make_state(),
            "x",
            [],
        )
        check(
            "bad json raises",
            False,
        )
    except ValueError:
        check(
            "bad json raises",
            True,
        )

    # --- 10. 缺 operation ---
    mod.post_chat = fake_post(
        {
            "target": "1",
            "operation_confidence": 0.9,
        }
    )

    try:
        choose(
            make_state(),
            "x",
            [],
        )
        check(
            "missing operation raises",
            False,
        )
    except ValueError:
        check(
            "missing operation raises",
            True,
        )

    # --- 11. missing env ---
    saved = os.environ.pop(
        "DECIDER_2B_BASE_URL",
        None,
    )

    try:
        choose(
            make_state(),
            "x",
            [],
        )
        check(
            "missing env raises",
            False,
        )
    except RuntimeError:
        check(
            "missing env raises",
            True,
        )

    if saved is not None:
        os.environ["DECIDER_2B_BASE_URL"] = saved

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    _smoke()