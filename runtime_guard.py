"""Runtime Guard.

snapshot.js 输出契约的运行时严格校验。

关联硬约束：
  A6  Runtime Guard 与 Validator 分层独立（本模块不做 Policy / 语义检查）
  A9  Runtime 契约的严格校验属于本模块，不属于 JSON Schema
  E5  失败是四维的，system 类 failure 不进训练集

职责边界：
  - 只校验"结构合法性"：长度、类型、位置
  - 不校验"语义"（例如 role 是否在 14 种支持列表——那是 snapshot.js 的职责）
  - 不实现 freshness 比对（那是 browser.py 的职责）
  - 不做任何 I/O

任何校验失败 → RuntimeContractViolation 这是系统错误。调用方按 crash 级处理：
  failure_class = "system"
  failure_mode  = "observe_failed"
  不进训练集
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# 契约常量（与 snapshot.js 一一对应）
# ---------------------------------------------------------------------------

MARKER_LEN = 10
PAGE_KEY_LEN = 7
GUARD_LEN = 14
INPUT_STATE_LEN = 6

MARKER_FIELDS = (
    "time_origin", "href", "scroll_x", "scroll_y",
    "inner_width", "inner_height",
    "title", "text", "semantics", "input_states",
)

PAGE_KEY_FIELDS = (
    "time_origin", "href", "scroll_x", "scroll_y",
    "inner_width", "inner_height", "input_states",
)

GUARD_FIELDS = (
    "identity", "role", "name", "value",
    "checked", "selected_index", "read_only", "disabled",
    "aria_disabled", "aria_expanded", "aria_checked", "aria_selected",
    "href", "scope_text",
)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class RuntimeContractViolation(Exception):
    """snapshot.js 输出违反约定结构。系统错误级别。"""

    def __init__(self, where: str, reason: str, value: Any = None):
        self.where = where
        self.reason = reason
        self.value = value
        msg = f"[runtime_guard:{where}] {reason}"
        if value is not None:
            preview = repr(value)
            if len(preview) > 200:
                preview = preview[:200] + "..."
            msg += f" (got {preview})"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# 基础类型谓词（严格：排除 bool 冒充 int）
# ---------------------------------------------------------------------------

def _is_bool(x: Any) -> bool:
    return isinstance(x, bool)


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_str_or_null(x: Any) -> bool:
    return x is None or isinstance(x, str)


def _is_bool_or_null(x: Any) -> bool:
    return x is None or isinstance(x, bool)


def _is_int_or_null(x: Any) -> bool:
    return x is None or (isinstance(x, int) and not isinstance(x, bool))


# ---------------------------------------------------------------------------
# input_states 叶子
# ---------------------------------------------------------------------------

def _check_input_state(idx: int, state: Any) -> None:
    if not isinstance(state, list) or len(state) != INPUT_STATE_LEN:
        raise RuntimeContractViolation(
            "input_states",
            f"item {idx} must be a list of length {INPUT_STATE_LEN}",
            state,
        )
    identity, value, checked, selected_index, disabled, read_only = state
    if not _is_int(identity) or identity < 1:
        raise RuntimeContractViolation(
            "input_states", f"item {idx}[0] identity must be int >= 1", identity,
        )
    if not isinstance(value, str):
        raise RuntimeContractViolation(
            "input_states", f"item {idx}[1] value must be str", value,
        )
    if not _is_bool(checked):
        raise RuntimeContractViolation(
            "input_states", f"item {idx}[2] checked must be bool", checked,
        )
    if not _is_int(selected_index):
        raise RuntimeContractViolation(
            "input_states", f"item {idx}[3] selected_index must be int", selected_index,
        )
    if not _is_bool(disabled):
        raise RuntimeContractViolation(
            "input_states", f"item {idx}[4] disabled must be bool", disabled,
        )
    if not _is_bool(read_only):
        raise RuntimeContractViolation(
            "input_states", f"item {idx}[5] read_only must be bool", read_only,
        )


def _check_input_states(states: Any) -> None:
    if not isinstance(states, list):
        raise RuntimeContractViolation("input_states", "must be a list", states)
    for i, item in enumerate(states):
        _check_input_state(i, item)


# ---------------------------------------------------------------------------
# 三个叶子结构
# ---------------------------------------------------------------------------

def validate_page_key(page_key: Any) -> None:
    """page_key: [timeOrigin, href, scrollX, scrollY, innerWidth, innerHeight, input_states]"""
    if not isinstance(page_key, list) or len(page_key) != PAGE_KEY_LEN:
        raise RuntimeContractViolation(
            "page_key", f"must be a list of length {PAGE_KEY_LEN}", page_key,
        )
    if not _is_num(page_key[0]):
        raise RuntimeContractViolation("page_key", "[0] time_origin must be numeric", page_key[0])
    if not isinstance(page_key[1], str):
        raise RuntimeContractViolation("page_key", "[1] href must be str", page_key[1])
    for i in (2, 3):
        if not _is_num(page_key[i]):
            raise RuntimeContractViolation("page_key", f"[{i}] must be numeric", page_key[i])
    for i in (4, 5):
        if not _is_int(page_key[i]):
            raise RuntimeContractViolation("page_key", f"[{i}] must be int", page_key[i])
    _check_input_states(page_key[6])


def validate_marker(marker: Any) -> None:
    """marker: [timeOrigin, href, scrollX, scrollY, innerWidth, innerHeight,
                title, text, semantics, input_states]"""
    if not isinstance(marker, list) or len(marker) != MARKER_LEN:
        raise RuntimeContractViolation(
            "marker", f"must be a list of length {MARKER_LEN}", marker,
        )
    if not _is_num(marker[0]):
        raise RuntimeContractViolation("marker", "[0] time_origin must be numeric", marker[0])
    if not isinstance(marker[1], str):
        raise RuntimeContractViolation("marker", "[1] href must be str", marker[1])
    for i in (2, 3):
        if not _is_num(marker[i]):
            raise RuntimeContractViolation("marker", f"[{i}] must be numeric", marker[i])
    for i in (4, 5):
        if not _is_int(marker[i]):
            raise RuntimeContractViolation("marker", f"[{i}] must be int", marker[i])
    if not isinstance(marker[6], str):
        raise RuntimeContractViolation("marker", "[6] title must be str", marker[6])
    if not isinstance(marker[7], str):
        raise RuntimeContractViolation("marker", "[7] text must be str", marker[7])
    if not isinstance(marker[8], list):
        raise RuntimeContractViolation("marker", "[8] semantics must be a list", marker[8])
    for i, item in enumerate(marker[8]):
        if not isinstance(item, dict):
            raise RuntimeContractViolation(
                "marker", f"[8] semantics[{i}] must be an object", item,
            )
    _check_input_states(marker[9])


def validate_guard(guard: Any) -> None:
    """guard: None（已失联）或 14 元素数组。"""
    if guard is None:
        return
    if not isinstance(guard, list) or len(guard) != GUARD_LEN:
        raise RuntimeContractViolation(
            "guard", f"must be None or a list of length {GUARD_LEN}", guard,
        )
    if not _is_int(guard[0]) or guard[0] < 1:
        raise RuntimeContractViolation("guard", "[0] identity must be int >= 1", guard[0])
    if not _is_str_or_null(guard[1]):
        raise RuntimeContractViolation("guard", "[1] role must be str or null", guard[1])
    if not isinstance(guard[2], str):
        raise RuntimeContractViolation("guard", "[2] name must be str", guard[2])
    if not _is_str_or_null(guard[3]):
        raise RuntimeContractViolation("guard", "[3] value must be str or null", guard[3])
    if not _is_bool_or_null(guard[4]):
        raise RuntimeContractViolation("guard", "[4] checked must be bool or null", guard[4])
    if not _is_int_or_null(guard[5]):
        raise RuntimeContractViolation("guard", "[5] selectedIndex must be int or null", guard[5])
    if not _is_bool_or_null(guard[6]):
        raise RuntimeContractViolation("guard", "[6] readOnly must be bool or null", guard[6])
    if not _is_bool(guard[7]):
        raise RuntimeContractViolation("guard", "[7] disabled must be bool", guard[7])
    for i in range(8, 12):
        if not _is_str_or_null(guard[i]):
            raise RuntimeContractViolation("guard", f"[{i}] must be str or null", guard[i])
    if not _is_str_or_null(guard[12]):
        raise RuntimeContractViolation("guard", "[12] href must be str or null", guard[12])
    if not isinstance(guard[13], str):
        raise RuntimeContractViolation("guard", "[13] scope_text must be str", guard[13])


def validate_guards(guards: Any) -> None:
    """guards: {digit_string_node_id: guard_or_null}"""
    if not isinstance(guards, dict):
        raise RuntimeContractViolation("guards", "must be a dict", guards)
    for key, val in guards.items():
        if not isinstance(key, str) or not key.isdigit():
            raise RuntimeContractViolation(
                "guards", f"key {key!r} must be a digit-string node id", key,
            )
        validate_guard(val)


# ---------------------------------------------------------------------------
# 顶层
# ---------------------------------------------------------------------------

def validate_observation(page: Any) -> None:
    """校验 browser.observe() 的完整输出。任一处失败立即抛。"""
    if not isinstance(page, dict):
        raise RuntimeContractViolation("observation", "must be a dict", page)

    for key in ("marker", "page_key", "guards"):
        if key not in page:
            raise RuntimeContractViolation(
                "observation", f"missing key {key!r}", list(page.keys()),
            )

    if not isinstance(page.get("url"), str):
        raise RuntimeContractViolation("observation", "url must be str", page.get("url"))
    if not isinstance(page.get("title"), str):
        raise RuntimeContractViolation("observation", "title must be str", page.get("title"))
    if not _is_int(page.get("w")):
        raise RuntimeContractViolation("observation", "w must be int", page.get("w"))
    if not _is_int(page.get("h")):
        raise RuntimeContractViolation("observation", "h must be int", page.get("h"))
    if not isinstance(page.get("text"), str):
        raise RuntimeContractViolation("observation", "text must be str", page.get("text"))
    if not isinstance(page.get("actions"), list):
        raise RuntimeContractViolation("observation", "actions must be a list", page.get("actions"))

    omitted = page.get("omitted_actions")
    if not _is_int(omitted) or omitted < 0:
        raise RuntimeContractViolation(
            "observation", "omitted_actions must be int >= 0", omitted,
        )

    scroll = page.get("scroll")
    if not isinstance(scroll, dict):
        raise RuntimeContractViolation("observation", "scroll must be a dict", scroll)
    if not _is_num(scroll.get("y")):
        raise RuntimeContractViolation("observation", "scroll.y must be numeric", scroll.get("y"))
    if not _is_num(scroll.get("height")):
        raise RuntimeContractViolation("observation", "scroll.height must be numeric", scroll.get("height"))

    validate_marker(page["marker"])
    validate_page_key(page["page_key"])
    validate_guards(page["guards"])


# ---------------------------------------------------------------------------
# 诊断辅助（不做校验）
# ---------------------------------------------------------------------------

def explain_marker(marker: Any) -> dict:
    if not isinstance(marker, list) or len(marker) != MARKER_LEN:
        return {"_invalid": True, "_value": marker}
    return dict(zip(MARKER_FIELDS, marker))


def explain_page_key(page_key: Any) -> dict:
    if not isinstance(page_key, list) or len(page_key) != PAGE_KEY_LEN:
        return {"_invalid": True, "_value": page_key}
    return dict(zip(PAGE_KEY_FIELDS, page_key))


def explain_guard(guard: Any) -> dict:
    if guard is None:
        return {"_detached": True}
    if not isinstance(guard, list) or len(guard) != GUARD_LEN:
        return {"_invalid": True, "_value": guard}
    return dict(zip(GUARD_FIELDS, guard))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

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

    def check_raises(name, fn, where=None):
        global passed, total
        total += 1
        try:
            fn()
        except RuntimeContractViolation as e:
            if where is None or e.where == where:
                passed += 1
            else:
                print(f"FAIL: {name} (where={e.where!r}, expected {where!r})")
        except Exception as e:
            print(f"FAIL: {name} (raised {type(e).__name__}: {e})")
        else:
            print(f"FAIL: {name} (no raise)")

    def sample_input_state(identity=12):
        return [identity, "", False, -1, False, False]

    def sample_page_key():
        return [1737600000.123, "https://example.com", 0, 0, 1120, 780, [sample_input_state(12)]]

    def sample_guard(identity=12):
        return [
            identity, "textbox", "Search", "", None, -1, False,
            False, None, None, None, None, None, "scope text",
        ]

    def sample_marker():
        return [
            1737600000.123, "https://example.com", 0, 0, 1120, 780,
            "Example", "page text",
            [{"id": "e1", "kind": "click", "label": "Search", "node": 12, "role": "button"}],
            [sample_input_state(12)],
        ]

    def sample_observation():
        return {
            "url": "https://example.com",
            "title": "Example",
            "w": 1120, "h": 780,
            "text": "page text",
            "scroll": {"y": 0, "height": 2000},
            "actions": [
                {"id": "e1", "kind": "click", "node": 12, "role": "button",
                 "label": "Search", "rect": {"x": 0, "y": 0, "w": 100, "h": 40}},
            ],
            "marker": sample_marker(),
            "page_key": sample_page_key(),
            "guards": {"12": sample_guard(12)},
            "omitted_actions": 0,
        }

    # --- 合法路径 ---
    ok = True
    try:
        validate_observation(sample_observation())
    except RuntimeContractViolation as e:
        ok = False
        print(f"FAIL: valid observation raised {e}")
    check("valid observation passes", ok)

    validate_marker(sample_marker()); check("valid marker", True)
    validate_page_key(sample_page_key()); check("valid page_key", True)
    validate_guard(sample_guard()); check("valid guard", True)
    validate_guard(None); check("None guard ok", True)
    validate_guards({"12": sample_guard(12), "13": None}); check("valid guards", True)
    validate_guards({}); check("empty guards ok", True)

    # --- 长度错误 ---
    check_raises("marker len 9", lambda: validate_marker(sample_marker()[:-1]), "marker")
    check_raises("marker len 11", lambda: validate_marker(sample_marker() + [0]), "marker")
    check_raises("page_key len 6", lambda: validate_page_key(sample_page_key()[:-1]), "page_key")
    check_raises("guard len 13", lambda: validate_guard(sample_guard()[:-1]), "guard")
    check_raises("guard len 15", lambda: validate_guard(sample_guard() + [0]), "guard")

    # --- 类型错误 ---
    bad = sample_marker(); bad[1] = 123
    check_raises("marker[1] not str", lambda: validate_marker(bad), "marker")

    bad = sample_marker(); bad[6] = None
    check_raises("marker[6] None", lambda: validate_marker(bad), "marker")

    bad = sample_marker(); bad[8] = {"not": "list"}
    check_raises("marker[8] not list", lambda: validate_marker(bad), "marker")

    bad = sample_marker(); bad[8] = [1, 2]
    check_raises("marker[8] items not dict", lambda: validate_marker(bad), "marker")

    bad = sample_page_key(); bad[4] = 1120.5
    check_raises("page_key[4] float not int", lambda: validate_page_key(bad), "page_key")

    bad = sample_guard(); bad[7] = None
    check_raises("guard disabled None", lambda: validate_guard(bad), "guard")

    bad = sample_guard(); bad[1] = 123
    check_raises("guard role int", lambda: validate_guard(bad), "guard")

    bad = sample_guard(); bad[2] = None
    check_raises("guard name None", lambda: validate_guard(bad), "guard")

    bad = sample_guard(); bad[0] = 0
    check_raises("guard identity 0", lambda: validate_guard(bad), "guard")

    # --- input_states ---
    bad_pk = sample_page_key(); bad_pk[6] = [[1, "", False]]
    check_raises("input_state short", lambda: validate_page_key(bad_pk), "input_states")

    bad_pk = sample_page_key(); bad_pk[6] = [[1, "", False, -1, False, False, 0]]
    check_raises("input_state long", lambda: validate_page_key(bad_pk), "input_states")

    bad_pk = sample_page_key(); bad_pk[6] = [["1", "", False, -1, False, False]]
    check_raises("input_state identity str", lambda: validate_page_key(bad_pk), "input_states")

    bad_pk = sample_page_key(); bad_pk[6] = [[1, "", 0, -1, False, False]]
    check_raises("input_state checked int", lambda: validate_page_key(bad_pk), "input_states")

    # --- guards dict ---
    check_raises("guards not dict", lambda: validate_guards([]), "guards")
    check_raises("guards key not digit", lambda: validate_guards({"abc": None}), "guards")
    check_raises("guards key int", lambda: validate_guards({12: None}), "guards")

    # --- 顶层 ---
    bad = sample_observation(); del bad["marker"]
    check_raises("observation missing marker", lambda: validate_observation(bad), "observation")

    bad = sample_observation(); bad["url"] = None
    check_raises("observation url None", lambda: validate_observation(bad), "observation")

    bad = sample_observation(); bad["omitted_actions"] = -1
    check_raises("observation omitted_actions -1", lambda: validate_observation(bad), "observation")

    bad = sample_observation(); bad["scroll"] = {"y": 0}
    check_raises("observation scroll missing height", lambda: validate_observation(bad), "observation")

    # --- bool/int 陷阱 ---
    bad_pk = sample_page_key(); bad_pk[4] = True
    check_raises("bool is not int (innerWidth True)", lambda: validate_page_key(bad_pk), "page_key")

    # --- explain_* ---
    em = explain_marker(sample_marker())
    check("explain_marker title", em["title"] == "Example")
    check("explain_marker has 10 fields", set(em.keys()) == set(MARKER_FIELDS))

    eg = explain_guard(sample_guard())
    check("explain_guard role", eg["role"] == "textbox")

    check("explain_guard None is detached", explain_guard(None) == {"_detached": True})
    check("explain_marker invalid", explain_marker([1, 2])["_invalid"] is True)

    # --- 异常消息 ---
    try:
        validate_marker(sample_marker()[:-1])
    except RuntimeContractViolation as e:
        check("exception has where", e.where == "marker")
        check("exception str contains where", "runtime_guard:marker" in str(e))

    print(f"SMOKE OK: {passed}/{total}")
