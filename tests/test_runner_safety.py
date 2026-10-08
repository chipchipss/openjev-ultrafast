"""Fix P 回归： tracked 脚本里不许有明文凭据、云端默认值、或裸杀浏览器。

发现的形状（2026-10-08，P0 事故之后的清扫）：
  1. `run_m4b_collect.ps1` / `m4a/run_flights_ours.ps1` / `m4a/run_m1_skills.ps1`
     把 API key 写成字面量存在 git 里（其中一个已随 `bb9c048` 推到 origin/main）。
  2. 11 个 runner 的 Text Helper **默认**是 Groq：直接调用就把页面内容送到云端，
     而报告的 `api_calls` 只数 teacher 路径，所以 `api_calls=0` 看不出泄漏。
  3. 7 个 runner 用 `Get-Process chrome | Stop-Process -Force` 清场 —— 这一刀会把
     用户自己的浏览器一起杀掉。连接侧（browser.py）已经钉死归属，杀伤侧不能留洞。

不连浏览器、不发消息：静态断言 + 本地 PowerShell 只读执行守卫函数。
负例 = `git show <PRE_FIX_REF>:<path>` 里改前那份。

运行：python tests/test_runner_safety.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = []
PS = "powershell"


class Skip(Exception):
    """无从对照（历史被改写 / 本机没有 powershell）。"""


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def tracked(suffixes=(".ps1", ".py")) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=str(REPO), capture_output=True)
    files = out.stdout.decode("utf-8", "replace").split()
    return [f for f in files if f.endswith(suffixes)]


def show(ref: str, rel: str) -> str:
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(REPO), capture_output=True)
    if out.returncode != 0:
        raise Skip(f"git show {ref}:{rel} failed")
    return out.stdout.decode("utf-8", "replace")


#: 凭据形状：够长、字符集像 key，且不是占位符 / 端点 / 模型名
SECRET = re.compile(
    r'(?i)(api_?key|_key|token|secret)\s*=\s*["\']'
    r'([A-Za-z0-9_\-]{20,})["\']')
PLACEHOLDER = re.compile(r"(?i)^(local|changeme|your[-_]?key|dummy|none|test)+$")

CLOUD = re.compile(r"https://(api\.groq\.com|api\.deepseek\.com|buddy\.chips\.us\.ci)")
BARE_KILL = re.compile(r"Get-Process[^|\n]*\bchrome\b[^|\n]*\|\s*Stop-Process")
#: 允许出现云端 URL 的文件：只有一个，就是 resolver 本身。
#: 入口脚本(run_demo / m1.run_suite / run_baseline_19 / scripts.run_one)现在一律
#: 经 Resolve-TextHelper 取值，文件里剩下的云端 URL 只有代理连通性探针（下面的
#: Invoke-WebRequest 白名单），不承载页面内容。
CLOUD_ALLOWED = {
    "scripts/text_helper.ps1",       # the only place a cloud URL may be spelled out
}


def helper_lines(text: str):
    """TEXT_HELPER_BASE_URL / TEACHER_BASE_URL 的赋值行。"""
    return [l for l in text.splitlines()
            if re.search(r'(TEXT_HELPER_BASE_URL|TEACHER_BASE_URL)\s*(=|\])', l)
            or re.search(r'\["TEXT_HELPER_BASE_URL"\]', l)]


@case("tracked 脚本里没有明文凭据")
def _no_literal_secrets():
    bad = []
    for rel in tracked((".ps1", ".py", ".sh")):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for m in SECRET.finditer(text):
            val = m.group(2)
            if PLACEHOLDER.match(val) or val.startswith(("http", "sk-please")):
                continue
            bad.append(f"{rel}: {m.group(1)}=...{val[-4:]}")
    assert not bad, "literal credentials still tracked: " + "; ".join(bad)


@case("没有 runner 把云端端点当默认值")
def _no_cloud_default():
    bad = []
    for rel in tracked((".ps1",)):
        if rel in CLOUD_ALLOWED:
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if not CLOUD.search(line):
                continue
            s = line.strip()
            if "Invoke-WebRequest" in s or "httpx" in s or "proxy" in s.lower():
                continue                       # 连通性探针不是推理调用
            if "注释" in s or s.startswith("#"):
                continue
            bad.append(f"{rel}: {s[:90]}")
    assert not bad, "unconditional cloud assignment: " + "; ".join(bad)


@case("Text Helper 一律经 Resolve-TextHelper 解析（显式点名才走）")
def _helpers_use_the_resolver():
    users = []
    for rel in tracked((".ps1",)):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if "Resolve-TextHelper" not in text:
            continue
        assert "Assert-TextHelper" in text, f"{rel} resolves a helper but never asserts it"
        assert ". \"$Repo\\scripts\\text_helper.ps1\"" in text or \
               '. "$root\\scripts\\text_helper.ps1"' in text or \
               '. "$Repo\\scripts\\text_helper.ps1"' in text, f"{rel} does not dot-source the resolver"
        users.append(rel)
    assert len(users) >= 11, f"only {len(users)} runners use the resolver"
    # 每个写 TEXT_HELPER_BASE_URL 的 runner 要么用 resolver，要么是 Fix N 已钉死的入口
    for rel in tracked((".ps1",)):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if not any("TEXT_HELPER_BASE_URL" in l and "=" in l for l in text.splitlines()):
            continue
        assert ("Resolve-TextHelper" in text or rel in CLOUD_ALLOWED
                or rel == "scripts/startlux_serve.ps1"), f"{rel} sets the helper outside the resolver"


@case("杀浏览器只经归属守卫，不再裸杀 chrome 进程")
def _kills_are_owned_only():
    bad = []
    for rel in tracked((".ps1",)):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue             # the guard's own docstring quotes the old form
            if BARE_KILL.search(line):
                bad.append(f"{rel}: {line.strip()[:90]}")
    assert not bad, "bare browser kill survives: " + "; ".join(bad)


@case("凡是要杀浏览器的脚本都必须挂着归属守卫")
def _killers_dot_source_the_guard():
    KILL = re.compile(r"Stop-Process[^|\n]*\b(chrome|msedge|chromium)\b", re.I)
    bad = []
    for rel in tracked((".ps1",)):
        if rel == "scripts/chrome_guard.ps1":
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        kills = [l for l in text.splitlines()
                 if not l.strip().startswith("#") and (BARE_KILL.search(l) or KILL.search(l))]
        if not kills:
            continue
        if "chrome_guard.ps1" not in text and "Get-OwnedChrome" not in text \
                and "Get-CdpChrome" not in text:
            bad.append(f"{rel}: {len(kills)} browser Stop-Process without the guard")
    assert not bad, "unguarded browser killer: " + "; ".join(bad)


@case("守卫画像标记与 browser.py 的 OWNED_PROFILE_MARKERS 一致")
def _markers_stay_in_sync():
    guard = (REPO / "scripts" / "chrome_guard.ps1").read_text(encoding="utf-8")
    py = (REPO / "jev_ultrafast" / "browser.py").read_text(encoding="utf-8")
    g = set(re.findall(r'"(chrome-[a-z\-]+)"', guard))
    p = set(re.findall(r'"(chrome-[a-z\-]+)"', py))
    assert g, "chrome_guard.ps1 lost its markers"
    assert g <= p or p <= g, f"markers drifted: guard={sorted(g)} browser.py={sorted(p)}"


#: 本轮修复之前的最后一次提交。负例必须对着**它**跑：HEAD 一旦带上修复，
#: 用 HEAD 当"改前"就会在落地那天自己骗自己。
PRE_FIX_REF = "9c9c857"


@case(f"负例：改前的 m4a/run_flights_ours.ps1（{PRE_FIX_REF}）有字面 key 且默认云端，会被抓住")
def _pre_fix_fails_the_assertions():
    ref = PRE_FIX_REF
    try:
        old = show(ref, "m4a/run_flights_ours.ps1")
    except Skip:
        raise
    caught = []
    if SECRET.search(old):
        caught.append("literal key")
    for line in old.splitlines():
        if CLOUD.search(line) and not line.strip().startswith("#"):
            caught.append("cloud default")
            break
    assert len(caught) >= 2, f"pre-fix file slipped through: {caught}"


@case(f"负例：改前的 run_agentjev_19.ps1（{PRE_FIX_REF}）裸杀 chrome，会被杀侧断言抓住")
def _pre_fix_kill_fails():
    old = show(PRE_FIX_REF, "run_agentjev_19.ps1")
    assert BARE_KILL.search(old), "pre-fix file has no bare browser kill -- assertion lost its teeth"


@case("resolver 实跑：无名指 / 未知项 / 无 key 云端都拒绝，本地端点查健康")
def _resolver_refuses_by_live_execution():
    try:
        subprocess.run([PS, "-NoProfile", "-Command", "Get-Date"],
                       capture_output=True, timeout=20, check=True)
    except Exception as e:                              # noqa: BLE001
        raise Skip(f"no usable powershell: {e}")
    script = r"""
