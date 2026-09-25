"""Decision Validator.

实现 D8 三级一致性。只做语义校验，不做类型校验（A10 落地）。

输入：
  decision: dict          — Decider 输出，schema 层已通过
  page:     dict          — browser.observe() 的输出，含 actions

输出：
  ValidationResult(valid, code, reason, detail)

调用方约定（A6）：
  - 不检查 freshness / occlusion / disabled — 那是 Runtime Guard 的职责
  - 不检查 Policy 黑名单 — 那是 Policy 的职责
  - 只检查 operation / target / choice 三者的映射链

codes（互斥）：
  ok
  unknown_operation       — operation 既不在 targets、controls，也不是 sentinel
  target_required         — target 缺失（operation 需要 target）
  target_not_allowed      — target 存在但 operation 不需要（control / sentinel）
  target_not_in_candidates — target 不在 targets[operation] 里
  choice_mismatch         — choice 与 (operation, target) 的映射不一致
  sentinel_mismatch       — operation 是 sentinel 但 choice ≠ operation
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


# 与 model.py:action_space() 的约定一致。
# 这里做一次独立的定义，避免 validator 依赖 model.py（Decision 层可被完全替换）。
SENTINELS = frozenset({"DONE", "BLOCKED"})


# ---------------------------------------------------------------------------
# 结果类型
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    code: str
    reason: str
    detail: dict = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("detail") is None:
            d.pop("detail", None)
        return d


def _ok() -> ValidationResult:
    return ValidationResult(True, "ok", "decision consistent with action space")


def _fail(code: str, reason: str, **detail) -> ValidationResult:
    return ValidationResult(False, code, reason, detail or None)


# ---------------------------------------------------------------------------
# action_space 内联（与 model.py 等价的最小子集）
# ---------------------------------------------------------------------------

def _build_targets_controls(actions: list[dict]) -> tuple[dict, dict]:
    """构造 targets / controls 索引。

    与 model.py:action_space() 语义一致：
      - click / fill / select 的 kind 映射到 operation 名
      - 其他 kind（scroll / wait）进入 controls，operation = id.upper()
      - select 的 target 形态为 "index:optindex"

    本函数不构造 elements，validator 不需要。
    """
    kind_to_op = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    targets: dict[str, dict[str, dict]] = {}
    controls: dict[str, dict] = {}
    # node → index（与 model.py 一致：按首次出现顺序分配）
    node_to_index: dict[int, int] = {}
    # index → 已产出的 select option 数量
    select_option_count: dict[int, int] = {}

    for action in actions:
        kind = action["kind"]
        if kind not in kind_to_op:
            controls[action["id"].upper()] = action
            continue

        node = action["node"]
        if node not in node_to_index:
            node_to_index[node] = len(node_to_index) + 1
        index = node_to_index[node]
        operation = kind_to_op[kind]

        target_id = str(index)
        if kind == "select":
            count = select_option_count.get(index, 0) + 1
            select_option_count[index] = count
            target_id = f"{index}:{count}"

        targets.setdefault(operation, {})[target_id] = action

    return targets, controls


# ---------------------------------------------------------------------------
# 主校验
# ---------------------------------------------------------------------------

def validate(
    decision: dict,
    page: dict,
    *,
    targets: Optional[dict] = None,
    controls: Optional[dict] = None,
) -> ValidationResult:
    """校验决策与当前 action space 的语义一致性。

    如果调用方已经算过 action_space()，可以传入 targets / controls 避免重复。
    否则内部按 page["actions"] 重新构造。
    """
    operation = decision.get("operation")
    target = decision.get("target")
    choice = decision.get("choice")

    if targets is None or controls is None:
        targets, controls = _build_targets_controls(page.get("actions", []))

    # --- sentinel ---
    if operation in SENTINELS:
        if target is not None:
            return _fail(
                "target_not_allowed",
                f"operation {operation} must not carry a target",
                operation=operation, target=target,
            )
        if choice != operation:
            return _fail(
                "sentinel_mismatch",
                f"choice must equal operation {operation} for sentinel",
                operation=operation, choice=choice,
            )
        return _ok()

    # --- operation 必须在 targets 或 controls 里 ---
    if operation in targets:
        if target is None:
            return _fail(
                "target_required",
                f"operation {operation} requires a target",
                operation=operation,
            )
        candidates = targets[operation]
        if target not in candidates:
            return _fail(
                "target_not_in_candidates",
                f"target {target!r} not in {operation} candidates",
                operation=operation, target=target,
                available=list(candidates.keys()),
            )
        expected_choice = candidates[target]["id"]
        if choice != expected_choice:
            return _fail(
                "choice_mismatch",
                f"choice {choice!r} != action id {expected_choice!r} "
                f"for ({operation}, {target!r})",
                operation=operation, target=target,
                choice=choice, expected=expected_choice,
            )
        return _ok()

    if operation in controls:
        if target is not None:
            return _fail(
                "target_not_allowed",
                f"control operation {operation} must not carry a target",
                operation=operation, target=target,
            )
        expected_choice = controls[operation]["id"]
        if choice != expected_choice:
            return _fail(
                "choice_mismatch",
                f"choice {choice!r} != control id {expected_choice!r} "
                f"for operation {operation}",
                operation=operation, choice=choice, expected=expected_choice,
            )
        return _ok()

    return _fail(
        "unknown_operation",
        f"operation {operation!r} not in targets, controls, or sentinels",
        operation=operation,
        targets=list(targets.keys()),
        controls=list(controls.keys()),
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _page(actions):
    return {"url": "https://example.com", "title": "t", "text": "", "actions": actions}


if __name__ == "__main__":
    passed = 0
    total = 0

    def check(name, cond):
        global passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def check_fail(name, result, expected_code):
        global passed, total
        total += 1
        if (not result.valid) and result.code == expected_code:
            passed += 1
        else:
            print(f"FAIL: {name} (valid={result.valid}, code={result.code!r}, "
                  f"expected code={expected_code!r})")

    # --- 构造一个混合页面 ---
    # 一个 textbox（可 fill 可 click），一个 button，一个 select，一个 scroll，一个 wait
    actions = [
        {"id": "e1", "kind": "fill",   "node": 12, "role": "textbox", "label": "Search", "value": ""},
        {"id": "e2", "kind": "click",  "node": 12, "role": "textbox", "label": "Open Search", "value": ""},
        {"id": "e3", "kind": "click",  "node": 42, "role": "button",  "label": "Search", "value": ""},
        {"id": "e4", "kind": "select", "node": 88, "role": "combobox","label": "Country → CH", "value": "CH"},
        {"id": "e5", "kind": "select", "node": 88, "role": "combobox","label": "Country → DE", "value": "DE"},
        {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
        {"id": "wait",        "kind": "wait",   "label": "Wait"},
    ]
    p = _page(actions)

    # --- 内部构造 targets/controls 的完整性 ---
    tg, ct = _build_targets_controls(actions)
    check("targets has CLICK", "CLICK" in tg)
    check("targets has TYPE_TEXT", "TYPE_TEXT" in tg)
    check("targets has SELECT", "SELECT" in tg)
    check("CLICK targets: index for 12 and 42", set(tg["CLICK"].keys()) == {"1", "2"})
    check("SELECT targets use index:opt", set(tg["SELECT"].keys()) == {"3:1", "3:2"})
    check("controls has SCROLL_DOWN", "SCROLL_DOWN" in ct)
    check("controls has WAIT", "WAIT" in ct)

    # --- 1. 合法 CLICK ---
    r = validate({"operation": "CLICK", "target": "2", "choice": "e3"}, p)
    check("CLICK e3 ok", r.valid and r.code == "ok")

    r = validate({"operation": "CLICK", "target": "1", "choice": "e2"}, p)
    check("CLICK e2 ok (same node, click kind)", r.valid)

    # --- 2. 合法 TYPE_TEXT ---
    r = validate({"operation": "TYPE_TEXT", "target": "1", "choice": "e1"}, p)
    check("TYPE_TEXT e1 ok", r.valid)

    # --- 3. 合法 SELECT ---
    r = validate({"operation": "SELECT", "target": "3:1", "choice": "e4"}, p)
    check("SELECT e4 ok", r.valid)
    r = validate({"operation": "SELECT", "target": "3:2", "choice": "e5"}, p)
    check("SELECT e5 ok", r.valid)

    # --- 4. 合法 control ---
    r = validate({"operation": "SCROLL_DOWN", "target": None, "choice": "scroll_down"}, p)
    check("SCROLL_DOWN ok", r.valid)
    r = validate({"operation": "WAIT", "target": None, "choice": "wait"}, p)
    check("WAIT ok", r.valid)

    # --- 5. 合法 sentinel ---
    r = validate({"operation": "DONE", "target": None, "choice": "DONE"}, p)
    check("DONE ok", r.valid)
    r = validate({"operation": "BLOCKED", "target": None, "choice": "BLOCKED"}, p)
    check("BLOCKED ok", r.valid)

    # --- 失败：unknown_operation ---
    check_fail(
        "unknown operation",
        validate({"operation": "HOVER", "target": None, "choice": "e3"}, p),
        "unknown_operation",
    )
    # 页面在顶部时不会有 SCROLL_UP
    check_fail(
        "SCROLL_UP absent",
        validate({"operation": "SCROLL_UP", "target": None, "choice": "scroll_up"}, p),
        "unknown_operation",
    )

    # --- 失败：target_required ---
    check_fail(
        "CLICK without target",
        validate({"operation": "CLICK", "target": None, "choice": "e3"}, p),
        "target_required",
    )

    # --- 失败：target_not_allowed ---
    check_fail(
        "SCROLL_DOWN with target",
        validate({"operation": "SCROLL_DOWN", "target": "1", "choice": "scroll_down"}, p),
        "target_not_allowed",
    )
    check_fail(
        "DONE with target",
        validate({"operation": "DONE", "target": "1", "choice": "DONE"}, p),
        "target_not_allowed",
    )

    # --- 失败：target_not_in_candidates ---
    check_fail(
        "CLICK target out of range",
        validate({"operation": "CLICK", "target": "99", "choice": "e3"}, p),
        "target_not_in_candidates",
    )
    check_fail(
        "SELECT target wrong form",
        validate({"operation": "SELECT", "target": "3", "choice": "e4"}, p),
        "target_not_in_candidates",
    )

    # --- 失败：choice_mismatch ---
    check_fail(
        "CLICK target 2 but choice e1 (wrong action)",
        validate({"operation": "CLICK", "target": "2", "choice": "e1"}, p),
        "choice_mismatch",
    )
    check_fail(
        "SCROLL_DOWN choice=scroll_up",
        validate({"operation": "SCROLL_DOWN", "target": None, "choice": "scroll_up"}, p),
        "choice_mismatch",
    )
    check_fail(
        "SELECT 3:1 but choice e5",
        validate({"operation": "SELECT", "target": "3:1", "choice": "e5"}, p),
        "choice_mismatch",
    )

    # --- 失败：sentinel_mismatch ---
    check_fail(
        "DONE with choice e3",
        validate({"operation": "DONE", "target": None, "choice": "e3"}, p),
        "sentinel_mismatch",
    )

    # --- 预计算 targets/controls 的短路 ---
    r = validate({"operation": "CLICK", "target": "2", "choice": "e3"}, p,
                 targets=tg, controls=ct)
    check("pre-computed targets/controls ok", r.valid)

    # --- 失败时 detail 携带上下文 ---
    r = validate({"operation": "CLICK", "target": "99", "choice": "e3"}, p)
    check("fail detail has available", "available" in (r.detail or {}))
    check("fail detail available contains 1", "1" in r.detail["available"])
    check("fail detail available contains 2", "2" in r.detail["available"])

    # --- ValidationResult.to_dict ---
    d = validate({"operation": "DONE", "target": None, "choice": "DONE"}, p).to_dict()
    check("to_dict has valid", d["valid"] is True)
    check("to_dict has code", d["code"] == "ok")
    check("to_dict omits detail when None", "detail" not in d)

    d = validate({"operation": "HOVER", "target": None, "choice": "e3"}, p).to_dict()
    check("to_dict keeps detail on fail", "detail" in d)

    print(f"SMOKE OK: {passed}/{total}")
