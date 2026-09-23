"""Text Helper 2B：字段文本提取（替换 model.py:field_text()，H2）。

接口边界（B）：复用 Decider2B 的 OpenAI-compatible HTTP 通道
（POST {base_url}/chat/completions），不绑定具体后端。

关联硬约束：
  A8   Text Helper 独立于 Decision Model；模型输出必须结构化 {"text": ...}
  D17  找不到值必须返回 null，不得编造；坏输出走 ValueError——
       这是设计特性，不是 bug

prompts/text_value.txt 为问题模板（<<hint>> / <<context>> 占位）。

来源说明：questions.py / model.py 原文不在 LA、DE 任何机器（基座 Step 1 未 fork），
prompts 按已冻结文档契约新写；model.py:field_text() 原签名在 Step 7 对接时适配。
本模块对外：field_text(hint, page) -> str | None。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .choose_2b import (
    Decider2B,
    DeciderError,
    _context,
    _extract_json,
    default_client,
    load_template,
    render,
)

SYSTEM_TEXT = "你是字段文本提取器。只输出一行 JSON，不要任何解释。"


class FieldText2B:
    def __init__(
        self,
        client: Optional[Decider2B] = None,
        prompts_dir: Optional[Path] = None,
    ) -> None:
        if client is not None and prompts_dir is not None:
            raise ValueError("prompts_dir only applies when client is omitted")
        self._client = client or Decider2B(prompts_dir=prompts_dir)

    def field_text(self, hint: str, page: dict) -> Optional[str]:
        """返回页面中该字段的真实文本；找不到返回 None（D17，禁止编造）。"""
        if not isinstance(hint, str) or not hint.strip():
            raise ValueError("field_text: hint must be a non-empty str")
        if not isinstance(page, dict):
            raise TypeError("page must be a dict")

        template = load_template(self._client.prompts_dir, "text_value.txt")
        user = render(template, {"hint": hint, "context": _context(page)})
        content, _meta = self._client.infer(SYSTEM_TEXT, user)

        # D17：坏输出 → ValueError（设计特性）；HTTP 通道问题保持 DeciderError
        try:
            obj = _extract_json(content)
        except DeciderError as e:
            raise ValueError(f"field_text: unparseable model output: {e}") from e
        if not isinstance(obj, dict) or "text" not in obj:
            raise ValueError('field_text: model output must be {"text": ...}')
        text = obj["text"]
        if text is None:
            return None
        if not isinstance(text, str):
            raise ValueError(
                f"field_text: text must be str or null, got {type(text).__name__}"
            )
        if not text.strip():
            return None
        return text


_default: Optional[FieldText2B] = None


def field_text(hint: str, page: dict) -> Optional[str]:
    """model.py:field_text() 的替换入口（Step 7 接线）。"""
    global _default
    if _default is None:
        _default = FieldText2B(client=default_client())
    return _default.field_text(hint, page)


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

    def check_raises(name, fn, exc):
        global passed, total
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
        def __init__(self, content):
            self.content = content
            self.calls = []

        def infer(self, system, user):
            self.calls.append((system, user))
            return self.content, {"model": "fake-2b", "latency_ms": 1.0}

    def make(content):
        ft = FieldText2B(client=Decider2B(base_url="http://backend/v1", model="m"))
        fake = Fake(content)
        ft._client.infer = fake.infer
        return ft, fake

    page = {
        "url": "https://example.com", "title": "Example",
        "text": "Profile page with name field", "actions": [],
    }

    # --- 正常提取 ---
    ft, fake = make('{"text": "张三"}')
    check("text extracted", ft.field_text("用户名", page) == "张三")
    check("hint rendered", "用户名" in fake.calls[0][1])
    check("context rendered", "https://example.com" in fake.calls[0][1])
    check("no token left", "<<" not in fake.calls[0][1])

    # --- null → None（D17 核心） ---
    ft, _ = make('{"text": null}')
    check("null → None", ft.field_text("用户名", page) is None)

    # --- 空串视为未找到（防编造） ---
    ft, _ = make('{"text": "   "}')
    check("blank → None", ft.field_text("用户名", page) is None)

    # --- 围栏 JSON 容忍 ---
    ft, _ = make('```json\n{"text": "value"}\n```')
    check("fenced json ok", ft.field_text("字段", page) == "value")

    # --- D17 ValueError 路径 ---
    ft, _ = make("the value is 张三")
    check_raises("non-JSON → ValueError",
                 lambda: ft.field_text("用户名", page), ValueError)
    ft, _ = make('{"value": "张三"}')
    check_raises("missing text key → ValueError",
                 lambda: ft.field_text("用户名", page), ValueError)
    ft, _ = make('{"text": 123}')
    check_raises("non-str text → ValueError",
                 lambda: ft.field_text("用户名", page), ValueError)

    # --- hint 契约 ---
    ft, _ = make('{"text": null}')
    check_raises("empty hint → ValueError",
                 lambda: ft.field_text("  ", page), ValueError)

    print(f"SMOKE OK: {passed}/{total}")