. "%s\scripts\text_helper.ps1"
$r = @()
try { $null = Resolve-TextHelper -Choice "" } catch { $r += "refuse-empty" }
try { $null = Resolve-TextHelper -Choice "bogus" } catch { $r += "refuse-unknown" }
$env:GROQ_API_KEY = ""
try { $null = Resolve-TextHelper -Choice "groq" } catch { $r += "refuse-cloud-without-key" }
$h = Resolve-TextHelper -Choice "startlux"
if ($h.Url -like "http://127.0.0.1*") { $r += "local-url" }
if (-not $h.Cloud) { $r += "not-cloud" }
try { Assert-TextHelper @{Url="x";Model="y";Key="z";Cloud=$true} } catch { $r += "BUG" }
$($r -join ",")
""" % str(REPO)
    p = subprocess.run([PS, "-NoProfile", "-Command", script],
                       capture_output=True, timeout=60)
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    line = out[-1] if out else ""
    assert p.returncode == 0, f"resolver script died: {p.stderr.decode('utf-8','replace')[:160]}"
    for want in ("refuse-empty", "refuse-unknown", "refuse-cloud-without-key",
                 "local-url", "not-cloud"):
        assert want in line, f"{want} missing from {line}"
    assert "BUG" not in line, "Assert-TextHelper threw on a cloud choice (it must only warn)"


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
