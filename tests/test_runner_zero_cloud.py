"""入口脚本的 Text Helper 必须指向本地，默认不许是云端。
（Fix N 接的三个入口 + 10-08 之后补上的第四个 `m1/run_suite.ps1`——它那份一直写死 groq。）

发现的形状（2026-09/10-08，r119）：`scripts/run_one.ps1` 从不设 TEXT_HELPER_*，
模型提出的 TYPE_TEXT 无值可取 → `agent.py` 连抛 3 次 `helper_fail_run>=3` →
`blocked`、`steps=0`，被记成 agent 决策失败。同时 `run_baseline_19.ps1` /
`run_demo.ps1` 的默认助手是 `.env` 里的云端 Groq，19 题基线累计 **56 次**
step 级云端调用（n004/x002/s002/l002），而报告的 `api_calls` 只数 teacher 路径，
所以 `api_calls=0` **不等于**"零云端"。硬线是"云端调用恒为 0"，这条要能被测试钉住。

接线形状（2026-10-08 收口之后）：端点不再由各入口自己写出来，全部由
`scripts/text_helper.ps1::Resolve-TextHelper` 按**点名的 choice** 解析，健康门在
`Assert-TextHelper` 里。于是"入口指向本地"这条断言拆成三段，都能静态检查：
① 入口点名的 choice 是本地的（默认值或 `-Choice "startlux"` 字面量）；
② resolver 把那个 choice 映射成回环地址；
③ 入口确实调了 `Assert-TextHelper`（不调就等于没有健康门）。
choice 的云端分支被拒绝、健康不可达会 throw —— 这两条的**实跑**证明在
`tests/test_runner_safety.py` 的最后一条里（本地 PowerShell，只读）。

不连浏览器、不调模型。负例 = `git show <REF>:<path>` 里那份**改前**内容。

运行：python tests/test_runner_zero_cloud.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = []

#: 四个会把决策送进模型的入口。run_one 是单任务/批次入口，另外三个是全量/演示入口。
ENTRY_RUNNERS = ("scripts/run_one.ps1", "run_baseline_19.ps1",
                 "run_demo.ps1", "m1/run_suite.ps1")
#: 本地 choice：startlux = llama-server :8081（和 wire 同一个常驻模型），
#: local = ollama，none = 干脆不配助手（TYPE_TEXT 会显式失败，不会偷跑云端）。
LOCAL_CHOICES = {"startlux", "local", "none"}


class Skip(Exception):
    """无从对照（例如历史被改写）——跳过，不算失败。"""


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def head_text(rel: str, ref: str = "HEAD") -> str:
    """某次提交里的脚本内容（负例用）。"""
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(REPO),
                         capture_output=True)
    if out.returncode != 0:
        raise AssertionError(f"git show {ref}:{rel} failed: "
                             f"{out.stderr.decode('utf-8', 'replace').strip()[:120]}")
    # text=True would decode with the ANSI codepage (GBK here) and die on the
    # UTF-8 Chinese comments the scripts carry.
    return out.stdout.decode("utf-8", "replace")


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def is_loopback(u: str) -> bool:
    return u.startswith("http://127.0.0.1") or u.startswith("http://localhost")


def resolver_map() -> dict[str, str]:
    """scripts/text_helper.ps1 里 choice -> Url 的映射（'none' 分支不赋 Url）。"""
    text = read("scripts/text_helper.ps1")
    return dict(re.findall(r'"([a-z]+)"\s*\{\s*\$out\.Url\s*=\s*"([^"]+)"', text))


def cloud_urls(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines()
            if re.search(r"https://(api\.groq\.com|api\.deepseek\.com|buddy\.chips\.us\.ci)", l)
            and "Invoke-WebRequest" not in l and "proxy" not in l.lower()
            and not l.strip().startswith("#")]


def named_choices(text: str) -> list[str]:
    """这个入口点名的 choice 字面量（-Choice "startlux"）和 param 默认值。"""
    out = re.findall(r'-Choice\s+"([a-z]+)"', text)
    m = re.search(r'\[string\]\$TextHelper\s*=\s*"([^"]*)"', text)
    if m:
        out.append(m.group(1))
    return out


@case("resolver 把每个本地 choice 映射到回环地址，云端 choice 独立存在")
def _resolver_maps_local_to_loopback():
    m = resolver_map()
    assert {"startlux", "local", "groq", "deepseek"} <= set(m), f"resolver lost branches: {sorted(m)}"
    for c in ("startlux", "local"):
        assert is_loopback(m[c]), f"{c} -> {m[c]} is not loopback"
    for c in ("groq", "deepseek"):
        assert not is_loopback(m[c]), f"{c} must stay an explicit cloud branch"


@case("四个入口都经 resolver 取助手，并调用健康门 Assert-TextHelper")
def _entries_use_the_resolver_and_the_gate():
    bad = []
    for rel in ENTRY_RUNNERS:
        text = read(rel)
        if "Resolve-TextHelper" not in text:
            bad.append(f"{rel}: no Resolve-TextHelper")
        if "Assert-TextHelper" not in text:
            bad.append(f"{rel}: no Assert-TextHelper (health gate lost)")
        if not re.search(r'\. "\$(?:Repo|root)\\scripts\\text_helper\.ps1"', text):
            bad.append(f"{rel}: does not dot-source the resolver")
    assert not bad, "; ".join(bad)


@case("入口点名的助手全是本地（改前默认 groq / 根本不配）")
def _entries_name_a_local_choice():
    m = resolver_map()
    bad = []
    for rel in ENTRY_RUNNERS:
        text = read(rel)
        choices = named_choices(text)
        assert choices, f"{rel}: no named -TextHelper default and no -Choice literal"
        for c in choices:
            if c not in LOCAL_CHOICES:
                bad.append(f"{rel} names {c!r}")
            elif c in m and not is_loopback(m[c]):
                bad.append(f"{rel}: {c} resolves to {m[c]}")
    assert not bad, "non-local helper named by an entry: " + "; ".join(bad)


@case("入口文件里不再自己写出云端 URL（只剩代理探针）")
def _entries_spell_no_cloud_url():
    bad = []
    for rel in ENTRY_RUNNERS + ("run_agentjev_19.ps1", "run_adapter_m4b.ps1",
                                "run_m1.ps1", "run_m4b_collect.ps1"):
        for line in cloud_urls(read(rel)):
            bad.append(f"{rel}: {line[:80]}")
    assert not bad, "cloud URL literal outside the resolver: " + "; ".join(bad)


@case("run_one.ps1 仍把助手三件套写进环境（改前一条都没设 → r119 的 steps=0）")
def _run_one_still_sets_the_triple():
    text = read("scripts/run_one.ps1")
    for k in ("TEXT_HELPER_BASE_URL", "TEXT_HELPER_MODEL", "TEXT_HELPER_API_KEY"):
        assert re.search(rf'\$env:{k}\s*=', text), f"run_one.ps1 no longer sets {k}"


@case("健康门本体在 Assert-TextHelper 里：不可达就 throw，不是继续跑")
def _gate_throws_by_construction():
    text = read("scripts/text_helper.ps1")
    fn = text.split("function Assert-TextHelper", 1)
    assert len(fn) == 2, "Assert-TextHelper gone from the resolver"
    assert "Invoke-RestMethod" in fn[1] and "throw" in fn[1], \
        "Assert-TextHelper lost its probe or its throw"


@case("负例：改前（HEAD）的 m1/run_suite.ps1 会被这套断言抓住")
def _run_suite_pre_fix_fails():
    """提交之后 HEAD 就带上修复了，那时无从对照 → Skip。"""
    try:
        old = head_text("m1/run_suite.ps1")
    except AssertionError as e:
        raise Skip(str(e))
    caught = []
    m = re.search(r'\[string\]\$TextHelper\s*=\s*"([^"]*)"', old)
    if not m or m.group(1) not in LOCAL_CHOICES:
        caught.append("default not local")
    if cloud_urls(old):
        caught.append("cloud URL written by the runner itself")
    if "Resolve-TextHelper" not in old:
        caught.append("no resolver")
    if len(caught) < 2:
        raise Skip("HEAD already carries the fix (commit landed) -- nothing to compare")
    assert len(caught) >= 2, f"pre-fix code slipped through: {caught}"


#: Fix N 之前最后一次提交（三个入口还没接助手）。负例必须对着**它**跑：
#: HEAD 现在已经带着修复，用 HEAD 当"改前"会在修复落地的那天自己骗自己。
PRE_FIX_REF = "1e7eb6e"


@case(f"负例：改前（{PRE_FIX_REF}）的 run_one.ps1 / run_baseline_19.ps1 会被这套断言抓住")
def _pre_fix_code_fails():
    try:
        old = head_text("scripts/run_one.ps1", PRE_FIX_REF)
        old_base = head_text("run_baseline_19.ps1", PRE_FIX_REF)
    except AssertionError as e:                      # 历史被改写 → 负例无从对照
        raise Skip(str(e))
    assert "$env:TEXT_HELPER_BASE_URL" not in old, "改前不该设 TEXT_HELPER_BASE_URL"
    assert "Resolve-TextHelper" not in old, "改前不该有 resolver 接线"
    caught = []
    if "$env:TEXT_HELPER_BASE_URL" not in old:
        caught.append("run_one sets nothing")
    m = re.search(r'\[string\]\$TextHelper\s*=\s*"([^"]*)"', old_base)
    if not m or m.group(1) not in LOCAL_CHOICES:
        caught.append("baseline default not local")
    assert len(caught) == 2, f"pre-fix code slipped through: {caught}"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except Skip as e:
            print(f"skip  {name}\n      {e}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
