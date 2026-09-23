"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import time
from pathlib import Path

from .browser import Browser, StalePage
from .model import action_space, choose, field_context, field_text
from .questions import MAX_STEPS

# --- M1: pre_execute 链 ---
from . import decision_validator
from . import policy
from .confidence_gate import (
    ConfidenceGate,
    ESCALATION_TEACHER,
    ESCALATION_RECOVERY,
    ESCALATION_ABORT,
)
from .step_budget import BudgetState, StepBudget


def _done_guard(decision: dict, state: dict) -> str | None:
    """R5 DoneGuard：rule-based DONE 拦截。返回拒绝原因，None=放行。

    落点在 _pre_execute（StepBudget → Validator → DoneGuard → Policy → Gate）：
    需要 goal / history / url 上下文，不进 decision_validator（保持其纯结构语义、
    可在 decider 侧独立单测）。拒绝走 StalePage（与决策 2/3 同构），
    持续拒绝由 StepBudget abort 兜底 → agent 类。

    已知误伤窗口（记档不修）：① 初始 url 即目标页 ② goal 含 "open search page"
    ——M1 的 20 任务均无此类；M6 扩任务时再细化规则。
    """
    if decision.get("operation") != "DONE":
        return None
    # 规则 1：0 步 DONE
    if len(state["history"]) == 0:
        return "DONE with no prior actions"
    # 规则 2：nav-goal 停在搜索结果页（goal 先 lower；关键词带空格防误伤 opener/navigational）
    goal = state["goal"].lower()
    url = state["page"]["url"]
    nav_goal = any(w in goal for w in ("open ", "navigate to ", "go to "))
    search_url = "?q=" in url or "/search" in url
    if nav_goal and search_url:
        return "DONE on search results page with navigation goal"
    return None


