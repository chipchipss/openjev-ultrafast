"""2B Decider：Decision 层替换实现（替换 model.py:choose()，H2）。

接口边界（B）：OpenAI-compatible HTTP —— POST {base_url}/chat/completions。
后端可换（llama.cpp server / Ollama / vLLM / 任意 OpenAI 兼容 API），
经 base_url + model 配置（DECIDER_BASE_URL / DECIDER_MODEL 环境变量或构造参数）。
本模块不 import 任何后端 SDK，不绑定 llama-cpp-python。

关联硬约束：
  A7   Decision = (Operation, Target)：两阶段——stage1 选 operation，
       DOM 类再由 stage2 选 target（Operation 决定 Target question 集合）
  A10  schema 管结构、Validator 管语义：产出必须经
       decision_validator.validate()（D8 三级一致性）自检，不通过即拒绝
  D9   双置信度：operation_confidence（stage1）+ target_confidence（stage2）
  D13  control（SCROLL_* / WAIT）无 target，choice 派生自 controls[op]["id"]
  sentinel：target = None，choice = operation
  B2.1 每步两次模型调用（stage1 + stage2）与 2× model_calls 预算对齐

prompts/next_action.txt、prompts/target.txt 为问题模板（<<token>> 占位）。

来源说明：questions.py / model.py 原文不在 LA、DE 任何机器（基座 Step 1 未 fork），
prompts 按已冻结文档契约新写；model.py:choose() 原签名在 Step 7 对接时适配。
本模块对外：choose(page: dict) -> decision dict（specs/decision.schema.json v2 字段）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from decision_validator import SENTINELS, _build_targets_controls, validate

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "decider-2b"
MAX_CONTEXT = 4000

SYSTEM_NEXT = "你是浏览器操作决策器。只输出一行 JSON，不要任何解释。"
SYSTEM_TARGET = "你是操作目标选择器。只输出一行 JSON，不要任何解释。"

OP_GLOSS = {
    "CLICK": "点击元素",
    "TYPE_TEXT": "向输入框填写文本",
    "SELECT": "选择下拉选项",
    "WAIT": "等待页面稳定",
    "DONE": "任务已完成，正常结束",
    "BLOCKED": "无法继续，异常结束",
}


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class DeciderError(Exception):
    """模型输出 / HTTP 通道问题。"""


class DecisionInvalid(DeciderError):
    """D8 三级一致性自检失败（A10：语义校验归 Validator）。"""

    def __init__(self, result):
        super().__init__(f"decision invalid: {result.code}: {result.reason}")
        self.result = result


# ---------------------------------------------------------------------------
# 模板与解析
# ---------------------------------------------------------------------------

def load_template(prompts_dir: Path, name: str) -> str:
    path = Path(prompts_dir) / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise DeciderError(f"prompt template missing: {path}") from e


def render(template: str, values: dict) -> str:
    out = template
    for key, val in values.items():
        out = out.replace(f"<<{key}>>", str(val))
    if "<<" in out:
        head = out[out.index("<<"):][:60]
        raise DeciderError(f"unresolved placeholder in prompt: {head!r}")
    return out


def _extract_json(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1:] if nl != -1 else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise DeciderError(f"no JSON object in model output: {text[:120]!r}")
    try:
        obj = json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise DeciderError(f"bad JSON from model: {e}") from e
    if not isinstance(obj, dict):
        raise DeciderError("model JSON is not an object")
    return obj


def _confidence(obj: dict, key: str) -> float:
    if key not in obj:
        raise DeciderError(f"model output missing {key}")
    try:
        val = float(obj[key])
    except (TypeError, ValueError) as e:
        raise DeciderError(f"{key} is not a number: {obj[key]!r}") from e
    if not (0.0 <= val <= 1.0):
        raise DeciderError(f"{key} out of range [0,1]: {val}")
    return val


def _context(page: dict) -> str:
    text = page.get("text") or ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) > MAX_CONTEXT:
        text = text[:MAX_CONTEXT] + "…（已截断）"
    return f"url: {page.get('url', '')}\ntitle: {page.get('title', '')}\ntext:\n{text}"


def _gloss(op: str) -> str:
    if op in OP_GLOSS:
        return OP_GLOSS[op]
    if op.startswith("SCROLL"):
        return "滚动页面"
    return "control 操作"


def _stage1_candidates(targets: dict, controls: dict) -> str:
    lines = [f"  {op} — {_gloss(op)}（DOM 操作，选定后追问 target）"
             for op in sorted(targets)]
    lines += [f"  {op} — {_gloss(op)}（control，无 target）"
              for op in sorted(controls)]
    lines += [f"  {op} — {_gloss(op)}（sentinel，无 target）"
              for op in sorted(SENTINELS)]
    return "\n".join(lines)


def _stage2_candidates(candidates: dict) -> str:
    lines = []
    for tid in sorted(candidates):
        a = candidates[tid]
        lines.append(
            f"  target={tid}  choice={a.get('id')}  "
            f"role={a.get('role', '')}  label={a.get('label', '')}"
        )
    return "\n".join(lines)


def _sum_usage(usages: list) -> Optional[dict]:
    if not usages:
        return None
    common = set(usages[0])
    for u in usages[1:]:
        common &= set(u)
    numeric = {k for k in common
               if all(isinstance(u[k], (int, float)) and not isinstance(u[k], bool)
                      for u in usages)}
    if not numeric:
        return None
    return {k: sum(u[k] for u in usages) for k in sorted(numeric)}


# ---------------------------------------------------------------------------
# Decider2B
# ---------------------------------------------------------------------------

class Decider2B:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        timeout: float = 60.0,
        temperature: float = 0.0,
        prompts_dir: Optional[Path] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("DECIDER_BASE_URL") or DEFAULT_BASE_URL
        self.model = model or os.environ.get("DECIDER_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.temperature = temperature
        self.prompts_dir = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
        self.api_key = api_key if api_key is not None else os.environ.get("DECIDER_API_KEY")

    # --- HTTP 出口（唯一网络边界） ---

    def _payload(self, system: str, user: str) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }

    def infer(self, system: str, user: str) -> tuple[str, dict]:
        """POST {base_url}/chat/completions → (content, meta)。"""
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(self._payload(system, user)).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DeciderError(f"infer HTTP {e.code} from {url}") from e
        except urllib.error.URLError as e:
            raise DeciderError(f"infer unreachable {url}: {e.reason}") from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise DeciderError(f"infer response body is not JSON: {e}") from e
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise DeciderError("infer response missing choices[0].message.content") from e
        if not isinstance(content, str):
            raise DeciderError("infer content is not a string")
        meta: dict = {"model": str(body.get("model") or self.model),
                      "latency_ms": latency_ms}
        if isinstance(body.get("usage"), dict):
            meta["usage"] = body["usage"]
        return content, meta

    # --- 两阶段决策 ---

    def choose(self, page: dict) -> dict:
        if not isinstance(page, dict):
            raise TypeError("page must be a dict")
        targets, controls = _build_targets_controls(page.get("actions", []))
        ctx = _context(page)

        latency = 0.0
        usages: list = []
        model_name = self.model

        # stage1：选 operation（A7）
        user1 = render(load_template(self.prompts_dir, "next_action.txt"), {
            "context": ctx,
            "candidates": _stage1_candidates(targets, controls),
        })
        content1, meta1 = self.infer(SYSTEM_NEXT, user1)
        latency += float(meta1.get("latency_ms") or 0)
        model_name = meta1.get("model") or model_name
        if isinstance(meta1.get("usage"), dict):
            usages.append(meta1["usage"])
        out1 = _extract_json(content1)
        operation = out1.get("operation")
        if not isinstance(operation, str) or not operation:
            raise DeciderError(f"model operation missing/invalid: {operation!r}")
        oc = _confidence(out1, "operation_confidence")

        target: Optional[str] = None
        tc: Optional[float] = None

        if operation in targets:
            # stage2：该 operation 的 target question 集合（A7）
            user2 = render(load_template(self.prompts_dir, "target.txt"), {
                "operation": operation,
                "context": ctx,
                "candidates": _stage2_candidates(targets[operation]),
            })
            content2, meta2 = self.infer(SYSTEM_TARGET, user2)
            latency += float(meta2.get("latency_ms") or 0)
            model_name = meta2.get("model") or model_name
            if isinstance(meta2.get("usage"), dict):
                usages.append(meta2["usage"])
            out2 = _extract_json(content2)
            target = out2.get("target")
            if not isinstance(target, str) or not target:
                raise DeciderError(f"model target missing/invalid: {target!r}")
            choice = out2.get("choice")
            if not isinstance(choice, str) or not choice:
                raise DeciderError(f"model choice missing/invalid: {choice!r}")
            tc = _confidence(out2, "target_confidence")
        elif operation in controls:
            # D13：control 的 choice 派生自 controls[op]["id"]
            choice = controls[operation]["id"]
        elif operation in SENTINELS:
            choice = operation
        else:
            # 未知 operation 交由 Validator 报 unknown_operation（A10）
            choice = operation

        decision = {
            "operation": operation,
            "target": target,
            "choice": choice,
            "operation_confidence": oc,
            "target_confidence": tc,
            "latency_ms": round(latency, 1),
            "model": model_name,
        }
        usage_sum = _sum_usage(usages)
        if usage_sum is not None:
            decision["usage"] = usage_sum

        result = validate(decision, page, targets=targets, controls=controls)
        if not result.valid:
            raise DecisionInvalid(result)
        return decision


# ---------------------------------------------------------------------------
# 默认客户端与入口
# ---------------------------------------------------------------------------

_default: Optional[Decider2B] = None


def default_client() -> Decider2B:
    global _default
    if _default is None:
        _default = Decider2B()
    return _default


def choose(page: dict) -> dict:
    """model.py:choose() 的替换入口（Step 7 接线）。"""
    return default_client().choose(page)


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

    def check_raises(name, fn, exc, attr=None, want=None):
        global passed, total
        total += 1
        try:
            fn()
        except exc as e:
            if attr is None or getattr(e, attr, None) == want:
                passed += 1
            else:
                print(f"FAIL: {name} (attr {attr}={getattr(e, attr, None)!r}, want {want!r})")
        except Exception as e:
            print(f"FAIL: {name} (raised {type(e).__name__}: {e})")
        else:
            print(f"FAIL: {name} (no raise)")

    class Fake:
        def __init__(self, replies):
            self.replies = list(replies)
            self.calls = []

        def infer(self, system, user):
            self.calls.append((system, user))
            return self.replies.pop(0), {
                "model": "fake-2b", "latency_ms": 1.5,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    def make(replies):
        d = Decider2B(base_url="http://backend/v1", model="cfg-model")
        fake = Fake(replies)
        d.infer = fake.infer
        return d, fake

    page = {
        "url": "https://example.com", "title": "Example", "w": 1120, "h": 780,
        "text": "search page", "scroll": {"y": 0, "height": 2000},
        "actions": [
            {"id": "e1", "kind": "fill", "node": 12, "role": "textbox",
             "label": "Search", "value": ""},
            {"id": "e2", "kind": "click", "node": 12, "role": "textbox",
             "label": "Open Search", "value": ""},
            {"id": "e3", "kind": "click", "node": 42, "role": "button",
             "label": "Search", "value": ""},
            {"id": "scroll_down", "kind": "scroll", "label": "Scroll down",
             "delta": 560},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
        "marker": [], "page_key": [], "guards": {}, "omitted_actions": 0,
    }

    # --- 配置与请求体 ---
    d0 = Decider2B(base_url="http://backend/v1/", model="m2")
    check("base_url kept", d0.base_url == "http://backend/v1/")
    check("model kept", d0.model == "m2")
    p = d0._payload("sys", "usr")
    check("payload model", p["model"] == "m2")
    check("payload temperature", p["temperature"] == 0.0)
    check("payload messages", [m["role"] for m in p["messages"]] == ["system", "user"])
    check("url joins /chat/completions",
          (d0.base_url.rstrip("/") + "/chat/completions").endswith("/v1/chat/completions"))

    # --- control 路径（stage1 即终局，choice 派生 D13） ---
    d, fake = make(['{"operation": "SCROLL_DOWN", "operation_confidence": 0.7}'])
    r = d.choose(page)
    check("control operation", r["operation"] == "SCROLL_DOWN")
    check("control target None", r["target"] is None)
    check("control choice derived", r["choice"] == "scroll_down")
    check("control tc None", r["target_confidence"] is None)
    check("control oc", r["operation_confidence"] == 0.7)
    check("single call", len(fake.calls) == 1)
    check("render has url", "https://example.com" in fake.calls[0][1])
    check("render has no token", "<<" not in fake.calls[0][1])
    check("latency from meta", r["latency_ms"] == 1.5)
    check("model from response", r["model"] == "fake-2b")
    check("usage present", r["usage"]["prompt_tokens"] == 10)

    # --- sentinel 路径 ---
    d, fake = make(['{"operation": "DONE", "operation_confidence": 0.99}'])
    r = d.choose(page)
    check("sentinel choice", r["choice"] == "DONE" and r["target"] is None)
    check("sentinel valid (no raise)", True)

    # --- DOM 两阶段路径（A7 + D8 自检） ---
    d, fake = make([
        '{"operation": "CLICK", "operation_confidence": 0.9}',
        '{"target": "2", "choice": "e3", "target_confidence": 0.8}',
    ])
    r = d.choose(page)
    check("dom target", r["target"] == "2")
    check("dom choice", r["choice"] == "e3")
    check("dom tc", r["target_confidence"] == 0.8)
    check("two calls", len(fake.calls) == 2)
    check("stage2 names operation", "CLICK" in fake.calls[1][1])
    check("stage2 lists candidates", "target=2" in fake.calls[1][1]
          and "choice=e3" in fake.calls[1][1])
    check("latency summed", r["latency_ms"] == 3.0)
    check("usage summed", r["usage"]["prompt_tokens"] == 20)

    # --- TYPE_TEXT 路径 ---
    d, fake = make([
        '{"operation": "TYPE_TEXT", "operation_confidence": 0.85}',
        '{"target": "1", "choice": "e1", "target_confidence": 0.75}',
    ])
    r = d.choose(page)
    check("type_text ok", r["operation"] == "TYPE_TEXT" and r["choice"] == "e1")

    # --- D8 拒绝：target/choice 不一致 ---
    d, fake = make([
        '{"operation": "CLICK", "operation_confidence": 0.9}',
        '{"target": "2", "choice": "e1", "target_confidence": 0.8}',
    ])
    check_raises("D8 choice_mismatch rejected", lambda: d.choose(page), DecisionInvalid)
    d, fake = make([
        '{"operation": "CLICK", "operation_confidence": 0.9}',
        '{"target": "2", "choice": "e1", "target_confidence": 0.8}',
    ])
    try:
        d.choose(page)
        check("D8 code choice_mismatch", False)
    except DecisionInvalid as e:
        check("D8 code choice_mismatch", e.result.code == "choice_mismatch")

    # --- 未知 operation 交 Validator ---
    d, fake = make(['{"operation": "HOVER", "operation_confidence": 0.5}'])
    try:
        d.choose(page)
        check("unknown op rejected", False)
    except DecisionInvalid as e:
        check("unknown op rejected", e.result.code == "unknown_operation")

    # --- 模型输出契约 ---
    d, fake = make(['{"operation": "WAIT"}'])
    check_raises("missing operation_confidence", lambda: d.choose(page), DeciderError)
    d, fake = make(['{"operation": "WAIT", "operation_confidence": 1.7}'])
    check_raises("confidence out of range", lambda: d.choose(page), DeciderError)
    d, fake = make(["I will click the button now."])
    check_raises("non-JSON output", lambda: d.choose(page), DeciderError)
    d, fake = make([
        '{"operation": "CLICK", "operation_confidence": 0.9}',
        '{"choice": "e3", "target_confidence": 0.8}',
    ])
    check_raises("stage2 missing target", lambda: d.choose(page), DeciderError)

    # --- _extract_json ---
    check("extract fenced json",
          _extract_json('```json\n{"a": 1}\n```') == {"a": 1})
    check_raises("extract garbage", lambda: _extract_json("no json here"),
                 DeciderError)

    # --- 模板缺失 ---
    d = Decider2B(base_url="http://backend/v1", prompts_dir="/nonexistent")
    check_raises("missing template", lambda: d.choose(page), DeciderError)

    # --- 真实 HTTP 通道：connection refused → DeciderError ---
    d = Decider2B(base_url="http://127.0.0.1:9/v1", timeout=2.0)
    check_raises("connection refused wrapped", lambda: d.infer("s", "u"), DeciderError)

    print(f"SMOKE OK: {passed}/{total}")
