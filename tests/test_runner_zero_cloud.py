"""Fix N 回归：三个入口脚本的 Text Helper 必须指向本地，默认不许是云端。

发现的形状（2026-10-08，r119）：`scripts/run_one.ps1` 从不设 TEXT_HELPER_*，
模型提出的 TYPE_TEXT 无值可取 → `agent.py` 连抛 3 次 `helper_fail_run>=3` →
`blocked`、`steps=0`，被记成 agent 决策失败。同时 `run_baseline_19.ps1` /
`run_demo.ps1` 的默认助手是 `.env` 里的云端 Groq，19 题基线累计 **56 次**
step 级云端调用（n004/x002/s002/l002），而报告的 `api_calls` 只数 teacher 路径，
所以 `api_calls=0` **不等于**"零云端"。硬线是"云端调用恒为 0"，这条要能被测试钉住。

不连浏览器、不调模型：读脚本源码断言接线。负例 = `git show HEAD:<path>` 的改前内容。

运行：python tests/test_runner_zero_cloud.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def head_text(rel: str) -> str:
    """改前的脚本内容（负例用）。"""
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO),
                         capture_output=True)
    if out.returncode != 0:
        raise AssertionError(f"git show HEAD:{rel} failed: "
                             f"{out.stderr.decode('utf-8', 'replace').strip()[:120]}")
    # text=True would decode with the ANSI codepage (GBK here) and die on the
    # UTF-8 Chinese comments the scripts carry.
    return out.stdout.decode("utf-8", "replace")


def helper_urls(text: str) -> list[str]:
    """所有 TEXT_HELPER_BASE_URL / $helperUrl 的赋值右值，按出现顺序。"""
    vals = re.findall(r'\$helperUrl\s*=\s*"([^"]+)"', text)
    vals += re.findall(r'TEXT_HELPER_BASE_URL"?\s*=\s*"([^"]+)"', text)
    return vals


def is_loopback(u: str) -> bool:
    return u.startswith("http://127.0.0.1") or u.startswith("http://localhost")


@case("run_one.ps1 配置了本地 Text Helper（改前根本没配）")
def _run_one_has_local_helper():
    text = (REPO / "scripts" / "run_one.ps1").read_text(encoding="utf-8")
    urls = helper_urls(text)
    assert urls, "run_one.ps1 sets no TEXT_HELPER_BASE_URL at all"
    assert all(is_loopback(u) for u in urls), f"non-loopback helper url: {urls}"
    assert "TEXT_HELPER_API_KEY" in text and "TEXT_HELPER_MODEL" in text


@case("run_one.ps1 有助手健康门：:8081 不可达就停，不静默量残废 agent")
def _run_one_health_gate():
    text = (REPO / "scripts" / "run_one.ps1").read_text(encoding="utf-8")
    assert re.search(r'/health', text), "no health probe"
    m = re.search(r'catch\s*\{\s*Write-Host[^\n]*\n?\s*exit 1', text)
    assert m, "health probe does not stop the run"


@case("两个全量入口的默认助手是本地（改前默认 groq）")
def _runners_default_local():
    for rel in ("run_baseline_19.ps1", "run_demo.ps1"):
        text = (REPO / rel).read_text(encoding="utf-8")
        m = re.search(r'\[string\]\$TextHelper\s*=\s*"([^"]+)"', text)
        assert m, f"{rel}: no $TextHelper param"
        assert m.group(1) == "startlux", f"{rel} defaults to {m.group(1)}"
        first = helper_urls(text)[0]
        assert is_loopback(first), f"{rel} first helper assignment is {first}"


@case("云端 URL 只出现在显式 -TextHelper 分支里")
def _cloud_only_behind_explicit_flag():
    for rel in ("run_baseline_19.ps1", "run_demo.ps1"):
        text = (REPO / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if not re.search(r'https://(api\.groq\.com|api\.deepseek\.com)', line):
                continue
            if "Invoke-WebRequest" in line or "proxy" in line.lower():
                continue          # 代理连通性探针不是推理调用
            assert re.search(r'\$TextHelper\s+-eq\s+"(groq|deepseek)"', line), \
                f"{rel}: unconditional cloud assignment -> {line.strip()[:90]}"


@case("负例：改前的 run_one.ps1 / run_baseline_19.ps1 会被这套断言抓住")
def _pre_fix_code_fails():
    old = head_text("scripts/run_one.ps1")
    assert not helper_urls(old), "改前不该有 TEXT_HELPER_BASE_URL"
    caught = []
    try:
        assert helper_urls(old), "run_one.ps1 sets no TEXT_HELPER_BASE_URL at all"
    except AssertionError:
        caught.append("run_one")
    old_base = head_text("run_baseline_19.ps1")
    m = re.search(r'\[string\]\$TextHelper\s*=\s*"([^"]+)"', old_base)
    if not m or m.group(1) != "startlux":
        caught.append("baseline default")
    assert len(caught) == 2, f"pre-fix code slipped through: {caught}"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:                              # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
