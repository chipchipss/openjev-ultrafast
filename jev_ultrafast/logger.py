"""Logger.

只读式抽取 agent 运行事件，落盘为 JSONL。

关联硬约束：
  A9  事件格式是 Runtime 的产物，由本模块离线抽取
  C4  训练样本必须携带来源（decider/helper 的 model 字段）
  E5  事件是四维失败（result / quadrant / failure_class / failure_mode）的输入源

设计要点：
  - 只读 agent.state / agent.step_budget，绝不修改
  - 游标式：每次 observe() 只输出新增事件
  - 5 类事件：step / decision / text_call / budget_transition / task_result
  - 一个 task 一个 JSONL
  - 不 import agent，用鸭子类型

已知边界（Step 9 观察 #2）：
  终态（DONE/BLOCKED）分支 state.pop("pre_execute") 后早返回，不写 history。
  因此终态的预算快照不会出现在 step 事件里。
  Logger 用 task_result.final_budget 补偿。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional


EVENT_STEP              = "step"
EVENT_DECISION          = "decision"
EVENT_TEXT_CALL         = "text_call"
EVENT_BUDGET_TRANSITION = "budget_transition"
EVENT_TASK_RESULT       = "task_result"
EVENT_TEACHER_SHADOW    = "teacher_shadow"


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def dbg(site: str, detail: str = "") -> None:
    """`JEV_DEBUG` 才出声的一行留痕（#68）。默认零输出，批日志与报告格式一字不变。

    存在的理由：仓库里有 29 处宽 `except Exception`，其中少数几处**会改变解释**——
    `skills.route()` 把技能异常吞成 `d = None`，行为正确（回落模型），但没人知道是哪个技能抛了什么；
    #59 那一轮"技能明明能判达却被读成模型能力问题"就是这个形状。留痕不改控制流：
    降级照旧降级，只是出事时能在 stderr 看到一行。
    """
    if not (os.environ.get("JEV_DEBUG") or "").strip():
        return
    sys.stderr.write(f"[dbg] {site}: {detail}" + chr(10))


def _to_jsonable(obj: Any) -> Any:
    """dataclass / Enum / 嵌套结构 → JSON 可序列化。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return str(obj)


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class Logger:
    def __init__(
        self,
        task_id: str,
        log_dir: str | Path,
        *,
        flush_every: int = 32,
    ) -> None:
        if not task_id:
            raise ValueError("task_id required")
        self.task_id = task_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{task_id}.jsonl"
        self.flush_every = max(1, int(flush_every))

        self._history_cursor = 0
        self._decisions_cursor = 0
        self._text_calls_cursor = 0
        self._transitions_cursor = 0
        self._teacher_cursor = 0
        self._buffer: list[dict] = []
        self._file = None  # lazy open

    # --- 主入口 ---

    def observe(self, state: dict, *, step_budget=None) -> list[dict]:
        """抽取 state 的新增事件。

        state:       agent.state（或等价的 dict）
        step_budget: agent.step_budget（可选，用于 budget_transition）

        返回本次新增事件列表；事件同时进入内部 buffer，达阈值自动 flush。
        """
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")

        now = time.time()
        new_events: list[dict] = []

        # 1. step
        history = state.get("history") or []
        for h in history[self._history_cursor:]:
            new_events.append({
                "event":     EVENT_STEP,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_step(h),
            })
        self._history_cursor = len(history)

        # 2. decision
        decisions = state.get("decisions") or []
        for d in decisions[self._decisions_cursor:]:
            new_events.append({
                "event":     EVENT_DECISION,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_decision(d),
            })
        self._decisions_cursor = len(decisions)

        # 3. text_call
        text_calls = state.get("text_calls") or []
        for t in text_calls[self._text_calls_cursor:]:
            new_events.append({
                "event":     EVENT_TEXT_CALL,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_text_call(t),
            })
        self._text_calls_cursor = len(text_calls)

        # 4b. teacher_shadow（M2）
        teacher_decisions = state.get("teacher_decisions") or []
        for td in teacher_decisions[self._teacher_cursor:]:
            new_events.append({
                "event":     EVENT_TEACHER_SHADOW,
                "task_id":   self.task_id,
                "timestamp": now,
                **self._clean_teacher_decision(td),
            })
        self._teacher_cursor = len(teacher_decisions)

        # 4. budget_transition
        if step_budget is not None:
            transitions = getattr(step_budget, "transitions", None) or []
            for tr in transitions[self._transitions_cursor:]:
                new_events.append({
                    "event":     EVENT_BUDGET_TRANSITION,
                    "task_id":   self.task_id,
                    "timestamp": now,
                    **_to_jsonable(tr),
                })
            self._transitions_cursor = len(transitions)

        self._buffer.extend(new_events)
        if len(self._buffer) >= self.flush_every:
            self.flush()
        return new_events

    def finalize(
        self,
        task_result: Any,
        *,
        step_budget=None,
        final_page: Optional[dict] = None,
        state_paid_ms: Optional[int] = None,
    ) -> dict:
        """写入 task_result 事件并 flush。

        task_result: evaluator.TaskResult（dataclass）或等价 dict
        step_budget: 可选，用于终态预算快照（补偿终态 pre_execute 丢失）
        final_page:  可选，最终页面的 url / title
        """
        if is_dataclass(task_result):
            result_dict = _to_jsonable(task_result)
        elif isinstance(task_result, dict):
            result_dict = _to_jsonable(task_result)
        else:
            raise TypeError("task_result must be dataclass or dict")

        event: dict = {
            "event":     EVENT_TASK_RESULT,
            "task_id":   self.task_id,
            "timestamp": time.time(),
            "result":    result_dict,
        }
        if step_budget is not None:
            event["final_budget"] = self._budget_snapshot(step_budget)
        # #65：这一行在收口前为重看付了多少毫秒（没付就不写这个键）。
        # 批里"这一刀花了多少秒"必须是产物里数得出来的，不靠墙钟差猜。
        _paid = state_paid_ms if state_paid_ms is not None else None
        if _paid:
            event["arrival_relook_ms"] = int(_paid)
        if final_page is not None:
            # #75：评测吃的那份正文必须留下可复核的痕迹。只记**摘要**（长度 + 16 位 sha1）——
            # 长度足以认出"这是半帧"（docs 族实测 654 → 1454），sha 足以确认两次读数是不是
            # 同一份页；整段正文不入库（体积，以及第三方页面内容没必要跟着报告一起走）。
            _txt = final_page.get("text") or ""
            event["final_page"] = {
                "url":   final_page.get("url"),
                "title": final_page.get("title"),
                "text_len": len(_txt),
                "text_sha16": hashlib.sha1(
                    _txt.encode("utf-8", "replace")).hexdigest()[:16],
            }

        self._buffer.append(event)
        self.flush()
        return event

    # --- IO ---

    def flush(self) -> None:
        if not self._buffer:
            return
        if self._file is None:
            self._file = self.log_path.open("a", encoding="utf-8")
        for ev in self._buffer:
            self._file.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._file.flush()
        self._buffer.clear()

    def close(self) -> None:
        self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # --- 清理 ---

    #: 有意不落的 step 字段。**加了新 history 字段而不登记在这里，`tests/test_logger_step_fields.py`
    #: 会红**——字段静默留在内存、丢在磁盘外，是 #59 那类"读日志读不到依据"的成因。
    STEP_DROP_KEYS = frozenset({"usage"})

    @staticmethod
    def _clean_step(h: dict) -> dict:
        """step 白名单。None 保留（page_changed=None 表示 observe 失败）。

        `outcome` / `url_from` / `page_fp_before` / `skill` 是后补的：前三个是**到达判据在读的字段**
        （`agent.py:605-623` 观测归静后结算出来的 outcome、#59 同主机守卫要的出发页、Fix P 的
        指纹依据），`skill` 记这一拍由哪个地板技能发出。2026-10-11 晚 b33 拆堆时，这四个都不在日志里，
        结果"结果文本何时出现"只能靠重开浏览器复探——诊断仪器不该缺这个。
        """
        keys = (
            "step", "action", "kind", "choice", "operation", "target",
            "confidence", "probability", "latency_ms",
            "text", "text_helper", "text_latency_ms",
            "page_changed", "url", "url_from", "page_fp_before", "outcome", "skill",
            "elapsed_ms", "executed_ms",
        )
        out = {k: h[k] for k in keys if k in h}
        if "pre_execute" in h:
            out["pre_execute"] = _to_jsonable(h["pre_execute"])
        if "outcome" in out:
            out["outcome"] = _to_jsonable(out["outcome"])
        return out

    @staticmethod
    def _clean_decision(d: dict) -> dict:
        keys = (
            "choice", "operation", "target",
            "operation_confidence", "target_confidence", "confidence",
            "model", "latency_ms", "usage",
            "fingerprint", "elapsed_ms", "rejected",
            "skill",                       # M16 技能层：命中时记录技能名（诊断/归因用）
        )
        out = {k: d[k] for k in keys if k in d}
        if "probabilities" in d:
            out["probabilities"] = _to_jsonable(d["probabilities"])
        return out

    @staticmethod
    def _clean_text_call(t: dict) -> dict:
        keys = ("model", "field", "value", "latency_ms", "usage")
        return {k: t[k] for k in keys if k in t}

    @staticmethod
    def _clean_teacher_decision(td: dict) -> dict:
        """白名单。保留 actions_snapshot（供 sample_extractor 重建 candidates）。

        C3 落地：actions_snapshot 是 structured 源；
        rendered 由 sample_extractor 从 actions_snapshot 重放 action_space 得到。
        """
        keys = (
            "step",
            "local", "teacher",
            "agree", "operation_match", "target_match",
            "latency_ms", "usage",
        )
        out = {k: td[k] for k in keys if k in td}
        if "actions_snapshot" in td:
            out["actions_snapshot"] = td["actions_snapshot"]
        # M4b Logger v2：page/history 快照（SFT user prompt 与线上推理同构）
        if "page_snapshot" in td:
            out["page_snapshot"] = td["page_snapshot"]
        if "history_snapshot" in td:
            out["history_snapshot"] = td["history_snapshot"]
        return out

    @staticmethod
    def _budget_snapshot(step_budget) -> dict:
        try:
            return _to_jsonable(step_budget.log_entry())
        except Exception:
            return {}
