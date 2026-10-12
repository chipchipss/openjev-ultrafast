r"""#69 的安全那半：真正发出杀动作的那一层，必须先证明"这个进程是我们的"。

硬线写的是"绝不动不属于我们那两个画像的浏览器"，杀侧版本从 2026-10-07 起一路在补
（`scripts/chrome_guard.ps1` 的命令行过滤）。这一支查的是同一件事**剩下的形状**，逐条实测：

- **完全没有判据的按名杀**：`scripts/test_n001.ps1:12 / :35`
  `Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | ForEach { Stop-Process ... }`
  —— 这一刀把**本机每一个 Chrome** 带走，包括你自己的那个。
- **按进程名砍**：`run_demo.ps1` 的 `Get-Process llama-server | Stop-Process -Force`、
  `scripts/startlux_serve.ps1:23` 的 `Get-Process | Where ProcessName -in "llama-server"`。
  "这台机器上只有一个 llama-server 是我们起的"是运行时事实，不是代码里的约束。
- **按库名砍**：五个 runner 的收尾都用 `-match "...|browser_harness"` 挑 python。
  `browser_harness` 是**库名**——任何 import 过它的 python 都算（你自己的 daemon、
  mcp server、探针）。同一批词也出现在 Step 2 的"别的 decider 在跑吗"**探测**里，
  那条只是 Warn/跳过、不砍进程，所以本条只审**发杀那条语句附近**的过滤串：
  判据把检测也一起骂，下次就没人信这仪器了。

四条判据都是文本级的（离线闸门要能在任何机器上跑，不真起进程、不真杀进程）：

1. 按进程名直连砍（`Get-Process <名字> | Stop-Process`，中间没有 ForEach-Object 的过滤）
   一律红——这种写法的判据只可能写在**同一条管道**里，别处再近的 `CommandLine` 都是别的语句的；
2. 其余 `Stop-Process` 必须回看到归属判据：本行/同一 ForEach 里的 `CommandLine` 过滤、
   自有画像清单，或它杀的 `-Id $x` 是本脚本自己 `Start-Process` 起来的；
   窗口回看 12 行但**先剔掉打印行与注释行**——`Log "手工清理建议…"` 里那句带 `CommandLine`
   的字符串是打印给人看的，不是这条代码的过滤条件（第一版把它算进窗口，
   恰好漏掉了全场唯一真正没判据的那一刀，是负例见证抓出来的）；
3. 发杀语句附近的过滤串不许是光秃秃的库名，也不许是 `serve` / `uvicorn` 这种匹配一切 server 的裸词；
4. `.ps1` 要么纯 ASCII，要么带 BOM 的 UTF-8——"非 ASCII 且无 BOM"会被 PS 5.1 当 GBK 读。

负例见证（同一仪器跑 `git show HEAD:<文件>`，见 `m2/real-log.md`）：改前 22 处可报缺陷，改后 0。

已知这仍不是完整归属证明：daemon 是共享基础设施，按模块名杀仍可能碰到你自己起的那个。
完整解法是 runner 侧落 pidfile、只杀自己写下的 PID，记在 #69 的下半场。

运行：python tests/test_ps_kill_scope.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TARGETS = sorted(REPO.glob("*.ps1")) + sorted((REPO / "scripts").glob("*.ps1"))

# 归属判据：窗口里看见任意一条，就算"这刀砍得有依据"
OWNERSHIP_MARKS = (
    "CommandLine",              # 按命令行过滤（画像名 / 脚本名 / gguf_server / daemon 模块名）
    "Get-CdpChrome",            # 自有 Chrome 清单
    "Get-OwnedChrome",
    "Stop-OwnedChrome",
    "chrome-cdp-test",
    "chrome-jev-profile",
)

# 打印给用户看的建议、以及注释，都不算这条代码的过滤条件
PRINT_OR_COMMENT = re.compile(r"^\s*(Log|Write-Host|Write-Output|Write-Warning|Write-Error|#)")

# `.` 默认不跨行，所以这条只认"同一行（或反引号续行拼成的一行）里的管道"
PIPELINE_KILL = re.compile(r"Get-Process.*\|.*Stop-Process")

Q, APOS, NL, DOT, BS = chr(34), chr(39), chr(10), chr(46), chr(92)
STR_LIT = r"-(?:match|like|eq)\s+[" + Q + APOS + r"]([^" + Q + APOS + r"]+)[" + Q + APOS + r"]"

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def strip_comments(src: str) -> str:
    """只去整行注释：行内 `#` 可能落在字符串字面量里，切掉会让判据自己变瞎。"""
    return NL.join("" if ln.lstrip().startswith("#") else ln for ln in src.split(NL))


def names_our_daemon(pattern: str) -> bool:
    r"""PowerShell 里"点"有三种写法（反斜杠点、[.]、裸点），归一化后看有没有指到 daemon 模块。"""
    flat = pattern.replace(BS, "").replace("[" + DOT + "]", DOT)
    return "browser_harness" + DOT + "daemon" in flat


def normalize_token(tok: str) -> str:
    return tok.strip().strip("^$").replace(BS, "").replace("[" + DOT + "]", DOT).replace(".*", "")


def self_started_vars(src: str) -> set[str]:
    """本脚本自己 `Start-Process` 回来的变量名：杀它合法（谁起的谁负责）。

    `-PassThru` 常被反引号续行拆到后面的行里（`run_adapter_m4b.ps1:154-156` 就是），
    所以只认 `$v = Start-Process` 这件事本身，不在同一行找 -PassThru。
    """
    return {m.group(1) for m in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Start-Process", src)}


def kill_sites(src: str):
    """yield (本行, 有效上文, 被杀 PID 的变量名或 None, 行号, 上一行)。一行只判一次。"""
    lines = src.split(NL)
    for i, line in enumerate(lines):
        if "Stop-Process" not in line:
            continue
        pid = re.search(r"-Id\s+\$([A-Za-z_][A-Za-z0-9_]*)", line[line.index("Stop-Process"):])
        ctx = [ln for ln in lines[max(0, i - 12):i] if not PRINT_OR_COMMENT.match(ln)]
        prev = lines[i - 1] if i else ""
        yield line, NL.join(ctx + [line]), (pid.group(1) if pid else None), i + 1, prev


def offenders_for(path: Path):
    src = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    started = self_started_vars(src)
    bad = []
    for line, window, pid, lineno, prev in kill_sites(src):
        chain = (prev + " " + line) if prev.rstrip().endswith("|") else line
        if PIPELINE_KILL.search(chain) and "ForEach-Object" not in chain:
            if not any(mark in chain for mark in OWNERSHIP_MARKS):
                bad.append((lineno, "按进程名直连砍: " + " ".join(chain.split())[:120]))
            continue
        if any(mark in line for mark in OWNERSHIP_MARKS):
            continue                      # 本行自己就带命令行/画像判据
        if pid and pid in started:
            continue                      # 杀的是本脚本 Start-Process 起来的那个进程
        if any(mark in window for mark in OWNERSHIP_MARKS):
            continue                      # 同一 ForEach 里的 $cl/CommandLine 过滤在上文
        bad.append((lineno, " ".join(window.split(NL)[-2:])[:130]))
    return bad


def kill_filter_patterns(path: Path):
    """只取**发杀那条语句附近**（上 6 行、本行）的过滤串；Step 2 的探测不在射程内。"""
    src = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    lines = src.split(NL)
    out = []
    for i, ln in enumerate(lines):
        if "Stop-Process" not in ln:
            continue
        win = NL.join(lines[max(0, i - 6):i + 2])
        for mt in re.finditer(STR_LIT, win):
            out.append((i + 1, mt.group(1)))
    return out


@case("按进程名直连砍一律红（Get-Process <名字> | Stop-Process，管道里没有归属判据）")
def t_no_pipeline_kill_by_name():
    offenders = []
    for f in TARGETS:
        src = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for line, _w, _pid, lineno, prev in kill_sites(src):
            chain = (prev + " " + line) if prev.rstrip().endswith("|") else line
            if PIPELINE_KILL.search(chain) and "ForEach-Object" not in chain \
                    and not any(mark in chain for mark in OWNERSHIP_MARKS):
                offenders.append(f"{f.name}:{lineno}  " + " ".join(chain.split())[:120])
    assert not offenders, (
        "这些是按进程名砍：本机同名进程全没，会连你自己起的同名进程一起带走：" + NL + "  "
        + (NL + "  ").join(offenders))


@case("其余每处 Stop-Process 都要回看到归属判据（CommandLine / 自有画像清单 / 自己起的 PID）")
def t_every_kill_has_ownership_proof():
    offenders = []
    for f in TARGETS:
        for line, snippet in offenders_for(f):
            offenders.append(f"{f.name}:{line}  {snippet}")
    assert not offenders, (
        "这些杀动作没有归属判据：" + NL + "  " + (NL + "  ").join(offenders))


@case("发杀语句附近的过滤串不许是光秃秃的库名，也不许是 serve/uvicorn 这种匹配一切 server 的裸词")
def t_kill_filters_name_our_processes():
    bad = []
    for f in TARGETS:
        for line, pat in kill_filter_patterns(f):
            if "browser_harness" in pat and not names_our_daemon(pat):
                bad.append(f"{f.name}:{line}  库名当杀判据 {pat!r}")
            for tok in pat.split("|"):
                if normalize_token(tok) in ("serve", "uvicorn", "server"):
                    bad.append(f"{f.name}:{line}  裸词 {tok.strip()!r} 会匹配任何 server 进程")
    assert not bad, (
        "清理判据必须指到我们自己的脚本/模块名，否则用户自己跑的 harness/daemon/开发服务器"
        "会一起被杀：" + NL + "  " + (NL + "  ").join(bad))


@case(".ps1 要么纯 ASCII，要么带 BOM 的 UTF-8（非 ASCII 且无 BOM 会被 PS 5.1 当 GBK 读）")
def t_ps_files_are_ascii_or_bom():
    bad = []
    for f in TARGETS:
        data = f.read_bytes()
        n = sum(1 for b in data if b > 127)
        if n and data[:3] != bytes([0xEF, 0xBB, 0xBF]):
            bad.append(f"{f.name}（非 ASCII {n} 字节，无 BOM）")
    assert not bad, (
        "这些 .ps1 会被 PowerShell 5.1 按 ANSI/GBK 读——一条 0x60 就能变成行继续符，"
        "把下一行吞进注释：" + NL + "  " + (NL + "  ").join(bad))


@case("浏览器归属判据只许有一份：自己另抄一条画像名过滤 = 迟早和连接侧漂移")
def t_ownership_predicate_lives_in_one_file():
    """2026-10-12 实测过：9 个 `.ps1` 里 **8 个**自带 Chrome 生命周期、**3 个**另抄了画像判据
    （`run_baseline_19.ps1` 甚至一边 dot-source `chrome_guard.ps1` 一边再抄一份），
    这正是"同一规则写几份、靠注释对齐"的病灶。现在三处都改成委托 `Get-/Stop-OwnedChrome`。
    """
    offenders = []
    for f in TARGETS:
        if f.name == "chrome_guard.ps1":
            continue                       # 判据的唯一的家
        src = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        lines = src.split(chr(10))
        for m in re.finditer(r"-like\s+[\"'][^\"']*chrome-cdp-test[^\"']*[\"']", src):
            line = src[:m.start()].count(chr(10)) + 1
            snippet = " ".join(lines[line - 1].split())
            if snippet.lstrip().startswith(("Log", "Write-Host", "#")):
                continue                   # 打印给人看的建议不是判据
            # 只审**发杀附近**的画像判据。"我刚起的那个浏览器在不在 :9222 上"是另一个问题：
            # 它必须窄到 cdp-test，否则换像活着时它会点头——把探测也算成副本，这条规则就在乱报。
            # （这条约束不是为了让读数变绿：`start_owned_chrome.ps1` 的杀侧确实交回了 guard。）
            if not any("Stop-Process" in ln for ln in lines[max(0, line - 7):line + 2]):
                continue
            offenders.append(f"{f.name}:{line}  {snippet[:90]}")
    assert not offenders, (
        "这些脚本自己写了一遍『哪个浏览器是我们的』。杀侧要改判据时必须和 "
        "jev_ultrafast/browser.py::OWNED_PROFILE_MARKERS 一起改——两处以上就一定会漂移：\n  "
        + "\n  ".join(offenders))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                       # noqa: BLE001
            pass
    failed = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}" + NL + "      " + str(e))
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}" + NL + f"      {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