class Agent:
    def __init__(self, url, goals, *, record_dir=None, screenshots=False,
                 task_spec=None, api_teacher=None, api_budget=None):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        plan = [task]
        self.pending_text = None
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)

        # --- M1/M2: pre_execute 组件 ---
        if task_spec is not None:
            self.step_budget = StepBudget.from_task_spec(task_spec)
        else:
            # 向后兼容：没有 TaskSpec 时退化为 MAX_STEPS 硬上限
            self.step_budget = StepBudget(MAX_STEPS, MAX_STEPS * 2)

        # --- M2: 默认 shadow（若提供 teacher） ---
        gate_mode = (ConfidenceGate.MODE_SHADOW
                     if api_teacher is not None
                     else ConfidenceGate.MODE_FIXED_HIGH)
        self.confidence_gate = ConfidenceGate(gate_mode)
        self.api_teacher = api_teacher
        self.api_budget = api_budget

        try:
            page = self.browser.observe(screenshot=self.screenshots)
        except Exception:
            self.browser.close()
            raise
        self.state = dict(
            browser=self.browser,
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            plan=plan,
            plan_index=0,
            decisions=[],
            text_calls=[],
            # --- M2 ---
            teacher_decisions=[],
            # --- M1 ---
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
            pre_execute=None,  # M1: pre_execute 结果暂存
        )
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    # --- M1: pre_execute 链 ---

    def _pre_execute(self) -> bool:
        """链内顺序：StepBudget → DecisionValidator → Policy → ConfidenceGate。

        返回 True 表示可以继续 act；False 表示 tick 应中断。

        副作用：
          - 更新 state["status"]（可能变为 "blocked" / "budget_exceeded"）
          - 写入 state["pre_execute"]（供 act 阶段写入 history）
          - 可能抛 StalePage（走 tick 的 except 分支重新 observe + predict）

        关联硬约束：A5 / B4 / D8
        """
        state = self.state
        page = state["page"]
        decision = state["decision"]
        pre = {
            "step_budget": None,
            "validator": None,
            "policy": None,
            "confidence_gate": None,
            "escalation": None,
        }
        state["pre_execute"] = pre

        # 1. StepBudget (B2 / B2.1 / B4)
        budget_state = self.step_budget.tick(
            len(state["history"]), len(state["decisions"])
        )
        pre["step_budget"] = self.step_budget.log_entry()
        if budget_state == BudgetState.ABORT:
            state["status"] = "budget_exceeded"
            return False

        # 2. DecisionValidator (D8 三级一致性)
        val = decision_validator.validate(decision, page)
        pre["validator"] = val.to_dict()
        if not val.valid:
            # 走 StalePage 路径：重新 observe → 重新 predict
            raise StalePage(f"Decision invalid: {val.code} — {val.reason}")

        # 2.5 DoneGuard（R5：rule-based DONE 拦截，与决策 2/3 同构走 StalePage）
        guard_reason = _done_guard(decision, state)
        if guard_reason is not None:
            raise StalePage(f"DONE guard rejected: {guard_reason}")

        # 3. Policy (A3)
        pol = policy.check(decision, page)
        pre["policy"] = pol.to_dict()
        if not pol.allow:
            state["status"] = "blocked"
            return False

        # 4. ConfidenceGate (A5 / D9 / B4)
        gate = self.confidence_gate.decide(decision, step_budget=self.step_budget)
        pre["confidence_gate"] = gate.to_dict()
        # 5. Shadow 采集（M2）
        if gate.shadow_requested and self.api_teacher is not None:
            self._run_shadow(decision, pre)

        # 6. §5bis 状态机（仅 calibrated 下 go_teacher=True 时进入）
        if not gate.go_teacher:
            return True
        escalation = self.confidence_gate.resolve_escalation(
            gate,
            step_budget=self.step_budget,
            api_budget=self.api_budget,
        )
        pre["escalation"] = escalation

        if escalation == ESCALATION_TEACHER:
            # M1 未接入 Teacher；保守退化为本地执行（记录以便 M5 分析）
            pre["escalation_note"] = "teacher_not_implemented_in_m1"
            return True
        if escalation == ESCALATION_RECOVERY:
            raise StalePage("Escalation → recovery")
        if escalation == ESCALATION_ABORT:
            state["status"] = "budget_exceeded"
            return False
        # ESCALATION_LOCAL
        return True

    def _run_shadow(self, local_decision: dict, pre: dict) -> None:
        """M2 影子采集。不改变执行路径，异常不向外抛（保 I1）。

        契约（§四）：api_teacher.choose(state_page_dict, goal_str, history_list)
        返回扁平 teacher decision（含 source / api_model / api_confidence，C4）。
        budget 消耗在 Validator 通过后由本方法执行（先验后消耗）。
        """
        state = self.state

        # 1. budget 检查
        if self.api_budget is not None:
            try:
                available = self.api_budget.teacher_available()
            except Exception:
                available = False
            if not available:
                pre["shadow"] = {"status": "budget_exhausted"}
                return

        # 2. 调用（全部异常吞掉，绝不阻塞 act）
        import time as _time
        started = _time.perf_counter()
        try:
            teacher_decision = self.api_teacher.choose(
                state["page"], state["goal"], state["history"]
            )
        except Exception as e:
            pre["shadow"] = {
                "status":  "failed",
                "error":   f"{type(e).__name__}: {e}",
                "latency_ms": round((_time.perf_counter() - started) * 1000),
            }
            return
        latency_ms = round((_time.perf_counter() - started) * 1000)

        # 3. 校验（C2：Teacher 输出必须经 Validator）
        try:
            val = decision_validator.validate(teacher_decision, state["page"])
        except Exception as e:
            pre["shadow"] = {
                "status": "validate_error",
                "error":  f"{type(e).__name__}: {e}",
                "latency_ms": latency_ms,
            }
            return

        if not val.valid:
            pre["shadow"] = {
                "status":  "invalid",
                "code":    val.code,
                "reason":  val.reason,
                "latency_ms": latency_ms,
            }
            # 无效的 teacher 决策不消耗 budget（先验后消耗）
            return

        # 4. 消耗 budget（仅在成功时）
        if self.api_budget is not None:
            try:
                self.api_budget.consume_teacher()
            except Exception:
                pass  # 消耗失败不影响采集（极端竞态）

        # 5. 记录对比
        local_choice    = local_decision.get("choice")
        teacher_choice  = teacher_decision.get("choice")
        local_op        = local_decision.get("operation")
        teacher_op      = teacher_decision.get("operation")
        local_target    = local_decision.get("target")
        teacher_target  = teacher_decision.get("target")

        entry = {
            "step":           len(state["history"]),
            "local": {
                "choice":    local_choice,
                "operation": local_op,
                "target":    local_target,
                "operation_confidence": local_decision.get("operation_confidence"),
                "target_confidence":    local_decision.get("target_confidence"),
            },
            "teacher": {
                "choice":    teacher_choice,
                "operation": teacher_op,
                "target":    teacher_target,
                "operation_confidence": teacher_decision.get("operation_confidence"),
                "target_confidence":    teacher_decision.get("target_confidence"),
                # C4 三字段
                "source":         teacher_decision.get("source", "api"),
                "api_model":      teacher_decision.get("api_model") or teacher_decision.get("model"),
                "api_confidence": teacher_decision.get("api_confidence") or teacher_decision.get("confidence"),
            },
            "agree":          local_choice == teacher_choice,
            "operation_match": local_op == teacher_op,
            "target_match":    local_target == teacher_target,
            "latency_ms":     latency_ms,
            "usage":          teacher_decision.get("usage", {}),
            # --- M2 #4a: 快照供 sample_extractor 使用（C3 structured 源）---
            # 浅拷贝 list(...)：基座约定 page 对象不被就地修改（browser.observe
            # 每次返回新对象）；若未来出现就地改 action dict 的路径需改 deepcopy。
            "actions_snapshot": list(state["page"]["actions"]),
        }
        state["teacher_decisions"].append(entry)
        pre["shadow"] = {
            "status":  "recorded",
            "agree":   entry["agree"],
            "latency_ms": latency_ms,
        }

    def command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                # --- M1: pre_execute 插入点 ---
                if not self._pre_execute():
                    return self.snapshot()
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                state["decision"] = None
                state["status"] = "ready"
                state["pre_execute"] = None  # M1: 清理暂存
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["decision"] = None
            if state["status"] in {"done", "blocked", "budget_exceeded"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                # 缺陷#5：纯拒收循环到此必须干净终止——raise ValueError 会逃逸
                # tick 变成 crash（违反 system 空判据）。置 budget_exceeded 后
                # 由下方 _pre_execute 的 StepBudget ABORT（先于 decision 访问）
                # 收口退出 run()。
                state["status"] = "budget_exceeded"
                return self.snapshot()
            try:
                state["decision"] = choose(state["page"], state["goal"], state["history"])
            except ValueError as e:
                # 2B 输出语义非法（unknown operation / target 越界）视同状态过期：
                # 走 StalePage 路径重新 observe + 重新 predict。
                # 缺陷#5（docs/10 契约：model_calls = len(decisions) 含 StalePage
                # 重试）：拒收也是一次真实模型调用，必须先入账再抛——否则
                # StepBudget(40) 与 MAX_STEPS*2 两道兜底全数不到，temp=0 时同一
                # 非法输出死循环（t004 实况：卡 70min+、3800+ 次空烧调用）。
                # 只捕 ValueError；HTTP 层 RuntimeError 继续上抛（交给 _http 退避）。
                state["decisions"].append({
                    "choice": None, "operation": None, "target": None,
                    "operation_confidence": None, "target_confidence": None,
                    "confidence": None, "latency_ms": None, "usage": None,
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "rejected": str(e),
                })
                raise StalePage(f"Decider returned invalid decision: {e}") from None
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                }
            )
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None

            # --- M1: pre_execute 结果取出（防止 tick 之间残留） ---
            pre = state.pop("pre_execute", None)

            selected = decision["choice"]
            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                state["status"] = "done" if selected == "DONE" else "blocked"
                state["plan_index"] = int(selected == "DONE")
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            action = next(a for a in page["actions"] if a["id"] == selected)
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    try:
                        text, helper = field_text(context)
                    except ValueError as e:
                        # D17: helper 拒绝编造值 → 该决策无效，与决策 2 同构
                        raise StalePage(f"Text helper could not supply value: {e}") from None
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            # Browser.act checks freshness immediately before input, including after text generation.
            state["browser"].act(action, page, text=text)
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                    # --- M1: pre_execute 链结果 ---
                    "pre_execute": pre,
                }
            )
            state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            state["status"] = (
                "blocked"
                if len(repeated) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in repeated)
                else "ready"
            )
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def run(self):
        # --- M1: 终止条件加 budget_exceeded ---
        while self.state["status"] not in {"done", "blocked", "budget_exceeded"}:
            yield self.command("tick")

    def close(self):
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
