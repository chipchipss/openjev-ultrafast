"""Task Success Evaluator.

独立于 jev-ultrafast。判定 Agent 是否真正完成一个 task。

输入：
  spec:       TaskSpec (dict)
  final_page: Observation (dict) | None
  history:    list[dict]
  status:     "done" | "blocked" | "budget_exceeded" | "error"
  meta:       {steps, model_calls, api_calls, elapsed_ms}

输出：
  TaskResult

判定不参与 Agent loop。只读。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# 类型别名
# ---------------------------------------------------------------------------

Result = Literal["PASS", "FAIL", "UNKNOWN"]
Quadrant = Literal[
    "true_success",
    "false_positive",
    "correct_abandon",
    "false_negative",
]
FailureClass = Literal["agent", "system"]

AGENT_MODES = frozenset({
    "decision",
    "assertion_mismatch",
    "budget_exceeded",
    "stale_loop",
    "recovery_storm",
})
SYSTEM_MODES = frozenset({
    "api_unavailable",
    "crash",
    "observe_failed",
    "assertion_error",
})

TERMINAL_STATUSES = frozenset({
    "done",
    "blocked",
    "budget_exceeded",
    "error",
})


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ClauseTrace:
    clause: dict
    ok: bool
    note: Optional[str] = None


@dataclass
class TaskResult:
    task_id: str
    result: Result
    quadrant: Optional[Quadrant] = None
    failure_class: Optional[FailureClass] = None
    failure_mode: Optional[str] = None
    evidence: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 断言执行
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _eval_assertion(
    assertion: dict,
    page: Optional[dict],
    history: list[dict],
) -> tuple[bool, list[ClauseTrace]]:
    """返回 (整体是否通过, 所有叶子 clause 的 trace)。"""
    kind = assertion.get("type")
    handler = _ASSERTION_HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"Unsupported assertion type: {kind!r}")
    return handler(assertion, page, history)


def _assert_all_of(a, page, history):
    traces: list[ClauseTrace] = []
    all_ok = True
    for clause in a["clauses"]:
        ok, sub = _eval_assertion(clause, page, history)
        all_ok = all_ok and ok
        traces.extend(sub)
    return all_ok, traces


def _assert_any_of(a, page, history):
    traces: list[ClauseTrace] = []
    any_ok = False
    for clause in a["clauses"]:
        ok, sub = _eval_assertion(clause, page, history)
        any_ok = any_ok or ok
        traces.extend(sub)
    return any_ok, traces


def _assert_url_matches(a, page, history):
    if page is None:
        return False, [ClauseTrace(a, False, "page is None")]
    try:
        m = _compile(a["pattern"]).search(page.get("url", ""))
    except re.error as e:
        return False, [ClauseTrace(a, False, f"invalid regex: {e}")]
    return bool(m), [ClauseTrace(a, bool(m), None)]


def _assert_url_not_matches(a, page, history):
    if page is None:
        return False, [ClauseTrace(a, False, "page is None")]
    try:
        m = _compile(a["pattern"]).search(page.get("url", ""))
    except re.error as e:
        return False, [ClauseTrace(a, False, f"invalid regex: {e}")]
    return (not m), [ClauseTrace(a, not m, None)]


def _assert_text_contains(a, page, history):
    if page is None:
        return False, [ClauseTrace(a, False, "page is None")]
    text = page.get("text", "")
    needle = a["value"]
    if not a.get("case_sensitive", False):
        text, needle = text.lower(), needle.lower()
    ok = needle in text
    return ok, [ClauseTrace(a, ok, None)]


def _assert_text_not_contains(a, page, history):
    if page is None:
        return False, [ClauseTrace(a, False, "page is None")]
    text = page.get("text", "")
    needle = a["value"]
    if not a.get("case_sensitive", False):
        text, needle = text.lower(), needle.lower()
    ok = needle not in text
    return ok, [ClauseTrace(a, ok, None)]


def _iter_actions(page):
    return page.get("actions", []) if page else []


def _action_matches(action: dict, role: str, label_contains: Optional[str]) -> bool:
    if action.get("role") != role:
        return False
    if label_contains and label_contains not in action.get("label", ""):
        return False
    return True


def _assert_element_exists(a, page, history):
    if page is None:
        return False, [ClauseTrace(a, False, "page is None")]
    role = a["role"]
    label_sub = a.get("label_contains")
    for action in _iter_actions(page):
        if _action_matches(action, role, label_sub):
            return True, [ClauseTrace(a, True, f"found in action {action.get('id')}")]
    return False, [ClauseTrace(a, False, None)]


def _assert_element_absent(a, page, history):
    if page is None:
        return False, [ClauseTrace(a, False, "page is None")]
    role = a["role"]
    label_sub = a.get("label_contains")
    for action in _iter_actions(page):
        if _action_matches(action, role, label_sub):
            return False, [ClauseTrace(a, False, f"still present in action {action.get('id')}")]
    return True, [ClauseTrace(a, True, None)]


def _assert_history_has_kind(a, page, history):
    kind = a["kind"]
    text_sub = a.get("text_contains")
    for h in history or []:
        if h.get("kind") != kind:
            continue
        if text_sub and text_sub not in (h.get("text") or ""):
            continue
        return True, [ClauseTrace(a, True, f"found in step {h.get('step')}")]
    return False, [ClauseTrace(a, False, None)]


_ASSERTION_HANDLERS = {
    "all_of":             _assert_all_of,
    "any_of":             _assert_any_of,
    "url_matches":        _assert_url_matches,
    "url_not_matches":    _assert_url_not_matches,
    "text_contains":      _assert_text_contains,
    "text_not_contains":  _assert_text_not_contains,
    "element_exists":     _assert_element_exists,
    "element_absent":     _assert_element_absent,
    "history_has_kind":   _assert_history_has_kind,
}


# ---------------------------------------------------------------------------
# 象限与失败分类
# ---------------------------------------------------------------------------

def _quadrant(status: str, result: Result) -> Optional[Quadrant]:
    if result == "UNKNOWN":
        return None
    if status == "error":
        return None
    if result == "PASS":
        if status == "done":
            return "true_success"
        if status in ("blocked", "budget_exceeded"):
            return "false_negative"
    if result == "FAIL":
        if status == "done":
            return "false_positive"
        if status in ("blocked", "budget_exceeded"):
            return "correct_abandon"
    return None


def _detect_stale_loop(history: list[dict], threshold: int = 3) -> bool:
    """连续 >= threshold 次 page_changed is None → stale_loop。"""
    streak = 0
    for h in history:
        if h.get("page_changed") is None:
            streak += 1
            if streak >= threshold:
                return True
        else:
            streak = 0
    return False


def _detect_recovery_storm(history: list[dict], threshold: int = 5) -> bool:
    """M1 阶段无 recovery 事件信号，先返回 False。M2 后接入。"""
    return False


def _classify(
    status: str,
    result: Result,
    quadrant: Optional[Quadrant],
    history: list[dict],
) -> tuple[Optional[FailureClass], Optional[str]]:
    if status == "error":
        return "system", "crash"
    if result == "UNKNOWN":
        return "system", "observe_failed"
    if quadrant in (None, "true_success", "false_negative"):
        return None, None

    if status == "budget_exceeded":
        return "agent", "budget_exceeded"
    if _detect_stale_loop(history):
        return "agent", "stale_loop"
    if _detect_recovery_storm(history):
        return "agent", "recovery_storm"

    if quadrant == "false_positive":
        return "agent", "decision"
    if quadrant == "correct_abandon":
        return "agent", "decision"
    return None, None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _meta(meta: Optional[dict], history: list[dict]) -> dict:
    meta = meta or {}
    return {
        "steps":       meta.get("steps", len(history)),
        "model_calls": meta.get("model_calls"),
        "api_calls":   meta.get("api_calls"),
        "elapsed_ms":  meta.get("elapsed_ms"),
    }


def _unknown(task_id: str, reason: str, meta: Optional[dict], history: list[dict]) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        result="UNKNOWN",
        quadrant=None,
        failure_class="system",
        failure_mode="observe_failed",
        evidence={"reason": reason},
        meta=_meta(meta, history),
    )


def evaluate(
    spec: dict,
    final_page: Optional[dict],
    history: Optional[list[dict]],
    status: str,
    meta: Optional[dict] = None,
) -> TaskResult:
    """评估一个已完成（或终止）的 task。"""
    if not isinstance(spec, dict):
        raise TypeError("spec must be a dict")
    if "task_id" not in spec or "success_assertion" not in spec:
        raise ValueError("spec missing task_id or success_assertion")
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"status must be terminal, got {status!r}")

    task_id = spec["task_id"]
    history = history or []

    if final_page is None:
        return _unknown(task_id, "final_page is None", meta, history)
    if not isinstance(final_page, dict):
        return _unknown(task_id, "final_page is not a dict", meta, history)

    url = final_page.get("url", "")
    if not url or url == "about:blank":
        return _unknown(task_id, "final_page.url is empty or about:blank", meta, history)

    assertion = spec["success_assertion"]
    try:
        assertion_ok, traces = _eval_assertion(assertion, final_page, history)
    except Exception as e:
        return TaskResult(
            task_id=task_id,
            result="UNKNOWN",
            quadrant=None,
            failure_class="system",
            failure_mode="assertion_error",
            evidence={"error": str(e)},
            meta=_meta(meta, history),
        )

    result: Result = "PASS" if assertion_ok else "FAIL"
    quadrant = _quadrant(status, result)
    failure_class, failure_mode = _classify(status, result, quadrant, history)

    return TaskResult(
        task_id=task_id,
        result=result,
        quadrant=quadrant,
        failure_class=failure_class,
        failure_mode=failure_mode,
        evidence={
            "final_url":       final_page.get("url"),
            "final_title":     final_page.get("title"),
            "assertion_trace": [asdict(t) for t in traces],
        },
        meta=_meta(meta, history),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def evaluate_from_files(
    spec_path: str,
    page_path: Optional[str] = None,
    history_path: Optional[str] = None,
    status: str = "error",
) -> TaskResult:
    import json
    from pathlib import Path

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    page = json.loads(Path(page_path).read_text(encoding="utf-8")) if page_path else None
    hist = json.loads(Path(history_path).read_text(encoding="utf-8")) if history_path else []
    return evaluate(spec, page, hist, status)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Evaluate a task result.")
    parser.add_argument("spec", help="TaskSpec JSON path")
    parser.add_argument("--page", help="final_page JSON path")
    parser.add_argument("--history", help="history JSON path")
    parser.add_argument("--status", default="error",
                        choices=sorted(TERMINAL_STATUSES))
    args = parser.parse_args()

    result = evaluate_from_files(args.spec, args.page, args.history, args.status)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
