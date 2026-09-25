"""Policy Guard.

只做 Safety 黑名单。M1 最小可运行版本。

关联硬约束：
  A2  Policy = permission
  A3  Policy 只保留三类内容（Safety / Validity / Hard constraints）
  A6  Runtime Guard 与 Validator 分层独立
  G1  不可逆操作默认拒绝
  G2  安全优先于任务成功
  G3  误杀率 ≤ 5%，漏杀率 = 0
  G4  LLM 永远无法突破 Policy

职责边界：
  - 只做 Safety。不做 Validity / Hard constraints（留待后续）
  - 不检查 operation / target 映射（那是 decision_validator 的活）
  - 不检查 freshness / occlusion / disabled（那是 runtime_guard / browser.py 的活）
  - 不做语义分析（M1 用关键词列表；不查 page.text 避免误杀）

输入：
  decision: dict  — {choice, operation, target, ...}
  page:     dict  — browser.observe() 输出

输出：
  PolicyResult(allow, code, reason, detail)

codes（互斥）：
  ok
  irreversible_blacklist  — 不可逆操作黑名单命中
  credential_blacklist    — 凭证 / 验证码类黑名单命中

匹配规则：
  - 大小写不敏感，substring 匹配
  - 只匹配 decision 涉及的 action 的 label
  - 命中即拒绝（allow=False）

M1 阶段观察目标：
  - 20 个任务跑完，误杀率 ≤ 5% 即通过
  - 若发现新黑名单词，追加进列表（但不扩逻辑）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


SENTINELS = frozenset({"DONE", "BLOCKED"})


# ---------------------------------------------------------------------------
# 黑名单（M1 第一版，谨慎精确）
# ---------------------------------------------------------------------------

IRREVERSIBLE_BLACKLIST = (
    # 支付
    "pay now", "confirm payment", "buy now", "checkout",
    "place order", "confirm order", "submit order", "purchase now",
    "确认付款", "立即支付", "立即购买", "提交订单", "确认订单", "立即下单",
    # 删除
    "delete account", "delete permanently", "remove account",
    "删除账户", "永久删除", "注销账户",
    # 发送
    "send message", "send email", "send now", "post comment",
    "发送消息", "发送邮件", "立即发送", "发布评论",
    # 授权
    "authorize", "grant access", "allow access",
    "授权", "授予访问",
    # 账号安全
    "change password", "reset password", "update password",
    "修改密码", "重置密码",
)

CREDENTIAL_BLACKLIST = (
    "verification code", "one-time code", "one time code",
    "otp code", "enter otp",
    "验证码", "短信验证码", "动态密码",
)


# ---------------------------------------------------------------------------
# 结果类型
# ---------------------------------------------------------------------------

@dataclass
class PolicyResult:
    allow: bool
    code: str
    reason: str
    detail: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("detail") is None:
            d.pop("detail", None)
        return d


def _ok() -> PolicyResult:
    return PolicyResult(True, "ok", "no policy violation")


def _deny(code: str, reason: str, **detail) -> PolicyResult:
    return PolicyResult(False, code, reason, detail or None)


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------

def _match(text: str, words: tuple[str, ...]) -> Optional[str]:
    """返回第一个命中的词。text 应该已 lower()。"""
    for w in words:
        if w in text:
            return w
    return None


def _find_action(page: dict, choice: str) -> Optional[dict]:
    for a in page.get("actions", []):
        if a.get("id") == choice:
            return a
    return None


# ---------------------------------------------------------------------------
# 主校验
# ---------------------------------------------------------------------------

def check(decision: dict, page: dict) -> PolicyResult:
    """检查决策是否允许执行。

    职责边界（A6）：
      - 不检查 target 是否存在 / 是否在 action space（validator 的活）
      - 不检查 freshness / disabled（runtime_guard / browser 的活）
      - 只做安全黑名单
    """
    choice = decision.get("choice")
    operation = decision.get("operation")

    # sentinel：不做安全判定，交给调用方
    if operation in SENTINELS:
        return _ok()

    # 找不到 action：不归 Policy 管，让 Validator 报错
    action = _find_action(page, choice) if isinstance(choice, str) else None
    if action is None:
        return _ok()

    label = action.get("label") or ""
    if not isinstance(label, str):
        return _ok()

    label_lower = label.lower()

    hit = _match(label_lower, IRREVERSIBLE_BLACKLIST)
    if hit:
        return _deny(
            "irreversible_blacklist",
            f"label matches irreversible blacklist word {hit!r}",
            choice=choice, label=label, matched=hit,
        )

    hit = _match(label_lower, CREDENTIAL_BLACKLIST)
    if hit:
        return _deny(
            "credential_blacklist",
            f"label matches credential blacklist word {hit!r}",
            choice=choice, label=label, matched=hit,
        )

    return _ok()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    passed = 0
    total = 0

    def check_eq(name, got, want):
        global passed, total
        total += 1
        if got == want:
            passed += 1
        else:
            print(f"FAIL: {name} (got {got!r}, want {want!r})")

    def check_true(name, cond):
        global passed, total
        total += 1
        if cond:
            passed += 1
        else:
            print(f"FAIL: {name}")

    def page_with(*actions):
        return {"url": "https://example.com", "title": "t", "text": "",
                "actions": list(actions)}

    def act(id_, label):
        return {"id": id_, "kind": "click", "node": 1, "role": "button",
                "label": label}

    # --- 基本：无命中 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Search")))
    check_eq("clean allow", r.allow, True)
    check_eq("clean code ok", r.code, "ok")

    # --- 不可逆：pay now ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Pay now")))
    check_eq("pay now deny", r.allow, False)
    check_eq("pay now code", r.code, "irreversible_blacklist")

    # --- 不可逆：大小写 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "PAY NOW")))
    check_eq("PAY NOW deny (case-insensitive)", r.allow, False)

    # --- 不可逆：中文 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "确认付款")))
    check_eq("确认付款 deny", r.allow, False)
    check_eq("确认付款 code", r.code, "irreversible_blacklist")

    # --- 不可逆：substring（前缀） ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Please confirm order now")))
    check_true("substring match", not r.allow)

    # --- 凭证：验证码 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Enter verification code")))
    check_true("verification code deny", not r.allow)
    check_eq("verification code code", r.code, "credential_blacklist")

    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "输入验证码")))
    check_true("输入验证码 deny", not r.allow)

    # --- 中等风险：应 allow（避免误杀） ---
    for safe_label in ("Add to cart", "加入购物车", "Delete", "Submit", "Search",
                       "Next", "Cancel", "Log in", "Sign in"):
        r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
                  page_with(act("e1", safe_label)))
        check_true(f"safe: {safe_label!r} allow", r.allow)

    # --- sentinel：allow（不做安全判定） ---
    r = check({"choice": "DONE", "operation": "DONE", "target": None},
              page_with(act("e1", "Pay now")))
    check_true("DONE allow (no label check)", r.allow)

    r = check({"choice": "BLOCKED", "operation": "BLOCKED", "target": None},
              page_with(act("e1", "确认付款")))
    check_true("BLOCKED allow", r.allow)

    # --- 找不到 action：allow（让 validator 报） ---
    r = check({"choice": "e99", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Pay now")))
    check_true("missing action allow", r.allow)
    check_eq("missing action code ok", r.code, "ok")

    # --- 无 label / 空 label ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with({"id": "e1", "kind": "click", "node": 1, "role": "button"}))
    check_true("no label allow", r.allow)

    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "")))
    check_true("empty label allow", r.allow)

    # --- scroll / wait（无 node，但 label 可能是 "Scroll down"） ---
    r = check({"choice": "scroll_down", "operation": "SCROLL_DOWN", "target": None},
              page_with({"id": "scroll_down", "kind": "scroll",
                         "label": "Scroll down", "delta": 560}))
    check_true("scroll allow", r.allow)

    # --- 中文删除 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "永久删除")))
    check_true("永久删除 deny", not r.allow)

    # --- 账号安全 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Reset password")))
    check_true("Reset password deny", not r.allow)

    # --- detail 携带 ---
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"},
              page_with(act("e1", "Pay now")))
    check_true("detail has matched", "matched" in (r.detail or {}))
    check_true("detail has label", "label" in (r.detail or {}))

    # --- to_dict ---
    d = _ok().to_dict()
    check_true("to_dict ok no detail", "detail" not in d)
    d = _deny("x", "y").to_dict()
    check_true("to_dict deny has code", d["code"] == "x")

    # --- 无关页面 text 不应触发 ---
    page = page_with(act("e1", "Search"))
    page["text"] = "This page contains the phrase pay now in the intro."
    r = check({"choice": "e1", "operation": "CLICK", "target": "1"}, page)
    check_true("page.text not scanned", r.allow)

    print(f"SMOKE OK: {passed}/{total}")
