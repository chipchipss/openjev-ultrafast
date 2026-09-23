"""API Teacher. M2 数据飞轮的 C 类数据采集器（Active Learning 第一阶段）。

关联硬约束：
  B1  每次询问消费 APIBudget 的 Teacher 池（分池限额，不碰 Recovery 池）
  B4  触发时机由上层编排（M2 MODE_SHADOW 无条件全量 / M5 Confidence Gate 按需）
      ——本模块只负责"问一次并记录"
  C2  Teacher 输出必须经 Validator 才能进训练集（校验在 sample_extractor 落地）
  C4  每条样本携带来源：source / api_model / api_confidence
  E5  失败四维：HTTP 层与响应损坏抛 RuntimeError（system 类），由 runner 归类

M2 定位：数据采集器，不是决策替代者——输出不进入执行路径，只进 shadow 记录。
M5 定位：按需触发（校准后 P(correct) 低才调）。

环境变量（与 decider 分开，required——禁止静默同源：同模型问不出分歧信号，
C 类数据必须来自与本地 decider 不同的 Teacher）：
  TEACHER_BASE_URL / TEACHER_MODEL / TEACHER_API_KEY

HTTP 通道复用 decider/_http.post_chat（唯一 POST 实现：退避重试 + 关 Thinking +
response_format json_object，全部继承）。

接口：
  correct(state, decision) -> dict
    state:   agent.state（url / title / text / actions / goal）
    decision: 本地 decider 的 decision（choice / operation / target / 双置信度）
    返回：{
      "source": "api",                 # C4
      "api_model": <teacher model>,    # C4
      "api_confidence": <float|null>,  # C4：Teacher 自报 operation_confidence（仅记录，
                                        #  C5 不信任——校准在 M5）
      "corrected": {operation, target, choice,
                    operation_confidence, target_confidence},   # 原样保留 Teacher 输出
      "usage": {...}, "latency_ms": int,
    }
"""
from __future__ import annotations

import json
import os
import time

try:  # 平铺（主仓）
    from api_budget import APIBudget, APIBudgetExhausted
    from decider._http import post_chat
except ImportError:  # 包内（fork: jev_ultrafast.*）
    from .api_budget import APIBudget, APIBudgetExhausted
    from .decider._http import post_chat


SYSTEM_TEACHER = (
    "You are a senior browser-automation reviewer. Given the user's goal, the "
    "current page, and the local model's decision, output the CORRECT decision "
    "as one JSON object with exactly these keys: "
    '{"operation": string, "target": string|null, "choice": string, '
    '"operation_confidence": number in [0,1], '
    '"target_confidence": number in [0,1] or null}. '
    "If the local decision is already correct, output it unchanged. "
    "No explanations, no code, no markdown. Only the JSON object."
)


try:  # 平铺（主仓）
    from decider.action_space import action_space
except ImportError:  # 包内（fork）
    from .decider.action_space import action_space

def _extract_json(content: str) -> dict:
    """content → dict。剥围栏 + 定位 braces——渠道偶发 ``` 围栏/前缀不至炸链。"""
    s = content.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1:] if nl != -1 else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        raise RuntimeError(f"Teacher returned non-JSON: {content[:120]!r}")
    try:
        obj = json.loads(s[a:b + 1])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Teacher returned non-JSON: {e}") from None
    if not isinstance(obj, dict):
        raise RuntimeError("Teacher response is not a JSON object")
    return obj


SYSTEM_TEACHER_CHOOSE = (
    "You are an expert browser-automation decision maker. Given the user's goal, "
    "the current page, recent actions, and the CANDIDATE LIST, output the decision "
    "YOU would take as one JSON object with exactly these keys: "
    '{"operation": string, "target": string|null, "choice": string, '
    '"operation_confidence": number in [0,1], '
    '"target_confidence": number in [0,1] or null}. '
    "Field contract: "
    'target = the target index EXACTLY as shown in the candidate list (e.g. "1" or "3:2"); '
    'choice = the choice id EXACTLY as shown (e.g. "e1" — never the label, never the index); '
    "for controls and sentinels use their listed choice id / the operation name. "
    "Only use operation/target/choice values that appear in the candidate list. "
    "No explanations, no code, no markdown. Only the JSON object."
)


def _candidate_block(targets: dict, controls: dict) -> str:
    """教师专用候选渲染：必须带 choice id（decider 的渲染不含 id，教师无法作答）。"""
    lines = ["Candidates — target = target, choice = choice_id:"]
    for op, cands in targets.items():
        for tid, a in cands.items():
            lines.append(f'  {op}: target="{tid}" → choice="{a.get("id")}" '
                         f'label="{a.get("label", "")}"')
    if controls:
        lines.append("Controls (target must be null):")
        for op, a in controls.items():
            lines.append(f'  {op} → choice="{a.get("id")}"')
    lines.append("Sentinels (target must be null, choice = operation): "
                 'DONE → choice="DONE", BLOCKED → choice="BLOCKED"')
    return "\n".join(lines)


