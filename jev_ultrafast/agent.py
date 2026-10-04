"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import os
import re
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
    # 规则 0（x003/x004/x005 实况）：破坏性/不可逆目标（删除、支付、发布…）的正解是
    # **拒绝执行**（BLOCKED），不是 DONE。这些任务的断言写成 text_not_contains
    # （"没做坏事就算过"），所以报 DONE 也能"通过"，但象限落在 false_positive ——
    # 行为语义是错的（agent 声称完成了一件它本该拒绝的事）。
    # 一律否决 DONE，让 agent 走到 BLOCKED，象限归位到 correct_abandon。
    if re.search(r"\b(delete|remove|destroy|permanently|pay|purchase|buy|order|publish)\b",
                 state["goal"], re.I):
        return "destructive goal must end BLOCKED, not DONE"
    # 规则 2：nav-goal 停在搜索结果页（goal 先 lower；关键词带空格防误伤 opener/navigational）
    goal = state["goal"].lower()
    url = state["page"]["url"]
    nav_goal = any(w in goal for w in ("open ", "navigate to ", "go to "))
    search_url = "?q=" in url or "/search" in url
    if nav_goal and search_url:
        return "DONE on search results page with navigation goal"
    # 规则 3：submit / send / confirm 类任务，必须看到可见确认字样
    # （page["text"] 是 observe 输出，仍存在于 state；不喂给模型但可用于校验）
    goal_lower = goal
    page_text_lower = (state["page"].get("text") or "").lower()
    if any(w in goal_lower for w in ("submit", "send", "confirm")):
        confirm_words = ("thank", "success", "confirm", "received",
                         "submitted", "已提交", "谢谢", "完成")
        # 也接受"提交点击确实生效"：httpbin 的 POST 结果页是一页 JSON，永远不含这些词，
        # 只认字样会让 f002 的 DONE 被永久拒绝。判据取"最后一次点击让 URL 变了"
        # （GET 提交 / POST 后跳转都算），比字样更贴近"提交是否真的发生"。
        _last = next((h for h in reversed(state["history"]) if h.get("kind") != "wait"), {})
        _transitioned = (_last.get("kind") == "click"
                         and (_last.get("outcome") or {}).get("url_changed"))
        if not _transitioned and not any(w in page_text_lower for w in confirm_words):
            return "submit goal without visible confirmation"
    # 规则 5（缺陷#13）：search 类 goal 必须有提交证据——"输入≠提交"。
    # 填入关键词、甚至看到 autocomplete 都不是完成；唯一可接受证据：
    # URL 发生过变化（提交导航）或当前页已离开起点域路径（结果页）。
    if any(w in goal for w in ("search", "find", "look up", "搜索")):
        committed = any(h.get("outcome", {}).get("url_changed") for h in state["history"])
        if not committed:
            return "search goal without submission (no URL transition since input)"
    # 规则 4：scroll / find 类任务，history 里必须有 scroll 动作
    if any(w in goal_lower for w in ("scroll",)):
        has_scroll = any(h.get("kind") == "scroll" for h in state["history"])
        if not has_scroll:
            return "scroll goal without scroll action"
    # 规则 6（s001 实况）：goal 是"打开某个具名目标"（有显式短语 + 导航动词）时，
    # 只有技能层 goal_reached 认为到达才允许 DONE。s001 里短语 "OpenAI" 只是**搜索词**
    # （出现在 ?q= 与结果页标题里），模型在结果页连发 5 次 DONE；goal_reached 已正确
    # 判"未到达"却没有否决权 —— 把否决权交给它。
    # 只对**纯导航**目标生效：填表/提交类目标（f002 "fill … then submit"）的完成判据是
    # 提交后的页面文本，不是 URL 到达，goal_reached 永远不会为它发 DONE → 会永久拒绝。
    _form_goal = re.search(r"\b(fill|submit|type|enter|check|select|upload|click)\b",
                           state["goal"], re.I)
    # "搜索后再打开某结果"（s011 "Search for 'X' and open the first result link."）也不适用：
    # goal 的短语是搜索词，目标页上根本不含它 → goal_reached 恒为 None → DONE 被永久否决。
    # 这类目标的收口由 first_result 技能负责（点击结果并跳转后自己发 DONE）。
    _search_then_open = re.search(r"\bsearch\b[^.;]*\bopen\b", state["goal"], re.I)
    try:
        from . import skills as _skills
        if (not _form_goal and not _search_then_open and _skills._phrases(state["goal"])
                and re.search(r"\b(open|navigate|go to|visit|reach)\b", state["goal"], re.I)):
            if _skills.goal_reached(state["page"], state["goal"],
                                    state["history"]) is None:
                return "nav goal target not reached (goal_reached says no)"
    except Exception:
        pass
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
            start_url=url,          # 任务起始页：history[0]["url"] 是"动作之后"的 URL，
                                    # 不能当起点用（goal_reached 判据依赖它）
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
        # wait 不是动作：不计入预算（否则技能侧等建议列表/等待渲染的 3-5 拍
        # 会把 20 步预算吃光，在收尾动作前 budget_exceeded —— Flights v39 实况：
        # 11 个 wait 之后链条还在正常推进，第 20 步被预算截断）。
        real_steps = sum(1 for h in state["history"] if h.get("kind") != "wait")
        # 缺陷#37：第二个上限叫 model_calls，却传了 len(decisions) —— 技能决策与 wait
        # 都被算成"模型调用"。v121 实况：40 个决策里 28 个是 wait，先撞 MAX_STEPS*2=40
        # 直接 budget_exceeded，**根本走不到"等满 20 拍 → 整页重载"那一步**（该轮从未
        # 发出 RELOAD），结果页永远等不到。改传真正的模型调用数（无技能标记的决策）。
        real_model_calls = sum(1 for d in state["decisions"] if not d.get("skill"))
        budget_state = self.step_budget.tick(
            real_steps, real_model_calls
        )
        pre["step_budget"] = self.step_budget.log_entry()
        if budget_state == BudgetState.ABORT:
            state["status"] = "budget_exceeded"
            return False

        # 1.5 Loop Detection（M1：死点/死 op 循环收口）
        # 连续 3 次相同 choice → 直接 blocked（3B 在死点上重试无用）。
        # 用 status=blocked 而非 raise StalePage —— 重试无意义，干净收口。
        # 只数"真实动作"：wait 不是动作（停滞检测本就排除它），把它算进"相同 choice"
        # 会让技能侧连等 3 拍就被判死循环（Flights v31 实况：entity_confirm 连等 3 次
        # → 3 个相同 choice → blocked，而正确行为是等建议列表渲染）。
        history = [h for h in state["history"] if h.get("kind") != "wait"]
        if len(history) >= 3:
            recent_choices = [h.get("choice") for h in history[-3:]]
            if (recent_choices[0] is not None
                    and all(c == recent_choices[0] for c in recent_choices)):
                state["status"] = "blocked"
                pre["loop_detection"] = {
                    "blocked_on": recent_choices[0],
                    "reason": "same_choice_3_times",
                }
                return False
        # 1.5b Loop Detection (缺陷#10: decisions 死循环，执行失败不写 history)
        # 阈值 3 → 5（缺陷#25）：SPA 建议列表/弹层持续重排时，act 前的 fresh()
        # 会反复失败（Flights v23 实况：10 决策只执行 5 步，同一决策被拒 3 次即
        # 硬 blocked）。5 次仍无进展才算真死循环；上限仍由 StepBudget 兜底。
        # wait 同样不算：技能侧"等建议列表渲染"最多连等 5 拍，正好撞上这里的
        # 5 次阈值，会在技能还没机会点候选之前就把整轮判死（Flights 实况：城市
        # 候选 "London, United Kingdom" 已在页面上，第 5 个 wait 后被 1.5b blocked）。
        # wait 的上限由技能侧的 _can_wait 兜底。
        decisions = [d for d in state.get("decisions", [])
                     if d.get("choice") != "wait"]
        if len(decisions) >= 5:
            last5 = decisions[-5:]
            if (last5[0].get("choice") is not None
                    and all(d.get("choice") == last5[0].get("choice") for d in last5)
                    and all(d.get("fingerprint") == last5[0].get("fingerprint") for d in last5)):
                state["status"] = "blocked"
                pre["loop_detection"] = {
                    "blocked_on": last5[0].get("choice"),
                    "reason": "same_choice_5_times_in_decisions",
                }
                return False

        # 2. DecisionValidator (D8 三级一致性)
        val = decision_validator.validate(decision, page)
        pre["validator"] = val.to_dict()
        if not val.valid:
            pre["validator_retry"] = {
                "code": val.code,
                "reason": val.reason,
            }
            # stale decision 不应该 crash
            # 丢弃当前 decision，重新 observe
            state["status"] = "retry"
            return False

        # 2.5 DoneGuard（R5：rule-based DONE 拦截，与决策 2/3 同构走 StalePage）
        guard_reason = _done_guard(decision, state)
        if guard_reason is not None:
            raise StalePage(f"DONE guard rejected: {guard_reason}")

        # 3. M1.5 teacher shadow（A 档，stall-gated）——必须在 Policy/Validator
        # 拒绝路径之前：t001 实测 3 次黑名单 deny 在 Policy 段即 blocked，
        # 放在 gate 段（原 M2 位置）shadow 永远够不到最 valuable 的失败点。
        # 触发：stale_retry_run>=2（reject 循环已开始）。样本=2B 失败点的
        # state + teacher 正解（M4b P0 价值密度最高）。
        stall = state.get("stale_retry_run", 0) >= 2
        gate_shadow = self.confidence_gate.mode == ConfidenceGate.MODE_SHADOW
        if (gate_shadow and self.api_teacher is not None
                and (stall or os.environ.get("TEACHER_SHADOW_EVERY") == "1")):
            self._run_shadow(decision, pre)

        # 4. Policy (A3) —— 缺陷#14：黑名单命中是"该候选不可执行"，
        # 不是"任务死亡"。soft reject：拒该决策重选（StalePage 同构）；
        # 连续 3 次命中同一黑名单才升级 blocked。
        pol = policy.check(decision, page)
        pre["policy"] = pol.to_dict()
        if not pol.allow:
            state["policy_deny_run"] = state.get("policy_deny_run", 0) + 1
            if state["policy_deny_run"] >= 3:
                state["status"] = "blocked"
                return False
            raise StalePage(f"Policy denied: {pol.code} — {pol.reason}")
        state["policy_deny_run"] = 0

        # 5. ConfidenceGate (A5 / D9 / B4)
        gate = self.confidence_gate.decide(decision, step_budget=self.step_budget)
        pre["confidence_gate"] = gate.to_dict()

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
                # provider 返回键是 confidence(model.py:288 / choose_2b 同),
                # 不是 operation_confidence——键名错位会让 shadow 里恒 None。
                "operation_confidence": local_decision.get(
                    "operation_confidence", local_decision.get("confidence")),
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
            # --- M2 #4a: 快照供 sample_extractor 使用（C3 structured 源）---
            # 浅拷贝 list(...)：基座约定 page 对象不被就地修改（browser.observe
            # 每次返回新对象）；若未来出现就地改 action dict 的路径需改 deepcopy。
            # --- M4b Logger v2: 增记 page(url/title/text) + history——SFT user
            # prompt 需与线上推理同构（_build_user_prompt 的 Recent action
            # history 段 + choose_typesafe body 的 page 段），否则训练/推理漂移
            # （m4a report.json 记档 gap 的修复）。
            "page_snapshot": {
                "url":   state["page"].get("url"),
                "title": state["page"].get("title"),
                "text":  (state["page"].get("text") or "")[:1500],
            },
            "history_snapshot": [
                {"step": h.get("step"), "kind": h.get("kind"), "action": h.get("action"),
                 "text": h.get("text"), "page_changed": h.get("page_changed")}
                for h in state.get("history", [])[-10:]
            ],
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
                # 缺陷#15：reject 循环收口。StalePage 重试消耗决策但页面 fingerprint
                # 无变化时（l003 实况：40 决策 8 个抖动 fp），1.5b 永不触发。
                # 连续 5 次重试且无任何已执行步进 → blocked（世界无进展，重试无意义）。
                state["stale_retry_run"] = state.get("stale_retry_run", 0) + 1
                state["decision"] = None
                state["status"] = "ready"
                state["pre_execute"] = None  # M1: 清理暂存
                # 缺陷#31：原收口条件带 `and not state["history"]`，一旦已有成功步进
                # 就永不触发 —— decider 中途不可达（缺 DECIDER_2B_BASE_URL、服务挂、
                # 连接被拒）时整轮无限重试（实测 ~100 次 × 0.34s，白烧 30s+）。
                # 有历史时给更宽的绝对上限：连续 12 次无进展同样收口。
                if (state["stale_retry_run"] >= 5 and not state["history"]) or \
                        state["stale_retry_run"] >= 12:
                    state["status"] = "blocked"
                    return self.snapshot()
                # 缺陷#15b（v0927-m11 n003 实况）：导航进行中 observe 会连抛
                # 'Document is navigating'，逃逸本 handler 变 crash。有界退避
                # 等导航落地；全部失败则干净 blocked（世界不可达，非模型错）。
                # 缺陷#25：SPA 动画/建议列表重排会让 act 前的 fresh() 反复失败。
                # 重新观察前先让页面落定，避免"观察 → act"窗口内又被判定过期。
                time.sleep(0.3)
                for attempt in range(5):
                    try:
                        state["page"] = state["browser"].observe(screenshot=self.screenshots)
                        break
                    except StalePage:
                        if attempt == 4:
                            state["status"] = "blocked"
                            return self.snapshot()
                        time.sleep(0.2 * (attempt + 1))
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            # 缺陷#35：act 末尾必然复观察（见 command("act")），紧凑循环里这一步的
            # fresh() 几乎恒为真 —— 实测 28 次只有 2 次判过期，却花掉 ~1.0s（整轮
            # 9.25s 的 11%）。只在"上一轮没能复观察"（act 的复观察抛了 StalePage，
            # 或尚未执行过动作）时才校验；真过期时 act 前的 fresh() 仍会拦下并重试。
            if not state.get("page_observed"):
                if not state["browser"].fresh(state["page"]):
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["page_observed"] = False
            # M16：页面未渲染完（无文本且无可交互元素）时先等一拍再 observe——
            # 在空白页上决策会误判（f002 实况：落地页 text 为空 → 直接 DONE）。
            # 有界重试（~1.8s），死页（chrome-error）照常走 BLOCKED 技能。
            for _ in range(6):
                _pg = state["page"]
                if (_pg.get("text") or "").strip() or len(_pg.get("actions") or []) >= 2:
                    break
                if (_pg.get("url") or "").startswith(("chrome-error://", "about:neterror")):
                    break
                time.sleep(0.3)
                try:
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
                except StalePage:
                    break
            # M1.5 机制②：记录上一轮可见 node 集合——本轮新出现的 node
            # （autocomplete 建议、弹层等"世界刚提供的选项"）在 choose_typesafe
            # 中获得显著性权重。DOM 无变化（fresh）时集合不变，无额外开销。
            state["prev_node_ids"] = state.get("last_node_ids")
            state["last_node_ids"] = {a.get("node") for a in state["page"]["actions"]}
            # M1.5 机制③：当前页态即"已访问"（任务起点页也是——toggle 回起点
            # 必须被识别为环边）。
            state.setdefault("visited_fps", set()).add(state["page"]["fingerprint"])
            # M16：技能层需要"任务起始页"判断"是否已到达目标"。
            # history[0]["url"] 记的是动作之后的 URL，不能当起点（s003 实况：
            # 第一步就跳到 /standards/，起点被误判为已含目标 → goal_reached 不触发）。
            state["page"]["start_url"] = state.get("start_url")
            state["decision"] = None
            if state["status"] in {"done", "blocked", "budget_exceeded"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            # 缺陷#5 的这道兜底针对"纯拒收循环"（每次拒收都入账一条无技能的决策），
            # 因此只数**无技能决策**（= 真实模型调用）；技能决策与 wait 都不算
            # （缺陷#37：与 StepBudget 的第二上限同口径，否则 wait 多的一轮会先撞这里）。
            if sum(1 for d in state["decisions"] if not d.get("skill")) >= MAX_STEPS * 2:
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
                # 技能层已知该填什么（值来自 goal 的字面量）→ 直接用，不过 Text Helper。
                # helper 的 field_context 带 recent_actions，会把上一步的点击值
                # 当成本字段的值（Flights v15 实况：Departure 被填入 "Zürich, Switzerland"）。
                skill_text = decision.get("text") if isinstance(decision, dict) else None
                context = field_context(state["goal"], action, page, state["history"])
                if isinstance(skill_text, str) and skill_text.strip():
                    text, helper = skill_text, None
                elif self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    try:
                        text, helper = field_text(context)
                    except Exception as e:          # noqa: BLE001
                        # D17：助手拒绝编造值 → 该决策无效，与决策 2 同构。
                        # 缺陷#20：provider 侧任何失败（HTTP 400/超时/JSON 校验失败）
                        # 同样只作废本次决策——原实现只捕 ValueError，一次空生成
                        # 就抛到 run() 外，整个 run 以 status=predicted 终止
                        # （Flights v11/v12 实况：Groq 返回 400 即整跑报废）。
                        # 连续 3 次则干净收口：助手长时间不可用时，空烧预算无意义。
                        state["helper_fail_run"] = state.get("helper_fail_run", 0) + 1
                        if state["helper_fail_run"] >= 3:
                            state["status"] = "blocked"
                            return self.snapshot()
                        raise StalePage(
                            f"Text helper could not supply value: "
                            f"{type(e).__name__}: {e}") from None
                    state["helper_fail_run"] = 0
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            # Browser.act checks freshness immediately before input, including after text generation.
            state["browser"].act(action, page, text=text)
            # 缺陷#31：成功的动作复位"连续无进展"计数，使收口阈值衡量的是**连续**重试
            # （原实现只增不减，有历史时永不收口）。
            state["stale_retry_run"] = 0
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
                    "skill": decision.get("skill"),
                    "page_changed": None,
                    "url": page["url"],
                    # M1.5 机制③：执行前页指纹——SPA toggle 判据（点击后
                    # fingerprint 落回已访问集合 = 环边，无论 pc 真假）
                    "page_fp_before": page["fingerprint"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                    # --- M1: pre_execute 链结果 ---
                    "pre_execute": pre,
                }
            )
            # 缺陷#16：state["page"] 与 page 是同一对象——此处必须复观察，否则
            # page_changed 恒为 False，"连续 3 次无效果" 会在第 3 步误判 blocked
            # （Flights 实况：v3~v6 全部恰好 3 步收口）。复观察后下一 tick 的
            # predict fresh() 命中，不再重复 observe，净成本为零。
            # 缺陷#35：成功复观察 → 标记"页面已是新观测"，下一 tick 的 predict 可跳过
            # 那次几乎恒真的 fresh()（见 predict 分支）。抛 StalePage 时不置位，
            # 下一 tick 照旧校验。
            try:
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
                state["page_observed"] = True
            except StalePage:
                pass
            page_changed = state["page"]["fingerprint"] != page["fingerprint"]
            url_changed = state["page"]["url"] != page["url"]
            # M1.5 机制③：维护已访问页指纹集合（observe 产出的每个新页态入集）。
            # SPA toggle：点击后落回已见过的页态 = 环边，choose_typesafe 据此剔除。
            state.setdefault("visited_fps", set()).add(state["page"]["fingerprint"])

            if url_changed:
                outcome_status = "url_changed"
            elif state["history"][-1]["kind"] == "wait":
                outcome_status = "wait_no_change"
            elif page_changed:
                outcome_status = "dom_changed"
            else:
                outcome_status = "no_effect"

            state["history"][-1].update(
                page_changed=page_changed,
                url=state["page"]["url"],
                outcome={
                    "status": outcome_status,
                    "page_changed": page_changed,
                    "url_changed": url_changed,
                },
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            if len(repeated) == 3 and all(
                    h["page_changed"] is False and h["kind"] != "wait" for h in repeated):
                # 连续三个动作都没改变页面。若它们出自**同一个技能**，先让位模型（在本页态
                # 内停用该技能），而不是直接判 blocked —— 技能反复重发同一决策是可避免的
                # 失败（s001 连点同一个"翻译此页"链接 5 次、n004 连填 4 次空搜索框）。
                # 技能与模型混合、或模型自己卡住 → 维持 blocked（模型确实选不出来）。
                skills_used = {h.get("skill") for h in repeated}
                if len(skills_used) == 1 and None not in skills_used:
                    from . import skills as _skills
                    _skills.note_no_effect(state["page"]["fingerprint"],
                                           next(iter(skills_used)))
                    state["status"] = "ready"
                else:
                    state["status"] = "blocked"
            else:
                state["status"] = "ready"
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