def _scenario_choose(state: dict, goal: str, history: list) -> str:
    text = state.get("text") or ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) > 6000:
        text = text[:6000] + "…（已截断）"
    recent = []
    for h in (history or [])[-10:]:
        line = f"  {h.get('step', '?')}. {h.get('kind', '?')} {h.get('action', '?')}"
        if h.get("text"):
            line += f' text="{h["text"]}"'
        if h.get("page_changed") is not None:
            line += f" page_changed={h['page_changed']}"
        recent.append(line)
    _, targets, controls = action_space(state.get("actions") or [])
    return "\n".join([
        f"Goal: {goal}",
        "",
        "Current page:",
        f"- url: {state.get('url', '')}",
        f"- title: {state.get('title', '')}",
        f"- text: {text}",
        "",
        _candidate_block(targets, controls),
        "",
        "Recent actions:",
        "\n".join(recent) if recent else "  (none)",
        "",
        "Output the decision you would take as one JSON object.",
    ])


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"Missing env {name} — Teacher model must be configured explicitly "
            f"(must differ from the local decider; same model produces no disagreement signal)"
        )
    return v


def _scenario(state: dict, decision: dict) -> str:
    text = state.get("text") or ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) > 6000:
        text = text[:6000] + "…（已截断）"
    return "\n".join([
        f"Goal: {state.get('goal', '')}",
        "",
        "Current page:",
        f"- url: {state.get('url', '')}",
        f"- title: {state.get('title', '')}",
        f"- text: {text}",
        "",
        "Local model's decision:",
        json.dumps(
            {k: decision.get(k) for k in
             ("choice", "operation", "target",
              "operation_confidence", "target_confidence")},
            ensure_ascii=False,
        ),
        "",
        "Output the correct decision as one JSON object.",
    ])


class APITeacher:
    def __init__(self, budget: APIBudget) -> None:
        if not isinstance(budget, APIBudget):
            raise ValueError("budget must be an APIBudget (B1: teacher pool lives here)")
        self.budget = budget

    def choose(self, state: dict, goal: str, history: list) -> dict:
        """§四契约：独立模式——不看本地 decision，Teacher 自己答同一题（无锚定）。

        不消耗 budget：由 agent._run_shadow 在 Validator 通过后 consume（先验后消耗）。
        返回扁平 decision dict + C4 字段（source / api_model / api_confidence / model）。
        """
        if not isinstance(state, dict):
            raise TypeError("state must be a dict (agent.state['page'])")
        if not isinstance(goal, str):
            raise TypeError("goal must be a str")
        if history is not None and not isinstance(history, list):
            raise TypeError("history must be a list")
        if not self.budget.teacher_available():
            raise APIBudgetExhausted(
                f"teacher pool exhausted ({self.budget.teacher_used}/{self.budget.teacher_limit})"
            )

        base = _env("TEACHER_BASE_URL").rstrip("/")
        model = _env("TEACHER_MODEL")
        key = os.environ.get("TEACHER_API_KEY", "")

        messages = [
            {"role": "system", "content": SYSTEM_TEACHER_CHOOSE},
            {"role": "user", "content": _scenario_choose(state, goal, history or [])},
        ]

        started = time.perf_counter()
        result, _ = post_chat(
            base, model, key, messages,
            max_tokens=512, temperature=0.0,
            response_format={"type": "json_object"},
        )
        latency_ms = round((time.perf_counter() - started) * 1000)

        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Teacher returned unexpected response shape") from None
        if not isinstance(content, str):
            raise RuntimeError("Teacher content is not a string")
        parsed = _extract_json(content)
        if "operation" not in parsed:
            raise RuntimeError("Teacher response missing 'operation'")

        api_confidence = parsed.get("operation_confidence")
        try:
            api_confidence = float(api_confidence) if api_confidence is not None else None
        except (TypeError, ValueError):
            api_confidence = None

        out = dict(parsed)
        out.update({
            "source":         "api",          # C4
            "api_model":      model,          # C4
            "model":          model,          # §四 字段
            "api_confidence": api_confidence,  # C4（C5 仅记录）
            "usage":          result.get("usage", {}),
            "latency_ms":     latency_ms,
        })
        return out

    def correct(self, state: dict, decision: dict) -> dict:
        """问 Teacher 一次，返回带 C4 来源标记的 corrected 记录。"""
        if not isinstance(state, dict) or not isinstance(decision, dict):
            raise TypeError("state and decision must be dicts")
        # B1：先查池（不可用时明确抛出，调用方/shadow runner 决定停采）
        if not self.budget.teacher_available():
            raise APIBudgetExhausted(
                f"teacher pool exhausted ({self.budget.teacher_used}/{self.budget.teacher_limit})"
            )

        base = _env("TEACHER_BASE_URL").rstrip("/")
        model = _env("TEACHER_MODEL")
        key = os.environ.get("TEACHER_API_KEY", "")

        messages = [
            {"role": "system", "content": SYSTEM_TEACHER},
            {"role": "user", "content": _scenario(state, decision)},
        ]

        started = time.perf_counter()
        result, _ = post_chat(
            base, model, key, messages,
            max_tokens=512, temperature=0.0,
            response_format={"type": "json_object"},
        )

        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Teacher returned unexpected response shape") from None
        if not isinstance(content, str):
            raise RuntimeError("Teacher content is not a string")

        corrected = _extract_json(content)
        if "operation" not in corrected:
            raise RuntimeError("Teacher response missing 'operation'")

        api_confidence = corrected.get("operation_confidence")
        try:
            api_confidence = float(api_confidence) if api_confidence is not None else None
        except (TypeError, ValueError):
            api_confidence = None

        self.budget.consume_teacher()

        return {
            "source":          "api",          # C4
            "api_model":       model,          # C4
            "api_confidence":  api_confidence,  # C4（C5：仅记录，M5 才校准）
            "corrected":       corrected,
            "usage":           result.get("usage", {}),
            "latency_ms":      round((time.perf_counter() - started) * 1000),
        }


# ---------------------------------------------------------------------------
# Smoke（mock post_chat，无网络；走真实 APIBudget）
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import sys

    mod = sys.modules[__name__]  # 平铺/包内通用自 patch（decider 冒烟同款）

    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def check_raises(name, fn, exc):
        nonlocal passed, total
        total += 1
        try:
            fn()
        except exc:
            passed += 1
        except Exception as e:
            print(f"FAIL: {name} (raised {type(e).__name__}: {e})")
        else:
            print(f"FAIL: {name} (no raise)")

    class Fake:
        def __init__(self, payload=None, shape_ok=True, raw=None):
            self.payload = payload
            self.shape_ok = shape_ok
            self.raw = raw
            self.calls = []

        def __call__(self, *args, **kw):
            self.calls.append({"args": args, **kw})
            if self.raw is not None:
                return self.raw, 11
            content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
            body = {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 42}}
            if not self.shape_ok:
                body = {"nope": True}
            return body, 11

    os.environ["TEACHER_BASE_URL"] = "http://teacher.test/v1"
    os.environ["TEACHER_MODEL"] = "teacher-model-x"
    os.environ["TEACHER_API_KEY"] = "sk-test"

    state = {"goal": "open the standards page", "url": "https://example.com/",
             "title": "t", "text": "body", "actions": []}
    local = {"choice": "e1", "operation": "CLICK", "target": "1",
             "operation_confidence": 0.6, "target_confidence": 0.5}

    # --- 构造 ---
    check_raises("budget required", lambda: APITeacher(None), ValueError)
    check_raises("budget type enforced",
                 lambda: APITeacher("not-a-budget"), ValueError)

    # --- 正常路径：C4 字段 + 消费 ---
    b = APIBudget(2, 1)
    t = APITeacher(b)
    mod.post_chat = Fake({"operation": "CLICK", "target": "2", "choice": "e3",
                          "operation_confidence": 0.95, "target_confidence": 0.9})
    rec = t.correct(state, local)
    check("source=api (C4)", rec["source"] == "api")
    check("api_model (C4)", rec["api_model"] == "teacher-model-x")
    check("api_confidence (C4)", rec["api_confidence"] == 0.95)
    check("corrected operation", rec["corrected"]["operation"] == "CLICK")
    check("corrected choice", rec["corrected"]["choice"] == "e3")
    check("usage carried", rec["usage"].get("total_tokens") == 42)
    check("latency int", isinstance(rec["latency_ms"], int))
    check("consumed 1/2", b.teacher_used == 1 and b.teacher_available())
    user_msg = mod.post_chat.calls[0]["args"][3][1]["content"]
    check("scenario carries goal & local decision",
          "open the standards page" in user_msg and "e1" in user_msg)

    # --- 第二次 OK，第三次预算耗尽（B1） ---
    t.correct(state, local)
    check("consumed 2/2", not b.teacher_available())
    check_raises("budget exhausted at entry",
                 lambda: t.correct(state, local), APIBudgetExhausted)

    # --- 响应损坏 → RuntimeError（E5 system 类） ---
    t2 = APITeacher(APIBudget(5, 1))
    mod.post_chat = Fake("not json at all")
    check_raises("non-JSON → RuntimeError", lambda: t2.correct(state, local), RuntimeError)
    check("non-consume on bad payload", APIBudget(5, 1).teacher_used == 0)
    mod.post_chat = Fake({"target": "1", "choice": "e1"})  # JSON 合法但缺 operation
    mod2 = APITeacher(APIBudget(5, 1))
    mod2_b = mod2.budget
    check_raises("missing operation → RuntimeError",
                 lambda: mod2.correct(state, local), RuntimeError)
    check("missing-op not consumed", mod2_b.teacher_used == 0)
    mod.post_chat = Fake(shape_ok=False)
    check_raises("bad shape → RuntimeError",
                 lambda: t2.correct(state, local), RuntimeError)

    # --- choose()（§四契约：独立模式、扁平输出、不自消耗） ---
    b4 = APIBudget(3, 1)
    t4 = APITeacher(b4)
    mod.post_chat = Fake({"operation": "CLICK", "target": "1", "choice": "e1",
                          "operation_confidence": 0.9, "target_confidence": 0.8})
    hist = [{"step": 1, "kind": "click", "action": "Open", "page_changed": True}]
    ch = t4.choose({"url": "https://example.com/", "title": "t", "text": "body"},
                   "go to the standards page", hist)
    check("choose flat choice", ch.get("choice") == "e1")
    check("choose flat operation", ch.get("operation") == "CLICK")
    check("choose source (C4)", ch.get("source") == "api")
    check("choose api_model (C4)", ch.get("api_model") == "teacher-model-x")
    check("choose model field (§四)", ch.get("model") == "teacher-model-x")
    check("choose api_confidence (C4)", ch.get("api_confidence") == 0.9)
    check("choose usage", ch.get("usage", {}).get("total_tokens") == 42)
    check("choose NOT consumed（agent 消费，§四）", b4.teacher_used == 0)
    umsg = mod.post_chat.calls[-1]["args"][3][1]["content"]
    check("choose renders goal + history",
          "go to the standards page" in umsg and "Open" in umsg)
    check("choose independent（无本地 decision 锚定）", "Local model" not in umsg)
    # 修正回归（候选可见性）：教师必须看到 elements/operations/sentinels，
    # 否则盲答 target/choice 会被 D8 全拒 → c_pairs 恒 0
    page_with_actions = {"url": "https://example.com/", "title": "t", "text": "body",
                         "actions": [{"id": "e1", "kind": "click", "node": 1,
                                      "role": "button", "label": "Go"}]}
    r_act = t4.choose(page_with_actions, "open the guide page", [])
    umsg2 = mod.post_chat.calls[-1]["args"][3][1]["content"]
    check("choose renders target+choice mapping",
          'target="1"' in umsg2 and 'choice="e1"' in umsg2)
    check("choose prompt has field contract",
          "choice id" in mod.post_chat.calls[-1]["args"][3][0]["content"])
    check("choose renders sentinels", "BLOCKED" in umsg2 and "DONE" in umsg2)
    check("choose still flat C4", r_act.get("source") == "api"
          and r_act.get("operation") is not None
          and r_act.get("api_model") is not None)
    # --- _extract_json 加固：围栏与空 content ---
    mod.post_chat = Fake('```json\n{"operation": "CLICK", "target": "1", '
                         '"choice": "e1", "operation_confidence": 0.9, '
                         '"target_confidence": 0.9}\n```')
    t5 = APITeacher(APIBudget(3, 1))
    r_fence = t5.choose({"url": "https://example.com/", "title": "t", "text": "b"},
                        "g", [])
    check("fenced content parses", r_fence.get("operation") == "CLICK")
    mod.post_chat = Fake("")
    check_raises("empty content → RuntimeError",
                 lambda: t5.choose({"url": "https://e.com/", "title": "t",
                                    "text": "b"}, "g", []),
                 RuntimeError)

    b4.consume_teacher()
    b4.consume_teacher()
    b4.consume_teacher()
    check_raises("choose exhausted → APIBudgetExhausted",
                 lambda: t4.choose({"url": "u"}, "g", []), APIBudgetExhausted)

    # --- 缺 env → RuntimeError ---
    os.environ.pop("TEACHER_MODEL", None)
    t3 = APITeacher(APIBudget(1, 1))
    check_raises("missing TEACHER_MODEL → RuntimeError",
                 lambda: t3.correct(state, local), RuntimeError)

    print(f"SMOKE OK: {passed}/{total}")


if __name__ == "__main__":
    _smoke()
